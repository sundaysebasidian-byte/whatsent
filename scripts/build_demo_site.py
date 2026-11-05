#!/usr/bin/env python3
"""Build the static live demo for GitHub Pages.

    python scripts/build_demo_site.py SITE_DIR

Writes SITE_DIR/demo/ (the real web UI in replay mode, the recorded events inlined in the page, no
backend) and SITE_DIR/sample-report.html (the demo run's report, rendered by the current code).
Record the events with scripts/record_demo.py.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

from whatsent import report

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "src" / "whatsent" / "ui"
FIXTURE = Path(__file__).with_name("demo-fixture.json")
ASSETS = ("app.js", "app.css", "icon.svg")
REPORT_URL = "../sample-report.html"


def demo_page(fixture: dict) -> str:
    events = json.loads(json.dumps(fixture["events"]))
    events[-1]["report"]["url"] = REPORT_URL
    inline = json.dumps({"events": events}, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    page = (UI / "index.html").read_text(encoding="utf-8")
    page = re.sub(r'<meta name="whatsent-token"[^>]*>\n', "", page)
    page = re.sub(r'(href|src)="/', r'\1="', page)  # relative, so the demo also works below a sub-path
    page = page.replace("<title>whatsent</title>", "<title>whatsent demo</title>")
    return page.replace('<script src="app.js">', f'<script type="application/json" id="whatsent-replay">{inline}</script>\n<script src="app.js">')


def build(site: Path, fixture_path: Path = FIXTURE) -> None:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    demo = site / "demo"
    demo.mkdir(parents=True, exist_ok=True)
    for name in ASSETS:
        shutil.copyfile(UI / name, demo / name)
    (demo / "index.html").write_text(demo_page(fixture), encoding="utf-8")
    nav = [("Live demo", "demo/"), ("Leaderboard", "./")]
    (site / "sample-report.html").write_text(report.render_html(fixture["summary"], nav), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("site", type=Path)
    args = ap.parse_args()
    build(args.site)
    print(f"build_demo_site: {args.site / 'demo'} and {args.site / 'sample-report.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
