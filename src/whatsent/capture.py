"""Run mitmproxy (mitmdump) as a local proxy and build the agent's proxy environment."""

from __future__ import annotations

import os
import re
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ADDON = Path(__file__).with_name("_addon.py")
PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
# Where an existing proxy is looked up, in order of preference.
UPSTREAM_VARS = ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def normalize_upstream(value: str) -> str:
    """Use mitmproxy's own server grammar; errors must never echo proxy credentials."""
    from mitmproxy.net.server_spec import parse

    value = value.strip()
    if any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("invalid whitespace in proxy address")
    try:
        parts = urlsplit(value if "://" in value else f"http://{value}")
    except ValueError:
        raise ValueError("invalid proxy address") from None
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"{parts.scheme} proxies are unsupported")
    url = urlunsplit(parts)
    try:
        parse(url, "http")
    except ValueError:
        raise ValueError("invalid proxy host or port; paths and URL credentials are unsupported") from None
    return url


def upstream_from_env(env: dict[str, str]) -> tuple[str | None, str | None]:
    """The proxy the agent would have used without whatsent, as ``(url, problem)``.

    Behind a corporate or VPN proxy the agent can only reach the internet through it, so
    whatsent has to forward to it instead of connecting directly. Only HTTP(S) proxies work as
    mitmproxy upstreams; for anything else ``problem`` says why traffic may fail."""
    for var in UPSTREAM_VARS:
        value = env.get(var, "").strip()
        if not value:
            continue
        try:
            return normalize_upstream(value), None
        except ValueError as exc:
            return None, f"{var}: {exc}; traffic may not get out"
    return None, None


def hide_credentials(url: str) -> str:
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc=parts.netloc.rpartition("@")[2]))


class Proxy:
    def __init__(self, run_dir: Path, canaries_file: Path, events_file: Path,
                 port: int | None = None, mitm_options: list[str] | None = None,
                 extra_env: dict[str, str] | None = None, local_spec: str | None = None,
                 upstream: str | None = None):
        self.confdir = run_dir / "mitmproxy"
        self.log_file = run_dir / "mitmproxy.log"
        self.canaries_file = canaries_file
        self.events_file = events_file
        self.ready_file = run_dir / ".proxy-ready"
        self.port = port or free_port()
        self.mitm_options = mitm_options or []
        self.extra_env = extra_env or {}
        self.local_spec = local_spec  # mitmproxy "local" mode: OS-level capture by process
        self.upstream = upstream  # forward to this HTTP(S) proxy instead of connecting directly
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
        token = secrets.token_hex(16)
        env["WHATSENT_READY_FILE"] = str(self.ready_file)
        env["WHATSENT_READY_TOKEN"] = token
        # Make the addon's `import whatsent` work even when run from a source checkout.
        pkg_parent = str(Path(__file__).resolve().parent.parent)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [pkg_parent, env.get("PYTHONPATH")]))
        mode = f"upstream:{self.upstream}" if self.upstream else "regular"
        cmd = [
            sys.executable, "-c", "from mitmproxy.tools.main import mitmdump; mitmdump()",
            "--mode", f"{mode}@127.0.0.1:{self.port}",
            "--set", f"confdir={self.confdir}",
            "--set", "flow_detail=0",
            "-q", "-s", str(ADDON),
        ]
        if self.local_spec:
            cmd += ["--mode", f"local:{self.local_spec}"]
        for opt in self.mitm_options:
            cmd += ["--set", opt]
        self.log = open(self.log_file, "w", encoding="utf-8")
        # Own session (process group on Windows), so a Ctrl-C meant for the agent does not kill the proxy.
        if sys.platform == "win32":
            detach = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        else:
            detach = {"start_new_session": True}
        try:
            self.proc = subprocess.Popen(cmd, env=env, stdout=self.log, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, **detach)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self.proc.poll() is not None:
                    raise RuntimeError(f"mitmproxy exited early, see {self.log_file}")
                try:
                    ready = self.ready_file.read_text(encoding="utf-8") == token
                except (OSError, UnicodeError):
                    ready = False
                if ready and self.ca_cert.exists() and _port_open(self.port):
                    return
                time.sleep(0.1)
            raise RuntimeError(f"mitmproxy did not start within {timeout}s, see {self.log_file}")
        except BaseException:
            self.stop()
            raise

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

    def forget_keys(self) -> list[str]:
        """Delete the run's CA private key. Only the certificate stays, so a shared report
        folder cannot be used to impersonate servers to anything that trusted this run's CA."""
        warnings = []
        for name in ("mitmproxy-ca.pem", "mitmproxy-ca.p12", "mitmproxy-dhparam.pem"):
            try:
                (self.confdir / name).unlink()
            except FileNotFoundError:
                pass
            except OSError:
                warnings.append(f"could not remove CA private key material {self.confdir / name}; "
                                "keep this run directory private")
        return warnings

    def local_capture_problem(self) -> str | None:
        """Best-effort check that OS-level capture actually started (it needs a macOS system
        extension, root + eBPF on Linux or an admin terminal on Windows, and fails quietly otherwise)."""
        if not self.local_spec:
            return None
        try:
            log = self.log_file.read_text(encoding="utf-8", errors="replace")
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
            parts.append(Path(certifi.where()).read_text(encoding="utf-8"))
        except ImportError:
            pass
        parts.append(self.ca_cert.read_text(encoding="utf-8"))
        path.write_text("\n".join(parts), encoding="utf-8")
        return path


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0
