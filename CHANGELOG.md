# Changelog

## 0.3.1

- Require Python 3.12+ and mitmproxy 12.3.1+; enforce security floors for transitive dependencies instead of retaining vulnerable legacy environments.
- Avoid obsolete YAML and ASN.1 dependencies that fail to build or import when resolving minimum dependencies on Python 3.12.
- Audit runtime dependencies in CI with visible, narrowly scoped and expiring exceptions for three unresolved Tornado advisories; verify offline capture does not import Tornado.

- Require a fresh recorder readiness signal after proxy listeners start; clean up failed startup and never mistake an unrelated occupied port for working capture.
- Validate proxy URLs and listening ports before launch. Invalid environment proxies stop startup instead of selecting direct traffic; errors redact credentials.
- Deduplicate runs and batches across mixed directory/file leaderboard arguments; reject unsafe counts and inconsistent date formats and validate aggregates before publication.
- Isolate terminal relaunch status and publish PID/exit files atomically; reject cancelled or expired terminal startup. Resolve relative macOS app bundles before changing the launch directory.
- Apply the same journal validation to live UI updates and final reports, including malformed timestamps, so a bad record cannot stop live updates.
- Record HTTP uploads before responses finish and merge completion events without double-counting. Scan archive bodies separately from headers.
- Bound decompression and archive reads; surface truncated or unsupported network decoding as uninspected.
- Inspect concatenated gzip/zstd frames with shared output limits, bound zstd history memory, and report corrupt streams or unsupported archives. Flag backend-specific completeness gaps.
- Preserve valid journal records and warn about missing, unreadable or damaged capture evidence. Report CA private-key cleanup failures instead of silently ignoring them.
- Reserve run directories and exported batch files atomically to preserve concurrent runs.
- Keep individual runs inside their batch and collect the aggregate once, excluding workspace JSON and duplicate input paths.
- Enforce disk scan limits inside large directories; skip special files and symlinks and recheck at read time.
- Stop agents when capture fails; clean up CA keys and demo listeners on failure and cancellation. Handle termination during startup and UI shutdown.
- Restrict IDE certificate exceptions to the per-run CA public key.
- Validate leaderboard inputs before publication and keep different platforms, capture modes, detector versions and canary definitions separate.
- Reject malformed/oversized UI requests; guard stale process cleanup against PID reuse. Display coverage warnings in reports and on the board.
- Extend CI to Python 3.14 and verify built wheel assets and the offline demo outside the source checkout.

Real IDEs and privileged OS-level capture still require manual validation. See README and SECURITY.md for the remaining scope and dependency limitations.
