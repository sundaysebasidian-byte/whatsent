"""End-to-end through the real proxy: ``whatsent demo`` and a Codex-like agent. Offline."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mitmproxy")
from whatsent import demo  # noqa: E402
from whatsent.cli import main, run  # noqa: E402
from whatsent.demo import AGENT_NAME, HOSTS  # noqa: E402


def test_capture_does_not_import_tornado_http_stack(tmp_path):
    guard = tmp_path / "guard"
    guard.mkdir()
    attempted = tmp_path / "tornado-imported"
    (guard / "sitecustomize.py").write_text('''
import importlib.abc
import os
import sys
from pathlib import Path
with open(os.environ["TORNADO_GUARD_MARKER"], "a") as marker:
    marker.write(str(os.getpid()) + "\\n")
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "tornado" or fullname.startswith("tornado."):
            Path(os.environ["TORNADO_IMPORT_MARKER"]).write_text(fullname)
            raise ImportError("Tornado is not part of the whatsent capture path")
sys.meta_path.insert(0, Guard())
''', encoding="utf-8")
    activated = tmp_path / "guard-activated"
    env = dict(os.environ, TORNADO_IMPORT_MARKER=str(attempted), TORNADO_GUARD_MARKER=str(activated))
    env["PYTHONPATH"] = os.pathsep.join([str(guard), str(Path(__file__).parents[1] / "src"),
                                       env.get("PYTHONPATH", "")])
    result = subprocess.run([sys.executable, "-m", "whatsent", "demo", "--out", str(tmp_path / "out")],
                            env=env, cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert len(set(activated.read_text().splitlines())) >= 3  # CLI, proxy and simulated agent
    assert not attempted.exists(), "Tornado was imported by the CLI or a capture subprocess"
    (output,) = (tmp_path / "out").glob("*/result.json")
    assert json.loads(output.read_text())["totals"]["leaked"] == 3


def test_demo_end_to_end(tmp_path):
    out = tmp_path / "out"
    assert main(["demo", "--out", str(out)]) == 0

    (run_dir,) = out.iterdir()
    s = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in s["canaries"]}
    assert s["agent"] == AGENT_NAME and s["sample"] is True
    assert json.loads((run_dir / "result.json").read_text(encoding="utf-8"))["sample"] is True
    assert main(["check", str(run_dir / "result.json")]) == 0
    board_out = tmp_path / "board"
    assert main(["board", str(out), "-o", str(board_out)]) == 0
    (row,) = json.loads((board_out / "leaderboard.json").read_text(encoding="utf-8"))["results"]
    assert row["sample"] is True and row["agent"] == AGENT_NAME

    assert by_id["dotenv"]["sent_to"] == [HOSTS["telemetry"]]  # plain HTTP
    assert by_id["task_file"]["sent_to"] == [HOSTS["api"]]  # HTTPS + gzip, decrypted via our CA
    assert by_id["file_name"]["sent_to"] == [HOSTS["api"]]  # directory listing
    assert by_id["unrelated_source"]["sent_to"] == []
    assert by_id["credentials"]["sent_to"] == []
    assert s["totals"]["leaked_sensitive"] == 1
    assert any(d["host"] == HOSTS["upload"] and d["bytes_out"] > 300 * 1024 for d in s["destinations"])

    # The fake home is redacted to ~ in the report.
    assert by_id["credentials"]["on_disk"] == ["~/.demo-agent/cache/snapshot.tar.gz"]
    assert [d["path"] for d in s["disk"]["suspicious"]] == ["~/.demo-agent/cache/upload.bin"]

    assert any(g["host"] == HOSTS["pinned"] for g in s["not_inspected"]["tls_failed"])
    assert any(c["local"] for c in s["not_inspected"]["direct_connections"])

    html = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "canaries left this machine" in html and AGENT_NAME in html
    assert by_id["dotenv"]["token"] not in html  # report never prints the planted values


@pytest.mark.parametrize("silent", [False, True])
def test_task_file_is_the_positive_control(tmp_path, silent, request):
    """A zstd-compressed upload through the real proxy is decoded; an agent that does the task
    without the task file ever being seen gets an unconfirmed result, not a clean one."""
    tls = demo.self_signed(tmp_path)
    resources = ExitStack()
    request.addfinalizer(resources.close)
    port = demo._serve(tls, resources=resources)
    host = HOSTS["api"]
    command = [sys.executable, str(Path(__file__).with_name("codex_like_agent.py")),
               "--api", f"https://{host}/backend-api/codex/responses"] + (["--silent"] if silent else [])
    out = tmp_path / "out"
    args = argparse.Namespace(
        out=out, port=None, watch=[], no_default_watch=True, app=None, capture="env",
        mitm_set=["ssl_insecure=true"], name="codex-like", agent_version=None,
        proxy_env={"WHATSENT_REMAP": json.dumps({host: ["127.0.0.1", port]})}, home=None, sample=False)
    assert run(args, command) == 0

    (run_dir,) = out.iterdir()
    s = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    task = {c["id"]: c for c in s["canaries"]}["task_file"]
    assert s["control"]["task_fixed"] is True
    if silent:
        assert task["sent_to"] == [] and s["control"]["status"] == "unconfirmed"
        assert "Result not confirmed" in (run_dir / "report.html").read_text(encoding="utf-8")
    else:
        assert task["sent_to"] == [host] and s["control"]["status"] == "ok"
