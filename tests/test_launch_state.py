"""Launch identity and malformed live events must not break a running audit."""

import json
import os
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from whatsent import apps, report, ui
from whatsent.cli import build_parser


def test_terminal_relaunch_ignores_previous_exit_and_preserves_spec(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(ui, "terminal_command", lambda script, args: ["fake-terminal", str(script)])
    specs = []

    def launch(args, **kwargs):
        if "whatsent.child" in args:
            spec_path = Path(args[-1])
        else:
            spec_path = Path(shlex.split(Path(args[-1]).read_text().splitlines()[-1])[-1])
        spec = json.loads(spec_path.read_text())
        Path(spec["pidfile"]).write_text(str(os.getpid()))
        specs.append((spec_path, spec_path.read_bytes()))
        return SimpleNamespace(pid=os.getpid())

    monkeypatch.setattr(ui.subprocess, "Popen", launch)
    first = ui.open_in_terminal("first", [sys.executable], workspace, dict(os.environ))
    first.exitfile.write_text("17")
    second = ui.open_in_terminal("second", [sys.executable], workspace, dict(os.environ))
    assert second.poll() is None
    assert first.poll() == 17
    assert first.exitfile != second.exitfile
    assert specs[0][0].read_bytes() == specs[0][1]


def test_terminal_startup_waits_for_valid_pid(tmp_path, monkeypatch):
    pidfile = tmp_path / "agent.pid"
    pidfile.write_text("partial")
    monkeypatch.setattr(ui.time, "sleep", lambda delay: pidfile.write_text(str(os.getpid())))
    agent = ui.TerminalAgent(pidfile, tmp_path / "agent.exit", timeout=1)
    assert agent.pid == os.getpid()


def test_failed_terminal_start_marks_the_launch_cancelled(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(ui, "terminal_command", lambda script, args: ["fake-terminal", str(script)])
    monkeypatch.setattr(ui.subprocess, "Popen", lambda *args, **kwargs: SimpleNamespace())

    def failed(*args, **kwargs):
        raise ui.UIError("terminal", "simulated startup failure")

    monkeypatch.setattr(ui, "TerminalAgent", failed)
    with pytest.raises(ui.UIError):
        ui.open_in_terminal("test", [sys.executable], workspace, dict(os.environ))
    (spec_path,) = tmp_path.rglob("agent.json")
    assert Path(json.loads(spec_path.read_text())["cancel_file"]).is_file()


@pytest.mark.parametrize("bad", [[], {}, {"type": "http", "host": "x", "ts": "now"},
                                 {"type": "http", "host": "x", "ts": float("nan")},
                                 {"type": "http", "host": "x", "flow_id": []},
                                 {"type": "http", "host": "x", "bytes_out": "10"}])
def test_live_stream_skips_invalid_records_and_keeps_valid_ones(tmp_path, bad):
    args = build_parser().parse_args(["run", "--out", str(tmp_path), "--no-default-watch", "--", "fake"])
    job = ui.Job(SimpleNamespace(), {"name": "fake"}, args, ["fake"], None)
    path = tmp_path / "events.jsonl"
    valid = {"type": "http", "host": "valid.test", "ts": 1, "bytes_out": 10, "canaries": []}
    path.write_text(json.dumps(bad) + "\n" + json.dumps(valid) + "\n")
    job.session.proxy = SimpleNamespace(events_file=path)
    job._pump()
    assert [e["host"] for e in job.hub.events if e["kind"] == "req"] == ["valid.test"]
    warnings = []
    assert report.load_events(path, warnings=warnings) == [valid]
    assert warnings


def test_relative_app_bundle_is_resolved_before_changing_working_directory(tmp_path, monkeypatch):
    import plistlib

    bundle = tmp_path / "Fake IDE.app"
    (bundle / "Contents/MacOS").mkdir(parents=True)
    with (bundle / "Contents/Info.plist").open("wb") as f:
        plistlib.dump({"CFBundleExecutable": "FakeIDE"}, f)
    exe = bundle / "Contents/MacOS/FakeIDE"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    assert apps.resolve("Fake IDE.app").executable == exe


@pytest.mark.parametrize("reason", ["expired", "cancelled"])
def test_late_terminal_helper_does_not_start_command(tmp_path, reason):
    import time
    from whatsent import child

    marker = tmp_path / "must-not-run"
    cancelled = tmp_path / "cancelled"
    if reason == "cancelled":
        cancelled.touch()
    spec = tmp_path / "agent.json"
    spec.write_text(json.dumps({
        "command": [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
        "cwd": str(tmp_path), "env": {}, "pidfile": str(tmp_path / "agent.pid"),
        "exitfile": str(tmp_path / "agent.exit"), "cancel_file": str(cancelled),
        "launch_deadline": time.monotonic() + (-1 if reason == "expired" else 30),
    }))
    assert child.main([str(spec)]) == 125
    assert not marker.exists()
    assert (tmp_path / "agent.exit").read_text() == "125"
