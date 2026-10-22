"""Run mitmproxy (mitmdump) as a local proxy and build the agent's proxy environment."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

ADDON = Path(__file__).with_name("_addon.py")
PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Proxy:
    def __init__(self, run_dir: Path, canaries_file: Path, events_file: Path,
                 port: int | None = None, mitm_options: list[str] | None = None,
                 extra_env: dict[str, str] | None = None, local_spec: str | None = None):
        self.confdir = run_dir / "mitmproxy"
        self.log_file = run_dir / "mitmproxy.log"
        self.canaries_file = canaries_file
        self.events_file = events_file
        self.port = port or free_port()
        self.mitm_options = mitm_options or []
        self.extra_env = extra_env or {}
        self.local_spec = local_spec  # mitmproxy "local" mode: OS-level capture by process
        self.proc: subprocess.Popen | None = None

    @property
    def ca_cert(self) -> Path:
        return self.confdir / "mitmproxy-ca-cert.pem"

    def start(self, timeout: float = 30) -> None:
        self.confdir.mkdir(parents=True, exist_ok=True)
        self.events_file.touch()
        env = {k: v for k, v in os.environ.items() if k not in PROXY_VARS}
        env["WHATSENT_CANARIES"] = str(self.canaries_file)
        env["WHATSENT_EVENTS"] = str(self.events_file)
        env.update(self.extra_env)
        # Make the addon's `import whatsent` work even when run from a source checkout.
        pkg_parent = str(Path(__file__).resolve().parent.parent)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [pkg_parent, env.get("PYTHONPATH")]))
        cmd = [
            sys.executable, "-c", "from mitmproxy.tools.main import mitmdump; mitmdump()",
            "--mode", f"regular@127.0.0.1:{self.port}",
            "--set", f"confdir={self.confdir}",
            "--set", "flow_detail=0",
            "-q", "-s", str(ADDON),
        ]
        if self.local_spec:
            cmd += ["--mode", f"local:{self.local_spec}"]
        for opt in self.mitm_options:
            cmd += ["--set", opt]
        self.log = open(self.log_file, "w")
        # Own session, so a Ctrl-C meant for the agent does not kill the proxy.
        self.proc = subprocess.Popen(cmd, env=env, stdout=self.log, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, start_new_session=True)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"mitmproxy exited early, see {self.log_file}")
            if self.ca_cert.exists() and _port_open(self.port):
                return
            time.sleep(0.1)
        self.stop()
        raise RuntimeError(f"mitmproxy did not start within {timeout}s, see {self.log_file}")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if getattr(self, "log", None):
            self.log.close()

    def local_capture_problem(self) -> str | None:
        """Best-effort check that OS-level capture actually started (it needs a macOS system
        extension or root + eBPF on Linux, and fails quietly otherwise)."""
        if not self.local_spec:
            return None
        try:
            log = self.log_file.read_text(errors="replace")
        except OSError:
            return None
        if re.search(r"(?i)redirector.*(fail|exited)|ebpf.*fail|local.*mode.*(error|fail)", log):
            return f"system-level capture did not start, see {self.log_file}"
        return None

    def agent_env(self, base: dict[str, str], ca_bundle: Path) -> dict[str, str]:
        """Environment for the agent: route traffic through us and trust our CA."""
        env = dict(base)
        url = f"http://127.0.0.1:{self.port}"
        for var in PROXY_VARS:
            env[var] = url
        env["NO_PROXY"] = env["no_proxy"] = ""
        env["NODE_USE_ENV_PROXY"] = "1"  # Node >= 24 honours HTTP(S)_PROXY with this
        for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "GIT_SSL_CAINFO"):
            env[var] = str(ca_bundle)
        env["NODE_EXTRA_CA_CERTS"] = str(self.ca_cert)
        return env

    def write_ca_bundle(self, path: Path) -> Path:
        """System/certifi roots plus our CA, so tools that replace their trust store still work."""
        parts = []
        try:
            import certifi
            parts.append(Path(certifi.where()).read_text())
        except ImportError:
            pass
        parts.append(self.ca_cert.read_text())
        path.write_text("\n".join(parts))
        return path


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0
