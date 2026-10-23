"""mitmproxy addon loaded by ``whatsent run``. Writes one JSON line per event.

Paths come from the environment: WHATSENT_CANARIES (JSON file with the
planted canaries) and WHATSENT_EVENTS (JSONL output). WHATSENT_REMAP, used only
by ``whatsent demo``, maps made-up host names to local test servers.
"""

from __future__ import annotations

import json
import os
import threading
import time

from whatsent.detect import Matcher, expand


class Recorder:
    def __init__(self) -> None:
        with open(os.environ["WHATSENT_CANARIES"]) as f:
            canaries = json.load(f)
        self.matcher = Matcher({c["id"]: c["token"] for c in canaries})
        self.out = open(os.environ["WHATSENT_EVENTS"], "a", buffering=1)
        self.lock = threading.Lock()
        self.remap = {h: tuple(a) for h, a in json.loads(os.environ.get("WHATSENT_REMAP", "{}")).items()}

    def server_connect(self, data) -> None:
        if self.remap and data.server.address and data.server.address[0] in self.remap:
            data.server.address = self.remap[data.server.address[0]]

    def _write(self, record: dict) -> None:
        record["ts"] = time.time()
        with self.lock:
            self.out.write(json.dumps(record) + "\n")

    @staticmethod
    def _via(conn) -> str:
        # "local": caught by OS-level capture, i.e. this traffic ignored the proxy settings.
        mode = getattr(conn, "proxy_mode", None)
        return "local" if mode is not None and getattr(mode, "type_name", "") == "local" else "proxy"

    def _http(self, flow, error: str | None = None) -> None:
        req = flow.request
        undecoded = None
        try:
            body = req.get_content() or b""  # undoes Content-Encoding: gzip, br, zstd...
        except ValueError:
            # Unknown or broken encoding. The matcher still unpacks what it can from the raw
            # bytes; if that finds nothing to unpack, the report lists the host as not inspected.
            body = req.raw_content or b""
            if len(expand(body, depth=1)) == 1:
                undecoded = req.headers.get("content-encoding", "?")
        head = f"{req.method} {req.url}\n".encode() + b"\n".join(
            k.encode() + b": " + v.encode() for k, v in req.headers.items(multi=True)
        )
        resp = flow.response
        self._write({
            "type": "http",
            "host": req.pretty_host,
            "port": req.port,
            "scheme": req.scheme,
            "method": req.method,
            "path": req.path[:300],
            "status": resp.status_code if resp else None,
            "bytes_out": len(head) + len(req.raw_content or b""),
            "bytes_in": len(resp.raw_content or b"") if resp else 0,
            "canaries": sorted(self.matcher.scan(head + b"\n" + body)),
            "error": error,
            "undecoded": undecoded,
            "via": self._via(flow.client_conn),
        })

    def response(self, flow) -> None:
        self._http(flow)

    def error(self, flow) -> None:
        self._http(flow, error=str(flow.error) if flow.error else "error")

    def websocket_message(self, flow) -> None:
        msg = flow.websocket.messages[-1]
        if not msg.from_client:
            return
        self._write({
            "type": "websocket",
            "host": flow.request.pretty_host,
            "port": flow.request.port,
            "path": flow.request.path[:300],
            "bytes_out": len(msg.content),
            "canaries": sorted(self.matcher.scan(msg.content)),
            "via": self._via(flow.client_conn),
        })

    def tls_failed_client(self, data) -> None:
        # The agent refused our certificate: likely certificate pinning or a
        # private trust store. Its traffic to this host was not inspected.
        server = data.context.server
        host = data.conn.sni or (server.address[0] if server.address else None)
        self._write({
            "type": "tls_failed",
            "host": host,
            "port": server.address[1] if server.address else None,
            "error": data.conn.error,
            "via": self._via(data.conn),
        })


addons = [Recorder()]
