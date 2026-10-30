"""Proxy startup and leaderboard inputs must identify the actual recorder/run."""

import json
import socket
from pathlib import Path

import pytest

from whatsent import board
from whatsent.capture import Proxy, upstream_from_env
from whatsent.cli import main


def example():
    return json.loads((Path(__file__).parents[1] / "examples/results/example-agent-a.json").read_text())


def test_occupied_port_and_old_ca_do_not_confirm_recorder_start(tmp_path):
    with socket.socket() as other:
        other.bind(("127.0.0.1", 0))
        other.listen()
        canaries = tmp_path / "canaries.json"
        canaries.write_text("[]")
        proxy = Proxy(tmp_path, canaries, tmp_path / "events.jsonl", port=other.getsockname()[1])
        proxy.confdir.mkdir()
        proxy.ca_cert.write_text("stale public certificate")
        try:
            with pytest.raises(RuntimeError):
                proxy.start(timeout=10)
            assert proxy.proc.poll() is not None
            assert proxy.log.closed
            with socket.create_connection(other.getsockname(), timeout=1):
                pass  # an unrelated listener remains untouched
        finally:
            proxy.stop()
            proxy.forget_keys()


@pytest.mark.parametrize("value", ["", "http://[", "http://", "http://proxy:abc", "http://proxy:70000",
                                 "http://proxy/path", "http://user:synthetic-secret@proxy:80"])
def test_bad_explicit_upstream_is_a_usage_error(value, monkeypatch, capsys):
    from whatsent import cli

    def should_not_run(*args, **kwargs):
        pytest.fail("invalid proxy must be rejected before starting a run")

    monkeypatch.setattr(cli, "run", should_not_run)
    assert main(["run", "--upstream", value, "--", "unused"]) == 2
    assert "synthetic-secret" not in capsys.readouterr().err


@pytest.mark.parametrize("value", ["http://[", "http://", "http://proxy:abc", "http://proxy:70000",
                                 "http://proxy/path", "http://user:synthetic-secret@proxy:80"])
def test_bad_environment_upstream_warns_without_exposing_credentials(value):
    url, warning = upstream_from_env({"HTTPS_PROXY": value})
    assert url is None and warning
    assert "synthetic-secret" not in warning


@pytest.mark.parametrize("command", ["run", "ui"])
@pytest.mark.parametrize("port", ["-1", "65536"])
def test_invalid_listen_port_is_a_usage_error(command, port, monkeypatch):
    from whatsent import cli, ui

    def should_not_run(*args, **kwargs):
        pytest.fail("invalid port must be rejected before starting a server")

    monkeypatch.setattr(cli, "run", should_not_run)
    monkeypatch.setattr(ui, "run_ui", should_not_run)
    suffix = ["--", "unused"] if command == "run" else []
    assert main([command, "--port", port, *suffix]) == 2


def test_directory_and_explicit_report_are_only_counted_once(tmp_path):
    result = example()
    run = tmp_path / "run"
    run.mkdir()
    (run / "result.json").write_text(json.dumps(result))
    # The report is intentionally not valid: the preferred result must be selected first.
    (run / "report.json").write_text("{}")
    assert board.collect([tmp_path, run / "report.json"]) == [result]


def test_explicit_nested_run_does_not_double_count_its_batch(tmp_path):
    result = example()
    batch = board.combine([result, result])
    (tmp_path / "result.json").write_text(json.dumps(batch))
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "result.json").write_text(json.dumps(result))
    assert board.collect([tmp_path, nested / "result.json"]) == [batch]


def test_invalid_environment_proxy_never_silently_selects_direct_mode(tmp_path, monkeypatch):
    from whatsent.cli import Session, build_parser

    monkeypatch.setenv("HTTPS_PROXY", "socks5://127.0.0.1:1080")
    args = build_parser().parse_args(["run", "--out", str(tmp_path), "--", "fake"])
    with pytest.raises(RuntimeError, match="upstream"):
        Session(args, ["fake"]).resolve_upstream()
    args.upstream = "none"
    assert Session(args, ["fake"]).resolve_upstream() is None


def test_oversized_counts_are_rejected_before_rendering(tmp_path):
    result = example()
    result["destinations"][0]["bytes_out"] = 10 ** 400
    result["totals"]["bytes_out"] = sum(d["bytes_out"] for d in result["destinations"])
    source = tmp_path / "large-count.json"
    source.write_text(json.dumps(result))
    assert board.build([source], tmp_path / "site") == 1
    assert not (tmp_path / "site/index.html").exists()


@pytest.mark.parametrize("value", ["20261030", "2026-W44-5"])
def test_result_dates_require_the_documented_calendar_format(value):
    from whatsent.check import validate

    result = example()
    result["date"] = value
    assert any("date" in problem for problem in validate(result))
