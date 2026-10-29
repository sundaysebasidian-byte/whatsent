# Security scope

whatsent observes a test agent with synthetic canaries. It is neither a sandbox nor a firewall: the agent still has the current user's files, login and permissions. Run only tools you trust. The local UI and proxy bind to loopback, and the UI requires a per-process token for API access. Do not expose these ports publicly.

Each run uses a private output directory on POSIX and a separate CA. IDE certificate exceptions are limited to that CA's public key. No system trust store is changed. Normal completion, cancellation and handled failures attempt to remove the CA private keys. Failed removal is reported in the terminal and, when generated, the report; keep that directory private. A machine crash or SIGKILL cannot run cleanup; treat an interrupted output directory as private.

Only `result.json` is intended for public submission. Full reports and raw journals may contain destination paths, command arguments, local paths and diagnostic details. Inspect them before sharing. Home-prefix redaction does not make a full report anonymous. `whatsent check` checks structure and consistency; it cannot establish that submitted measurements are authentic or that arbitrary labels contain no private information.

Missing canaries do not prove that data stayed local. Pinning, application encryption, unsupported encodings, sampling gaps and size/depth limits can hide uploads. A positive control proves visibility of that marker, not complete coverage. Warnings must be reviewed before drawing conclusions. These results describe the tested configuration only.

## Dependency audit, 2026-10-29

The Python 3.13 audit resolved mitmproxy 12.3.1 and Tornado 6.5.10. Three Tornado advisories remain in that dependency set:

- [GHSA-pcg2-g6cj-q92c](https://github.com/tornadoweb/tornado/security/advisories/GHSA-pcg2-g6cj-q92c): CPU exhaustion while parsing folded HTTP headers.
- [GHSA-r4j5-9xpp-3985](https://github.com/tornadoweb/tornado/security/advisories/GHSA-r4j5-9xpp-3985): excessive CPU and memory when parsing many small HTTP chunks.
- [GHSA-pw9p-v7r6-gx4p](https://github.com/tornadoweb/tornado/security/advisories/GHSA-pw9p-v7r6-gx4p): open redirects in vulnerable RedirectHandler templates.

Tornado 6.6 fixes these, but mitmproxy 12.3.1 requires `tornado>=6.5.0,<=6.5.10`. Forcing 6.6 would violate its dependency contract. whatsent launches mitmdump, not mitmweb; its own UI uses Python's HTTP server. Inspection found no Tornado HTTP server/client or RedirectHandler in whatsent's runtime path. This reduces the observed exposure but does not make the dependency audit clean. Do not run mitmweb from this environment; re-audit when upstream supports patched Tornado. Other Python versions may resolve different dependencies.

## Reporting

Report reproducible issues to the repository owner with the whatsent version, OS, Python version and a minimal synthetic example. Do not publish raw captures, credentials or private CA keys in an issue.
