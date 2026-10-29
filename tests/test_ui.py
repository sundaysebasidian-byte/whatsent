"""``whatsent ui``: the local server, its guards, and a full run of the simulated agent
driven through the API and followed on the event stream. Offline."""

from __future__ import annotations

import http.client
import json
import sys
import time

import pytest

from whatsent import ui


@pytest.fixture
def server(tmp_path):
    srv = ui.UI(tmp_path / "out")
    import threading
    threading.Thread(target=srv.server.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def request(srv, method, path, body=None, token=True, host=None, ctype="application/json"):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
    headers = {"Host": host or f"127.0.0.1:{srv.port}"}
    if token:
        headers["X-Whatsent-Token"] = srv.token
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = ctype
    conn.request(method, path, body=data, headers=headers)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    return resp.status, raw


def events(srv, job, until, timeout=90):
    """Read the event stream until an event of kind ``until`` arrives."""
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=timeout)
    conn.request("GET", f"/api/events?job={job}&since=0&token={srv.token}", headers={"Host": f"127.0.0.1:{srv.port}"})
    resp = conn.getresponse()
    assert resp.status == 200 and resp.getheader("Content-Type") == "text/event-stream"
    got = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = resp.fp.readline().decode()
        if line.startswith("data: "):
            ev = json.loads(line[6:])
            got.append(ev)
            if ev["kind"] in (until, "error"):
                break
    conn.close()
    return got


def test_page_and_guards(server):
    status, page = request(server, "GET", "/", token=False)
    assert status == 200 and server.token.encode() in page and b"/app.js" in page
    for asset in ("/app.js", "/app.css", "/icon.svg"):
        assert request(server, "GET", asset, token=False)[0] == 200

    # API calls need the page's token and a Host header naming this server.
    assert request(server, "GET", "/api/state", token=False)[0] == 403
    assert request(server, "GET", "/api/state", host="evil.example:80")[0] == 403
    assert request(server, "GET", "/", token=False, host=f"evil.example:{server.port}")[0] == 403
    assert request(server, "POST", "/api/start", {"tool": "demo"}, token=False)[0] == 403
    assert request(server, "POST", "/api/start", {"tool": "demo"}, ctype="text/plain")[0] == 415
    assert request(server, "GET", "/runs/../../etc/passwd")[0] == 404
    assert request(server, "GET", "/runs/20260101-000000/report.html")[0] == 404

    status, body = request(server, "GET", "/api/state")
    state = json.loads(body)
    assert status == 200 and state["job"] is None and state["platform"] == sys.platform


def test_tool_scan(server, monkeypatch, tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "claude").write_text("#!/bin/sh\n")
    (fake / "claude").chmod(0o755)
    (fake / "claude.cmd").write_text("@echo off\n")
    monkeypatch.setenv("PATH", str(fake))
    tools = {t["id"]: t for t in json.loads(request(server, "GET", "/api/tools")[1])["tools"]}
    assert tools["claude"] == {"id": "claude", "name": "Claude Code", "kind": "cli", "installed": True}
    assert tools["codex"]["installed"] is False
    assert tools["cursor"]["kind"] == "app" and set(tools) >= {"cursor", "trae", "vscode", "aider"}


def test_unknown_app_is_not_found(server):
    status, body = request(server, "POST", "/api/start", {"tool": "definitely-not-an-ide"})
    assert status == 400 and json.loads(body)["error"] == "not_found"


def test_demo_run_streams_live_events_and_report(server):
    pytest.importorskip("mitmproxy")
    status, body = request(server, "POST", "/api/start", {"tool": "demo", "pace": 0.2})
    assert status == 200
    job = json.loads(body)["job"]
    assert request(server, "POST", "/api/start", {"tool": "demo"})[0] == 409  # one run at a time

    got = events(server, job, "done")
    kinds = [e["kind"] for e in got]
    assert kinds[0] == "job" and kinds[-1] == "done", kinds
    assert [e["seq"] for e in got] == list(range(1, len(got) + 1))
    assert {"canaries", "ready", "launched", "req", "gap", "finishing"} <= set(kinds)
    tokens = {c["id"] for c in next(e for e in got if e["kind"] == "canaries")["items"]}
    assert "dotenv" in tokens
    assert all("token" not in c for c in next(e for e in got if e["kind"] == "canaries")["items"])

    reqs = [e for e in got if e["kind"] == "req"]
    assert any("dotenv" in e["canaries"] and e["host"] == "telemetry.demo-agent.test" for e in reqs)
    assert any(e["kind"] == "gap" and e["why"] == "tls" for e in got)  # the pinned connection

    report = got[-1]["report"]
    assert report["totals"]["leaked_sensitive"] == 1 and report["sample"] is True
    assert all("token" not in c for c in report["canaries"])
    status, html = request(server, "GET", f"{report['url']}?token={server.token}", token=False)
    assert status == 200 and b"canaries left this machine" in html

    # A reload replays the same run from the start.
    assert [e["kind"] for e in events(server, job, "done")] == kinds
    # The stream of a run that is no longer current ends at once, so the page stops retrying.
    assert request(server, "GET", f"/api/events?job=old&token={server.token}")[0] == 204


def test_stop_ends_a_running_agent_and_still_writes_the_report(server):
    pytest.importorskip("mitmproxy")
    _, body = request(server, "POST", "/api/start", {"tool": "demo", "pace": 30})
    job = json.loads(body)["job"]
    events(server, job, "launched")
    assert request(server, "POST", "/api/stop", {})[0] == 200
    got = events(server, job, "done")
    report = got[-1]["report"]
    assert report["totals"]["requests"] == 0
    s = json.loads((server.out / report["run"] / "report.json").read_text(encoding="utf-8"))
    assert s["exit_code"] == "stopped"


def test_child_runs_command_with_added_env(tmp_path):
    from whatsent import child

    spec = tmp_path / "agent.json"
    out = tmp_path / "seen.txt"
    spec.write_text(json.dumps({
        "command": [sys.executable, "-c", f"import os; open({str(out)!r}, 'w').write(os.environ['HTTPS_PROXY'])"],
        "cwd": str(tmp_path), "env": {"HTTPS_PROXY": "http://127.0.0.1:9"}, "prompt": "p",
        "pidfile": str(tmp_path / "agent.pid"), "exitfile": str(tmp_path / "agent.exit"),
    }))
    assert child.main([str(spec)]) == 0
    assert out.read_text() == "http://127.0.0.1:9"
    assert (tmp_path / "agent.exit").read_text() == "0" and (tmp_path / "agent.pid").read_text().isdigit()


def test_terminal_agent_reports_exit(tmp_path):
    import os
    (tmp_path / "agent.pid").write_text(str(os.getpid()))
    agent = ui.TerminalAgent(tmp_path / "agent.pid", tmp_path / "agent.exit")
    assert agent.poll() is None  # our own process is alive
    (tmp_path / "agent.exit").write_text("3")
    assert agent.poll() == 3


def test_terminal_command(monkeypatch, tmp_path):
    script = tmp_path / "open-agent.command"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert ui.terminal_command(script, ["sh", str(script)]) == ["open", "-a", "Terminal", str(script)]
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(ui.shutil, "which", lambda name: "/usr/bin/xterm" if name == "xterm" else None)
    assert ui.terminal_command(script, ["sh", str(script)]) == ["/usr/bin/xterm", "-e", "sh", str(script)]
    monkeypatch.setattr(ui.shutil, "which", lambda name: None)
    with pytest.raises(ui.UIError):
        ui.terminal_command(script, ["sh", str(script)])


@pytest.mark.parametrize("value", ["invalid", "-1"])
def test_invalid_event_cursor_returns_an_error(server, value):
    assert request(server, "GET", f"/api/events?since={value}")[0] == 400


@pytest.mark.parametrize("body", [[], {"tool": "demo", "pace": []}, {"tool": "demo", "pace": float("inf")},
                                 {"tool": "demo", "pace": -1}])
def test_invalid_api_bodies_do_not_launch_jobs(server, body):
    assert request(server, "POST", "/api/start", body)[0] == 400
    assert server.job is None


def test_api_rejects_oversized_and_negative_lengths(server):
    for length, expected in [(ui.MAX_BODY + 1, 413), (-1, 400)]:
        conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
        conn.request("POST", "/api/start", headers={"Content-Length": str(length),
                     "Content-Type": "application/json", "X-Whatsent-Token": server.token})
        response = conn.getresponse()
        assert response.status == expected
        response.read()
        conn.close()


def test_unicode_token_is_rejected_without_crashing(server):
    assert request(server, "GET", "/api/state?token=%E4%B8%AD", token=False)[0] == 403


def test_report_route_accepts_collision_suffix(server):
    run = server.out / "20261029-123456-2"
    run.mkdir()
    (run / "report.html").write_text("report")
    assert request(server, "GET", f"/runs/{run.name}/report.html") == (200, b"report")


def test_failed_job_always_disposes_of_its_ca(server, monkeypatch):
    def fail(job):
        job.session.prepare()
        job.session.start_proxy()
        raise RuntimeError("simulated failure after proxy startup")

    monkeypatch.setattr(ui.Job, "_steps", fail)
    job = server.start_job({"tool": "demo", "pace": 0})
    job.thread.join(timeout=30)
    assert not job.active and job.state == "failed"
    assert job.session.proxy.proc.poll() is not None
    assert not (job.session.proxy.confdir / "mitmproxy-ca.pem").exists()


def test_stale_pid_reuse_cannot_terminate_an_unrelated_process(server, monkeypatch):
    from types import SimpleNamespace

    killed = []
    proc = SimpleNamespace(create_time=lambda: 100, exe=lambda: "/fake/app", terminate=lambda: killed.append(True))
    monkeypatch.setattr(ui.psutil, "Process", lambda pid: proc)
    (server.out / ui.STALE_FILE).write_text(json.dumps({"pid": 123, "exe": "/fake/app", "created": 99}))
    server.close_stale()
    assert not killed
