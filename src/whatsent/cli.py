"""Command line entry point: ``whatsent run -- <agent command>``."""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import psutil

from whatsent import __version__, agents, apps, board, canary, diskwatch, report
from whatsent.capture import Proxy, hide_credentials, normalize_upstream, upstream_from_env
from whatsent.detect import Matcher
from whatsent.netwatch import ConnectionSampler

QUICK_EXIT = 5.0  # an app that quits this fast probably handed over to a running copy


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="whatsent", description="See what your AI coding agent sends, and where.")
    p.add_argument("--version", action="version", version=f"whatsent {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run an agent inside a canary project and report what left the machine",
                         usage="whatsent run [options] -- <agent command> [args...]\n"
                               "       whatsent run --app <cursor|trae|...|path> [options] [-- app args]")
    run.add_argument("--out", type=Path, default=Path("whatsent-report"),
                     help="folder for reports (default: ./whatsent-report)")
    run.add_argument("--app", metavar="NAME|PATH",
                     help=f"desktop IDE agent to launch: {', '.join(sorted(apps.KNOWN))}, a .app bundle "
                          f"or an executable (.exe on Windows)")
    run.add_argument("--capture", default="env", metavar="MODE",
                     help="env (default): proxy settings only. local or local:SPEC: also capture at OS level "
                          "the traffic of processes matching SPEC (experimental; macOS asks to allow a "
                          "system extension, Linux needs root, Windows an admin terminal)")
    run.add_argument("--port", type=int, help="proxy port (default: a free port)")
    run.add_argument("--watch", type=Path, action="append", default=[], metavar="DIR",
                     help="extra folder to watch for files the agent writes (repeatable)")
    run.add_argument("--no-default-watch", action="store_true",
                     help="only watch folders given with --watch")
    run.add_argument("--mitm-set", action="append", default=[], metavar="KEY=VALUE",
                     help="pass an option through to mitmproxy (advanced, repeatable)")
    run.add_argument("--upstream", metavar="URL|none",
                     help="forward to this HTTP(S) proxy (default: the one in HTTPS_PROXY, if any; "
                          "none: connect directly)")
    run.add_argument("--timeout", type=float, metavar="SECONDS",
                     help="stop the agent after this long (default: wait for it to exit)")
    run.add_argument("--runs", type=int, default=1, metavar="N",
                     help="run the agent N times and combine them into one result: a canary counts as "
                          "sent if any run sent it (agents vary from run to run)")
    run.add_argument("--clean", action="store_true",
                     help="turn off your MCP servers, connectors and plugins (claude, codex, codebuddy and copilot), so the "
                          "run shows the agent itself")
    run.add_argument("--result-to", type=Path, metavar="DIR",
                     help="also copy result.json into DIR as <agent>-<version>[-clean].json, e.g. results/")
    run.add_argument("--name", help="agent name shown in the report (default: the command name)")
    run.add_argument("--agent-version",
                     help="agent version shown in the report and leaderboard (default: asked from the agent)")
    run.add_argument("command", nargs=argparse.REMAINDER, help="agent command, after --")
    demo = sub.add_parser("demo", help="see a sample report: a simulated agent against local servers, offline")
    demo.add_argument("--out", type=Path, default=Path("whatsent-report"),
                      help="folder for reports (default: ./whatsent-report)")
    ui = sub.add_parser("ui", help="open the visual interface in your browser (a local page on 127.0.0.1)")
    ui.add_argument("--out", type=Path, default=Path("whatsent-report"),
                    help="folder for reports (default: ./whatsent-report)")
    ui.add_argument("--port", type=int, help="port for the local page (default: a free port)")
    ui.add_argument("--no-browser", action="store_true", help="print the address instead of opening a browser")
    board = sub.add_parser("board", help="build the leaderboard page from report.json files")
    board.add_argument("reports", nargs="+", type=Path, help="report.json files or folders containing them")
    board.add_argument("-o", "--out", type=Path, default=Path("site"), help="output folder (default: ./site)")
    check = sub.add_parser("check", help="check result.json files before they are added to the leaderboard")
    check.add_argument("results", nargs="+", type=Path, help="result.json files or folders containing them")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "port", None) is not None and not 0 <= args.port <= 65535:
        print("whatsent: --port must be between 0 and 65535 (0 selects a free port)", file=sys.stderr)
        return 2
    if args.cmd == "demo":
        from whatsent.demo import run_demo
        return run_demo(args)
    if args.cmd == "ui":
        from whatsent.ui import run_ui
        return run_ui(args)
    if args.cmd == "check":
        from whatsent.check import check
        return check(args.results)
    if args.cmd == "board":
        from whatsent.board import build
        return build(args.reports, args.out)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if args.capture != "env" and args.capture != "local" and not args.capture.startswith("local:"):
        print("whatsent: --capture is env, local or local:SPEC", file=sys.stderr)
        return 2
    if args.timeout is not None and (not math.isfinite(args.timeout) or args.timeout <= 0):
        print("whatsent: --timeout must be more than 0 seconds", file=sys.stderr)
        return 2
    if args.runs < 1:
        print("whatsent: --runs must be at least 1", file=sys.stderr)
        return 2
    if args.clean and args.app:
        print("whatsent: --clean works for CLI agents (claude, codex, codebuddy, copilot), not for IDE apps", file=sys.stderr)
        return 2
    if args.upstream is not None and args.upstream.strip().lower() != "none":
        try:
            args.upstream = normalize_upstream(args.upstream)
        except ValueError as exc:
            print(f"whatsent: --upstream is an http:// or https:// proxy, or none: {exc}", file=sys.stderr)
            return 2
    if not args.app and not command:
        print("whatsent: give the agent command after --, e.g. whatsent run -- claude", file=sys.stderr)
        return 2
    if args.runs > 1:
        return run_many(args, command)
    return run_app(args, command) if args.app else run(args, command)


def run_app(args: argparse.Namespace, extra: list[str], collect: list[dict] | None = None) -> int:
    try:
        app = apps.resolve(args.app)
    except apps.AppError as exc:
        print(f"whatsent: {exc}", file=sys.stderr)
        return 2
    if apps.running(app):
        print(f"whatsent: {app.name} is already running. Quit it completely first: a second launch is handed "
              f"to the running copy, which whatsent cannot see.", file=sys.stderr)
        return 2
    args.name = args.name or app.name
    return run(args, extra, app=app, collect=collect)


def run(args: argparse.Namespace, command: list[str], app: apps.ResolvedApp | None = None,
        collect: list[dict] | None = None) -> int:
    """One recorded run. With ``collect``, the run's summary is appended to it."""
    session = Session(args, command, app)
    old_term = {sig: signal.signal(sig, _terminate) for sig in
                filter(None, (getattr(signal, n, None) for n in ("SIGTERM", "SIGHUP")))}
    try:
        return _run_session(session, args, app, collect)
    finally:
        try:
            session.stop_agent()
        finally:
            try:
                session.close(final=True)
            finally:
                for sig, handler in old_term.items():
                    signal.signal(sig, handler)


def _run_session(session: "Session", args: argparse.Namespace, app: apps.ResolvedApp | None,
                 collect: list[dict] | None) -> int:
    print(f"whatsent: snapshotting {len(session.roots)} folders...", file=sys.stderr)
    session.prepare()
    try:
        session.start_proxy()
    except RuntimeError as exc:
        session.close(final=True)
        print(f"whatsent: {exc}", file=sys.stderr)
        return 1
    if app:
        how = (f"In {app.name}: open the AI chat, ask the prompt below and let it finish, "
               f"then quit {app.name} completely (Cmd+Q / File > Exit).")
    else:
        how = ("Use this prompt (the same one for every agent you compare). Let the agent finish fixing the bug, "
               "then exit it:")
    local = session.proxy.local_spec
    extra = "".join(f"whatsent: {line}\n" for line in session.notes)
    print(f"""
whatsent: canary project ready at {session.workspace}
whatsent: proxy on 127.0.0.1:{session.proxy.port}{f", OS-level capture for {local!r}" if local else ""}
{extra}whatsent: starting {session.name}
whatsent: {how}

    {canary.TASK_PROMPT}
""", file=sys.stderr)

    # Ctrl-C belongs to the agent; we keep running so the report still gets written.
    old_sigint = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        try:
            session.launch()
        except OSError as exc:
            session.close(final=True)
            print(f"whatsent: could not start {session.command[0]}: {exc}", file=sys.stderr)
            return 127
        session.wait()
    except BaseException:
        session.close(final=True)  # terminated: no report will be written
        raise
    finally:
        signal.signal(signal.SIGINT, old_sigint)
        session.stop_agent()
        session.close()

    print("whatsent: checking watched folders...", file=sys.stderr)
    summary, html = session.finish()
    print_summary(summary, html)
    if collect is not None:
        collect.append(summary)
    if getattr(args, "result_to", None):
        print(f"whatsent: result at {save_result(html.parent / 'result.json', args.result_to, summary)}",
              file=sys.stderr)
    code = session.exit_code
    return code if isinstance(code, int) and code >= 0 else 1


def run_many(args: argparse.Namespace, command: list[str]) -> int:
    """Run the agent ``args.runs`` times, then write one combined result."""
    folder = reserve_directory(args.out / f"{datetime.now():%Y%m%d-%H%M%S}-x{args.runs}")
    summaries: list[dict] = []
    codes = []
    for i in range(args.runs):
        print(f"\nwhatsent: run {i + 1} of {args.runs}", file=sys.stderr)
        each = copy.copy(args)
        each.runs, each.result_to = 1, None
        each.out = folder
        codes.append(run_app(each, command, summaries) if args.app else run(each, command, collect=summaries))
    if summaries:
        combined = board.combine([board.to_result(s) for s in summaries])
        if any(codes):
            combined["warnings"] = max(1, combined["warnings"])
        (folder / "result.json").write_text(json.dumps(combined, indent=2), encoding="utf-8")
        print_combined(combined, folder / "result.json")
        if args.result_to:
            print(f"whatsent: result at {save_result(folder / 'result.json', args.result_to, combined)}",
                  file=sys.stderr)
    return next((c for c in codes if c), 0)


def print_combined(r: dict, path: Path) -> None:
    t, n = r["totals"], r["runs"]
    lines = [f"\nwhatsent: {r['agent']} over {n} runs: {t['leaked']} of {t['canaries']} canaries left this "
             f"machine in at least one run ({t['leaked_sensitive']} sensitive)"]
    for c in r["canaries"].values():
        if c["sent_to"]:
            lines.append(f"  - {c['short']}: {c['seen_in']}/{n} runs -> {', '.join(c['sent_to'])}")
    ctl = r.get("control", "ok")
    if ctl != "ok":
        lines.append(f"  ! {report.CONTROL_HEAD[ctl]} in at least one run: {report.CONTROL_SUB[ctl]}")
    lines.append(f"whatsent: combined result at {path}")
    print("\n".join(lines), file=sys.stderr)


def _terminate(signum: int, frame) -> None:
    raise SystemExit(128 + signum)


def save_result(result: Path, folder: Path, summary: dict) -> Path:
    """Copy result.json to ``folder`` as <agent>-<version>[-clean].json, the name the leaderboard expects.
    A file already there is kept: this batch of runs gets -2, -3 ... and the board combines them."""
    folder.mkdir(parents=True, exist_ok=True)
    batch = 1
    data = result.read_bytes()
    while True:
        target = folder / board.result_name(summary, batch)
        try:
            with target.open("xb") as f:
                f.write(data)
            return target
        except FileExistsError:
            batch += 1


def reserve_directory(path: Path) -> Path:
    """Atomically reserve a new run folder without touching an existing run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate, batch = path, 1
    while True:
        try:
            candidate.mkdir(mode=0o700)
            return candidate
        except FileExistsError:
            batch += 1
            candidate = path.with_name(f"{path.name}-{batch}")


def popen(command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    """Start the agent as our child, in the foreground of this terminal."""
    if sys.platform == "win32":
        # Windows children get Ctrl-C regardless of our handler, and only PATH lookup of
        # .exe is built in, so resolve npm-style shims such as claude.cmd ourselves.
        return subprocess.Popen([shutil.which(command[0]) or command[0], *command[1:]], cwd=cwd, env=env)
    return subprocess.Popen(command, cwd=cwd, env=env,
                            preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))


class Session:
    """One recorded run: canary project, proxy, agent, report. ``whatsent run`` goes straight
    through; ``whatsent ui`` drives the same steps one by one and can stop the agent early."""

    def __init__(self, args: argparse.Namespace, command: list[str], app: apps.ResolvedApp | None = None):
        self.args = args
        self.app = app
        self.name = args.name or (app.name if app else Path(command[0]).name)
        self.started = datetime.now()
        self.run_dir = (args.out / self.started.strftime("%Y%m%d-%H%M%S")).resolve()
        self.workspace = self.run_dir / "workspace"
        self.roots = ([] if args.no_default_watch else diskwatch.default_roots()) + \
            [w.resolve() for w in args.watch]
        self.warnings: list[str] = []
        self.notes: list[str] = []  # what whatsent changed or decided, printed before the agent starts
        self.clean = False
        self.extra_env: dict[str, str] = {}
        if getattr(args, "clean", False) and command:
            preset = agents.clean(command)
            if preset:
                command, self.extra_env, self.clean = preset.command, preset.env, True
                self.notes.append(f"clean: {', '.join(preset.notes)}")
            else:
                self.notes.append(f"no clean mode for {Path(command[0]).name}: running with your own "
                                  f"MCP servers and plugins")
        self.command = command
        self.agent_version = args.agent_version
        self.upstream: str | None = None
        self.proxy: Proxy | None = None
        self.agent = None  # anything with pid, poll(), terminate() and kill(), like a Popen
        self.sampler: ConnectionSampler | None = None
        self.direct: list[dict] = []
        self.stop_requested = threading.Event()
        self.exit_code: int | str | None = None
        self.t0: float | None = None
        self.duration = 0.0

    def prepare(self) -> None:
        self.run_dir = reserve_directory(self.run_dir)
        self.workspace = self.run_dir / "workspace"
        self.canaries = [c.to_dict() for c in canary.create_workspace(self.workspace)]
        self.canaries_file = self.run_dir / "canaries.json"
        self.canaries_file.write_text(json.dumps(self.canaries, indent=2), encoding="utf-8")
        self.matcher = Matcher({c["id"]: c["token"] for c in self.canaries})
        if not self.agent_version:
            self.agent_version = (agents.app_version(self.app.executable) if self.app
                                  else agents.detect_version(self.command))
        self.since_ns = time.time_ns()
        self.before, self.truncated = diskwatch.snapshot(self.roots, exclude=[self.run_dir])

    def resolve_upstream(self) -> str | None:
        """The proxy to forward to: --upstream, else the one the agent would have used without us."""
        choice = getattr(self.args, "upstream", None)
        if choice and choice.strip().lower() == "none":
            return None
        if choice is not None:
            return normalize_upstream(choice)
        url, problem = upstream_from_env(dict(os.environ))
        if problem:
            raise RuntimeError(f"cannot use upstream proxy: {problem}; correct the proxy settings "
                               "or explicitly use --upstream none for a direct CLI run")
        return url

    def start_proxy(self, capture: str | None = None) -> None:
        """Start the proxy, or restart it with another capture mode before the agent is launched."""
        capture = capture or getattr(self.args, "capture", "env")
        local_spec = None
        if capture.startswith("local"):
            local_spec = capture.partition(":")[2] or (self.app.executable.name if self.app
                                                       else Path(self.command[0]).name)
        if self.proxy:
            self.proxy.stop()
        else:
            self.upstream = self.resolve_upstream()
            if self.upstream:
                self.notes.append(f"forwarding to your proxy {hide_credentials(self.upstream)}")
        self.proxy = Proxy(self.run_dir, self.canaries_file, self.run_dir / "events.jsonl", self.args.port,
                           self.args.mitm_set, getattr(self.args, "proxy_env", None), local_spec, self.upstream)
        self.proxy.start()
        self.env = self.proxy.agent_env(dict(os.environ), self.proxy.write_ca_bundle(self.run_dir / "ca-bundle.pem"))
        self.env.update(self.extra_env)

    def agent_command(self) -> list[str]:
        if self.app:
            return apps.command(self.app, self.proxy.port, self.workspace, self.command, self.proxy.ca_cert)
        return self.command

    def launch(self, launcher=popen) -> None:
        """Start (or restart) the agent. ``launcher(command, cwd, env)`` returns the process."""
        self.agent = launcher(self.agent_command(), self.workspace, self.env)
        self.launched_at = time.monotonic()
        self.t0 = self.t0 or self.launched_at
        # With OS-level capture every connection is redirected, so sampling for bypasses means nothing.
        if not self.proxy.local_spec:
            if self.sampler:
                self.sampler.pid = self.agent.pid
            else:
                self.sampler = ConnectionSampler(self.agent.pid, self.proxy.port)
                self.sampler.start()

    def stop_agent(self, timeout: float = 10) -> None:
        """Ask the agent to quit, the way closing its window would, and kill it if it hangs."""
        agent = self.agent
        if agent is None or agent.poll() is not None:
            return
        try:  # its children too: claude and codex run their tools as subprocesses
            family = psutil.Process(agent.pid).children(recursive=True)
        except psutil.Error:
            family = []
        agent.terminate()
        for child in family:
            try:
                child.terminate()
            except psutil.Error:
                pass
        deadline = time.monotonic() + timeout
        while agent.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if agent.poll() is None:
            agent.kill()
        for child in family:
            try:
                if child.is_running():
                    child.kill()
            except psutil.Error:
                pass

    def wait(self) -> None:
        limit = getattr(self.args, "timeout", None)
        while (code := self.agent.poll()) is None:
            if self.proxy.proc.poll() is not None:
                self.warnings.append("capture stopped unexpectedly; the run is incomplete")
                self.stop_agent()
                code = "capture_failed"
                break
            if self.stop_requested.wait(0.2):
                self.stop_agent()
                code = "stopped"
                break
            if limit and time.monotonic() - self.t0 > limit:
                self.stop_agent()
                self.warnings.append(f"stopped after the {limit:g}s time limit")
                code = "timeout"
                break
        self.exit_code = code
        self.duration = time.monotonic() - self.t0
        self.last_run = time.monotonic() - self.launched_at
        time.sleep(1.0)  # let in-flight requests reach the log

    def close(self, final: bool = False) -> None:
        """Stop sampling and the proxy. ``final`` also deletes the run's CA private key, which a
        report folder that gets shared should not carry."""
        if self.sampler:
            self.direct = self.sampler.stop()
            self.warnings.extend(sorted(self.sampler.warnings))
            self.sampler = None
        if self.proxy:
            self.proxy.stop()
            if final:
                for warning in self.proxy.forget_keys():
                    if warning not in self.warnings:
                        self.warnings.append(warning)
                        print(f"whatsent: {warning}", file=sys.stderr)
        if final and getattr(self.args, "demo_cleanup", None):
            self.args.demo_cleanup()

    def finish(self) -> tuple[dict, Path]:
        self.close(final=True)
        if self.app and self.exit_code != "stopped" and self.last_run < QUICK_EXIT:
            self.warnings.append(
                f"{self.app.name} exited after {self.last_run:.0f}s. If it was already open, it handed this run "
                f"to the running copy and nothing was captured. Quit it completely and run again.")
        problem = self.proxy.local_capture_problem()
        if problem:
            self.warnings.append(problem)

        after, truncated_after = diskwatch.snapshot(self.roots, exclude=[self.run_dir])
        partial = sorted(set(self.truncated) | set(truncated_after))
        disk = diskwatch.diff(self.before, after, self.matcher, self.since_ns, partial, self.name)
        disk["roots"] = [str(r) for r in self.roots]
        disk["truncated_roots"] = partial
        if disk["incomplete_files"]:
            self.warnings.append(f"{len(disk['incomplete_files'])} changed files could not be fully inspected "
                                 "(read, size or decoding limits); disk findings are incomplete")
        if partial:
            self.warnings.append(f"{len(partial)} watched {'folder was' if len(partial) == 1 else 'folders were'} "
                                 f"only partly scanned, so the disk findings may be incomplete: "
                                 f"{', '.join(_tilde(p) for p in partial)}")

        args = self.args
        meta = {
            "whatsent_version": __version__,
            "agent": self.name,
            "agent_version": self.agent_version,
            "kind": "app" if self.app else "cli",
            "capture": f"local:{self.proxy.local_spec}" if self.proxy.local_spec else "env",
            "clean": self.clean,
            "command": self.agent_command(),
            "started_at": self.started.isoformat(timespec="seconds"),
            "duration_s": self.duration,
            "exit_code": self.exit_code,
            "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "workspace": str(self.workspace),
            "task_prompt": canary.TASK_PROMPT,
            "warnings": self.warnings,
            "sample": getattr(args, "sample", False),  # True for the simulated demo agent
        }
        events = report.load_events(self.proxy.events_file, warnings=self.warnings)
        summary = report.summarize(meta, self.canaries, events, disk,
                                   self.direct, home=getattr(args, "home", None),
                                   task_fixed=canary.task_fixed(self.workspace))
        return summary, report.write(summary, self.run_dir)


def _tilde(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home):].replace(os.sep, "/") if path.startswith(home + os.sep) else path


def print_summary(s: dict, html: Path) -> None:
    t = s["totals"]
    lines = [
        "",
        f"whatsent: {s['agent']}: {t['leaked']} of {t['canaries']} canaries left this machine"
        f" ({t['leaked_sensitive']} sensitive), {t['requests']} requests to {t['hosts']} destinations,"
        f" {report.human_bytes(t['bytes_out'])} sent",
    ]
    for c in s["canaries"]:
        if c["sent_to"]:
            lines.append(f"  - {c['label']} ({c['file']}) -> {', '.join(c['sent_to'])}")
    ctl = report.control_status(s)
    if ctl != "ok":
        lines.append(f"  ! {report.CONTROL_HEAD[ctl]}: {report.CONTROL_SUB[ctl]}. {report.CONTROL_HELP[ctl]}")
    if t["not_inspected"]:
        lines.append(f"  ! not inspected: {report.gap_names(s)}, see the report")
    for w in s.get("warnings", []):
        lines.append(f"  ! {w}")
    lines.append(f"whatsent: report at {html}")
    print("\n".join(lines), file=sys.stderr)
