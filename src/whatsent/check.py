"""Checks on result.json files before they reach the leaderboard.

A result should hold only aggregates. The check rejects files with extra fields (paths, prompts,
commands), strings that look like paths or canary values, and numbers that do not add up. It cannot
tell a real run from a made-up one whose numbers are consistent; reviewers still do that.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

from whatsent import board

TOP = {"type", "schema", "agent", "agent_version", "kind", "capture", "clean", "platform", "date",
       "whatsent_version", "sample", "canaries", "destinations", "totals", "warnings", "control", "runs"}
OPTIONAL = {"clean", "control", "runs"}
CANARY = {"short", "sensitive", "sent_to", "on_disk", "seen_in"}
DEST = {"host", "requests", "bytes_out"}
TOTALS = ("canaries", "leaked", "leaked_sensitive", "requests", "hosts", "bytes_out", "not_inspected",
          "copied_to_disk")
CONTROLS = {"ok", "missed", "unconfirmed", "unfinished"}
NAME = re.compile(r"[A-Za-z0-9 ._+()-]{1,60}")
VERSION = re.compile(r"[A-Za-z0-9 ._+()-]{1,40}")
CAPTURE = re.compile(r"env|local(:[A-Za-z0-9 ._-]{1,40})?")
HOST = re.compile(r"[A-Za-z0-9._:-]{1,253}")
TOKEN = re.compile(r"wsc\d[0-9a-f]{16}")


def _count(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x >= 0


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def validate(r: object, name: str | None = None) -> list[str]:
    """What is wrong with this result, as short messages. Empty if it is fine. ``name`` is the file name."""
    if not isinstance(r, dict):
        return ["not a JSON object"]
    if r.get("type") != "whatsent-result" or type(r.get("schema")) is not int or r["schema"] != board.SCHEMA:
        return ["not a whatsent result (type whatsent-result, schema 1); a full report.json must not be submitted"]
    problems: list[str] = []
    extra = sorted(set(r) - TOP)
    if extra:
        problems.append(f"unexpected fields: {', '.join(extra)}")
    missing = sorted(TOP - OPTIONAL - set(r))
    if missing:
        return problems + [f"missing fields: {', '.join(missing)}"]

    for s in _strings(r):
        if "/" in s or "\\" in s:
            problems.append(f"a value looks like a path: {s[:40]!r}")
        elif TOKEN.search(s):
            problems.append("a value contains a canary marker")
        elif len(s) > 200:
            problems.append("a value is longer than 200 characters")

    def text(key: str, pattern: re.Pattern, none_ok: bool = False) -> None:
        v = r.get(key)
        if v is None and none_ok:
            return
        if not isinstance(v, str) or not pattern.fullmatch(v):
            problems.append(f"{key} has an unexpected value")

    text("agent", NAME)
    text("agent_version", VERSION, none_ok=True)
    text("whatsent_version", VERSION)
    text("platform", NAME)
    text("capture", CAPTURE)
    if r["kind"] not in ("cli", "app"):
        problems.append("kind is not cli or app")
    try:
        date.fromisoformat(r["date"])
    except (TypeError, ValueError):
        problems.append("date is not YYYY-MM-DD")
    for key in ("sample", "clean"):
        if key in r and not isinstance(r[key], bool):
            problems.append(f"{key} is not true or false")
    if not _count(r["warnings"]):
        problems.append("warnings is not a count")
    runs = r.get("runs", 1)
    if not _count(runs) or runs < 1:
        problems.append("runs is not a count of at least 1")
        runs = 1
    if "control" in r and (not isinstance(r["control"], str) or r["control"] not in CONTROLS):
        problems.append("control is not ok, missed, unconfirmed or unfinished")

    canaries = r["canaries"]
    if not isinstance(canaries, dict) or not canaries:
        return problems + ["canaries is empty"]
    for cid, c in canaries.items():
        if not isinstance(cid, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,59}", cid):
            problems.append("canary id has an unexpected value")
        if not isinstance(c, dict) or {"short", "sensitive", "sent_to", "on_disk"} - set(c) or set(c) - CANARY:
            problems.append(f"canary {cid}: unexpected fields")
            return problems
        if not isinstance(c["short"], str) or not isinstance(c["sensitive"], bool) or not isinstance(c["on_disk"], bool):
            problems.append(f"canary {cid}: wrong types")
        hosts = c["sent_to"]
        if not isinstance(hosts, list) or not all(isinstance(h, str) and HOST.fullmatch(h) for h in hosts) \
                or len(set(hosts)) != len(hosts):
            problems.append(f"canary {cid}: sent_to is not a list of distinct hosts")
            return problems
        if "seen_in" in c:
            seen = c["seen_in"]
            if not _count(seen) or seen > runs or (seen > 0) != bool(hosts):
                problems.append(f"canary {cid}: seen_in does not fit runs and sent_to")
        elif runs > 1:
            problems.append(f"canary {cid}: seen_in is required for multiple runs")

    dests = r["destinations"]
    if not isinstance(dests, list) or any(not isinstance(d, dict) or set(d) != DEST for d in dests):
        return problems + ["destinations have unexpected fields"]
    if any(not (isinstance(d["host"], str) and HOST.fullmatch(d["host"]) and _count(d["requests"])
                and _count(d["bytes_out"])) for d in dests):
        return problems + ["destinations have unexpected values"]
    destination_hosts = {d["host"] for d in dests}
    if len(destination_hosts) != len(dests):
        problems.append("destinations contain duplicate hosts")
    for cid, c in canaries.items():
        if not set(c["sent_to"]) <= destination_hosts:
            problems.append(f"canary {cid}: sent_to contains a host missing from destinations")

    t = r["totals"]
    if not isinstance(t, dict) or set(t) != set(TOTALS) or not all(_count(t[k]) for k in TOTALS):
        return problems + ["totals are not the expected counts"]
    sent = [c for c in canaries.values() if c["sent_to"]]
    expected = {
        "canaries": len(canaries), "leaked": len(sent), "leaked_sensitive": sum(1 for c in sent if c["sensitive"]),
        "requests": sum(d["requests"] for d in dests), "hosts": len(dests),
        "bytes_out": sum(d["bytes_out"] for d in dests),
        "copied_to_disk": sum(1 for c in canaries.values() if c["on_disk"]),
    }
    for k, v in expected.items():
        if t[k] != v:
            problems.append(f"totals.{k} is {t[k]} but the entries add up to {v}")

    if not r["sample"]:
        if r.get("control", "ok") == "ok" and not (canaries.get("task_file") or {}).get("sent_to"):
            problems.append("the task file was never seen leaving, but control is not marked "
                            "(rerun with the latest whatsent)")
        stem = board.result_name(r)[:-len(".json")]
        if name is not None and not re.fullmatch(re.escape(stem) + r"(-[2-9]|-[1-9]\d+)?\.json", name):
            problems.append(f"file name should be {stem}.json (or {stem}-2.json for a second batch)")
    return problems


def check(paths: list[Path]) -> int:
    files: list[Path] = []
    for p in paths:
        files += sorted(p.rglob("*.json")) if p.is_dir() else [p]
    bad = 0
    for f in files:
        try:
            problems = validate(json.loads(f.read_text(encoding="utf-8")), f.name)
        except (OSError, ValueError, RecursionError) as exc:
            problems = [f"cannot read: {exc}"]
        for line in problems:
            print(f"{f}: {line}", file=sys.stderr)
        bad += bool(problems)
    print(f"whatsent: checked {len(files)} results, {bad} with problems", file=sys.stderr)
    return 1 if bad or not files else 0
