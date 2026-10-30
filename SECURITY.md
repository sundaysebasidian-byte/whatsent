# Security scope

whatsent observes a test agent with synthetic canaries. It is neither a sandbox nor a firewall: the agent still has the current user's files, login and permissions. Run only tools you trust. The local UI and proxy bind to loopback, and the UI requires a per-process token for API access. Do not expose these ports publicly.

Each run uses a private output directory on POSIX and a separate CA. IDE certificate exceptions are limited to that CA's public key. No system trust store is changed. Normal completion, cancellation and handled failures attempt to remove the CA private keys. Failed removal is reported in the terminal and, when generated, the report; keep that directory private. A machine crash or SIGKILL cannot run cleanup; treat an interrupted output directory as private.

Only `result.json` is intended for public submission. Full reports and raw journals may contain destination paths, command arguments, local paths and diagnostic details. Inspect them before sharing. Home-prefix redaction does not make a full report anonymous. `whatsent check` checks structure and consistency; it cannot establish that submitted measurements are authentic or that arbitrary labels contain no private information.

Missing canaries do not prove that data stayed local. Pinning, application encryption, unsupported encodings, sampling gaps and size/depth limits can hide uploads. A positive control proves visibility of that marker, not complete coverage. Warnings must be reviewed before drawing conclusions. These results describe the tested configuration only.

## Dependency audit, 2026-10-30

Python 3.12+ and mitmproxy 12.3.1+ are now required. The old Python 3.10 resolver selected mitmproxy 11.0.2 and produced 64 advisory records across nine packages. Python 3.10/3.11 can no longer install this candidate. Recreate older environments with Python 3.12+ when upgrading. Explicit security floors also prevent an existing environment from retaining vulnerable transitive versions that mitmproxy's broad lower bounds would otherwise allow.

The current Python 3.13 runtime resolves mitmproxy 12.3.1 and Tornado 6.5.10. These three Tornado advisories remain **unresolved**:

| Advisory | Affected path | Fixed version |
| --- | --- | --- |
| [GHSA-pcg2-g6cj-q92c](https://github.com/tornadoweb/tornado/security/advisories/GHSA-pcg2-g6cj-q92c) / CVE-2026-116577 | Folded HTTP header parsing can exhaust CPU in Tornado HTTP servers. | 6.6 |
| [GHSA-r4j5-9xpp-3985](https://github.com/tornadoweb/tornado/security/advisories/GHSA-r4j5-9xpp-3985) / CVE-2026-115927 | Many small HTTP chunks block Tornado servers and SimpleAsyncHTTPClient and increase memory use. | 6.6 |
| [GHSA-pw9p-v7r6-gx4p](https://github.com/tornadoweb/tornado/security/advisories/GHSA-pw9p-v7r6-gx4p) / CVE-2026-116578 | RedirectHandler templates permitting substitutions in the scheme or host can redirect externally. | 6.6 |

The published mitmproxy 12.3.1 metadata and its current main branch require `tornado>=6.5.0,<=6.5.10`. Resolving it with `tornado>=6.6` fails. Tornado 6.6 also requires Python 3.11+. Downgrading mitmproxy to obtain a looser Tornado bound restores other known vulnerabilities. Do not force-install incompatible versions, edit installed package metadata, or treat removal of audit findings as a patch.

whatsent starts mitmdump; its own UI uses Python's HTTP server. Source inspection found no use of Tornado's HTTP server/client or RedirectHandler in that capture path. A regression test blocks every Tornado import in the CLI, proxy and simulated-agent subprocesses while the real offline HTTP/HTTPS capture completes. This supports the exposure assessment for that tested path, not all possible modes or external uses of the environment. Do not run mitmweb from this environment. The three installed-package findings remain valid.

### Continuous checks

CI audits independently installed runtime dependencies on Python 3.12, 3.13 and 3.14, separate from the audit tool's own dependencies. The complete raw JSON, resolved versions and readable findings are retained as workflow artifacts. A successful CI policy check **does not mean zero vulnerabilities**.

`scripts/check_dependency_audit.py` recognizes only the three advisory identities above on **Tornado 6.5.10**, with a review deadline of **2026-11-29 UTC**. It prints each as UNRESOLVED. New advisories, other affected versions/packages, skipped or missing audit results, and findings remaining after that deadline fail CI. There are no `--ignore-vuln` flags. Once mitmproxy supports patched Tornado, raise the floor to 6.6 or newer, rerun capture tests and dependency audits, and remove the obsolete exception. A patched, clean dependency set passes without using the exception.

## Reporting

Report reproducible issues to the repository owner with the whatsent version, OS, Python version and a minimal synthetic example. Do not publish raw captures, credentials or private CA keys in an issue.
