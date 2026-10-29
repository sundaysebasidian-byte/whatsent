from __future__ import annotations

import gzip
import http.server
import json
import plistlib
import stat
import struct
import sys
import threading
from pathlib import Path

import pytest

from whatsent import apps
from whatsent.capture import Proxy
from whatsent.detect import Matcher

TOKEN = "wsc2deadbeefcafef00d"


def test_resolve_app_bundle(tmp_path):
    bundle = tmp_path / "Fake IDE.app"
    (bundle / "Contents" / "MacOS").mkdir(parents=True)
    with open(bundle / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump({"CFBundleExecutable": "FakeIDE"}, f)
    app = apps.resolve(str(bundle))
    assert app.name == "Fake IDE"
    assert app.executable == bundle / "Contents" / "MacOS" / "FakeIDE"


def test_resolve_prefers_binary_next_to_launcher_script(tmp_path):
    (tmp_path / "bin").mkdir()
    for p in (tmp_path / "bin" / "fakeide", tmp_path / "fakeide"):
        p.write_text("#!/bin/sh\n")
        p.chmod(p.stat().st_mode | stat.S_IXUSR)
    assert apps.resolve(str(tmp_path / "bin" / "fakeide")).executable == tmp_path / "fakeide"


def test_resolve_known_app_on_windows(tmp_path, monkeypatch):
    exe = tmp_path / "Programs" / "cursor" / "Cursor.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ProgramFiles", raising=False)
    assert apps.resolve("cursor") == apps.ResolvedApp("Cursor", exe)


def test_resolve_unknown_name():
    with pytest.raises(apps.AppError, match="unknown app"):
        apps.resolve("definitely-not-an-ide")


def test_app_command_routes_through_proxy(tmp_path):
    import base64
    import hashlib
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from whatsent.demo import self_signed

    app = apps.ResolvedApp("X", tmp_path / "x")
    cert, _ = self_signed(tmp_path)
    key = x509.load_pem_x509_certificate(cert.read_bytes()).public_key()
    expected = base64.b64encode(hashlib.sha256(key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    cmd = apps.command(app, 8123, tmp_path / "ws", ["--verbose"], cert)
    assert cmd[0] == str(tmp_path / "x") and cmd[-1] == str(tmp_path / "ws")
    assert "--proxy-server=http://127.0.0.1:8123" in cmd
    assert f"--ignore-certificate-errors-spki-list={expected}" in cmd
    assert "--ignore-certificate-errors" not in cmd


def test_embedded_compressed_messages():
    m = Matcher({"x": TOKEN})
    msg = gzip.compress(f'{{"code":"{TOKEN}"}}'.encode())
    frame = b"\x01" + struct.pack(">I", len(msg)) + msg  # gRPC / Connect envelope
    assert m.scan(b"\x00\x00\x00\x00\x02{}" + frame + b"trailing") == {"x"}


def test_local_capture_problem_is_reported(tmp_path):
    proxy = Proxy(tmp_path, tmp_path / "c.json", tmp_path / "e.jsonl", local_spec="Cursor")
    proxy.log_file.write_text("Local redirector started.\nError: eBPF initialization failed\n")
    assert "did not start" in proxy.local_capture_problem()
    proxy.log_file.write_text("Local redirector started.\n")
    assert proxy.local_capture_problem() is None


class _Sink(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


def test_run_app_end_to_end(tmp_path, monkeypatch):
    pytest.importorskip("mitmproxy")
    from whatsent.cli import main

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Sink)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    if sys.platform == "win32":  # no shebangs: a .cmd shim stands in for the .exe
        fake = tmp_path / "fakeide.cmd"
        fake.write_text(f'@"{sys.executable}" "{Path(__file__).with_name("fake_app.py")}" %*\n')
    else:
        fake = tmp_path / "fakeide"
        fake.write_text(f"#!{sys.executable}\n" + Path(__file__).with_name("fake_app.py").read_text())
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("FAKE_APP_URL", f"http://127.0.0.1:{srv.server_address[1]}/v1/chat")

    out = tmp_path / "out"
    assert main(["run", "--out", str(out), "--no-default-watch", "--app", str(fake)]) == 0
    (run_dir,) = out.iterdir()
    s = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert s["agent"] == "fakeide" and s["kind"] == "app"
    assert {c["id"]: c for c in s["canaries"]}["task_file"]["sent_to"] == ["127.0.0.1"]
    assert any("exited after" in w for w in s["warnings"])  # quick exit looks like a hand-over
