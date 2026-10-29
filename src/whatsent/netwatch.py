"""Sample the agent's open sockets to spot traffic that skipped the proxy.

This only sees connections that are open at sample time, so very short
connections can be missed. It catches tools that ignore proxy settings.
"""

from __future__ import annotations

import socket
import threading

import psutil


class ConnectionSampler:
    def __init__(self, pid: int, proxy_port: int, interval: float = 0.2):
        self.pid = pid
        self.proxy_port = proxy_port
        self.interval = interval
        self.seen: dict[tuple[str, int, str], dict] = {}
        self.warnings: set[str] = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> list[dict]:
        self._stop.set()
        self._thread.join(timeout=5)
        return sorted(self.seen.values(), key=lambda c: (c["local"], c["ip"], c["port"]))

    def _run(self) -> None:
        while not self._stop.is_set():
            self.sample()
            self._stop.wait(self.interval)

    def sample(self) -> None:
        try:
            root = psutil.Process(self.pid)
            procs = [root, *root.children(recursive=True)]
        except psutil.AccessDenied:
            self.warnings.add("agent process inspection was denied; bypass detection is incomplete")
            return
        except psutil.Error:
            return
        for proc in procs:
            try:
                conns = proc.net_connections(kind="inet")
                name = proc.name()
            except psutil.AccessDenied:
                self.warnings.add("socket inspection was denied for an agent process; bypass detection is incomplete")
                continue
            except psutil.Error:
                continue
            for c in conns:
                if not c.raddr or c.raddr.port == 53:  # DNS lookups carry no payload
                    continue
                if c.raddr.port == self.proxy_port and _is_loopback(c.raddr.ip):
                    continue
                proto = "udp" if c.type == socket.SOCK_DGRAM else "tcp"
                key = (c.raddr.ip, c.raddr.port, proto)
                if key not in self.seen:
                    self.seen[key] = {"ip": c.raddr.ip, "port": c.raddr.port, "proto": proto,
                                      "process": name, "local": _is_loopback(c.raddr.ip)}


def _is_loopback(ip: str) -> bool:
    return ip.startswith("127.") or ip in ("::1", "::ffff:127.0.0.1") or ip.startswith("::ffff:127.")
