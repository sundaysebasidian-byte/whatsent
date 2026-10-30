"""Keep unresolved advisories visible; fail on new, skipped or expired findings."""

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# mitmproxy 12.3.1 caps Tornado below 6.6. See SECURITY.md for exposure and removal criteria.
REVIEW_UNTIL = date(2026, 11, 29)
TORNADO_ADVISORIES = {
    "CVE-2026-116577", "GHSA-pcg2-g6cj-q92c",
    "CVE-2026-115927", "GHSA-r4j5-9xpp-3985",
    "CVE-2026-116578", "GHSA-pw9p-v7r6-gx4p",
}


def check(report: dict, today: date) -> tuple[list[str], list[str]]:
    errors, known = [], []
    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        return ["missing dependency audit results"], []
    names = {d.get("name") for d in dependencies if isinstance(d, dict)}
    if not {"mitmproxy", "tornado"} <= names:
        errors.append("audit must include the mitmproxy and tornado runtime dependencies")
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            errors.append("invalid dependency audit entry")
            continue
        name, version = dependency.get("name"), dependency.get("version")
        vulnerabilities = dependency.get("vulns")
        if dependency.get("skip_reason") or not isinstance(vulnerabilities, list):
            errors.append(f"{name}: dependency was not audited")
            continue
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict) or not isinstance(vulnerability.get("id"), str):
                errors.append(f"{name}: invalid advisory entry")
                continue
            aliases = vulnerability.get("aliases", [])
            if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
                errors.append(f"{name}: invalid advisory aliases")
                continue
            finding = f"{name} {version}: {vulnerability['id']}"
            if (name == "tornado" and version == "6.5.10" and today <= REVIEW_UNTIL
                    and ({vulnerability["id"], *aliases} & TORNADO_ADVISORIES)):
                known.append(f"UNRESOLVED: {finding}; review expires {REVIEW_UNTIL}")
            else:
                errors.append(f"{finding}: new, out-of-scope or expired finding")
    return errors, known


def main() -> int:
    try:
        report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("audit report must be an object")
        errors, known = check(report, datetime.now(timezone.utc).date())
    except (IndexError, OSError, ValueError) as exc:
        print(f"Dependency audit failed: {exc}", file=sys.stderr)
        return 1
    for message in known + errors:
        print(message)
    print(f"Dependency audit: {len(errors)} blocking findings, {len(known)} unresolved reviewed findings.")
    if known:
        print("This is not a clean vulnerability audit. See SECURITY.md.")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
