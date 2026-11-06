#!/usr/bin/env python3
"""Record a real ``whatsent ui`` demo run as the fixture behind the static live demo.

    python scripts/record_demo.py            # writes scripts/demo-fixture.json

It starts ``whatsent ui`` on a free port, starts the simulated demo agent through the same HTTP
API the web page uses, and stores the event stream with its timing, plus the finished run's
report.json (paths scrubbed) so the demo's full report can be rendered. Set-up time before the
agent starts is trimmed; the agent's own requests keep their real timing. Run it again whenever
the UI events or the report change, then commit the fixture.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = Path(__file__).with_name("demo-fixture.json")
LEAD_IN_MS = 700  # what remains of the set-up time before "launched"
MAX_WAIT_MS = 1500  # longest idle stretch kept between the last request and the end


def start_server(out: Path) -> tuple[subprocess.Popen, str]:
    proc = subprocess.Popen([sys.executable, "-m", "whatsent", "ui", "--no-browser", "--out", str(out)],
                            stderr=subprocess.PIPE, text=True, cwd=ROOT)
    lines: queue.Queue[str] = queue.Queue()
    # readline() blocks, so read on a thread and wait on the queue with the deadline.
    threading.Thread(target=lambda: [lines.put(line) for line in proc.stderr], daemon=True).start()
    deadline = time.monotonic() + 30
    while (left := deadline - time.monotonic()) > 0:
        try:
            line = lines.get(timeout=min(left, 0.5))
        except queue.Empty:
            if proc.poll() is not None:
                break
            continue
        match = re.search(r"http://127\.0\.0\.1:\d+/", line)
        if match:
            return proc, match.group(0)
    proc.kill()
    proc.wait()
    raise SystemExit("record_demo: whatsent ui did not start")


def request(url: str, token: str, body: dict | None = None):
    headers = {"X-Whatsent-Token": token}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    return urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=120)


def record(base: str) -> tuple[list[dict], dict]:
    page = urllib.request.urlopen(base, timeout=30).read().decode()
    token = re.search(r'name="whatsent-token" content="([^"]+)"', page).group(1)
    t0 = time.monotonic()
    job = json.load(request(base + "api/start", token, {"tool": "demo"}))["job"]
    events: list[dict] = []
    with request(f"{base}api/events?job={job}&since=0&token={token}", token) as stream:
        for raw in stream:
            line = raw.decode().strip()
            if not line.startswith("data:"):
                continue
            ev = json.loads(line[5:])
            ev["at"] = round((time.monotonic() - t0) * 1000)
            events.append(ev)
            if ev["kind"] in ("done", "error"):
                break
    if events[-1]["kind"] != "done":
        raise SystemExit(f"record_demo: the run ended with {events[-1]}")
    return events, events[-1]["report"]


def trim(events: list[dict]) -> list[dict]:
    """Squeeze the set-up before the agent starts into LEAD_IN_MS and the idle wait after its last
    request into MAX_WAIT_MS; the agent's own requests keep their recorded timing."""
    launch = next(ev["at"] for ev in events if ev["kind"] == "launched")
    out, saved = [], 0
    for prev, ev in zip([None, *events], events):
        at = ev["at"]
        if at <= launch:
            at = round(at * LEAD_IN_MS / launch)
        else:
            if prev is not None and ev["kind"] == "finishing" and prev["at"] > launch:
                saved += max(0, ev["at"] - prev["at"] - MAX_WAIT_MS)
            at = at - launch + LEAD_IN_MS - saved
        ev = {k: v for k, v in ev.items() if k not in ("seq", "wall")} | {"at": at}
        if ev["kind"] == "job":
            ev["id"] = "replay"
        out.append(ev)
    return out


def scrub(summary: dict) -> dict:
    """The run's report.json without this machine's paths or this run's random markers."""
    def arg(a: str) -> str:
        return os.path.basename(a) if os.path.isabs(a) and not a.startswith("~") else a
    summary["command"] = [arg(a) for a in summary["command"]]
    summary["workspace"] = "workspace"
    for c in summary["canaries"]:
        c["token"] = ""
    leaks = [p for p in ("/Users/", "/home/", "/var/folders", "/private/", "/tmp/") if p in json.dumps(summary)]
    if leaks:
        raise SystemExit(f"record_demo: the report still contains local paths ({leaks})")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="whatsent-record-") as tmp:
        proc, base = start_server(Path(tmp))
        try:
            events, view = record(base)
        finally:
            proc.terminate()
            try:
                proc.wait(15)
            except subprocess.TimeoutExpired:
                proc.kill()
        summary = scrub(json.loads((Path(tmp) / view["run"] / "report.json").read_text(encoding="utf-8")))
    from whatsent import __version__
    fixture = {"schema": 1, "whatsent_version": __version__, "events": trim(events), "summary": summary}
    args.out.write_text(json.dumps(fixture, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"record_demo: {len(fixture['events'])} events over {fixture['events'][-1]['at'] / 1000:.1f}s -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
