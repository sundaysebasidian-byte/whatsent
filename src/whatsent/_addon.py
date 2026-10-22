"""mitmproxy addon loaded by ``whatsent run``. Writes one JSON line per event.

Paths come from the environment: WHATSENT_CANARIES (JSON file with the
planted canaries) and WHATSENT_EVENTS (JSONL output).
"""

from __future__ import annotations

import json
import os
import threading
import time

from whatsent.detect import Matcher


class Recorder:
    def __init__(self) -> None:
        with open(os.environ["WHATSENT_CANARIES"]) as f:
            canaries = json.load(f)
        self.matcher = Matcher({c["id"]: c["token"] for c in canaries})
        self.out = open(os.environ["WHATSENT_EVENTS"], "a", buffering=1)
        self.lock = threading.Lock()

    def _write(self, record: dict) -> None:
        record["ts"] = time.time()
        with self.lock:
            self.out.write(json.dumps(record) + "\n")

    def _http(self, flow, error: str | None = None) -> None:
        req = flow.request
        body = req.get_content(strict=False) or b""
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
        })


addons = [Recorder()]
