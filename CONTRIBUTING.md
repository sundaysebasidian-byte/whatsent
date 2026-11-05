# Contributing

whatsent is a small, dependency-light tool with a strict offline test suite. Changes that widen the trust boundary or add a network dependency to a test need to be discussed in an issue first.

## Development setup

```bash
python -m venv .venv
. .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[test]"
pytest
node --test tests/ui_workflows.test.js
```

Python 3.12 or newer is required. `pytest` covers the Python side; the Node test runs the shipped `ui/app.js` state and transport code under `node:test` and needs Node 20+. The `package` job in `.github/workflows/test.yml` runs both.

No test may use the network. `whatsent demo`, the simulated agent and `tests/fake_app.py` talk only to local servers on 127.0.0.1, and the suite must pass with no internet, no installed agent and no ambient `HTTPS_PROXY`. If a change needs a real remote host to be tested, it cannot be a test; describe it in the pull request instead.

## Project layout

| Module | Responsibility |
| --- | --- |
| `src/whatsent/cli.py` | Argument parsing and the `run`, `demo`, `ui`, `board` and `check` commands. |
| `src/whatsent/canary.py` | Build the throwaway project and plant one unique token per planted value. |
| `src/whatsent/capture.py` | Start `mitmdump`, wait for its readiness signal and build the agent's proxy environment. |
| `src/whatsent/_addon.py` | mitmproxy addon loaded into the proxy; writes one JSON line per request, response and error. |
| `src/whatsent/detect.py` | Search bodies for tokens through gzip, zstd, base64, URL encoding and zip/tar archives. |
| `src/whatsent/diskwatch.py` | Snapshot the watched folders before and after the run and report new archives and large files. |
| `src/whatsent/netwatch.py` | Sample the agent's open sockets to catch connections that skipped the proxy. |
| `src/whatsent/report.py` | Turn the journals into `report.json` and the single-file `report.html`. |
| `src/whatsent/board.py` | Build the static leaderboard and `leaderboard.json` from result files. |
| `src/whatsent/check.py` | Validate submitted `result.json` files before they reach `results/`. |
| `src/whatsent/agents.py` | Ask an agent for its version and compute the `--clean` command line. |
| `src/whatsent/apps.py` | Resolve and launch desktop IDEs with the per-run proxy and certificate switches. |
| `src/whatsent/child.py` | Run a CLI agent in a terminal window opened by the UI. |
| `src/whatsent/ui.py` | The loopback-only web server behind `whatsent ui`. |
| `src/whatsent/demo.py` | Wire the offline demo: local servers, the simulated agent and a report. |
| `src/whatsent/demo_agent.py` | The simulated agent that leaks in every way whatsent should catch. |

`src/whatsent/ui/` holds the page, styles and script served by `ui.py`. `tests/` mirrors these modules; `examples/` holds the made-up leaderboard input used until `results/` has real runs.

## Adding an agent to `--clean`

`--clean` is best effort and only claims what the agent itself prints. Two edits in `src/whatsent/agents.py`:

1. Add the program name to `KNOWN` so `detect_version` is allowed to run `<agent> --version`. The set exists because an arbitrary command's `--version` could start the agent instead.
2. Add a branch to `clean()` that returns a `Clean` with the rewritten `command`, any `env` additions and the `notes` that whatsent prints to the user. Return `None` when no switch is known: `--clean` then says so and runs the command unchanged.

Agents whose switches have to be discovered at runtime can follow `_clean_codex`, which reads `features list` and `mcp list --json` and only passes names that match `SAFE_NAME`. Keep every added flag visible in `notes`; a silent flag would make a run look cleaner than it was.

Add cases to `tests/test_features.py` (`test_clean_claude`, `test_clean_codex`) that assert the exact command line. A new agent with no switch needs a test showing that `clean()` returns `None`.

## Adding an IDE

`src/whatsent/apps.py` resolves a name to a binary through its `KNOWN` mapping:

```python
"cursor": AppInfo("Cursor", ("Cursor.app",), ("cursor",), ("cursor/Cursor.exe",)),
```

The fields are the display name, macOS bundle names searched under `/Applications` and `~/Applications`, Linux executables found on `PATH`, and Windows executables relative to `%LOCALAPPDATA%\Programs` or `%ProgramFiles%`. Paths you have not verified may simply fail to resolve; that is acceptable because `--app /path/to/app` always works.

Nothing else is needed to launch it: `command()` adds `--proxy-server`, the SPKI-scoped certificate exception, `--disable-quic` and the workspace path. Check the addition against `tests/test_apps.py` (resolution and the proxy switches) and `tests/fake_app.py`, the stand-in Electron app used by the end-to-end test. When you have run a real IDE, say which version and OS in the pull request and update the limitations in `README.md`.

## Submitting a leaderboard result

Follow [`results/README.md`](results/README.md): run the agent with the suggested prompt and `--result-to results/`, then run `whatsent check results/` and open a pull request with the new file. `check` rejects extra fields, path-like strings, canary values and totals that do not add up; CI runs it on every pull request. Reviewers still read the pull request, because consistent numbers cannot prove a run happened.

Run only agents you trust, and read `SECURITY.md` before sharing anything: `result.json` is the only file meant for publication. Full reports and journals contain paths and command arguments.

## Commits and pull requests

Commit messages are one imperative sentence, capitalised, no trailing period, with the reason in the body when it is not obvious:

```
Keep unreadable folders out of the partial-scan warning

A folder the user may not read made the whole watched root count as
only partly scanned, which put a warning on every run.
```

Keep one logical change per commit. Before opening a pull request, run `pytest` and the Node test, and add a `CHANGELOG.md` entry when the change is visible to users. Pull requests that add a result file need `whatsent check results/` to pass and nothing else.

## Reporting a vulnerability

Do not open a public issue. See [`SECURITY.md`](SECURITY.md) for the scope and the private reporting route.
