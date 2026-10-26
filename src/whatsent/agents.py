"""Per-agent helpers: find an agent's version, and a clean mode with MCP servers and plugins off.

Your own MCP servers, connectors and plugins send traffic of their own, so a run with them on
says more about your setup than about the agent. ``--clean`` turns them off for the agents
whose switches are known; it is best effort and every change is printed.
"""

from __future__ import annotations

import json
import plistlib
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Agent CLIs whose --version is safe to ask. Anything else could be a script that starts the agent.
KNOWN = frozenset({"claude", "codex", "gemini", "aider", "opencode", "kimi", "goose", "qwen", "amp",
                   "cursor-agent", "copilot", "crush", "droid"})
VERSION = re.compile(r"\d+\.\d+(?:\.\d+)?(?:[-+.][0-9A-Za-z.]+)*")
SAFE_NAME = re.compile(r"[A-Za-z0-9_-]+")
# Codex features that start MCP servers or connectors of their own. Only those this build knows are used.
CODEX_FEATURES = ("plugins", "apps", "computer_use", "browser_use", "in_app_browser")


@dataclass
class Clean:
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def program(command: list[str]) -> str:
    return Path(command[0]).stem.lower() if command else ""


def detect_version(command: list[str]) -> str | None:
    """The agent's version from ``<agent> --version``, or None if it cannot be told."""
    name = program(command)
    exe = shutil.which(command[0]) if name in KNOWN else None
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10,
                             stdin=subprocess.DEVNULL, errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    found = VERSION.search(out.stdout or out.stderr)
    return found.group(0).rstrip(".") if found else None


def app_version(executable: Path) -> str | None:
    """The version of a macOS app bundle, from its Info.plist."""
    for parent in executable.parents:
        if parent.suffix == ".app":
            try:
                with open(parent / "Contents" / "Info.plist", "rb") as f:
                    info = plistlib.load(f)
            except (OSError, plistlib.InvalidFileException):
                return None
            return info.get("CFBundleShortVersionString") or info.get("CFBundleVersion")
    return None


def clean(command: list[str]) -> Clean | None:
    """The command and environment with MCP servers, connectors and plugins off, or None for
    an agent we know no switches for."""
    name = program(command)
    if name == "claude":
        return Clean([command[0], "--strict-mcp-config", *command[1:]],
                     {"ENABLE_CLAUDEAI_MCP_SERVERS": "false"},
                     ["--strict-mcp-config", "ENABLE_CLAUDEAI_MCP_SERVERS=false"])
    if name == "codex":
        return _clean_codex(command)
    return None


def _clean_codex(command: list[str]) -> Clean | None:
    exe = shutil.which(command[0])
    if not exe:
        return None
    features = _codex_features(exe)
    flags = [x for f in features for x in ("--disable", f)]
    servers = _codex_servers(exe, flags)
    flags += [x for n in servers for x in ("-c", f"mcp_servers.{n}.enabled=false")]
    at = 2 if command[1:2] in (["exec"], ["e"]) else 1  # the options belong to the subcommand
    notes = [f"{', '.join(features)} off"]
    if servers:
        notes.append(f"{len(servers)} MCP servers off")
    return Clean([*command[:at], *flags, *command[at:]], {}, notes)


def _run(exe: str, args: list[str]) -> str:
    try:
        return subprocess.run([exe, *args], capture_output=True, text=True, timeout=20,
                              stdin=subprocess.DEVNULL, errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _codex_features(exe: str) -> list[str]:
    known = {line.split()[0] for line in _run(exe, ["features", "list"]).splitlines() if line.split()}
    return [f for f in CODEX_FEATURES if f in known] if known else list(CODEX_FEATURES)


def _codex_servers(exe: str, flags: list[str]) -> list[str]:
    """MCP servers defined in the user's config that would start, with the plugin features off."""
    try:
        listing = json.loads(_run(exe, [*flags, "mcp", "list", "--json"]))
        return [s["name"] for s in listing if s.get("enabled") and SAFE_NAME.fullmatch(s.get("name", ""))]
    except (ValueError, TypeError, KeyError, AttributeError):
        return []
