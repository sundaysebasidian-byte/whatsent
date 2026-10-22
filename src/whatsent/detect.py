"""Find canary tokens in raw bytes, including common encodings and archives."""

from __future__ import annotations

import base64
import gzip
import io
import tarfile
import zipfile
import zlib
from urllib.parse import unquote_to_bytes

MAX_EXPANDED = 200 * 1024 * 1024  # stop unpacking past this many bytes in total


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


def _unpack(blob: bytes) -> list[bytes]:
    children: list[bytes] = []
    try:
        if blob[:2] == b"\x1f\x8b":
            children.append(gzip.decompress(blob))
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
