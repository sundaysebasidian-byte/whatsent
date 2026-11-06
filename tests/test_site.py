"""The shared visual system, the static live demo and the pages that link to it. Offline."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from whatsent import board, report

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "src" / "whatsent" / "ui"
EXAMPLES = ROOT / "examples" / "results"
FIXTURE = ROOT / "scripts" / "demo-fixture.json"
needs_repo = pytest.mark.skipif(not FIXTURE.is_file(), reason="scripts/ is not part of this source tree")


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def summary(**changes) -> dict:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {**fixture["summary"], **changes}


def test_app_css_starts_with_the_report_core():
    assert report.CORE.strip() in (UI / "app.css").read_text(encoding="utf-8")


@needs_repo
def test_report_has_dark_mode_and_print_styles_and_no_external_requests():
    html = report.render_html(summary())
    assert "prefers-color-scheme:dark" in html and "@media print" in html
    # Self-contained: no scripts, stylesheets, images or web fonts from anywhere.
    assert not re.search(r"<script|<link rel=\"stylesheet\"|@import|url\(|src=", html)
    assert set(re.findall(r'href="([^"]+)"', html)) <= {"https://" + report.REPO} | {
        h for h in re.findall(r'href="(data:[^"]+)"', html)}


@needs_repo
def test_report_tiles_use_one_class_per_state():
    html = report.render_html(summary())
    for state in ("secret", "file", "unk"):
        assert f'<li class="{state}">' in html
    base = summary()
    canaries = [{**c, "sent_to": []} if c["id"] == "task_file" else c for c in base["canaries"]]
    unconfirmed = report.render_html(summary(canaries=canaries, control={"status": "unconfirmed", "task_fixed": True}))
    assert '<li class="unk"><b aria-hidden="true">?</b>' in unconfirmed
    assert '<div class="notice"><b>Result not confirmed</b>' in unconfirmed


@needs_repo
def test_long_hosts_and_empty_tables_render():
    s = summary(destinations=[{"host": "x" * 200 + ".example.com", "requests": 1, "bytes_out": 5, "bytes_in": 1,
                               "canaries": []}],
                not_inspected={"tls_failed": [], "undecoded": [], "direct_connections": []})
    html = report.render_html(s)
    assert "x" * 200 in html and "Nothing. All traffic seen went through the proxy." in html
    assert 'data-label="Destination"' in html  # tables turn into labelled rows on phones


def test_board_links_the_live_demo_and_sample_report_only_when_they_exist(tmp_path):
    assert board.build([EXAMPLES], tmp_path) == 0
    assert 'href="demo/"' not in (tmp_path / "index.html").read_text(encoding="utf-8")
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "index.html").write_text("x", encoding="utf-8")
    (tmp_path / "sample-report.html").write_text("x", encoding="utf-8")
    assert board.build([EXAMPLES], tmp_path) == 0
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert 'href="demo/"' in html and 'href="sample-report.html"' in html


def test_board_draws_one_square_per_canary_and_has_dark_mode(tmp_path):
    assert board.build([EXAMPLES], tmp_path) == 0
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert html.count('<div class="pips"') == 5 and html.count('<i class="secret"') == 4
    assert "prefers-color-scheme:dark" in html and "<th>#</th>" in html


@needs_repo
def test_demo_fixture_is_a_complete_recording():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    kinds = [ev["kind"] for ev in fixture["events"]]
    assert kinds[0] == "job" and kinds[-1] == "done" and "launched" in kinds and "canaries" in kinds
    assert kinds.count("req") >= 3 and "gap" in kinds
    times = [ev["at"] for ev in fixture["events"]]
    assert times == sorted(times)
    done = fixture["events"][-1]["report"]
    assert done["totals"] == fixture["summary"]["totals"]
    assert "/Users/" not in json.dumps(fixture) and "/var/folders" not in json.dumps(fixture)


@needs_repo
def test_static_demo_site(tmp_path):
    build = load_script("build_demo_site")
    build.build(tmp_path)
    demo = tmp_path / "demo"
    assert {p.name for p in demo.iterdir()} == {"index.html", "app.js", "app.css", "icon.svg"}
    page = (demo / "index.html").read_text(encoding="utf-8")
    assert 'id="whatsent-replay"' in page and "whatsent-token" not in page
    assert not re.search(r'(?:href|src)="/', page)  # relative, so it works below /whatsent/demo/
    inline = json.loads(re.search(r'id="whatsent-replay">(.*?)</script>', page, re.S).group(1).replace("<\\/", "</"))
    assert inline["events"][-1]["report"]["url"] == "../sample-report.html"
    sample = (tmp_path / "sample-report.html").read_text(encoding="utf-8")
    assert "4 of 8 canaries left this machine" in sample
    assert 'href="demo/"' in sample and 'href="./"' in sample
    assert (demo / "app.js").read_bytes() == (UI / "app.js").read_bytes()  # the real UI, not a copy of it


def test_ui_files_make_no_outside_requests():
    for name in ("app.js", "app.css", "index.html", "icon.svg"):
        text = (UI / name).read_text(encoding="utf-8")
        urls = set(re.findall(r"https?://[^\s'\"\\)>]+", text))
        assert urls <= {"https://github.com/sundaysebasidian-byte/whatsent", "http://www.w3.org/2000/svg"}, (name, urls)
    assert "@import" not in (UI / "app.css").read_text(encoding="utf-8")
