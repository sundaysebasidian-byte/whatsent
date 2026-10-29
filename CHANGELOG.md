# Changelog

## 0.3.1

- Record HTTP uploads before responses finish and merge completion events without double-counting. Scan archive bodies separately from headers.
- Bound decompression and archive reads; surface truncated or unsupported network decoding as uninspected.
- Reserve run directories and exported batch files atomically to preserve concurrent runs.
- Keep individual runs inside their batch and collect the aggregate once, excluding workspace JSON and duplicate input paths.
- Enforce disk scan limits inside large directories; skip special files and symlinks and recheck at read time.
- Stop agents when capture fails; clean up CA keys and demo listeners on failure and cancellation. Handle termination during startup and UI shutdown.
- Restrict IDE certificate exceptions to the per-run CA public key.
- Validate leaderboard inputs before publication and keep different platforms, capture modes, detector versions and canary definitions separate.
- Reject malformed/oversized UI requests; guard stale process cleanup against PID reuse. Display coverage warnings in reports and on the board.
- Extend CI to Python 3.14 and verify built wheel assets and the offline demo outside the source checkout.

Real IDEs and privileged OS-level capture still require manual validation. See README and SECURITY.md for the remaining scope and dependency limitations.
