"""Disk watch coverage, upstream proxies, agent presets, time limit and result files."""

from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from whatsent import agents, board, diskwatch, report
from whatsent.capture import Proxy, hide_credentials, upstream_from_env
from whatsent.cli import Session, build_parser, main, save_result
from whatsent.detect import Matcher


def test_snapshot_reports_partly_scanned_roots(tmp_path):
    for name in ("a", "b", "c"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "f.txt").write_text(name)
    files, partial = diskwatch.snapshot([tmp_path], [])
    assert len(files) == 3 and partial == []
    files, partial = diskwatch.snapshot([tmp_path], [], max_files=1)
    assert len(files) == 1 and partial == [str(tmp_path)]
    files, partial = diskwatch.snapshot([tmp_path], [], seconds=-1)
    assert files == {} and partial == [str(tmp_path)]


def test_snapshot_skips_noise_and_excluded_folders(tmp_path):
    for name in ("node_modules", "keep", "skip"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "f.txt").write_text(name)
    files, _ = diskwatch.snapshot([tmp_path], [tmp_path / "skip"])
    assert list(files) == [str(tmp_path / "keep" / "f.txt")]


def test_diff_ignores_old_files_a_partial_scan_missed(tmp_path):
    blob = tmp_path / "old.bin"
    blob.write_bytes(b"\0" * (diskwatch.LARGE_FILE + 1))
    after, _ = diskwatch.snapshot([tmp_path], [])
    mtime = after[str(blob)][1]
    nobody = Matcher({})
    started_after_file = diskwatch.diff({}, after, nobody, since_ns=mtime + 1, partial=[str(tmp_path)])
    assert started_after_file["changed_files"] == 0 and started_after_file["suspicious"] == []
    started_before_file = diskwatch.diff({}, after, nobody, since_ns=mtime - 1, partial=[str(tmp_path)])
    assert [x["path"] for x in started_before_file["suspicious"]] == [str(blob)]
    complete = diskwatch.diff({}, after, nobody, since_ns=mtime + 1, partial=[])
    assert complete["changed_files"] == 1  # a complete "before" really did not have it


def test_suspicious_files_are_marked_related_to_the_agent(tmp_path):
    for name in ("alpha-cache", "beta"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "x.bin").write_bytes(b"\0" * (diskwatch.LARGE_FILE + 1))
    (tmp_path / "beta" / "bigger.bin").write_bytes(b"\0" * (diskwatch.LARGE_FILE * 2))
    after, _ = diskwatch.snapshot([tmp_path], [])
    d = diskwatch.diff({}, after, Matcher({}), agent="Alpha")
    assert [(Path(x["path"]).parent.name, x["related"]) for x in d["suspicious"]] == [
        ("alpha-cache", True), ("beta", False), ("beta", False)]
    assert diskwatch.related("/h/.trae-cn/x", "Trae CN") and diskwatch.related("/h/x", None)
    assert diskwatch.related("/h/x", "ab") and not diskwatch.related("/h/Claude/x", "codex")
    assert diskwatch.related("/h/.demo-agent/cache/x", "demo-agent (simulated)")
    # An app's own Chromium stores are never the agent's, even when the app has the agent's name.
    assert not diskwatch.related("/h/Library/Application Support/Claude/IndexedDB/https_claude.ai_0.indexeddb.blob/1/x", "claude")
    assert not diskwatch.related("/h/Library/Application Support/Claude/blob_storage/x", "claude")


def test_upstream_proxy_from_environment():
    assert upstream_from_env({}) == (None, None)
    assert upstream_from_env({"HTTPS_PROXY": "127.0.0.1:7890"}) == ("http://127.0.0.1:7890", None)
    assert upstream_from_env({"HTTP_PROXY": "http://a:1", "https_proxy": "http://b:2"})[0] == "http://b:2"
    url, problem = upstream_from_env({"ALL_PROXY": "socks5://127.0.0.1:1080"})
    assert url is None and "socks5" in problem
    assert hide_credentials("http://user:secret@proxy:3128") == "http://proxy:3128"
    assert hide_credentials("http://proxy:3128") == "http://proxy:3128"


def _session(tmp_path, *flags):
    args = build_parser().parse_args(["run", "--out", str(tmp_path), "--no-default-watch", *flags, "--", "agent"])
    return Session(args, args.command[1:])


def test_session_picks_the_upstream(tmp_path, monkeypatch):
    assert _session(tmp_path).resolve_upstream() is None
    monkeypatch.setenv("HTTPS_PROXY", "127.0.0.1:7890")
    assert _session(tmp_path).resolve_upstream() == "http://127.0.0.1:7890"
    assert _session(tmp_path, "--upstream", "none").resolve_upstream() is None
    assert _session(tmp_path, "--upstream", "10.0.0.1:3128").resolve_upstream() == "http://10.0.0.1:3128"
    monkeypatch.setenv("HTTPS_PROXY", "socks5://127.0.0.1:1080")
    session = _session(tmp_path)
    assert session.resolve_upstream() is None and "socks5" in session.warnings[0]


class _FakeUpstream(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"FROM-UPSTREAM {self.path}".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_proxy_forwards_to_the_upstream_proxy(tmp_path):
    pytest.importorskip("mitmproxy")
    upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeUpstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    canaries = tmp_path / "canaries.json"
    canaries.write_text("[]")
    proxy = Proxy(tmp_path, canaries, tmp_path / "events.jsonl",
                  upstream=f"http://127.0.0.1:{upstream.server_address[1]}")
    proxy.start()
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": f"http://127.0.0.1:{proxy.port}"}))
        assert opener.open("http://example.invalid/hello", timeout=20).read() == b"FROM-UPSTREAM http://example.invalid/hello"
    finally:
        proxy.stop()
        upstream.shutdown()


def test_detect_version(monkeypatch):
    output = {"value": "codex-cli 0.164.0-alpha.11.1\n"}
    monkeypatch.setattr(agents.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(agents.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=output["value"], stderr=""))
    assert agents.detect_version(["codex", "exec", "x"]) == "0.164.0-alpha.11.1"
    output["value"] = "2.1.301 (Claude Code)\n"
    assert agents.detect_version(["/usr/local/bin/claude"]) == "2.1.301"
    output["value"] = "no digits here\n"
    assert agents.detect_version(["claude"]) is None
    output["value"] = "Python 3.14.0\n"
    assert agents.detect_version([sys.executable, "agent.py"]) is None  # a launcher says nothing about the agent
    monkeypatch.setattr(agents.shutil, "which", lambda name: None)
    assert agents.detect_version(["claude"]) is None


def test_clean_claude():
    c = agents.clean(["claude", "-p", "hi"])
    assert c.command == ["claude", "--strict-mcp-config", "-p", "hi"]
    assert c.env == {"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}
    assert agents.clean(["codebuddy", "-p", "hi"]).command == ["codebuddy", "--strict-mcp-config", "-p", "hi"]
    assert agents.clean(["copilot", "-p", "hi"]).command == ["copilot", "--disable-builtin-mcps", "-p", "hi"]
    assert agents.clean(["aider", "--yes"]) is None and agents.clean([]) is None


def test_clean_codex(monkeypatch):
    listing = [{"name": "gate", "enabled": True}, {"name": "off", "enabled": False},
               {"name": "bad name", "enabled": True}, {"name": "node_repl", "enabled": True}]

    def fake_run(exe, args):
        return "plugins stable true\napps stable true\nfuture_thing stable false\n" if args[0] == "features" \
            else json.dumps(listing)

    monkeypatch.setattr(agents.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(agents, "_run", fake_run)
    off = ["--disable", "plugins", "--disable", "apps",
           "-c", "mcp_servers.gate.enabled=false", "-c", "mcp_servers.node_repl.enabled=false"]
    assert agents.clean(["codex", "exec", "fix it"]).command == ["codex", "exec", *off, "fix it"]
    assert agents.clean(["codex"]).command == ["codex", *off]
    monkeypatch.setattr(agents, "_run", lambda exe, args: "")  # a codex we cannot ask: still turn features off
    assert agents.clean(["codex", "exec", "x"]).command[:4] == ["codex", "exec", "--disable", "plugins"]


def test_save_result_names_the_file_after_agent_and_version(tmp_path):
    src = tmp_path / "result.json"
    src.write_text("{}")
    assert save_result(src, tmp_path / "r", {"agent": "Trae CN", "agent_version": "1.2/3"}).name == "trae-cn-1.2-3.json"
    assert save_result(src, tmp_path / "r", {"agent": "claude", "agent_version": None}).name == "claude-unversioned.json"
    assert save_result(src, tmp_path / "r", {"agent": "claude", "agent_version": "1", "clean": True}).name == "claude-1-clean.json"


def test_report_groups_unrelated_files_and_shows_warnings(tmp_path):
    meta = {"whatsent_version": "0", "agent": "x", "command": ["x"], "started_at": "2026-10-26T10:00:00",
            "duration_s": 1, "exit_code": 0, "platform": "test", "clean": True, "agent_version": "1.0",
            "warnings": ["1 watched folder was only partly scanned"]}
    disk = {"leaks": [], "changed_files": 2, "roots": ["/r"], "truncated_roots": ["/r"],
            "suspicious": [{"path": "/r/x/own.bin", "size": 5, "new": True, "related": True},
                           {"path": "/r/other/theirs.bin", "size": 9, "new": True, "related": False}]}
    s = report.summarize(meta, [], [], disk, [])
    html = report.write(s, tmp_path).read_text(encoding="utf-8")
    assert "1 other new large file, probably from other programs" in html
    assert "only partly scanned" in html and "1.0 · clean config" in html
    assert html.index("own.bin") < html.index("other new large") < html.index("theirs.bin")


def test_clean_runs_are_ranked_apart_from_default_runs():
    base = {"agent": "A", "agent_version": "1", "date": "2026-01-01", "sample": False}
    rows = board.latest_per_agent([base, {**base, "clean": True}])
    assert sorted(bool(r.get("clean")) for r in rows) == [False, True]


def test_time_limit_stops_the_agent_and_cleans_up(tmp_path):
    pytest.importorskip("mitmproxy")
    out, results = tmp_path / "out", tmp_path / "results"
    code = main(["run", "--out", str(out), "--no-default-watch", "--timeout", "1", "--result-to", str(results),
                 "--agent-version", "9.9", "--name", "sleeper", "--",
                 sys.executable, "-c", "import time; time.sleep(60)"])
    assert code == 1
    (run_dir,) = out.iterdir()
    s = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert s["exit_code"] == "timeout" and any("time limit" in w for w in s["warnings"])
    assert s["clean"] is False and s["agent_version"] == "9.9"
    assert json.loads((results / "sleeper-9.9.json").read_text(encoding="utf-8"))["agent"] == "sleeper"
    assert not (run_dir / "mitmproxy" / "mitmproxy-ca.pem").exists()  # the CA private key is gone
    assert (run_dir / "mitmproxy" / "mitmproxy-ca-cert.pem").exists()


def test_bad_options_are_refused(tmp_path, capsys):
    assert main(["run", "--timeout", "0", "--", "x"]) == 2
    assert main(["run", "--clean", "--app", "cursor"]) == 2
    assert "--clean works for CLI agents" in capsys.readouterr().err
    assert main(["run", "--upstream", "socks5://127.0.0.1:1080", "--", "x"]) == 2
    assert "--upstream is an http:// or https:// proxy" in capsys.readouterr().err


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_terminating_whatsent_stops_the_agent_and_the_proxy(tmp_path):
    pytest.importorskip("mitmproxy")
    out = tmp_path / "out"
    cmd = [sys.executable, "-m", "whatsent", "run", "--out", str(out), "--no-default-watch", "--",
           sys.executable, "-c", "import time; time.sleep(120)"]
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)
    try:
        for line in proc.stderr:  # the agent is launched right after the prompt is printed
            if "Use this prompt" in line:
                break
        deadline = time.monotonic() + 20
        while len(psutil.Process(proc.pid).children(recursive=True)) < 2 and time.monotonic() < deadline:
            time.sleep(0.2)  # the proxy and the agent
        children = psutil.Process(proc.pid).children(recursive=True)
        assert len(children) >= 2
        proc.terminate()
        assert proc.wait(timeout=30) == 128 + 15
        _, alive = psutil.wait_procs(children, timeout=15)
        assert alive == []
    finally:
        proc.kill()
    (run_dir,) = out.iterdir()
    assert not (run_dir / "mitmproxy" / "mitmproxy-ca.pem").exists()


def _result(sent: dict[str, list[str]], hosts: list[tuple[str, int, int]], **extra) -> dict:
    canaries = {cid: {"short": cid, "sensitive": cid == "dotenv", "sent_to": to, "on_disk": False}
                for cid, to in sent.items()}
    return {"agent": "x", "agent_version": "1", "kind": "cli", "platform": "p", "date": "2026-10-26",
            "clean": True, "sample": False, "whatsent_version": "0",
            "canaries": canaries,
            "destinations": [{"host": h, "requests": r, "bytes_out": b} for h, r, b in hosts],
            "totals": {"canaries": len(canaries), "leaked": 0, "leaked_sensitive": 0, "requests": 0, "hosts": 0,
                       "bytes_out": 0, "not_inspected": 0, "copied_to_disk": 0},
            "warnings": 0, **extra}


def test_combine_counts_a_canary_if_any_run_sent_it():
    a = _result({"task": ["api.x"], "dotenv": []}, [("api.x", 10, 1000)])
    b = _result({"task": ["api.x"], "dotenv": ["telemetry.x"]}, [("api.x", 20, 3000), ("t.x", 2, 40)],
                date="2026-10-27")
    r = board.combine([a, b])
    assert r["runs"] == 2 and r["date"] == "2026-10-27"
    assert r["canaries"]["task"]["seen_in"] == 2 and r["canaries"]["dotenv"]["seen_in"] == 1
    assert r["canaries"]["dotenv"]["sent_to"] == ["telemetry.x"]
    assert r["totals"]["leaked"] == 2 and r["totals"]["leaked_sensitive"] == 1
    assert [(d["host"], d["requests"], d["bytes_out"]) for d in r["destinations"]] == [
        ("api.x", 15, 2000), ("t.x", 1, 20)]  # averaged per run
    assert r["totals"]["hosts"] == 2 and r["totals"]["bytes_out"] == 2020
    html = board.render(board.latest_per_agent([r]))
    assert "dotenv 1/2" in html and "task 2/2" in html and "2 runs" in html


def test_combine_is_only_confirmed_if_every_run_was():
    ok = _result({"task": ["api.x"]}, [("api.x", 1, 10)], control="ok")
    old = _result({"task": ["api.x"]}, [("api.x", 1, 10)])  # results made before the control existed
    assert board.combine([ok, old])["control"] == "ok"
    for bad in ("unfinished", "unconfirmed", "missed"):
        r = board.combine([ok, _result({"task": []}, [("api.x", 1, 10)], control=bad)])
        assert r["control"] == bad
        assert board.status(r)[0] == "warn" and "unconfirmed" in board.status(r)[1]
    worst = board.combine([_result({"task": []}, [], control="unfinished"), _result({"task": []}, [], control="missed")])
    assert worst["control"] == "missed"
    rows = board.latest_per_agent([board.combine([ok, _result({"task": []}, [], control="unconfirmed")])])
    assert "unconfirmed: task file not seen" in board.render(rows)


def test_several_runs_give_one_combined_result(tmp_path):
    pytest.importorskip("mitmproxy")
    out, results = tmp_path / "out", tmp_path / "results"
    code = main(["run", "--out", str(out), "--no-default-watch", "--runs", "2", "--result-to", str(results),
                 "--agent-version", "1", "--name", "twice", "--", sys.executable, "-c", "pass"])
    assert code == 0
    assert len([d for d in out.iterdir() if not d.name.endswith("-x2")]) == 2  # one report folder per run
    combined = json.loads((results / "twice-1.json").read_text(encoding="utf-8"))
    assert combined["runs"] == 2 and combined["agent"] == "twice"
    assert all("seen_in" in c for c in combined["canaries"].values())
    assert main(["run", "--runs", "0", "--", "x"]) == 2
