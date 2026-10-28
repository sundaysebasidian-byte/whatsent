from __future__ import annotations

import base64
import gzip
import io
import json
import zipfile
from urllib.parse import quote

from whatsent import canary, diskwatch, report
from whatsent.detect import Matcher

TOKEN = "wsc2deadbeefcafef00d"


def test_matcher_finds_encoded_forms():
    m = Matcher({"x": TOKEN})
    secret = f"KEY=sk-{TOKEN}\n".encode()
    assert m.scan(b"plain " + secret) == {"x"}
    assert m.scan(quote(secret.decode(), safe="").encode()) == {"x"}
    assert m.scan(gzip.compress(secret)) == {"x"}
    for pad in range(3):  # base64 at every alignment, standard and url-safe
        enc = base64.b64encode(b"a" * pad + secret)
        assert m.scan(b'{"blob":"' + enc + b'"}') == {"x"}
        assert m.scan(base64.urlsafe_b64encode(b"a" * pad + secret)) == {"x"}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"notes/{TOKEN}.md", "x")
    assert m.scan(buf.getvalue()) == {"x"}
    assert m.scan(b"nothing to see") == set()


def test_workspace_plants_unique_tokens(tmp_path):
    cs = canary.create_workspace(tmp_path)
    assert len({c.token for c in cs}) == len(cs)
    for c in cs:
        if c.id == "file_name":
            assert (tmp_path / c.file).exists() and c.token in c.file
        elif c.id != "git_history":
            assert c.token in (tmp_path / c.file).read_text(encoding="utf-8")


def test_diskwatch_diff(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    (root / "old.txt").write_text("unchanged")
    excluded = root / "skip"
    excluded.mkdir()
    before, _ = diskwatch.snapshot([root], exclude=[excluded])
    (root / "copy.json").write_text(f'{{"k": "{TOKEN}"}}')
    (root / "blob.bin").write_bytes(b"\0" * (diskwatch.LARGE_FILE + 1))
    (root / "small.log").write_text("hello")
    (excluded / "ignored.txt").write_text(TOKEN)
    after, _ = diskwatch.snapshot([root], exclude=[excluded])
    d = diskwatch.diff(before, after, Matcher({"x": TOKEN}))
    assert [x["path"] for x in d["leaks"]] == [str(root / "copy.json")]
    assert [x["path"] for x in d["suspicious"]] == [str(root / "blob.bin")]
    assert d["changed_files"] == 3


def test_report_escapes_and_summarizes(tmp_path):
    canaries = [{"id": "dotenv", "token": TOKEN, "file": ".env", "label": "Secret", "sensitive": True}]
    events = [
        {"type": "http", "host": "<script>x</script>", "bytes_out": 2048, "bytes_in": 10, "canaries": ["dotenv"]},
        {"type": "http", "host": "api.example.com", "bytes_out": 10, "bytes_in": 10, "canaries": []},
        {"type": "tls_failed", "host": "pinned.example.com", "port": 443, "error": "unknown ca"},
    ]
    meta = {"whatsent_version": "0", "command": ["agent"], "started_at": "now", "duration_s": 1,
            "exit_code": 0, "platform": "test"}
    s = report.summarize(meta, canaries, events, None, [])
    assert s["totals"] == {"canaries": 1, "leaked": 1, "leaked_sensitive": 1, "requests": 2,
                           "hosts": 2, "bytes_out": 2058, "not_inspected": 1, "copied_to_disk": 0}
    assert s["destinations"][0]["host"] == "<script>x</script>"
    html = report.write(s, tmp_path).read_text(encoding="utf-8")
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html
    assert "pinned.example.com" in html and TOKEN not in html


def test_redact_home_only_replaces_path_prefixes(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)  # like macOS /var -> /private/var
    out = report.redact_home(
        {"a": f"{real}/x", "b": [f"{link}/y", str(link)], "c": f"/other{real}/z"}, link)
    assert out == {"a": "~/x", "b": ["~/y", "~"], "c": f"/other{real}/z"}


def test_task_token_is_on_the_line_the_fix_needs(tmp_path):
    cs = {c.id: c for c in canary.create_workspace(tmp_path)}
    app = tmp_path / canary.TASK_FILE
    (bug_line,) = [line for line in app.read_text(encoding="utf-8").splitlines() if canary.BUGGY in line]
    assert cs["task_file"].token in bug_line
    assert not canary.task_fixed(tmp_path)
    app.write_text(app.read_text(encoding="utf-8").replace(canary.BUGGY, "a + b"), encoding="utf-8")
    assert canary.task_fixed(tmp_path)


def test_control_flags_runs_where_the_task_file_was_not_seen(tmp_path):
    canaries = [{"id": "task_file", "token": TOKEN, "file": "src/app.py", "label": "Task", "sensitive": False,
                 "short": "task file"}]
    meta = {"whatsent_version": "0", "command": ["agent"], "started_at": "now", "duration_s": 1,
            "exit_code": 0, "platform": "test"}
    sent = [{"type": "http", "host": "api.example.com", "bytes_out": 10, "bytes_in": 1, "canaries": ["task_file"]}]
    silent = [{"type": "http", "host": "api.example.com", "bytes_out": 10, "bytes_in": 1, "canaries": []},
              {"type": "tls_failed", "host": "pinned.example.com", "port": 443, "error": "unknown ca"}]
    on_disk = {"leaks": [{"path": "/x/session.jsonl", "size": 1, "new": True, "canaries": ["task_file"]}],
               "suspicious": [], "changed_files": 1}

    def status(events, disk=None, fixed=None):
        return report.summarize(meta, canaries, events, disk, [], task_fixed=fixed)["control"]["status"]

    assert status(sent, fixed=False) == "ok"
    assert status(silent, on_disk, fixed=True) == "missed"
    assert status(silent, fixed=True) == "unconfirmed"
    assert status(silent, fixed=None) == "unconfirmed"
    assert status(silent, fixed=False) == "unfinished"

    s = report.summarize(meta, canaries, silent, None, [], task_fixed=True)
    html = report.write(s, tmp_path).read_text(encoding="utf-8")
    assert 'class="hero unknown"' in html and "Result not confirmed" in html
    assert "expected to leave, not seen" in html and "pinned.example.com" in html.split("</h1>")[1]
    assert json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))["control"] == "unconfirmed"


def test_undecoded_bodies_count_as_not_inspected():
    canaries = [{"id": "dotenv", "token": TOKEN, "file": ".env", "label": "Secret", "sensitive": True}]
    events = [{"type": "http", "host": "api.example.com", "bytes_out": 10, "bytes_in": 1, "canaries": [],
               "undecoded": "x-custom"}]
    meta = {"whatsent_version": "0", "command": ["agent"], "started_at": "now", "duration_s": 1,
            "exit_code": 0, "platform": "test"}
    s = report.summarize(meta, canaries, events, None, [])
    assert s["totals"]["not_inspected"] == 1
    assert s["not_inspected"]["undecoded"] == [{"host": "api.example.com", "encoding": "x-custom", "count": 1}]
