import copy
import json
from pathlib import Path

import pytest

from whatsent import board
from whatsent.check import check, validate
from whatsent.cli import main

ROOT = Path(__file__).resolve().parents[1]


def good() -> dict:
    return {
        "type": "whatsent-result", "schema": 1, "agent": "claude", "agent_version": "2.1.301", "kind": "cli",
        "capture": "env", "clean": True, "platform": "Darwin arm64", "date": "2026-10-27",
        "whatsent_version": "0.3.0", "sample": False, "runs": 3, "control": "ok",
        "canaries": {
            "task_file": {"short": "task file", "sensitive": False, "sent_to": ["api.x"], "on_disk": True, "seen_in": 3},
            "dotenv": {"short": ".env secret", "sensitive": True, "sent_to": [], "on_disk": False, "seen_in": 0},
        },
        "destinations": [{"host": "api.x", "requests": 10, "bytes_out": 5000}],
        "totals": {"canaries": 2, "leaked": 1, "leaked_sensitive": 0, "requests": 10, "hosts": 1, "bytes_out": 5000,
                   "not_inspected": 0, "copied_to_disk": 1},
        "warnings": 0,
    }


def edit(fn) -> dict:
    r = copy.deepcopy(good())
    fn(r)
    return r


def test_a_good_result_passes():
    assert validate(good(), "claude-2.1.301-clean.json") == []


@pytest.mark.parametrize("fn, expected", [
    (lambda r: r.update(command=["claude", "-p", "x"]), "unexpected fields: command"),
    (lambda r: r.update(agent="/usr/local/bin/claude"), "looks like a path"),
    (lambda r: r.update(platform="C:\\Users\\me"), "looks like a path"),
    (lambda r: r["canaries"]["dotenv"].update(short="wsc01234567890abcdef0"), "canary marker"),
    (lambda r: r["canaries"]["dotenv"].update(note="x"), "unexpected fields"),
    (lambda r: r["totals"].update(leaked=2), "totals.leaked is 2"),
    (lambda r: r["totals"].update(bytes_out=1), "totals.bytes_out is 1"),
    (lambda r: r["destinations"].append({"host": "b.x", "requests": 1, "bytes_out": 1}), "totals.hosts is 1"),
    (lambda r: r["destinations"][0].update(host="https://api.x/v1"), "looks like a path"),
    (lambda r: r["canaries"]["dotenv"].update(sent_to=["t.x"]), "seen_in does not fit"),
    (lambda r: r["canaries"]["task_file"].update(seen_in=4), "seen_in does not fit"),
    (lambda r: r.update(date="27-10-2026"), "date is not"),
    (lambda r: r.update(kind="web"), "kind is not"),
    (lambda r: r.update(control="great"), "control is not"),
    (lambda r: r.update(runs=0), "runs is not"),
    (lambda r: r["canaries"]["task_file"].update(sent_to=[], seen_in=0), "task file was never seen"),
    (lambda r: r.pop("totals"), "missing fields: totals"),
])
def test_defects_are_reported(fn, expected):
    problems = validate(edit(fn), "claude-2.1.301-clean.json")
    assert any(expected in p for p in problems), problems


def test_an_unseen_task_file_is_fine_if_the_result_says_so():
    def unseen(r):
        r["control"] = "unconfirmed"
        r["canaries"]["task_file"].update(sent_to=[], seen_in=0)
        r["totals"].update(leaked=0)
    assert validate(edit(unseen), "claude-2.1.301-clean.json") == []


def test_file_name_must_match_the_content():
    assert any("file name should be claude-2.1.301-clean.json" in p for p in validate(good(), "mine.json"))
    assert board.result_name(good()) == "claude-2.1.301-clean.json"
    assert validate(good()) == []  # no name given, no name check
    assert validate(good(), "claude-2.1.301-clean-2.json") == []  # a second batch of runs
    assert validate(good(), "claude-2.1.301-clean-12.json") == []
    for wrong in ("claude-2.1.301-clean-1.json", "claude-2.1.301-clean-x.json", "claude-2.1.301.json"):
        assert validate(good(), wrong), wrong


def test_a_full_report_is_not_accepted():
    assert any("not a whatsent result" in p for p in validate({"canaries": [], "command": ["x"]}))
    assert validate([1]) == ["not a JSON object"]


def test_check_command_reads_files_and_folders(tmp_path, capsys):
    ok = tmp_path / "claude-2.1.301-clean.json"
    ok.write_text(json.dumps(good()), encoding="utf-8")
    assert check([tmp_path]) == 0
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    assert main(["check", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "bad.json: cannot read" in err and "2 results, 1 with problems" in err
    assert check([tmp_path / "empty"]) == 1  # nothing to check is not a pass


def test_the_results_in_this_repository_pass():
    assert check([ROOT / "results", ROOT / "examples" / "results"]) == 0
