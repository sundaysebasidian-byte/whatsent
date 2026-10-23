"""Snapshot agent cache/config directories before and after a run.

Some tools encrypt what they upload, so the network side only shows size and
destination. Their staging files on disk often still reveal what was packed.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from whatsent.detect import Matcher, looks_like_archive

MAX_FILES_PER_ROOT = 200_000
MAX_SCAN_BYTES = 100 * 1024 * 1024
LARGE_FILE = 256 * 1024

AGENT_DIRS = [".claude", ".codex", ".gemini", ".aider", ".zcode", ".trae", ".cursor",
              ".qoder", ".kimi", ".codebuddy", ".continue", ".opencode", ".grok"]
# Busy directories that change on their own and only add noise.
NOISY = ("/Google/Chrome", "/Mozilla", "/BraveSoftware", "/Microsoft Edge", "/com.apple.",
         "/Safari", "/Slack", "/Spotify", "/pip/http", "/Microsoft/Edge", "/Microsoft/Windows")


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


def snapshot(roots: list[Path], exclude: list[Path]) -> tuple[Snapshot, list[str]]:
    """Return file stats under ``roots`` and a list of roots that were truncated."""
    excluded = [str(p.resolve()) for p in exclude]
    files: Snapshot = {}
    truncated = []
    for root in roots:
        count = 0
        for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
            if _skip(dirpath, excluded):
                dirnames[:] = []
                continue
            for name in filenames:
                path = os.path.join(dirpath, name)
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                files[path] = (st.st_size, st.st_mtime_ns)
                count += 1
            if count >= MAX_FILES_PER_ROOT:
                truncated.append(str(root))
                break
    return files, truncated


def _skip(dirpath: str, excluded: list[str]) -> bool:
    real = os.path.realpath(dirpath)
    return any(real == e or real.startswith(e + os.sep) for e in excluded) or any(
        n in dirpath.replace(os.sep, "/") for n in NOISY
    )


def diff(before: Snapshot, after: Snapshot, matcher: Matcher) -> dict:
    """Changed files that contain canaries, plus new large or archive files."""
    leaks, suspicious, changed = [], [], 0
    for path, (size, mtime) in after.items():
        old = before.get(path)
        if old == (size, mtime):
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
            suspicious.append(entry)
    suspicious.sort(key=lambda e: e["size"], reverse=True)
    return {"leaks": leaks, "suspicious": suspicious[:50], "changed_files": changed}
