# whatsent

**See what your AI coding agent sends, and where.** One command runs any agent, CLI or IDE, inside a throwaway project full of fake secrets, records its traffic and the files it leaves behind, and gives you a one-page report of what left your machine.

![A whatsent report: 3 of 6 canaries left this machine, including the .env secret](docs/report.png)

<sub>Report from `whatsent demo`, which runs a simulated agent against local servers. Not a real product.</sub>

```bash
pipx install git+https://github.com/sundaysebasidian-byte/whatsent   # or: uv tool install git+https://...
whatsent demo                  # 10-second offline demo, no agent needed
whatsent ui                    # the same, in a local web app: pick a tool, watch it live
whatsent run -- claude         # a CLI agent
whatsent run --app cursor      # an IDE agent
```

On Windows, in PowerShell (needs [Python 3.12+](https://www.python.org/downloads/windows/) and [Git](https://git-scm.com/download/win)):

```powershell
py -m pip install --user pipx; py -m pipx ensurepath   # once, then open a new terminal
pipx install git+https://github.com/sundaysebasidian-byte/whatsent
whatsent demo
whatsent ui
whatsent run -- claude
whatsent run --app cursor
```

[中文说明](README_zh.md) · [Leaderboard](https://sundaysebasidian-byte.github.io/whatsent/) · [Sample report](https://sundaysebasidian-byte.github.io/whatsent/sample-report.html)

## Why

Coding agents read your whole project. Most of what they send is the code you asked them to work on, which is expected. The question is what else goes along: your `.env`, gitignored credentials, git history, files you never mentioned, or a packed snapshot of the entire workspace. Vendor privacy pages describe intent; whatsent shows behaviour.

whatsent is an audit tool, not a firewall. It does not block anything.

## How it works

1. **Canary project.** whatsent creates a small fake project and plants a unique random marker in each file: the file the task is about, an unrelated source file, a gitignored `.env`, a gitignored credentials file, a file whose *name* is the marker, and a git commit message. All values are obviously fake and new on every run.
2. **Traffic capture.** It starts a local [mitmproxy](https://mitmproxy.org) and points the agent at it with a per-run CA certificate, so HTTPS requests can be read. Every request is searched for the markers, including gzip, zstd, URL-encoded, base64, zip/tar payloads and compressed gRPC/Connect messages.
3. **Disk watch.** It snapshots the agent's cache and config folders before and after the run. Tools that encrypt their uploads usually stage them on disk first; whatsent lists new archives and large blobs and searches them for markers.
4. **Bypass check.** It samples the agent's open sockets during the run, so a connection that skips the proxy (TCP or UDP/QUIC) shows up as "not inspected" instead of silently looking clean.
5. **Report.** A single `report.html` (plus `report.json` and a shareable `result.json`) in `./whatsent-report/<timestamp>/`. Your home folder is shown as `~`.

## Usage

### Web app

```bash
whatsent ui                                  # opens http://127.0.0.1:<port>/ in your browser
```

Pick an installed agent or IDE, follow the steps, and watch requests and canaries arrive live; the report opens when the agent exits and can be saved as an image. CLI agents open in a new terminal window; IDEs are relaunched in test mode, as below. The server only listens on 127.0.0.1 and needs no internet. Press Ctrl+C to stop it.

### CLI agents

```bash
whatsent run -- claude                       # interactive: type the suggested prompt, exit once the agent is done
whatsent run -- codex exec "Fix the bug in src/app.py so that add() returns the sum of its arguments."
whatsent run -- gemini
whatsent run -- aider --yes-always --message "Fix the bug in src/app.py so that add() returns the sum of its arguments."
```

whatsent prints a suggested prompt before the agent starts. Use the same prompt for every agent you compare. The agent runs inside the canary project, with your normal login and settings.

Relative executable paths (such as `./.venv/bin/agent`) are resolved from the directory where you start whatsent. Relative file paths in the agent's arguments refer to the canary project; use absolute paths if you intentionally need files elsewhere.

Your own MCP servers, connectors and plugins send traffic of their own. Add `--clean` to turn them off for `claude`, `codex`, `codebuddy` and `copilot`, so the report is about the agent and not your setup; whatsent prints what it switched off. For other agents `--clean` says it has no switches and runs as usual.

```bash
whatsent run --clean -- claude -p "Fix the bug in src/app.py so that add() returns the sum of its arguments." --permission-mode acceptEdits
whatsent run --clean --timeout 300 --result-to results/ -- codex exec -s workspace-write "Fix the bug in src/app.py so that add() returns the sum of its arguments."
```

Agents vary from run to run, so a result from one run can mislead. `--runs 3` runs the agent three times, each in a fresh canary project, and writes one combined result: a canary counts as sent if any run sent it, the board shows in how many (for example `2/3`), and uploads are averaged per run.

The agent version is asked from the agent (`--version`) unless you pass `--agent-version`. `--timeout` stops an agent that hangs, and `--result-to results/` saves the run's `result.json` as `results/<agent>-<version>[-clean].json`. Run folders are reserved atomically (a same-second collision gets a numeric suffix). A file already there is never overwritten, including concurrent exports: a later batch of runs is saved as `-2`, `-3` and the board combines them.

Multi-run batches keep their individual reports inside one `<timestamp>-xN/` folder, alongside the combined `result.json`. The board reads that aggregate once and ignores the nested workspace files. For output from versions before 0.3.1, pass the combined result explicitly or use the `--result-to` folder to avoid counting individual runs again.

If `HTTPS_PROXY` is set (a corporate or VPN proxy), whatsent forwards to it, because the agent could only reach the internet through it. Choose another with `--upstream URL`, or explicitly use `--upstream none` to connect directly. Only HTTP(S) host-and-port URLs work; invalid addresses, URL credentials and unsupported proxies such as SOCKS stop startup rather than silently switching to a direct connection. Proxy errors do not print URL credentials.

### IDE agents (Cursor, Trae, Windsurf, …)

```bash
whatsent run --app cursor                    # also: trae, trae-cn, windsurf, kiro, qoder, codebuddy, vscode
whatsent run --app "/Applications/Some IDE.app"
whatsent run --app "$env:LOCALAPPDATA\Programs\cursor\Cursor.exe"   # Windows: path to the .exe
```

Quit the app completely first: a second launch is handed to the running copy, which whatsent cannot see. whatsent starts the app's own binary with the canary project open and Chromium's `--proxy-server`, `--ignore-certificate-errors-spki-list` and `--disable-quic` switches. The certificate exception is restricted to this run's CA public key; unrelated invalid certificates remain untrusted. mitmproxy still verifies the real servers' certificates. An IDE that does not support this Chromium switch may reject the proxy certificate; that is reported as uninspected traffic. Ask the AI chat the suggested prompt, wait for it to finish, then quit the app (Cmd+Q, or File > Exit on Windows).

### Traffic that ignores proxy settings (experimental)

```bash
whatsent run --capture local -- some-agent
whatsent run --app trae --capture local:Trae
```

`--capture local` adds mitmproxy's local capture mode, which redirects the traffic of matching processes at OS level. On macOS this asks you once to allow mitmproxy's system extension; on Linux it needs root; on Windows, run it from an administrator terminal. Hosts reached this way are marked "ignored proxy, caught at OS level" in the report. If the capture fails to start, the report says so instead of looking clean.

### Options

| Option | Meaning |
| --- | --- |
| `--app NAME\|PATH` | Launch a desktop IDE agent |
| `--capture env\|local[:SPEC]` | Proxy settings only (default), or add OS-level capture for processes matching SPEC |
| `--clean` | Turn off your MCP servers, connectors and plugins (`claude`, `codex`, `codebuddy`, `copilot`) |
| `--name`, `--agent-version` | Label the run in the report and leaderboard (the version is asked from the agent by default) |
| `--runs N` | Run the agent N times and combine them into one result |
| `--timeout SECONDS` | Stop the agent after this long |
| `--upstream URL\|none` | Forward to this HTTP(S) proxy; default is the one in `HTTPS_PROXY`, if any |
| `--out DIR` | Where reports go (default `./whatsent-report`) |
| `--result-to DIR` | Also copy `result.json` to `DIR/<agent>-<version>[-clean].json`; a file already there is kept and this one gets `-2`, `-3` |
| `--watch DIR` | Also watch this folder for files the agent writes (repeatable) |
| `--no-default-watch` | Watch only the `--watch` folders |
| `--port N` | Fixed proxy port |
| `--mitm-set KEY=VALUE` | Pass an option to mitmproxy (advanced), e.g. `ssl_insecure=true` |

By default whatsent watches agent folders such as `~/.claude`, `~/.codex`, `~/.gemini`, `~/.cursor`, `~/.trae`, plus `~/.cache`, `~/.config`, `~/.local/share` and the temp folder on Linux, `~/Library/Caches` and `~/Library/Application Support` on macOS, and `%APPDATA%` and `%LOCALAPPDATA%` (which holds the temp folder) on Windows. Busy browser caches are skipped.

## Reading the report

- **Grey: not confirmed / incomplete**: the task file (`src/app.py`, with its marker on the buggy line) must reach the model, so it is the run's check that capture works. If it was never seen leaving, the report says so at the top instead of looking clean: either the agent did not finish the task (run again and exit only after it is done), or it sent the file in a form whatsent could not read. With `--runs`, one run that is not confirmed marks the combined result.
- **Red**: something no task needed left the machine (`.env`, credentials, git history).
- **Amber / →**: ordinary project files left the machine. Sending the file you asked about to the model is expected; sending unrelated files or a directory listing tells you how much context the agent uploads.
- **Not inspected**: hosts that rejected whatsent's certificate (certificate pinning) or connections that ignored the proxy. A clean report means nothing if this section is not empty.
- **Written to disk**: local copies of your files (for example conversation logs) and new archives. An archive that appears right before a large upload is worth a closer look.

## Leaderboard

`whatsent board results/ -o site/` turns many `result.json` files into a static page and `leaderboard.json`; GitHub Actions publishes it to GitHub Pages. To add an agent, run it with the suggested prompt, for example `whatsent run --clean --result-to results/ -- <agent>`, and open a pull request with the file it saves in [`results/`](results/README.md). `result.json` holds only aggregates: which canaries left, destination hosts and byte counts, with no paths, prompts or file contents. `whatsent check results/` rejects files that carry more than aggregates or whose numbers do not add up, and CI runs it on every pull request. The board validates its inputs before writing anything and refuses invalid or empty input. Runs are combined only when the agent version, clean mode, operating system/architecture, capture mode, whatsent version and canary definitions match. A run with `--clean` is marked on the board and ranked apart from one with the machine's own MCP servers and plugins.

Results from [`results/`](results/) are what the board shows. While that folder is empty it shows made-up examples of fictional agents, labelled as examples ([examples/make_examples.py](examples/make_examples.py)).

## Requirements

- macOS, Linux or Windows 10/11, Python 3.12+ (the macOS system Python is too old; use Homebrew Python, `pipx` or `uv tool install`).
- The agent you want to test, already installed and logged in.

## Known limitations

See [SECURITY.md](SECURITY.md) for the trust boundary, report privacy and current dependency advisories.

- Without `--capture local`, only traffic that honours proxy settings is decrypted. Tools that pin certificates or ship their own trust store are listed under "Not inspected", not analysed.
- IDE support relies on Electron honouring `--proxy-server` and the extension host honouring `HTTPS_PROXY` / `NODE_EXTRA_CA_CERTS`. It has been tested with a stand-in app, not yet with real Cursor or Trae. App names other than the path you pass may not match your install.
- `--capture local` has not yet been tested on a real Mac or Windows PC; the Linux path needs root and eBPF.
- Windows support is tested in CI (the demo and the stand-in IDE), not yet with real agents. The Windows install paths of the IDEs are best guesses; if `--app NAME` does not find yours, pass the `.exe` path.
- HTTP uploads are journaled when the request is read, even if its response never finishes. A captured upload is not proof that the remote server stored or processed it.
- Decoding and archive expansion have a 200 MiB output budget, two nested expansion levels, 4,096 entries per archive and 64 embedded streams of each type per blob. Network decoding limits or unavailable codecs are reported as uninspected; opaque application encryption remains unreadable. On older Brotli builds without bounded decoding, Brotli bodies are flagged as uninspected.
- Gzip and zstd members are scanned beyond the first frame, within shared output limits; zstd history is capped at 128 MiB. Damaged streams and unsupported 7z archives are flagged. The older `zstandard` backend cannot verify completeness of bounded multi-frame, unknown-size or empty-frame reads, so these remain uninspected even when some markers are found.
- Missing, unreadable or damaged capture journals produce a coverage warning while preserving valid records. CA-key removal failures are reported in the terminal and report; keep the affected run directory private.
- Capture failures, inaccessible sockets and partial disk scans produce warnings; rows with warnings are never classified as clean. A task-file positive control confirms only that this marker was visible, not that all traffic was captured.
- The socket sampler checks every 0.2 s, so very short direct connections can be missed.
- Encrypted uploads can only be measured (destination and size), not read. The disk watch helps only if the tool stages the data in a watched folder.
- Disk watch lists any new large file in watched folders, including ones other programs wrote during the run. Files whose path does not mention the agent are grouped as "probably from other programs". Keep runs short and other apps quiet.
- A watched folder that takes more than 45 s to scan, or holds over a million files, is only partly scanned. The report then carries a warning and the disk findings for that folder may be incomplete. Subfolders the user may not read (for example macOS-protected ones) are skipped and counted in the report; they do not make the folder partial.
- Agents vary between runs. In the six 0.3.0 runs of the same task, `codex` sent the git history in one and the file listing in two, and `copilot` listed the files in one. The published results therefore combine batches of three runs (`--runs 3`); use `--runs` for anything you plan to compare. Results from different whatsent versions stay on separate rows, because a newer version may capture more, so an agent version can appear twice: the 0.3.0 rows hold six runs, the 0.3.1 rows three.
- Real agents tested so far: `claude`, `codex`, `codebuddy` and `copilot` on macOS (Apple silicon), run headless (`claude -p`, `codex exec`, `codebuddy -p`, `copilot -p`) with `--clean`, six runs each with 0.3.0 and three with 0.3.1. `copilot` ran with `--allow-tool=write` only, so it could edit files but not run shell commands. Interactive sessions, IDE agents, other agents, and real runs on Windows and Linux are still to come.

This candidate requires Python 3.12+ and current proxy dependencies. Recreate older virtual environments when upgrading; Python 3.10/3.11 are no longer supported because they resolve vulnerable older dependencies. Three upstream Tornado advisories remain tracked in [SECURITY.md](SECURITY.md).

## Development

```bash
python -m venv .venv && . .venv/bin/activate   # Windows PowerShell: py -m venv .venv; .venv\Scripts\Activate.ps1
pip install -e ".[test]"
pytest
```

`whatsent/demo_agent.py` is a simulated agent that leaks over HTTP and HTTPS, uses a pinned connection, bypasses the proxy and drops a snapshot in a cache folder. `whatsent demo` and the end-to-end test run it against local servers, fully offline. `tests/fake_app.py` stands in for an Electron IDE.

## License

MIT
