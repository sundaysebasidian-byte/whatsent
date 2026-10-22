# whatsent

**See what your AI coding agent sends, and where.** One command runs any agent inside a throwaway project full of fake secrets, records its traffic and the files it leaves behind, and gives you a one-page report of what left your machine.

```bash
pipx install git+https://github.com/sundaysebasidian-byte/whatsent
whatsent run -- claude
```

[中文说明](README_zh.md)

## Why

Coding agents read your whole project. Most of what they send is the code you asked them to work on, which is expected. The question is what else goes along: your `.env`, gitignored credentials, git history, files you never mentioned, or a packed snapshot of the entire workspace. Vendor privacy pages describe intent; whatsent shows behaviour.

whatsent is an audit tool, not a firewall. It does not block anything.

## How it works

1. **Canary project.** whatsent creates a small fake project and plants a unique random marker in each file: the file the task is about, an unrelated source file, a gitignored `.env`, a gitignored credentials file, a file whose *name* is the marker, and a git commit message. All values are obviously fake and new on every run.
2. **Traffic capture.** It starts a local [mitmproxy](https://mitmproxy.org) and launches the agent with `HTTPS_PROXY` and a per-run CA certificate, so HTTPS requests can be read. Every request is searched for the markers, including gzip, URL-encoded, base64 and zip/tar payloads.
3. **Disk watch.** It snapshots the agent's cache and config folders before and after the run. Tools that encrypt their uploads usually stage them on disk first; whatsent lists new archives and large blobs and searches them for markers.
4. **Bypass check.** It samples the agent's open sockets during the run, so a connection that skips the proxy shows up as "not inspected" instead of silently looking clean.
5. **Report.** A single `report.html` (plus `report.json`) in `./whatsent-report/<timestamp>/`: which markers left, to which domains, how much was uploaded, what was written to disk, and what could not be inspected.

## Usage

```bash
whatsent run -- claude                       # interactive: type the suggested prompt, then exit the agent
whatsent run -- codex exec "Fix the bug in src/app.py so that add() returns the sum of its arguments."
whatsent run -- gemini
whatsent run -- aider --yes-always --message "Fix the bug in src/app.py so that add() returns the sum of its arguments."
```

whatsent prints a suggested prompt before the agent starts. Use the same prompt for every agent you want to compare. The agent runs inside the canary project, with your normal login and settings.

Options:

| Option | Meaning |
| --- | --- |
| `--out DIR` | Where reports go (default `./whatsent-report`) |
| `--watch DIR` | Also watch this folder for files the agent writes (repeatable) |
| `--no-default-watch` | Watch only the `--watch` folders |
| `--port N` | Fixed proxy port |
| `--mitm-set KEY=VALUE` | Pass an option to mitmproxy, e.g. `mode=upstream:http://corp-proxy:8080` |

By default whatsent watches agent folders such as `~/.claude`, `~/.codex`, `~/.gemini`, plus `~/.cache`, `~/.config`, `~/.local/share` and the temp folder on Linux, and `~/Library/Caches` and `~/Library/Application Support` on macOS. Busy browser caches are skipped.

## Reading the report

- **Red**: something no task needed left the machine (`.env`, credentials, git history).
- **Amber**: ordinary project files left the machine. Sending the file you asked about to the model is expected; sending unrelated files or a directory listing tells you how much context the agent uploads.
- **Not inspected**: hosts that rejected whatsent's certificate (certificate pinning) or connections that ignored the proxy. A clean report means nothing if this section is not empty.
- **Written to disk**: local copies of your files (for example conversation logs) and new archives. An archive that appears right before a large upload is worth a closer look.

## Requirements

- macOS or Linux, Python 3.10+ (the macOS system Python is too old; use Homebrew Python or `uv tool install`).
- The agent you want to test, already installed and logged in.

## Known limitations

- Only traffic that honours `HTTP(S)_PROXY` is decrypted. Tools that ignore proxy settings, pin certificates or ship their own trust store are listed under "Not inspected", not analysed. Electron/IDE agents (Cursor, Trae, …) mostly fall in this group; system-level capture is planned.
- The socket sampler checks every 0.2 s, so very short direct connections can be missed. UDP/QUIC payloads are never decrypted.
- Encrypted uploads can only be measured (destination and size), not read. The disk watch helps only if the tool stages the data in a watched folder.
- Disk watch flags any new large file in watched folders, including ones other programs wrote during the run. Keep runs short and other apps quiet.
- Markers are detected in plain, gzip, deflate, URL, base64, zip and tar forms. Other encodings (for example protobuf with compression the proxy does not decode) can hide them.
- Tested end to end with a mock agent on Linux. Real agents have not been run through v0.1 yet; results per agent will be published as they are verified.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
pytest
```

`tests/mock_agent.py` is a fake agent that leaks over HTTP and HTTPS, uses a pinned connection, bypasses the proxy and drops a snapshot in a cache folder. The end-to-end test runs it under `whatsent run` against local servers, fully offline.

## License

MIT
