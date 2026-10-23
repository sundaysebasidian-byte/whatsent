"""``whatsent ui``: the same run as ``whatsent run``, driven from a local web page.

The server listens on 127.0.0.1 only. Every API call needs the token that is baked into
the page and a Host header naming this server, so other web pages open in the browser
cannot drive it (no CORS, and DNS rebinding fails the Host check). Live events go to the
page as Server-Sent Events; the page keeps their sequence numbers, so a reload replays
the run so far.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import psutil

from whatsent import __version__, apps, canary, report
from whatsent.cli import Session, print_summary

STATIC = Path(__file__).with_name("ui")
IDLE_AFTER = 30.0  # seconds without a request before suggesting to reopen the app
CLIS = {  # command -> shown name; only the ones on PATH can be picked
    "claude": "Claude Code",
    "codex": "Codex CLI",
    "gemini": "Gemini CLI",
    "qwen": "Qwen Code",
    "kimi": "Kimi CLI",
    "opencode": "opencode",
    "aider": "Aider",
}
RUN_ID = re.compile(r"^\d{8}-\d{6}$")
STALE_FILE = ".ui-running.json"


class UIError(Exception):
    def __init__(self, code: str, message: str = "", status: int = 400):
        super().__init__(message or code)
        self.code, self.status = code, status


class Hub:
    """Ordered log of events for the current run, with blocking reads for the event stream."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.cond = threading.Condition()

    def emit(self, event: str, **data) -> None:
        with self.cond:
            self.events.append({"seq": len(self.events) + 1, "kind": event, **data})
            self.cond.notify_all()

    def since(self, seq: int, timeout: float) -> list[dict]:
        with self.cond:
            if len(self.events) <= seq:
                self.cond.wait(timeout)
            return self.events[seq:]


def scan_tools() -> list[dict]:
    running = set()
    for proc in psutil.process_iter(["exe"]):
        try:
            if proc.info["exe"]:
                running.add(Path(proc.info["exe"]))
        except psutil.Error:
            continue
    tools = []
    for key, info in apps.KNOWN.items():
        try:
            app = apps.resolve(key)
        except apps.AppError:
            tools.append({"id": key, "name": info.name, "kind": "app", "installed": False})
            continue
        tools.append({"id": key, "name": app.name, "kind": "app", "installed": True,
                      "running": app.executable in running})
    for cmd, name in CLIS.items():
        tools.append({"id": cmd, "name": name, "kind": "cli", "installed": shutil.which(cmd) is not None})
    return tools


def detached(command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    """Start an app outside our process group, so Ctrl-C on ``whatsent ui`` reaches us first
    and we can close the app and still write the report."""
    if sys.platform == "win32":
        return subprocess.Popen(command, cwd=cwd, env=env, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    return subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)


class TerminalAgent:
    """A CLI agent running in a terminal window we opened (see ``whatsent.child``)."""

    def __init__(self, pidfile: Path, exitfile: Path, timeout: float = 30):
        self.exitfile = exitfile
        deadline = time.monotonic() + timeout
        while not pidfile.exists() or not pidfile.read_text(encoding="utf-8").strip():
            if time.monotonic() > deadline:
                raise UIError("terminal", "the terminal window did not start")
            time.sleep(0.1)
        self.pid = int(pidfile.read_text(encoding="utf-8"))
        try:
            self.proc = psutil.Process(self.pid)
        except psutil.Error:
            self.proc = None

    def poll(self) -> int | None:
        if self.exitfile.exists():
            try:
                return int(self.exitfile.read_text(encoding="utf-8"))
            except ValueError:
                pass
        if self.proc is None or not self.proc.is_running() or self.proc.status() == psutil.STATUS_ZOMBIE:
            return -1  # the window was closed
        return None

    def _signal(self, kill: bool) -> None:
        try:
            procs = [*self.proc.children(recursive=True), self.proc] if self.proc else []
        except psutil.Error:
            procs = []
        for p in procs:
            try:
                p.kill() if kill else p.terminate()
            except psutil.Error:
                pass

    def terminate(self) -> None:
        self._signal(False)

    def kill(self) -> None:
        self._signal(True)


def terminal_command(script: Path, child_args: list[str]) -> list[str]:
    """How to open a new terminal window running ``child_args`` on this platform."""
    if sys.platform == "darwin":
        return ["open", "-a", "Terminal", str(script)]
    for name, flag in (("x-terminal-emulator", "-e"), ("gnome-terminal", "--"), ("konsole", "-e"),
                       ("xfce4-terminal", "-x"), ("kitty", ""), ("alacritty", "-e"), ("xterm", "-e")):
        found = shutil.which(name)
        if found:
            return [found, *([flag] if flag else []), *child_args]
    raise UIError("no_terminal", "no terminal program found")


def open_in_terminal(name: str, command: list[str], cwd: Path, env: dict[str, str]) -> TerminalAgent:
    run_dir = cwd.parent
    added = {k: v for k, v in env.items() if os.environ.get(k) != v}
    pkg_parent = str(Path(__file__).resolve().parent.parent)  # works from a source checkout too
    added["PYTHONPATH"] = os.pathsep.join(filter(None, [pkg_parent, os.environ.get("PYTHONPATH")]))
    pidfile, exitfile = run_dir / "agent.pid", run_dir / "agent.exit"
    spec = run_dir / "agent.json"
    spec.write_text(json.dumps({"name": name, "command": command, "cwd": str(cwd), "env": added,
                                "prompt": canary.TASK_PROMPT, "pidfile": str(pidfile),
                                "exitfile": str(exitfile)}), encoding="utf-8")
    child_args = [sys.executable, "-m", "whatsent.child", str(spec)]
    child_env = {**os.environ, "PYTHONPATH": added["PYTHONPATH"]}
    if sys.platform == "win32":
        subprocess.Popen(child_args, env=child_env, creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        script = run_dir / "open-agent.command"  # macOS Terminal runs .command files
        script.write_text("#!/bin/sh\nclear\n"
                          f"PYTHONPATH={shlex.quote(added['PYTHONPATH'])} exec {shlex.join(child_args)}\n",
                          encoding="utf-8")
        script.chmod(0o755)
        subprocess.Popen(terminal_command(script, ["sh", str(script)]), env=child_env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return TerminalAgent(pidfile, exitfile)


class Job:
    """One test started from the page. Runs the session steps in a thread and reports
    each one to the hub: project, recorder, (close the running app), launch, live, report."""

    def __init__(self, ui: "UI", tool: dict, args: argparse.Namespace, command: list[str],
                 app: apps.ResolvedApp | None, demo: bool = False):
        self.ui, self.tool, self.demo = ui, tool, demo
        self.id = secrets.token_hex(6)
        self.hub = Hub()
        self.session = Session(args, command, app)
        self.app = app
        self.deep = args.capture != "env"
        self.go = threading.Event()  # set when the user presses "start test"
        self.cancelled = threading.Event()
        self.relaunching = threading.Event()
        self.state = "preparing"
        self.thread = threading.Thread(target=self._run, daemon=True)
        self._pos = 0
        self._partial = b""
        self._gaps: set[tuple] = set()
        self._last_event = time.monotonic()
        self._idle_sent = False
        self._deep_warned = False
        self._t0_wall: float | None = None

    # steps: 0 project, 1 recorder, 2 close running app (apps only), last: launch
    def _step(self, i: int, state: str) -> None:
        self.hub.emit("step", i=i, state=state)

    def _run(self) -> None:
        try:
            if self._steps() is False:
                self.state = "cancelled"
                self.hub.emit("cancelled")
        except UIError as exc:
            self.state = "failed"
            self.hub.emit("error", code=exc.code, message=str(exc))
        except Exception as exc:  # noqa: BLE001 - shown on the page; the server keeps running
            self.state = "failed"
            self.hub.emit("error", code="internal", message=f"{type(exc).__name__}: {exc}")
        finally:
            self.session.stop_agent()
            self.session.close()
            self.ui.clear_stale()

    def _steps(self) -> bool:
        s = self.session
        self.hub.emit("job", id=self.id, tool=self.tool, demo=self.demo, prompt=canary.TASK_PROMPT)
        self._step(0, "doing")
        s.prepare()
        self.hub.emit("canaries", items=[{k: c[k] for k in ("id", "file", "short", "sensitive")}
                                         for c in s.canaries])
        self._step(0, "done")
        self._step(1, "doing")
        try:
            s.start_proxy("local" if self.deep else "env")
        except RuntimeError as exc:
            raise UIError("deep" if self.deep else "recorder", str(exc)) from exc
        self._step(1, "done")
        last = 2
        if self.app:
            last = 3
            if apps.running(self.app):
                self.state = "needs_quit"
                self._step(2, "action")
                while apps.running(self.app):
                    if self.cancelled.wait(0.5):
                        return False
            self._step(2, "done")
        self.state = "ready"
        self.hub.emit("ready")
        if not self.demo:
            while not self.go.wait(0.2):
                if self.cancelled.is_set():
                    return False
        if self.cancelled.is_set():
            return False
        self._step(last, "doing")
        if (s.proxy.local_spec is not None) != self.deep:
            try:
                s.start_proxy("local" if self.deep else "env")
            except RuntimeError as exc:
                raise UIError("deep" if self.deep else "recorder", str(exc)) from exc
        self._launch()
        self._step(last, "done")
        self.state = "running"
        pump = threading.Thread(target=self._pump_loop, daemon=True)
        pump.start()
        while True:
            s.wait()
            if self.relaunching.is_set() and not s.stop_requested.is_set():
                self.relaunching.clear()
                self._launch()
                continue
            break
        self.state = "finishing"
        self.hub.emit("finishing")
        summary, html = s.finish()
        self._pump()
        print_summary(summary, html)
        self.state = "done"
        self.hub.emit("done", report=report_view(summary, s.run_dir.name))
        return True

    def _launch(self) -> None:
        s = self.session
        if self.app or self.demo:
            launcher = detached
        else:
            def launcher(cmd, cwd, env):
                return open_in_terminal(self.tool["name"], cmd, cwd, env)
        try:
            s.launch(launcher)
        except OSError as exc:
            raise UIError("launch", str(exc)) from exc
        self._last_event = time.monotonic()
        self._t0_wall = self._t0_wall or time.time()
        self._idle_sent = False
        if self.app:
            self.ui.mark_stale(self.app, s.agent.pid)
        self.hub.emit("launched", wall=self._t0_wall)

    def _pump_loop(self) -> None:
        while self.state == "running":
            self._pump()
            time.sleep(0.3)

    def _pump(self) -> None:
        """Forward new proxy log lines and newly seen bypassing connections to the page."""
        s = self.session
        path = s.proxy.events_file
        try:
            with open(path, "rb") as f:
                f.seek(self._pos)
                chunk = f.read()
                self._pos = f.tell()
        except OSError:
            chunk = b""
        lines = (self._partial + chunk).split(b"\n")
        self._partial = lines.pop()
        t0 = s.t0 or time.monotonic()
        t0_wall = self._t0_wall or time.time()
        for line in lines:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            self._last_event = time.monotonic()
            t = max(0.0, ev.get("ts", time.time()) - t0_wall)
            if ev.get("type") == "tls_failed":
                self.hub.emit("gap", t=t, host=f"{ev.get('host')}:{ev.get('port')}", why="tls")
                continue
            self.hub.emit("req", t=t, host=ev.get("host"), method=ev.get("method") or ev.get("type", "").upper(),
                          path=ev.get("path", ""), bytes=ev.get("bytes_out", 0), canaries=ev.get("canaries", []),
                          error=bool(ev.get("error")))
        if s.sampler:
            for key, c in list(s.sampler.seen.items()):
                if not c["local"] and key not in self._gaps:
                    self._gaps.add(key)
                    self._last_event = time.monotonic()
                    self.hub.emit("gap", t=time.monotonic() - t0, host=f"{c['ip']}:{c['port']}", why=c["proto"])
        if (self.app and not self._idle_sent and self.state == "running"
                and time.monotonic() - self._last_event > IDLE_AFTER):
            self._idle_sent = True
            self.hub.emit("idle", seconds=int(IDLE_AFTER))
        if self.deep and not self._deep_warned and s.proxy.local_capture_problem():
            self._deep_warned = True
            self.hub.emit("deep_problem")

    # actions from the page
    def start(self, deep: bool) -> None:
        if self.state != "ready":
            raise UIError("state", f"cannot start while {self.state}")
        self.deep = deep
        self.go.set()

    def quit_app(self) -> None:
        for pid in apps.running(self.app) if self.app else []:
            try:
                psutil.Process(pid).terminate()
            except psutil.Error:
                pass

    def relaunch(self) -> None:
        if self.state != "running":
            raise UIError("state", f"cannot reopen while {self.state}")
        self.relaunching.set()
        self.session.stop_agent()

    def stop(self) -> None:
        self.cancelled.set()
        self.session.stop_requested.set()

    @property
    def active(self) -> bool:
        return self.thread.is_alive()


def report_view(s: dict, run_id: str) -> dict:
    """What the report screen needs; no paths or canary values."""
    return {
        "run": run_id,
        "url": f"/runs/{run_id}/report.html",
        "agent": s["agent"], "started_at": s["started_at"], "duration_s": s["duration_s"],
        "sample": s.get("sample", False), "capture": s.get("capture", "env"), "warnings": s.get("warnings", []),
        "totals": s["totals"], "control": s.get("control"), "gap_names": report.gap_names(s),
        "canaries": [{k: c[k] for k in ("id", "file", "short", "sensitive", "sent_to")} | {"on_disk": bool(c["on_disk"])}
                     for c in s["canaries"]],
    }


class UI:
    def __init__(self, out: Path, port: int = 0):
        self.out = out.resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(24)
        self.job: Job | None = None
        self.lock = threading.Lock()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/"

    # A test window left open by a crashed run still points at a proxy that is gone.
    def mark_stale(self, app: apps.ResolvedApp, pid: int) -> None:
        (self.out / STALE_FILE).write_text(json.dumps({"name": app.name, "exe": str(app.executable), "pid": pid}),
                                           encoding="utf-8")

    def clear_stale(self) -> None:
        (self.out / STALE_FILE).unlink(missing_ok=True)

    def stale(self) -> dict | None:
        try:
            info = json.loads((self.out / STALE_FILE).read_text(encoding="utf-8"))
            proc = psutil.Process(info["pid"])
            if Path(proc.exe()) == Path(info["exe"]):
                return info
        except (OSError, ValueError, KeyError, psutil.Error):
            pass
        if not (self.job and self.job.active):
            self.clear_stale()
        return None

    def close_stale(self) -> None:
        info = self.stale()
        if info:
            psutil.Process(info["pid"]).terminate()
        self.clear_stale()

    def start_job(self, body: dict) -> Job:
        with self.lock:
            if self.job and self.job.active:
                raise UIError("busy", "a test is already running", 409)
            deep = bool(body.get("deep"))
            args = argparse.Namespace(out=self.out, port=None, watch=[], no_default_watch=False, mitm_set=[],
                                      name=None, agent_version=None, capture="local" if deep else "env")
            tool_id = str(body.get("tool") or "")
            app = None
            if tool_id == "demo":
                from whatsent.demo import AGENT_NAME, setup
                args, command = setup(self.out, pace=float(body.get("pace", 1.2)))
                tool = {"id": "demo", "name": AGENT_NAME, "kind": "cli"}
                job = Job(self, tool, args, command, None, demo=True)
            elif tool_id in CLIS:
                if not shutil.which(tool_id):
                    raise UIError("not_found", CLIS[tool_id])
                tool = {"id": tool_id, "name": CLIS[tool_id], "kind": "cli"}
                job = Job(self, tool, args, [tool_id], None)
            else:
                spec = str(body.get("path") or tool_id)
                try:
                    app = apps.resolve(spec)
                except apps.AppError as exc:
                    name = apps.KNOWN[tool_id].name if tool_id in apps.KNOWN else spec
                    raise UIError("not_found", name) from exc
                tool = {"id": tool_id or app.name, "name": app.name, "kind": "app"}
                args.name = app.name
                job = Job(self, tool, args, [], app)
            self.job = job
            job.thread.start()
            return job

    def pick_app(self) -> str | None:
        if sys.platform != "darwin":
            raise UIError("unsupported", status=501)
        r = subprocess.run(["osascript", "-e", "POSIX path of (choose application)"],
                           capture_output=True, text=True, timeout=300)
        return r.stdout.strip() or None

    def open_settings(self) -> None:
        if sys.platform != "darwin":
            raise UIError("unsupported", status=501)
        subprocess.Popen(["open", "-b", "com.apple.systempreferences"])

    def _handler(self):
        ui = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _json(self, status: int, obj) -> None:
                self._send(status, json.dumps(obj).encode(), "application/json")

            def _host_ok(self) -> bool:
                return self.headers.get("Host", "") in (f"127.0.0.1:{ui.port}", f"localhost:{ui.port}")

            def _token_ok(self, query: dict) -> bool:
                given = self.headers.get("X-Whatsent-Token") or (query.get("token") or [""])[0]
                return secrets.compare_digest(given, ui.token)

            def do_GET(self):
                url = urlsplit(self.path)
                query = parse_qs(url.query)
                if not self._host_ok():
                    return self._json(403, {"error": "host"})
                if url.path == "/":
                    page = (STATIC / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", ui.token)
                    return self._send(200, page.encode(), "text/html; charset=utf-8",
                                      {"Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; "
                                                                  "style-src 'self'; script-src 'self'; "
                                                                  "frame-ancestors 'none'"})
                static = {"/app.js": "text/javascript", "/app.css": "text/css", "/icon.svg": "image/svg+xml"}
                if url.path in static:
                    return self._send(200, (STATIC / url.path[1:]).read_bytes(), static[url.path] + "; charset=utf-8")
                if not self._token_ok(query):
                    return self._json(403, {"error": "token"})
                if url.path == "/api/state":
                    job = ui.job
                    return self._json(200, {
                        "version": __version__, "platform": sys.platform, "stale": ui.stale(),
                        "job": {"id": job.id, "state": job.state, "tool": job.tool, "active": job.active,
                                "demo": job.demo} if job else None,
                    })
                if url.path == "/api/tools":
                    return self._json(200, {"tools": scan_tools()})
                if url.path == "/api/events":
                    since = max(int((query.get("since") or ["0"])[0] or 0),
                                int(self.headers.get("Last-Event-ID") or 0))
                    return self._events((query.get("job") or [""])[0], since)
                m = re.fullmatch(r"/runs/([^/]+)/report\.html", url.path)
                if m and RUN_ID.match(m.group(1)):
                    report = ui.out / m.group(1) / "report.html"
                    if report.is_file():
                        return self._send(200, report.read_bytes(), "text/html; charset=utf-8",
                                          {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})
                return self._json(404, {"error": "not found"})

            def _events(self, job_id: str, since: int) -> None:
                job = ui.job
                if job is None or job.id != job_id:
                    # 204 tells EventSource to stop reconnecting: the page asks for the new run.
                    return self._send(204, b"", "text/plain")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                seq = since
                try:
                    while True:
                        events = job.hub.since(seq, 15)
                        if not events:
                            self.wfile.write(b": keep-alive\n\n")
                        for ev in events:
                            self.wfile.write(f"id: {ev['seq']}\ndata: {json.dumps(ev)}\n\n".encode())
                            seq = ev["seq"]
                        self.wfile.flush()
                        if ui.job is not job:
                            return
                except OSError:
                    return

            def do_POST(self):
                url = urlsplit(self.path)
                if not self._host_ok() or not self._token_ok({}):
                    return self._json(403, {"error": "forbidden"})
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    return self._json(415, {"error": "json only"})
                try:
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                    result = self._action(url.path, body if isinstance(body, dict) else {})
                except UIError as exc:
                    return self._json(exc.status, {"error": exc.code, "message": str(exc)})
                except ValueError:
                    return self._json(400, {"error": "bad request"})
                return self._json(200, result or {"ok": True})

            def _action(self, path: str, body: dict):
                job = ui.job
                if path == "/api/start":
                    return {"job": ui.start_job(body).id}
                if path == "/api/pick":
                    return {"path": ui.pick_app()}
                if path == "/api/open-settings":
                    return ui.open_settings()
                if path == "/api/stale/close":
                    return ui.close_stale()
                if job is None:
                    raise UIError("no_job", status=409)
                if path == "/api/launch":
                    return job.start(bool(body.get("deep")))
                if path == "/api/quit-app":
                    return job.quit_app()
                if path == "/api/relaunch":
                    return job.relaunch()
                if path == "/api/stop":
                    return job.stop()
                raise UIError("not_found", status=404)

        return Handler

    def serve(self, open_browser: bool = True) -> int:
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        print(f"whatsent: interface at {self.url}  (Ctrl-C to quit)", file=sys.stderr)
        if open_browser:
            webbrowser.open(self.url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        self.shutdown()
        return 0

    def shutdown(self) -> None:
        job = self.job
        if job and job.active:
            print("whatsent: stopping the test and writing the report...", file=sys.stderr)
            job.stop()
            job.thread.join(timeout=60)
        self.server.shutdown()
        self.server.server_close()


def run_ui(args: argparse.Namespace) -> int:
    try:
        ui = UI(args.out, args.port or 0)
    except OSError as exc:
        print(f"whatsent: could not start the interface: {exc}", file=sys.stderr)
        return 1
    return ui.serve(open_browser=not args.no_browser)
