import importlib.util
from datetime import date
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("audit_policy", Path(__file__).parents[1] / "scripts/check_dependency_audit.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


def report(name="tornado", version="6.5.10", identifier="CVE-2026-116577"):
    return {"dependencies": [
        {"name": "mitmproxy", "version": "12.3.1", "vulns": []},
        {"name": name, "version": version, "vulns": [{"id": identifier, "aliases": []}]},
    ]}


def test_reviewed_findings_remain_visible():
    errors, known = policy.check(report(identifier="GHSA-pcg2-g6cj-q92c"), date(2026, 10, 30))
    assert not errors and len(known) == 1 and "UNRESOLVED" in known[0]


@pytest.mark.parametrize("changes", [
    {"identifier": "CVE-2099-0001"}, {"version": "6.5.9"}, {"name": "other-package"},
])
def test_new_advisory_or_changed_scope_blocks(changes):
    assert policy.check(report(**changes), date(2026, 10, 30))[0]


def test_exception_expires():
    assert policy.check(report(), date(2026, 11, 30))[0]


@pytest.mark.parametrize("value", [{}, {"dependencies": []}, {"dependencies": [
    {"name": "tornado", "skip_reason": "offline"}, {"name": "mitmproxy", "vulns": []},
]}])
def test_empty_or_skipped_audit_blocks(value):
    assert policy.check(value, date(2026, 10, 30))[0]


def test_patched_dependency_needs_no_exception_even_after_expiry():
    value = report(version="6.6")
    value["dependencies"][1]["vulns"] = []
    assert policy.check(value, date(2026, 11, 30)) == ([], [])
