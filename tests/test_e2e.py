"""End-to-end: ``whatsent demo`` runs the simulated agent under ``whatsent run``. Offline."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("mitmproxy")
from whatsent.cli import main  # noqa: E402
from whatsent.demo import AGENT_NAME, HOSTS  # noqa: E402


def test_demo_end_to_end(tmp_path):
    out = tmp_path / "out"
    assert main(["demo", "--out", str(out)]) == 0

    (run_dir,) = out.iterdir()
    s = json.loads((run_dir / "report.json").read_text())
    by_id = {c["id"]: c for c in s["canaries"]}
    assert s["agent"] == AGENT_NAME and s["sample"] is True
    assert json.loads((run_dir / "result.json").read_text())["sample"] is True

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

    html = (run_dir / "report.html").read_text()
    assert "canaries left this machine" in html and AGENT_NAME in html
    assert by_id["dotenv"]["token"] not in html  # report never prints the planted values
