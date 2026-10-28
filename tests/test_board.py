from __future__ import annotations

import json
from pathlib import Path

from whatsent import board, report

EXAMPLES = Path(__file__).parent.parent / "examples" / "results"
TOKEN = "wsc2deadbeefcafef00d"


def test_result_is_shareable():
    canaries = [{"id": "dotenv", "token": TOKEN, "file": ".env", "label": "Secret", "sensitive": True,
                 "short": ".env secret"}]
    events = [{"type": "http", "host": "api.x.test", "bytes_out": 10, "bytes_in": 1, "canaries": ["dotenv"]}]
    disk = {"leaks": [{"path": "/home/me/.x/log", "size": 1, "new": True, "canaries": ["dotenv"]}],
            "suspicious": [], "changed_files": 1, "roots": ["/home/me/.x"]}
    meta = {"whatsent_version": "0", "agent": "x", "command": ["x", "--secret-flag"], "started_at": "2026-10-22T10:00:00",
            "duration_s": 1, "exit_code": 0, "platform": "Darwin 25.0 (arm64)", "workspace": "/home/me/ws"}
    result = board.to_result(report.summarize(meta, canaries, events, disk, [], home=Path("/home/me")))
    text = json.dumps(result)
    for leaked in (TOKEN, "/home/me", "~/", "--secret-flag", "workspace"):
        assert leaked not in text
    assert result["canaries"]["dotenv"] == {"short": ".env secret", "sensitive": True,
                                            "sent_to": ["api.x.test"], "on_disk": True}
    assert result["platform"] == "Darwin arm64" and result["date"] == "2026-10-22"


def test_board_from_examples(tmp_path):
    assert board.build([EXAMPLES], tmp_path) == 0
    data = json.loads((tmp_path / "leaderboard.json").read_text(encoding="utf-8"))
    names = [r["agent"] for r in data["results"]]
    assert names[0] == "Example Agent A" and names[-1] == "Example IDE E"  # clean first, most secrets last
    assert all(r["sample"] for r in data["results"])
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "Example data." in html and "not measurements of any real product" in html


def test_results_of_the_same_agent_are_combined_under_the_newest_date():
    old = json.loads((EXAMPLES / "example-agent-a.json").read_text(encoding="utf-8"))
    new = {**old, "date": "2099-02-01"}
    (row,) = board.latest_per_agent([old, new])
    assert row["date"] == "2099-02-01" and row["runs"] == 2
