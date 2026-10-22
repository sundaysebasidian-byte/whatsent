"""Command line entry point: ``whatsent run -- <agent command>``."""

from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from whatsent import __version__, canary, diskwatch, report
from whatsent.capture import Proxy
from whatsent.detect import Matcher
from whatsent.netwatch import ConnectionSampler


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="whatsent", description="See what your AI coding agent sends, and where.")
    p.add_argument("--version", action="version", version=f"whatsent {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run an agent inside a canary project and report what left the machine",
                         usage="whatsent run [options] -- <agent command> [args...]")
    run.add_argument("--out", type=Path, default=Path("whatsent-report"),
                     help="folder for reports (default: ./whatsent-report)")
    run.add_argument("--port", type=int, help="proxy port (default: a free port)")
    run.add_argument("--watch", type=Path, action="append", default=[], metavar="DIR",
                     help="extra folder to watch for files the agent writes (repeatable)")
    run.add_argument("--no-default-watch", action="store_true",
                     help="only watch folders given with --watch")
    run.add_argument("--mitm-set", action="append", default=[], metavar="KEY=VALUE",
                     help="pass an option through to mitmproxy (advanced, repeatable)")
    run.add_argument("command", nargs=argparse.REMAINDER, help="agent command, after --")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        print("whatsent: give the agent command after --, e.g. whatsent run -- claude", file=sys.stderr)
        return 2
    return run(args, command)


def run(args: argparse.Namespace, command: list[str]) -> int:
    started = datetime.now()
    run_dir = (args.out / started.strftime("%Y%m%d-%H%M%S")).resolve()
    workspace = run_dir / "workspace"
    run_dir.mkdir(parents=True, exist_ok=True)

    canaries = [c.to_dict() for c in canary.create_workspace(workspace)]
    canaries_file = run_dir / "canaries.json"
    canaries_file.write_text(json.dumps(canaries, indent=2))
    matcher = Matcher({c["id"]: c["token"] for c in canaries})

    roots = ([] if args.no_default_watch else diskwatch.default_roots()) + [w.resolve() for w in args.watch]
    print(f"whatsent: snapshotting {len(roots)} folders…", file=sys.stderr)
    before, truncated = diskwatch.snapshot(roots, exclude=[run_dir])

    proxy = Proxy(run_dir, canaries_file, run_dir / "events.jsonl", args.port, args.mitm_set)
    try:
        proxy.start()
    except RuntimeError as exc:
        print(f"whatsent: {exc}", file=sys.stderr)
        return 1
    env = proxy.agent_env(dict(os.environ), proxy.write_ca_bundle(run_dir / "ca-bundle.pem"))

    print(f"""
whatsent: canary project ready at {workspace}
whatsent: proxy on 127.0.0.1:{proxy.port}, starting: {" ".join(command)}
whatsent: suggested prompt (use the same one for every agent you compare):

    {canary.TASK_PROMPT}
""", file=sys.stderr)

    t0 = time.monotonic()
    # Ctrl-C belongs to the agent; we keep running so the report still gets written.
    old_sigint = signal.signal(signal.SIGINT, signal.SIG_IGN)
    exit_code: int | str
    try:
        agent = subprocess.Popen(command, cwd=workspace, env=env,
                                 preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    except OSError as exc:
        signal.signal(signal.SIGINT, old_sigint)
        proxy.stop()
        print(f"whatsent: could not start {command[0]}: {exc}", file=sys.stderr)
        return 127
    sampler = ConnectionSampler(agent.pid, proxy.port)
    sampler.start()
    try:
        exit_code = agent.wait()
        duration = time.monotonic() - t0
        time.sleep(1.0)  # let in-flight requests reach the log
    finally:
        signal.signal(signal.SIGINT, old_sigint)
        direct = sampler.stop()
        proxy.stop()

    print("whatsent: checking watched folders…", file=sys.stderr)
    after, truncated_after = diskwatch.snapshot(roots, exclude=[run_dir])
    disk = diskwatch.diff(before, after, matcher)
    disk["roots"] = [str(r) for r in roots]
    disk["truncated_roots"] = sorted(set(truncated) | set(truncated_after))

    meta = {
        "whatsent_version": __version__,
        "command": command,
        "started_at": started.isoformat(timespec="seconds"),
        "duration_s": duration,
        "exit_code": exit_code,
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "workspace": str(workspace),
        "task_prompt": canary.TASK_PROMPT,
    }
    summary = report.summarize(meta, canaries, report.load_events(proxy.events_file), disk, direct)
    html = report.write(summary, run_dir)
    print_summary(summary, html)
    return exit_code if isinstance(exit_code, int) and exit_code >= 0 else 1


def print_summary(s: dict, html: Path) -> None:
    t = s["totals"]
    lines = [
        "",
        f"whatsent: {t['leaked']} of {t['canaries']} canaries left this machine"
        f" ({t['leaked_sensitive']} sensitive), {t['requests']} requests to {t['hosts']} destinations,"
        f" {report.human_bytes(t['bytes_out'])} sent",
    ]
    for c in s["canaries"]:
        if c["sent_to"]:
            lines.append(f"  - {c['label']} ({c['file']}) -> {', '.join(c['sent_to'])}")
    ni = s["not_inspected"]
    if ni["tls_failed"] or any(not c["local"] for c in ni["direct_connections"]):
        lines.append("  ! some traffic could not be inspected, see the report")
    lines.append(f"whatsent: report at {html}")
    print("\n".join(lines), file=sys.stderr)
