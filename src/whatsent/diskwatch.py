"""Snapshot agent cache/config directories before and after a run.

Some tools encrypt what they upload, so the network side only shows size and
destination. Their staging files on disk often still reveal what was packed.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import time
from pathlib import Path

from whatsent.detect import Matcher, looks_like_archive

MAX_FILES_PER_ROOT = 1_000_000
ROOT_SECONDS = 45.0  # one slow folder must not hold up the whole run
MAX_SCAN_BYTES = 100 * 1024 * 1024
LARGE_FILE = 256 * 1024

AGENT_DIRS = [".claude", ".codex", ".gemini", ".aider", ".zcode", ".trae", ".cursor",
              ".qoder", ".kimi", ".codebuddy", ".continue", ".opencode", ".grok"]
# Busy directories that change on their own and only add noise.
NOISY = ("/Google/Chrome", "/Mozilla", "/BraveSoftware", "/Microsoft Edge", "/com.apple.",
         "/Safari", "/Slack", "/Spotify", "/pip/http", "/Microsoft/Edge", "/Microsoft/Windows")
NOISY_NAMES = frozenset({"node_modules", "__pycache__"})
# Stores that Electron and Chromium apps keep for their own windows. A new blob there is the
# app's UI at work, not an agent staging an upload, so it never counts as related to the agent.
CHROMIUM_STORES = frozenset({"indexeddb", "blob_storage", "cache_data", "code cache", "gpucache",
                             "dawncache", "service worker", "local storage", "session storage", "crashpad"})


def default_roots() -> list[Path]:
    home = Path.home()
    roots = [home / d for d in AGENT_DIRS]
    if sys.platform == "darwin":
        roots += [home / "Library/Caches", home / "Library/Application Support"]
    if sys.platform == "win32":
        roots += [Path(os.environ[v]) for v in ("APPDATA", "LOCALAPPDATA") if os.environ.get(v)]
    roots += [home / ".cache", home / ".config", home / ".local/share", home / ".local/state",
              Path(tempfile.gettempdir())]
    return [r for r in roots if r.is_dir()]


Snapshot = dict[str, tuple[int, int]]  # path -> (size, mtime_ns)


def snapshot(roots: list[Path], exclude: list[Path], seconds: float = ROOT_SECONDS,
             max_files: int = MAX_FILES_PER_ROOT) -> tuple[Snapshot, list[str]]:
    """Return file stats under ``roots`` and the roots that were only partly scanned
    (they took longer than ``seconds`` or held more than ``max_files`` files)."""
    excluded = {os.path.realpath(p) for p in exclude} | {os.path.abspath(p) for p in exclude}
    files: Snapshot = {}
    partial = []
    for root in roots:
        root = str(root)
        real = os.path.realpath(root)
        if real in excluded:
            continue
        deadline = time.monotonic() + seconds
        count = 0
        stack = [root]
        while stack:
            if count >= max_files or time.monotonic() > deadline:
                partial.append(root)
                break
            directory = stack.pop()
            try:
                it = os.scandir(directory)
            except OSError:
                continue
            with it:
                for entry in it:
                    if len(files) % 4096 == 0 and time.monotonic() > deadline:
                        break  # one huge folder must not outlast the budget either
                    try:
                        if not entry.is_dir(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                            files[entry.path] = (st.st_size, st.st_mtime_ns)
                            count += 1
                        elif entry.name not in NOISY_NAMES and not _skip(entry.path, root, real, excluded):
                            stack.append(entry.path)
                    except OSError:
                        continue
    return files, partial


def _skip(path: str, root: str, real_root: str, excluded: set[str]) -> bool:
    # Symlinks are not followed, so the real path is the real root plus the path below it.
    if real_root + path[len(root):] in excluded:
        return True
    return any(n in path.replace(os.sep, "/") for n in NOISY)


def diff(before: Snapshot, after: Snapshot, matcher: Matcher, since_ns: int = 0,
         partial: list[str] | tuple[str, ...] = (), agent: str | None = None) -> dict:
    """Changed files that contain canaries, plus new large or archive files.

    A root that was only partly scanned may have hidden files from ``before``; a file there
    that is missing from ``before`` but older than ``since_ns`` is not counted as new.
    ``agent`` marks suspicious files whose path does not mention the agent as unrelated."""
    prefixes = tuple(r + os.sep for r in partial)
    leaks, suspicious, changed = [], [], 0
    for path, (size, mtime) in after.items():
        old = before.get(path)
        if old == (size, mtime):
            continue
        if old is None and mtime < since_ns and prefixes and path.startswith(prefixes):
            continue
        changed += 1
        try:
            with open(path, "rb") as f:
                data = f.read(MAX_SCAN_BYTES)
        except OSError:
            continue
        hits = matcher.scan(data)
        entry = {"path": path, "size": size, "new": old is None}
        if hits:
            leaks.append({**entry, "canaries": sorted(hits)})
        elif old is None and (size >= LARGE_FILE or looks_like_archive(data[:512])):
            entry["archive"] = looks_like_archive(data[:512])
            entry["related"] = related(path, agent)
            suspicious.append(entry)
    suspicious.sort(key=lambda e: (not e["related"], -e["size"]))
    return {"leaks": leaks, "suspicious": suspicious[:50], "changed_files": changed}


def related(path: str, agent: str | None) -> bool:
    """Whether ``path`` mentions the agent by name (``Trae CN`` matches ``.trae-cn/``, and
    ``demo-agent (simulated)`` matches ``.demo-agent/``). Without a usable name every file counts."""
    if any(part.lower() in CHROMIUM_STORES or part.lower().endswith(".indexeddb.blob")
           for part in re.split(r"[\\/]", path)):
        return False
    whole = _squash(agent or "")
    names = {w for w in re.findall(r"[a-z0-9]+", (agent or "").lower()) if len(w) >= 4}
    if len(whole) >= 3:
        names.add(whole)
    squashed = _squash(path)
    return not names or any(n in squashed for n in names)


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())
