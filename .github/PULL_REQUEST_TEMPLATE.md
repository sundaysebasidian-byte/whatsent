## What changed

<!-- One or two sentences. Say why, not only what. -->

## Checklist

- [ ] `pytest` and `node --test tests/ui_workflows.test.js` pass locally.
- [ ] No test needs network access, a real agent or a configured proxy.
- [ ] `CHANGELOG.md` has an entry, or the change is not user-visible.
- [ ] Result PRs only: the new files are in `results/`, `whatsent check results/` passes, and no report, journal or canary value is included.
- [ ] Detection changes say which encoding or transport the new case covers and how it was verified offline.
- [ ] Changes to capture, the UI or the proxy follow `SECURITY.md`: loopback only, no system trust store change, no new path for a page to reach the API.
