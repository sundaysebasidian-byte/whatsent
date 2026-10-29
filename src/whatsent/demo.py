"""``whatsent demo``: run a simulated agent against local servers, so anyone can see a
report in seconds without installing or logging in to a real agent. Fully offline.

The simulated agent talks to made-up ``*.demo-agent.test`` hosts; the proxy routes
them to servers on 127.0.0.1 (see ``WHATSENT_REMAP`` in the addon).
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import datetime
import http.server
import ipaddress
import json
import socketserver
import ssl
import sys
import tempfile
import threading
from pathlib import Path

from cryptography import x509  # installed with mitmproxy
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

AGENT_NAME = "demo-agent (simulated)"
HOSTS = {
    "api": "api.demo-agent.test",
    "telemetry": "telemetry.demo-agent.test",
    "upload": "sync.demo-agent.test",
    "pinned": "pinned.demo-agent.test",
}


class _Sink(http.server.BaseHTTPRequestHandler):
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
    sans = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            *(x509.DNSName(h) for h in HOSTS.values())]
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp / "server.pem", tmp / "server.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return cert_path, key_path


def _serve(tls: tuple[Path, Path] | None = None, *, resources: ExitStack) -> int:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Sink)
    resources.callback(srv.server_close)
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(*tls)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    resources.callback(srv.shutdown)
    return srv.server_address[1]


def _tcp_listener(resources: ExitStack) -> int:
    stopped = threading.Event()

    class Hold(socketserver.BaseRequestHandler):
        def handle(self):
            stopped.wait(3)

    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Hold)
    srv.daemon_threads = True
    resources.callback(srv.server_close)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    resources.callback(srv.shutdown)
    resources.callback(stopped.set)
    return srv.server_address[1]


def setup(out: Path, pace: float = 0.0) -> tuple[argparse.Namespace, list[str]]:
    """Start the local servers and return ``whatsent run`` arguments and the agent command.
    ``pace`` spaces out the simulated agent's requests, so ``whatsent ui`` can show them arrive."""
    tmp = Path(tempfile.mkdtemp(prefix="whatsent-demo-"))
    tls = self_signed(tmp)
    resources = ExitStack()
    try:
        http_port = _serve(resources=resources)
        https_port = _serve(tls, resources=resources)
        direct_port = _tcp_listener(resources)
    except BaseException:
        resources.close()
        raise
    home = tmp / "home"
    cache = home / ".demo-agent" / "cache"
    cache.mkdir(parents=True)

    remap = {HOSTS["telemetry"]: ["127.0.0.1", http_port]}
    remap.update({HOSTS[k]: ["127.0.0.1", https_port] for k in ("api", "upload", "pinned")})
    command = [
        sys.executable, "-m", "whatsent.demo_agent",
        "--api", f"https://{HOSTS['api']}/v1/chat",
        "--telemetry", f"http://{HOSTS['telemetry']}/v1/events",
        "--upload", f"https://{HOSTS['upload']}/v2/blobs",
        "--pinned", f"https://{HOSTS['pinned']}/v1/flags", "--pinned-ca", str(tls[0]),
        "--direct", f"127.0.0.1:{direct_port}",
        "--cache-dir", str(cache),
        "--pace", str(pace),
    ]
    run_args = argparse.Namespace(
        out=out, port=None, watch=[home], no_default_watch=True, app=None, capture="env",
        # Our fake upstream servers use a self-signed certificate.
        mitm_set=["ssl_insecure=true"], name=AGENT_NAME, agent_version=None, upstream="none",
        proxy_env={"WHATSENT_REMAP": json.dumps(remap)}, home=home, sample=True,
        demo_cleanup=resources.close,
    )
    return run_args, command


def run_demo(args: argparse.Namespace) -> int:
    from whatsent.cli import run  # late import: cli imports this module

    run_args, command = setup(args.out)
    print("whatsent: demo with a simulated agent and local servers; nothing leaves this machine.",
          file=sys.stderr)
    return run(run_args, command)
