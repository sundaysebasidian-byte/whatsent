"""End-to-end: run the mock agent under ``whatsent run`` against local fake servers. Offline."""

from __future__ import annotations

import datetime
import http.server
import ipaddress
import json
import socket
import ssl
import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("mitmproxy")
from cryptography import x509  # noqa: E402  (installed with mitmproxy)
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

from whatsent.cli import main  # noqa: E402

MOCK = Path(__file__).with_name("mock_agent.py")


class Sink(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


def self_signed(tmp: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName(
            [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp / "server.pem", tmp / "server.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return cert_path, key_path


def serve(tls: tuple[Path, Path] | None = None) -> int:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Sink)
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(*tls)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


def tcp_listener() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()

    def accept():
        while True:
            conn, _ = s.accept()
            threading.Timer(3, conn.close).start()

    threading.Thread(target=accept, daemon=True).start()
    return s.getsockname()[1]


def test_run_end_to_end(tmp_path):
    tls = self_signed(tmp_path)
    http_port, https_port = serve(), serve(tls)
    direct_port = tcp_listener()
    cache = tmp_path / "fakehome" / ".cache"
    cache.mkdir(parents=True)
    out = tmp_path / "out"

    code = main([
        "run", "--out", str(out), "--no-default-watch", "--watch", str(cache),
        "--mitm-set", "ssl_insecure=true",  # our fake upstream uses a self-signed cert
        "--", sys.executable, str(MOCK),
        "--http", f"http://127.0.0.1:{http_port}/telemetry",
        "--https", f"https://127.0.0.1:{https_port}/v1/upload",
        "--pinned", f"https://localhost:{https_port}/pinned", "--pinned-ca", str(tls[0]),
        "--direct", f"127.0.0.1:{direct_port}",
        "--cache-dir", str(cache),
    ])
    assert code == 0

    (run_dir,) = out.iterdir()
    s = json.loads((run_dir / "report.json").read_text())
    by_id = {c["id"]: c for c in s["canaries"]}

    assert by_id["dotenv"]["sent_to"] == ["127.0.0.1"]  # plain HTTP
    assert by_id["task_file"]["sent_to"] == ["127.0.0.1"]  # HTTPS + gzip, decrypted via our CA
    assert by_id["file_name"]["sent_to"] == ["127.0.0.1"]  # directory listing
    assert by_id["unrelated_source"]["sent_to"] == []
    assert by_id["credentials"]["sent_to"] == []
    assert s["totals"]["leaked_sensitive"] == 1

    paths = {d["path"] for d in s["disk"]["leaks"]}
    assert str(cache / "snapshot.tar.gz") in paths
    assert by_id["credentials"]["on_disk"] == [str(cache / "snapshot.tar.gz")]
    assert [d["path"] for d in s["disk"]["suspicious"]] == [str(cache / "upload.bin")]

    assert any(g["host"] == "localhost" for g in s["not_inspected"]["tls_failed"])
    assert any(c["port"] == direct_port for c in s["not_inspected"]["direct_connections"])

    html = (run_dir / "report.html").read_text()
    assert "canaries left this machine" in html
    assert by_id["dotenv"]["token"] not in html  # report never prints the planted values
