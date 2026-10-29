"""Launch desktop (Electron) IDE agents such as Cursor or Trae under whatsent.

Electron apps ignore HTTPS_PROXY for most of their traffic, so we start the app's
own binary with Chromium's proxy switches. Certificate exceptions are restricted
to the public key of this run's CA; unrelated invalid certificates are not trusted.
Extension hosts get the usual proxy variables plus NODE_EXTRA_CA_CERTS.
"""

from __future__ import annotations

import os
import base64
import hashlib
import plistlib
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import psutil


@dataclass(frozen=True)
class AppInfo:
    name: str
    mac_bundles: tuple[str, ...]
    linux_bins: tuple[str, ...]
    win_exes: tuple[str, ...] = ()  # relative to %LOCALAPPDATA%\Programs or %ProgramFiles%


# Bundle and binary names. Ones we have not seen on a real machine simply fail to
# resolve, and the user can pass the path instead.
KNOWN = {
    "cursor": AppInfo("Cursor", ("Cursor.app",), ("cursor",), ("cursor/Cursor.exe",)),
    "windsurf": AppInfo("Windsurf", ("Windsurf.app",), ("windsurf",), ("Windsurf/Windsurf.exe",)),
    "trae": AppInfo("Trae", ("Trae.app",), ("trae",), ("Trae/Trae.exe",)),
    "trae-cn": AppInfo("Trae CN", ("Trae CN.app",), ("trae-cn",), ("Trae CN/Trae CN.exe",)),
    "kiro": AppInfo("Kiro", ("Kiro.app",), ("kiro",), ("Kiro/Kiro.exe",)),
    "qoder": AppInfo("Qoder", ("Qoder.app",), ("qoder",), ("Qoder/Qoder.exe",)),
    "codebuddy": AppInfo("CodeBuddy", ("CodeBuddy.app", "CodeBuddy CN.app"), ("codebuddy",),
                         ("CodeBuddy/CodeBuddy.exe", "CodeBuddy CN/CodeBuddy CN.exe")),
    "vscode": AppInfo("VS Code", ("Visual Studio Code.app",), ("code",), ("Microsoft VS Code/Code.exe",)),
}


@dataclass
class ResolvedApp:
    name: str
    executable: Path


class AppError(Exception):
    pass


def resolve(spec: str) -> ResolvedApp:
    """``spec`` is a known name (cursor, trae, ...), a .app bundle or an executable path."""
    path = Path(spec).expanduser()
    if path.suffix == ".app" and path.is_dir():
        return ResolvedApp(path.stem, _bundle_executable(path))
    if path.is_file() and os.access(path, os.X_OK):
        return ResolvedApp(path.stem if sys.platform == "win32" else path.name, _real_binary(path))
    info = KNOWN.get(spec.lower())
    if info is None:
        raise AppError(f"unknown app {spec!r}. Known: {', '.join(sorted(KNOWN))}; or pass a path "
                       f"to the .app bundle or executable")
    if sys.platform == "darwin":
        for folder in (Path("/Applications"), Path.home() / "Applications"):
            for bundle in info.mac_bundles:
                if (folder / bundle).is_dir():
                    return ResolvedApp(info.name, _bundle_executable(folder / bundle))
    elif sys.platform == "win32":
        folders = [Path(os.environ[v]) / sub for v, sub in (("LOCALAPPDATA", "Programs"), ("ProgramFiles", ""))
                   if os.environ.get(v)]
        for folder in folders:
            for exe in info.win_exes:
                if (folder / exe).is_file():
                    return ResolvedApp(info.name, folder / exe)
    else:
        for name in info.linux_bins:
            found = shutil.which(name)
            if found:
                return ResolvedApp(info.name, _real_binary(Path(found)))
    example = r"%LOCALAPPDATA%\Programs\X\X.exe" if sys.platform == "win32" else "/Applications/X.app"
    raise AppError(f"could not find {info.name}. Pass its path instead, e.g. --app {example}")


def _bundle_executable(bundle: Path) -> Path:
    plist = bundle / "Contents" / "Info.plist"
    try:
        with open(plist, "rb") as f:
            exe = plistlib.load(f)["CFBundleExecutable"]
    except (OSError, KeyError, plistlib.InvalidFileException) as exc:
        raise AppError(f"{bundle} does not look like an app bundle: {exc}") from exc
    return bundle / "Contents" / "MacOS" / exe


def _real_binary(path: Path) -> Path:
    """Linux launchers like /usr/bin/code are scripts that start the app detached and
    exit at once. Prefer the Electron binary next to them (<dir>/bin/code -> <dir>/code)."""
    real = path.resolve()
    if real.parent.name == "bin":
        candidate = real.parent.parent / real.name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return real


def running(app: ResolvedApp) -> list[int]:
    """PIDs of an already running copy. Electron apps hand a second launch over to the
    running instance, which would then run outside whatsent."""
    pids = []
    for proc in psutil.process_iter(["exe"]):
        try:
            exe = proc.info["exe"]
        except psutil.Error:
            continue
        if exe and Path(exe) == app.executable:
            pids.append(proc.pid)
    return pids


def command(app: ResolvedApp, proxy_port: int, workspace: Path, extra: list[str], ca_cert: Path) -> list[str]:
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    cert = x509.load_pem_x509_certificate(ca_cert.read_bytes())
    spki = cert.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    trusted_key = base64.b64encode(hashlib.sha256(spki).digest()).decode("ascii")
    return [
        str(app.executable),
        f"--proxy-server=http://127.0.0.1:{proxy_port}",
        f"--ignore-certificate-errors-spki-list={trusted_key}",
        "--disable-quic",  # QUIC/HTTP3 is UDP and would skip the proxy
        *extra,
        str(workspace),
    ]
