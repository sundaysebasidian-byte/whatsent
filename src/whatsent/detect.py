"""Find canary tokens in raw bytes, including common encodings and archives."""

from __future__ import annotations

import base64
import gzip
import importlib
import io
import tarfile
import zipfile
import zlib
from urllib.parse import unquote_to_bytes

MAX_EXPANDED = 200 * 1024 * 1024  # stop unpacking past this many bytes in total
MAX_EMBEDDED = 64  # compressed streams to try per blob when they do not start at byte 0
GZIP_MAGIC = b"\x1f\x8b\x08"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def _base64_forms(token: bytes) -> list[bytes]:
    """Substrings that appear whenever ``token`` is base64-encoded at any byte offset."""
    forms = []
    for pad in range(3):
        enc = base64.b64encode(b"\0" * pad + token)
        start = (0, 2, 3)[pad]
        end = (len(token) + pad) // 3 * 4
        core = enc[start:end]
        forms += [core, core.replace(b"+", b"-").replace(b"/", b"_")]
    return forms


class Matcher:
    def __init__(self, tokens: dict[str, str]):
        """``tokens`` maps canary id -> token string."""
        self.patterns = {
            cid: [tok.encode(), *_base64_forms(tok.encode())] for cid, tok in tokens.items()
        }

    def scan(self, data: bytes) -> set[str]:
        hits = set()
        for blob in expand(data):
            if b"%" in blob:
                blob = blob + b"\n" + unquote_to_bytes(blob)
            for cid, pats in self.patterns.items():
                if cid not in hits and any(p in blob for p in pats):
                    hits.add(cid)
        return hits


def expand(data: bytes, depth: int = 2) -> list[bytes]:
    """Return ``data`` plus anything we can unpack from it (gzip, zlib, zip, tar)."""
    out = [data]
    budget = [MAX_EXPANDED]

    def walk(blob: bytes, level: int) -> None:
        if level == 0 or budget[0] <= 0:
            return
        for child in _unpack(blob):
            budget[0] -= len(child)
            if budget[0] < 0:
                return
            out.append(child)
            walk(child, level - 1)

    walk(data, depth)
    return out


def _embedded(blob: bytes) -> list[bytes]:
    """Compressed streams inside a larger body, e.g. gRPC or Connect messages, which put a
    5-byte frame header before each gzip/zstd-compressed message."""
    out: list[bytes] = []
    for magic, inflate in ((GZIP_MAGIC, _gunzip_prefix), (ZSTD_MAGIC, _unzstd_prefix)):
        pos = blob.find(magic, 1)
        tries = 0
        while pos != -1 and tries < MAX_EMBEDDED:
            tries += 1
            data = inflate(blob[pos:])
            if data:
                out.append(data)
            pos = blob.find(magic, pos + 1)
    return out


def _gunzip_prefix(blob: bytes) -> bytes:
    """Decompress a gzip stream at the start of ``blob``, ignoring whatever follows it."""
    try:
        return zlib.decompressobj(wbits=31).decompress(blob, MAX_EXPANDED)
    except zlib.error:
        return b""


def _zstd_module():
    # Python 3.14 has zstd in the standard library; mitmproxy installs a backport or zstandard.
    for name in ("compression.zstd", "backports.zstd", "zstandard"):
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    return None


def _unzstd_prefix(blob: bytes) -> bytes:
    mod = _zstd_module()
    if mod is None:
        return b""
    try:
        if hasattr(mod, "ZstdDecompressor") and hasattr(mod.ZstdDecompressor, "decompressobj"):
            return mod.ZstdDecompressor().decompressobj().decompress(blob)[:MAX_EXPANDED]  # zstandard
        return mod.ZstdDecompressor().decompress(blob, max_length=MAX_EXPANDED)  # stdlib API
    except Exception:  # not really zstd, or truncated
        return b""


def _unpack(blob: bytes) -> list[bytes]:
    children: list[bytes] = _embedded(blob)
    try:
        if blob[:2] == b"\x1f\x8b":
            children.append(gzip.decompress(blob))
        elif blob[:4] == ZSTD_MAGIC:
            children.append(_unzstd_prefix(blob))
        elif blob[:1] == b"\x78" and len(blob) > 2:
            children.append(zlib.decompress(blob))
        elif blob[:4] == b"PK\x03\x04":
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                for info in zf.infolist():
                    children.append(info.filename.encode())
                    if not info.is_dir() and info.file_size < MAX_EXPANDED:
                        children.append(zf.read(info))
        elif len(blob) > 262 and blob[257:262] == b"ustar":
            with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
                for member in tf.getmembers():
                    children.append(member.name.encode())
                    if member.isfile() and member.size < MAX_EXPANDED:
                        f = tf.extractfile(member)
                        if f:
                            children.append(f.read())
    except (OSError, EOFError, zlib.error, zipfile.BadZipFile, tarfile.TarError, ValueError):
        pass
    return children


def looks_like_archive(head: bytes) -> bool:
    return (
        head[:2] == b"\x1f\x8b"
        or head[:4] == b"PK\x03\x04"
        or head[:6] == b"7z\xbc\xaf\x27\x1c"
        or head[:4] == b"\x28\xb5\x2f\xfd"  # zstd
        or (len(head) > 262 and head[257:262] == b"ustar")
    )
