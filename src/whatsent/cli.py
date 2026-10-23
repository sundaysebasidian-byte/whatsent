"""Command line entry point: ``whatsent run -- <agent command>``."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from whatsent import __version__, apps, canary, diskwatch, report
from whatsent.capture import Proxy
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
    run.add_argument("--name", help="agent name shown in the report (default: the command name)")
    run.add_argument("--agent-version", help="agent version shown in the report and leaderboard")
    run.add_argument("command", nargs=argparse.REMAINDER, help="agent command, after --")
    demo = sub.add_parser("demo", help="see a sample report: a simulated agent against local servers, offline")
    demo.add_argument("--out", type=Path, default=Path("whatsent-report"),
                      help="folder for reports (default: ./whatsent-report)")
    board = sub.add_parser("board", help="build the leaderboard page from report.json files")
    board.add_argument("reports", nargs="+", type=Path, help="report.json files or folders containing them")
    board.add_argument("-o", "--out", type=Path, default=Path("site"), help="output folder (default: ./site)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "demo":
        from whatsent.demo import run_demo
        return run_demo(args)
    if args.cmd == "board":
        from whatsent.board import build
        return build(args.reports, args.out)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if args.capture != "env" and args.capture != "local" and not args.capture.startswith("local:"):
        print("whatsent: --capture is env, local or local:SPEC", file=sys.stderr)
        return 2
    if args.app:
        return run_app(args, command)
    if not command:
        print("whatsent: give the agent command after --, e.g. whatsent run -- claude", file=sys.stderr)
        return 2
    return run(args, command)


def run_app(args: argparse.Namespace, extra: list[str]) -> int:
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
    return run(args, extra, app=app)


def run(args: argparse.Namespace, command: list[str], app: apps.ResolvedApp | None = None) -> int:
    started = datetime.now()
    run_dir = (args.out / started.strftime("%Y%m%d-%H%M%S")).resolve()
    workspace = run_dir / "workspace"
    run_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    canaries = [c.to_dict() for c in canary.create_workspace(workspace)]
    canaries_file = run_dir / "canaries.json"
    canaries_file.write_text(json.dumps(canaries, indent=2), encoding="utf-8")
    matcher = Matcher({c["id"]: c["token"] for c in canaries})

    roots = ([] if args.no_default_watch else diskwatch.default_roots()) + [w.resolve() for w in args.watch]
    print(f"whatsent: snapshotting {len(roots)} folders...", file=sys.stderr)
    before, truncated = diskwatch.snapshot(roots, exclude=[run_dir])

    capture = getattr(args, "capture", "env")
    local_spec = None
    if capture.startswith("local"):
        local_spec = capture.partition(":")[2] or (app.executable.name if app else Path(command[0]).name)
    proxy = Proxy(run_dir, canaries_file, run_dir / "events.jsonl", args.port, args.mitm_set,
                  getattr(args, "proxy_env", None), local_spec)
    try:
        proxy.start()
    except RuntimeError as exc:
        print(f"whatsent: {exc}", file=sys.stderr)
        return 1
    env = proxy.agent_env(dict(os.environ), proxy.write_ca_bundle(run_dir / "ca-bundle.pem"))
    if app:
        command = apps.command(app, proxy.port, workspace, command)
        how = (f"In {app.name}: open the AI chat, ask the prompt below and let it finish, "
               f"then quit {app.name} completely (Cmd+Q / File > Exit).")
    else:
        how = "Use this prompt (the same one for every agent you compare), then exit the agent:"

    print(f"""
whatsent: canary project ready at {workspace}
whatsent: proxy on 127.0.0.1:{proxy.port}{f", OS-level capture for {local_spec!r}" if local_spec else ""}
whatsent: starting {args.name or Path(command[0]).name}
whatsent: {how}

    {canary.TASK_PROMPT}
""", file=sys.stderr)

    t0 = time.monotonic()
    # Ctrl-C belongs to the agent; we keep running so the report still gets written.
    old_sigint = signal.signal(signal.SIGINT, signal.SIG_IGN)
    exit_code: int | str
    try:
        if sys.platform == "win32":
            # Windows children get Ctrl-C regardless of our handler, and only PATH lookup of
            # .exe is built in, so resolve npm-style shims such as claude.cmd ourselves.
            agent = subprocess.Popen([shutil.which(command[0]) or command[0], *command[1:]],
                                     cwd=workspace, env=env)
        else:
            agent = subprocess.Popen(command, cwd=workspace, env=env,
                                     preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    except OSError as exc:
        signal.signal(signal.SIGINT, old_sigint)
        proxy.stop()
        print(f"whatsent: could not start {command[0]}: {exc}", file=sys.stderr)
        return 127
    # With OS-level capture every connection is redirected, so sampling for bypasses means nothing.
    sampler = None if local_spec else ConnectionSampler(agent.pid, proxy.port)
    if sampler:
        sampler.start()
    try:
        exit_code = agent.wait()
        duration = time.monotonic() - t0
        time.sleep(1.0)  # let in-flight requests reach the log
    finally:
        signal.signal(signal.SIGINT, old_sigint)
        direct = sampler.stop() if sampler else []
        proxy.stop()

    if app and duration < QUICK_EXIT:
        warnings.append(f"{app.name} exited after {duration:.0f}s. If it was already open, it handed this run "
                        f"to the running copy and nothing was captured. Quit it completely and run again.")
    problem = proxy.local_capture_problem()
    if problem:
        warnings.append(problem)

    print("whatsent: checking watched folders...", file=sys.stderr)
    after, truncated_after = diskwatch.snapshot(roots, exclude=[run_dir])
    disk = diskwatch.diff(before, after, matcher)
    disk["roots"] = [str(r) for r in roots]
    disk["truncated_roots"] = sorted(set(truncated) | set(truncated_after))

    meta = {
        "whatsent_version": __version__,
        "agent": args.name or Path(command[0]).name,
        "agent_version": args.agent_version,
        "kind": "app" if app else "cli",
        "capture": f"local:{local_spec}" if local_spec else "env",
        "command": command,
        "started_at": started.isoformat(timespec="seconds"),
        "duration_s": duration,
        "exit_code": exit_code,
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "workspace": str(workspace),
        "task_prompt": canary.TASK_PROMPT,
        "warnings": warnings,
        "sample": getattr(args, "sample", False),  # True for the simulated demo agent
    }
    summary = report.summarize(meta, canaries, report.load_events(proxy.events_file), disk, direct,
                               home=getattr(args, "home", None))
    html = report.write(summary, run_dir)
    print_summary(summary, html)
    return exit_code if isinstance(exit_code, int) and exit_code >= 0 else 1


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
    if t["not_inspected"]:
        lines.append("  ! some traffic could not be inspected, see the report")
    for w in s.get("warnings", []):
        lines.append(f"  ! {w}")
    lines.append(f"whatsent: report at {html}")
    print("\n".join(lines), file=sys.stderr)
