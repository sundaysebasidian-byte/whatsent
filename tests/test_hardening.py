"""Regression cases for interrupted capture, concurrent runs, and untrusted inputs."""

import copy
import gzip
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from whatsent import board, detect, diskwatch, report
from whatsent.check import validate
from whatsent.cli import Session, build_parser, save_result


def session(out):
    args = build_parser().parse_args([
        "run", "--out", str(out), "--no-default-watch", "--agent-version", "test", "--", sys.executable,
    ])
    return Session(args, args.command[1:])


def example():
    path = Path(__file__).parents[1] / "examples/results/example-agent-a.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_simultaneous_sessions_preserve_existing_workspace(tmp_path):
    first, second = session(tmp_path), session(tmp_path)
    first.prepare()
    marker = first.workspace / "keep.txt"
    marker.write_text("original")
    original = first.canaries_file.read_bytes()
    second.prepare()
    assert first.run_dir != second.run_dir
    assert first.canaries_file.read_bytes() == original
    assert marker.read_text() == "original"


def test_result_exports_do_not_overwrite_concurrent_batches(tmp_path):
    source = tmp_path / "result.json"
    source.write_text("{}")
    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(lambda _: save_result(source, tmp_path / "results", {"agent": "same"}), range(24)))
    assert len(set(paths)) == 24
    assert all(p.read_text() == "{}" for p in paths)


def test_snapshot_limits_one_large_directory(tmp_path):
    for i in range(20):
        (tmp_path / str(i)).write_text("x")
    files, partial = diskwatch.snapshot([tmp_path], [], max_files=3)
    assert len(files) == 3
    assert partial == [str(tmp_path)]


def test_snapshot_reports_permission_denied_apart_from_partial_scans(tmp_path, monkeypatch):
    (tmp_path / "ok").write_text("x")
    denied = tmp_path / "protected"
    denied.mkdir()
    broken = tmp_path / "broken"
    broken.mkdir()
    real = os.scandir

    def scandir(path):
        if str(path) == str(denied):
            raise PermissionError(1, "Operation not permitted", str(path))
        if str(path) == str(broken):
            raise OSError(5, "Input/output error", str(path))
        return real(path)

    monkeypatch.setattr(os, "scandir", scandir)
    skipped = []
    files, partial = diskwatch.snapshot([tmp_path], [], unreadable=skipped)
    assert set(files) == {str(tmp_path / "ok")}
    assert skipped == [str(denied)]
    assert partial == [str(tmp_path)]  # the I/O error still makes the root partial
    (tmp_path / "broken").rmdir()
    _, partial = diskwatch.snapshot([tmp_path], [], unreadable=[])
    assert partial == []
    _, partial = diskwatch.snapshot([tmp_path], [])  # callers that do not ask keep the stricter reading
    assert partial == [str(tmp_path)]


def test_a_root_that_cannot_be_listed_is_partial(tmp_path, monkeypatch):
    def scandir(path):
        raise PermissionError(1, "Operation not permitted", str(path))

    monkeypatch.setattr(os, "scandir", scandir)
    files, partial = diskwatch.snapshot([tmp_path], [], unreadable=[])
    assert files == {} and partial == [str(tmp_path)]


def test_decoding_gaps_in_browser_caches_do_not_make_disk_findings_incomplete(tmp_path):
    token = "wsc0deadbeefcafef00d"
    stray = b"0\r\xa7" + b"\x1f\x8b\x08\x00" + b"not a gzip stream" * 4
    for folder in ("Cache_Data", "other"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "entry").write_bytes(stray)
    (tmp_path / "Cache_Data" / "hit").write_bytes(stray + token.encode())
    after, _ = diskwatch.snapshot([tmp_path], [])
    disk = diskwatch.diff({}, after, detect.Matcher({"task_file": token}))
    assert disk["incomplete_files"] == [str(tmp_path / "other" / "entry")]
    assert [leak["path"] for leak in disk["leaks"]] == [str(tmp_path / "Cache_Data" / "hit")]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX special files")
def test_snapshot_ignores_symlinks_and_named_pipes(tmp_path):
    ordinary = tmp_path / "ordinary"
    ordinary.write_text("x")
    (tmp_path / "link").symlink_to(ordinary)
    os.mkfifo(tmp_path / "pipe")
    files, partial = diskwatch.snapshot([tmp_path], [])
    assert set(files) == {str(ordinary)}
    assert not partial


def test_expansion_keeps_a_bounded_prefix(monkeypatch):
    monkeypatch.setattr(detect, "MAX_EXPANDED", 128)
    data = gzip.compress(b"wsc0deadbeefcafef00d" + b"x" * 4096)
    expanded = detect.expand(data)
    assert 0 < sum(map(len, expanded[1:])) <= 128
    assert detect.Matcher({"task_file": "wsc0deadbeefcafef00d"}).scan(data) == {"task_file"}


@pytest.mark.parametrize("control", [[], {}, 42, None])
def test_validator_rejects_wrong_control_types(control):
    result = example()
    result["control"] = control
    assert validate(result)


def test_validator_checks_destination_references():
    result = example()
    result["canaries"]["task_file"]["sent_to"] = ["unlisted.invalid"]
    assert validate(result)


@pytest.mark.parametrize("field,value", [("platform", "Windows AMD64"), ("capture", "local:agent")])
def test_board_keeps_distinct_capture_environments_apart(field, value):
    first = example()
    second = copy.deepcopy(first)
    second[field] = value
    assert len(board.latest_per_agent([first, second])) == 2


def test_board_does_not_publish_invalid_results(tmp_path):
    result = example()
    result["private_prompt"] = "must never be published"
    source = tmp_path / "input.json"
    source.write_text(json.dumps(result))
    out = tmp_path / "site"
    assert board.build([source], out) == 1
    assert not (out / "leaderboard.json").exists()


def test_http_completion_does_not_double_count_uploads(tmp_path):
    event = {"type": "http", "flow_id": "one", "host": "example.test", "bytes_out": 42,
             "bytes_in": 0, "canaries": ["dotenv"], "ts": 1}
    completed = {**event, "bytes_in": 100, "status": 200, "ts": 2}
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join(map(json.dumps, [event, completed])))
    loaded = report.load_events(path)
    assert len(loaded) == 1
    assert loaded[0]["bytes_in"] == 100
    assert loaded[0]["ts"] == 1


def test_capture_failure_stops_the_agent(tmp_path):
    from whatsent.cli import popen

    run = session(tmp_path)
    run.command = [sys.executable, "-c", "import time; time.sleep(120)"]
    try:
        run.prepare()
        run.start_proxy()
        run.launch(popen)
        run.proxy.proc.terminate()
        run.proxy.proc.wait(timeout=10)
        run.wait()
        assert run.exit_code == "capture_failed"
        assert run.agent.wait(timeout=5) is not None
        assert any("incomplete" in w for w in run.warnings)
    finally:
        run.stop_agent()
        run.close(final=True)


def test_demo_resources_close_their_listening_sockets(tmp_path):
    import socket
    from whatsent.demo import setup

    args, _ = setup(tmp_path)
    ports = {address[1] for address in json.loads(args.proxy_env["WHATSENT_REMAP"]).values()}
    try:
        for port in ports:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                pass
    finally:
        args.demo_cleanup()
    for port in ports:
        with socket.socket() as sock:
            assert sock.connect_ex(("127.0.0.1", port)) != 0


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_nonfinite_timeout_is_refused(value):
    from whatsent.cli import main

    assert main(["run", f"--timeout={value}", "--", "unused"]) == 2


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "zstd", "br"])
def test_http_decoders_limit_expanded_output(monkeypatch, encoding):
    import zlib
    import brotli

    payload = b"wsc0deadbeefcafef00d" + b"x" * 8192
    compressors = {"gzip": gzip.compress, "deflate": zlib.compress, "br": brotli.compress}
    if encoding == "zstd":
        module = detect._zstd_module()
        compress = module.compress if hasattr(module, "compress") else module.ZstdCompressor().compress
    else:
        compress = compressors[encoding]
    monkeypatch.setattr(detect, "MAX_EXPANDED", 128)
    issues = []
    data = detect.decode_body(compress(payload), encoding, issues)
    assert issues
    # Older Brotli builds cannot bound output; they return the raw body and flag it.
    if not any("unavailable" in issue for issue in issues):
        assert len(data) <= 128 and data.startswith(b"wsc0deadbeefcafef00d")


def test_warnings_prevent_a_clean_board_verdict():
    result = example()
    result["warnings"] = 1
    assert board.status(result) == ("warn", "incomplete: run has warnings")


def test_partial_archive_scan_is_bounded_across_members(monkeypatch):
    import io
    import zipfile

    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for i in range(10):
            archive.writestr(f"{i}.txt", b"x" * 1000)
    monkeypatch.setattr(detect, "MAX_EXPANDED", 100)
    issues = []
    blobs = detect.expand(packed.getvalue(), issues=issues)
    assert sum(map(len, blobs[1:])) <= 100 and issues


def test_canary_changes_are_separate_board_rows():
    first, second = example(), example()
    second["canaries"].pop("git_history")
    assert len(board.latest_per_agent([first, second])) == 2


def test_partial_disk_reads_are_reported(tmp_path, monkeypatch):
    source = tmp_path / "large.log"
    source.write_bytes(b"x" * 1000)
    monkeypatch.setattr(diskwatch, "MAX_SCAN_BYTES", 128)
    after, _ = diskwatch.snapshot([tmp_path], [])
    result = diskwatch.diff({}, after, detect.Matcher({}))
    assert result["incomplete_files"] == [str(source)]


def test_plaintext_starting_with_x_is_not_a_broken_archive():
    issues = []
    detect.Matcher({}).scan(b"xml and ordinary text", issues=issues)
    assert not issues


def test_socket_permission_denial_is_visible(monkeypatch):
    import psutil
    from whatsent import netwatch

    def denied(pid):
        raise psutil.AccessDenied(pid)

    monkeypatch.setattr(netwatch.psutil, "Process", denied)
    sampler = netwatch.ConnectionSampler(123, 456)
    sampler.sample()
    assert any("incomplete" in warning for warning in sampler.warnings)


def test_collect_prefers_run_results_and_ignores_workspace_files(tmp_path):
    result = example()
    (tmp_path / "result.json").write_text(json.dumps(result))
    (tmp_path / "report.json").write_text("{not a public result}")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "credentials.json").write_text('{"password": "fake"}')
    assert board.collect([tmp_path, tmp_path / "result.json"]) == [result]


@pytest.mark.parametrize("bad", [b'{"type":', b'\xff\xfe', b'[]', b'{}', b'{"type":"http","host":"x","bytes_out":-1}'])
def test_damaged_journal_preserves_good_events_and_warns(tmp_path, bad):
    event = {"type": "http", "host": "example.test", "bytes_out": 42, "ts": 1}
    path = tmp_path / "events.jsonl"
    path.write_bytes(json.dumps(event).encode() + b"\n" + bad + b"\n")
    warnings = []
    assert report.load_events(path, warnings=warnings) == [event]
    assert warnings and "incomplete" in warnings[0]


def test_missing_journal_warns(tmp_path):
    warnings = []
    assert report.load_events(tmp_path / "missing.jsonl", warnings=warnings) == []
    assert warnings


def test_ca_cleanup_failure_is_visible(tmp_path, monkeypatch, capsys):
    from whatsent.capture import Proxy

    run = session(tmp_path)
    run.proxy = Proxy(tmp_path, tmp_path / "canaries.json", tmp_path / "events.jsonl")
    run.proxy.confdir.mkdir()
    key = run.proxy.confdir / "mitmproxy-ca.pem"
    key.write_text("synthetic test key")
    unlink = Path.unlink

    def denied(path, *args, **kwargs):
        if path == key:
            raise PermissionError("synthetic denial")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", denied)
    run.close(final=True)
    run.close(final=True)
    assert key.exists() and len(run.warnings) == 1
    assert "private key" in run.warnings[0]
    assert "private key" in capsys.readouterr().err


def test_damaged_journal_warning_reaches_the_export(tmp_path):
    from whatsent.capture import Proxy

    run = session(tmp_path)
    run.prepare()
    run.proxy = Proxy(run.run_dir, run.canaries_file, run.run_dir / "events.jsonl")
    run.proxy.events_file.write_bytes(b'{"type":"http"')
    summary, html = run.finish()
    assert any("journal" in warning for warning in summary["warnings"])
    assert "journal" in html.read_text()
    assert json.loads(html.with_name("result.json").read_text())["warnings"] > 0
