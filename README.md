# whatsent

**See what your AI coding agent sends, and where.** One command runs any agent, CLI or IDE, inside a throwaway project full of fake secrets, records its traffic and the files it leaves behind, and gives you a one-page report of what left your machine.

![A whatsent report: 3 of 6 canaries left this machine, including the .env secret](docs/report.png)

<sub>Report from `whatsent demo`, which runs a simulated agent against local servers. Not a real product.</sub>

```bash
pipx install git+https://github.com/sundaysebasidian-byte/whatsent   # or: uv tool install git+https://...
whatsent demo                  # 10-second offline demo, no agent needed
whatsent run -- claude         # a CLI agent
whatsent run --app cursor      # an IDE agent
```

On Windows, in PowerShell (needs [Python 3.10+](https://www.python.org/downloads/windows/) and [Git](https://git-scm.com/download/win)):

```powershell
py -m pip install --user pipx; py -m pipx ensurepath   # once, then open a new terminal
pipx install git+https://github.com/sundaysebasidian-byte/whatsent
whatsent demo
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

### CLI agents

```bash
whatsent run -- claude                       # interactive: type the suggested prompt, then exit the agent
whatsent run -- codex exec "Fix the bug in src/app.py so that add() returns the sum of its arguments."
whatsent run -- gemini
whatsent run -- aider --yes-always --message "Fix the bug in src/app.py so that add() returns the sum of its arguments."
```

whatsent prints a suggested prompt before the agent starts. Use the same prompt for every agent you compare. The agent runs inside the canary project, with your normal login and settings.

### IDE agents (Cursor, Trae, Windsurf, …)

```bash
whatsent run --app cursor                    # also: trae, trae-cn, windsurf, kiro, qoder, codebuddy, vscode
whatsent run --app "/Applications/Some IDE.app"
whatsent run --app "$env:LOCALAPPDATA\Programs\cursor\Cursor.exe"   # Windows: path to the .exe
```

Quit the app completely first: a second launch is handed to the running copy, which whatsent cannot see. whatsent starts the app's own binary with the canary project open and Chromium's `--proxy-server`, `--ignore-certificate-errors` and `--disable-quic` switches. The certificate switch only affects this run, and only whatsent's local proxy ever presents a certificate to the app; mitmproxy still verifies the real servers' certificates. Ask the AI chat the suggested prompt, wait for it to finish, then quit the app (Cmd+Q, or File > Exit on Windows).

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
| `--name`, `--agent-version` | Label the run in the report and leaderboard |
| `--out DIR` | Where reports go (default `./whatsent-report`) |
| `--watch DIR` | Also watch this folder for files the agent writes (repeatable) |
| `--no-default-watch` | Watch only the `--watch` folders |
| `--port N` | Fixed proxy port |
| `--mitm-set KEY=VALUE` | Pass an option to mitmproxy, e.g. `mode=upstream:http://corp-proxy:8080` |

By default whatsent watches agent folders such as `~/.claude`, `~/.codex`, `~/.gemini`, `~/.cursor`, `~/.trae`, plus `~/.cache`, `~/.config`, `~/.local/share` and the temp folder on Linux, `~/Library/Caches` and `~/Library/Application Support` on macOS, and `%APPDATA%` and `%LOCALAPPDATA%` (which holds the temp folder) on Windows. Busy browser caches are skipped.

## Reading the report

- **Red**: something no task needed left the machine (`.env`, credentials, git history).
- **Amber / →**: ordinary project files left the machine. Sending the file you asked about to the model is expected; sending unrelated files or a directory listing tells you how much context the agent uploads.
- **Not inspected**: hosts that rejected whatsent's certificate (certificate pinning) or connections that ignored the proxy. A clean report means nothing if this section is not empty.
- **Written to disk**: local copies of your files (for example conversation logs) and new archives. An archive that appears right before a large upload is worth a closer look.

## Leaderboard

`whatsent board results/ -o site/` turns many `result.json` files into a static page and `leaderboard.json`; GitHub Actions publishes it to GitHub Pages. To add an agent, run it with the suggested prompt and open a pull request that adds its `result.json` to [`results/`](results/README.md). `result.json` holds only aggregates: which canaries left, destination hosts and byte counts, with no paths, prompts or file contents.

Until real results are submitted, the board shows made-up examples of fictional agents, labelled as examples ([examples/make_examples.py](examples/make_examples.py)).

## Requirements

- macOS, Linux or Windows 10/11, Python 3.10+ (the macOS system Python is too old; use Homebrew Python, `pipx` or `uv tool install`).
- The agent you want to test, already installed and logged in.

## Known limitations

- Without `--capture local`, only traffic that honours proxy settings is decrypted. Tools that pin certificates or ship their own trust store are listed under "Not inspected", not analysed.
- IDE support relies on Electron honouring `--proxy-server` and the extension host honouring `HTTPS_PROXY` / `NODE_EXTRA_CA_CERTS`. It has been tested with a stand-in app, not yet with real Cursor or Trae. App names other than the path you pass may not match your install.
- `--capture local` has not yet been tested on a real Mac or Windows PC; the Linux path needs root and eBPF.
- Windows support is tested in CI (the demo and the stand-in IDE), not yet with real agents. The Windows install paths of the IDEs are best guesses; if `--app NAME` does not find yours, pass the `.exe` path.
- The socket sampler checks every 0.2 s, so very short direct connections can be missed.
- Encrypted uploads can only be measured (destination and size), not read. The disk watch helps only if the tool stages the data in a watched folder.
- Disk watch flags any new large file in watched folders, including ones other programs wrote during the run. Keep runs short and other apps quiet.
- Real agents have not been run through whatsent yet; per-agent results will be published as they are verified.

## Development

```bash
python -m venv .venv && . .venv/bin/activate   # Windows PowerShell: py -m venv .venv; .venv\Scripts\Activate.ps1
pip install -e ".[test]"
pytest
```

`whatsent/demo_agent.py` is a simulated agent that leaks over HTTP and HTTPS, uses a pinned connection, bypasses the proxy and drops a snapshot in a cache folder. `whatsent demo` and the end-to-end test run it against local servers, fully offline. `tests/fake_app.py` stands in for an Electron IDE.

## License

MIT
