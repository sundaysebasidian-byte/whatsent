"""Write made-up example results for the leaderboard page.

These are NOT measurements. The agents are fictional, the hosts use the reserved
.test domain, and every result is marked "sample": true so the page labels it.
Run: python examples/make_examples.py
"""

from __future__ import annotations

import json
from pathlib import Path

from whatsent import report
from whatsent.board import to_result

OUT = Path(__file__).with_name("results")
CANARIES = [
    ("task_file", "src/app.py", "File the task asks about", False, "task file"),
    ("unrelated_source", "src/billing.py", "Source file unrelated to the task", False, "unrelated file"),
    ("dotenv", ".env", "Secret in .env (gitignored)", True, ".env secret"),
    ("credentials", "config/credentials.json", "Cloud credentials file (gitignored)", True, "cloud credentials"),
    ("file_name", "notes/x.md", "File name only (directory listing)", False, "file listing"),
    ("git_history", ".git", "Commit message in git history", True, "git history"),
]

# name, kind, capture, [(host, requests, bytes, canaries, via)], tls_failed hosts, canaries copied to disk
EXAMPLES = [
    ("Example Agent A", "cli", "env", [("api.example-a.test", 6, 48_000, ["task_file"], "proxy")], [], []),
    ("Example Agent B", "cli", "env",
     [("api.example-b.test", 11, 162_000, ["task_file", "unrelated_source", "file_name"], "proxy"),
      ("telemetry.example-b.test", 4, 9_000, [], "proxy")], [], ["dotenv"]),
    ("Example Agent C", "cli", "env",
     [("api.example-c.test", 8, 95_000, ["task_file", "file_name"], "proxy"),
      ("logs.example-c.test", 3, 21_000, ["dotenv"], "proxy")], [], []),
    ("Example Agent D", "cli", "env", [("api.example-d.test", 5, 40_000, ["task_file"], "proxy")],
     ["stream.example-d.test"], []),
    ("Example IDE E", "app", "local:Example IDE E",
     [("api.example-e.test", 23, 410_000, ["task_file", "unrelated_source", "file_name"], "proxy"),
      ("sync.example-e.test", 2, 1_900_000, ["credentials", "git_history"], "local")], [], ["credentials"]),
]


def main() -> None:
    OUT.mkdir(exist_ok=True)
    canaries = [{"id": i, "token": "example", "file": f, "label": l, "sensitive": s, "short": sh}
                for i, f, l, s, sh in CANARIES]
    for n, (name, kind, capture, hosts, pinned, disk_ids) in enumerate(EXAMPLES):
        events = []
        for host, requests, size, ids, via in hosts:
            for r in range(requests):
                events.append({"type": "http", "host": host, "bytes_out": size // requests, "bytes_in": 100,
                               "canaries": ids if r == 0 else [], "via": via})
        events += [{"type": "tls_failed", "host": h, "port": 443, "error": "unknown ca"} for h in pinned]
        disk = {"leaks": [{"path": "~/.example/log.jsonl", "size": 1000, "new": True, "canaries": disk_ids}]
                if disk_ids else [], "suspicious": [], "changed_files": 3, "roots": []}
        meta = {"whatsent_version": "0.2.0", "agent": name, "agent_version": "1.0 (example)", "kind": kind,
                "capture": capture, "command": ["example"], "started_at": f"2026-10-2{n}T12:00:00",
                "duration_s": 60, "exit_code": 0, "platform": "Darwin 25.0 (arm64)", "sample": True,
                "warnings": []}
        result = to_result(report.summarize(meta, canaries, events, disk, []))
        slug = name.lower().replace(" ", "-")
        (OUT / f"{slug}.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
