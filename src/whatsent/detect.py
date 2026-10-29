"""Find canary tokens in raw bytes, including common encodings and archives."""

from __future__ import annotations

import base64
import importlib
import io
import tarfile
import zipfile
import zlib
from collections.abc import Iterator
from urllib.parse import unquote_to_bytes

MAX_EXPANDED = 200 * 1024 * 1024  # stop unpacking past this many bytes in total
MAX_MEMBERS = 4096  # archive entries, including empty files
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

    def scan(self, data: bytes, *, issues: list[str] | None = None) -> set[str]:
        hits = set()
        for blob in expand(data, issues=issues):
            if b"%" in blob:
                blob = blob + b"\n" + unquote_to_bytes(blob)
            for cid, pats in self.patterns.items():
                if cid not in hits and any(p in blob for p in pats):
                    hits.add(cid)
        return hits


def expand(data: bytes, depth: int = 2, *, issues: list[str] | None = None) -> list[bytes]:
    """Unpack lazily with one shared output budget, including nested archives."""
    out = [data]
    budget = [MAX_EXPANDED]

    def walk(blob: bytes, level: int) -> None:
        if level == 0:
            if looks_like_archive(blob):
                _issue(issues, "archive nesting limit reached")
            return
        for child in _unpack(blob, budget, issues):
            budget[0] -= len(child)
            if child:
                out.append(child)
            if budget[0] <= 0:
                _issue(issues, "expanded data limit reached")
                return
            walk(child, level - 1)
            if budget[0] <= 0:
                return

    walk(data, depth)
    return out


def _issue(issues: list[str] | None, message: str) -> None:
    if issues is not None and message not in issues:
        issues.append(message)


def _embedded(blob: bytes, budget: list[int], issues: list[str] | None) -> Iterator[bytes]:
    """Compressed streams inside gRPC/Connect or another framed body."""
    for magic, inflate in ((GZIP_MAGIC, _gunzip_prefix), (ZSTD_MAGIC, _unzstd_prefix)):
        pos = blob.find(magic, 1)
        tries = 0
        while pos != -1 and budget[0] > 0:
            if tries >= MAX_EMBEDDED:
                _issue(issues, "embedded stream limit reached")
                break
            tries += 1
            data = inflate(blob[pos:], budget[0])
            if data:
                yield data
            pos = blob.find(magic, pos + 1)


def _gunzip_prefix(blob: bytes, limit: int | None = None) -> bytes:
    """Decode a bounded prefix without allocating the entire decompressed stream."""
    try:
        return zlib.decompressobj(wbits=31).decompress(blob, MAX_EXPANDED if limit is None else limit)
    except zlib.error:
        return b""


def decode_body(data: bytes, encoding: str, issues: list[str]) -> bytes:
    """Bound HTTP content decoding as well as the archive expansion that follows it."""
    encoding = encoding.strip().lower()
    if not encoding or encoding == "identity":
        return data
    try:
        if encoding in ("gzip", "deflate"):
            decoder = zlib.decompressobj(31 if encoding == "gzip" else 15)
            try:
                decoded = decoder.decompress(data, MAX_EXPANDED)
            except zlib.error:
                if encoding != "deflate":
                    raise
                decoder = zlib.decompressobj(-15)
                decoded = decoder.decompress(data, MAX_EXPANDED)
            if not decoder.eof or decoder.unused_data:
                _issue(issues, f"{encoding} body not fully decoded")
            return decoded
        if encoding == "zstd":
            decoded = _unzstd_prefix(data)
            if not decoded or len(decoded) >= MAX_EXPANDED:
                _issue(issues, "zstd body not fully decoded")
            return decoded
        if encoding == "br":
            import brotli  # installed with mitmproxy

            decoder = brotli.Decompressor()
            if not hasattr(decoder, "can_accept_more_data"):
                _issue(issues, "bounded brotli decoding unavailable")
                return data
            try:
                decoded = decoder.process(data, output_buffer_limit=MAX_EXPANDED)
            except brotli.error:
                _issue(issues, "br body could not be decoded")
                return data
            if not decoder.is_finished() or len(decoded) > MAX_EXPANDED:
                _issue(issues, "br body not fully decoded")
            return decoded[:MAX_EXPANDED]
    except zlib.error:
        _issue(issues, f"{encoding} body could not be decoded")
        return data
    _issue(issues, f"unsupported content encoding: {encoding}")
    return data


def _zstd_module():
    # Python 3.14 has zstd in the standard library; mitmproxy installs a backport or zstandard.
    for name in ("compression.zstd", "backports.zstd", "zstandard"):
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    return None


def _unzstd_prefix(blob: bytes, limit: int | None = None) -> bytes:
    mod = _zstd_module()
    if mod is None:
        return b""
    limit = MAX_EXPANDED if limit is None else limit
    try:
        if hasattr(mod.ZstdDecompressor, "stream_reader"):  # zstandard
            with mod.ZstdDecompressor().stream_reader(io.BytesIO(blob)) as reader:
                return reader.read(limit)
        return mod.ZstdDecompressor().decompress(blob, max_length=limit)  # stdlib/backport
    except (mod.ZstdError, EOFError):
        return b""


def _unpack(blob: bytes, budget: list[int], issues: list[str] | None) -> Iterator[bytes]:
    try:
        if blob[:2] == b"\x1f\x8b":
            yield _gunzip_prefix(blob, budget[0])
        elif blob[:4] == ZSTD_MAGIC:
            yield _unzstd_prefix(blob, budget[0])
        elif blob[:1] == b"\x78" and len(blob) > 2 and (blob[0] * 256 + blob[1]) % 31 == 0:
            yield zlib.decompressobj().decompress(blob, budget[0])
        elif blob[:4] == b"PK\x03\x04":
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                for i, info in enumerate(zf.infolist()):
                    if i >= MAX_MEMBERS:
                        _issue(issues, "archive entry limit reached")
                        break
                    yield info.filename.encode()[:budget[0]]
                    if not info.is_dir():
                        with zf.open(info) as f:
                            yield f.read(budget[0])
        elif len(blob) > 262 and blob[257:262] == b"ustar":
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r|") as tf:
                for i, member in enumerate(tf):
                    if i >= MAX_MEMBERS:
                        _issue(issues, "archive entry limit reached")
                        break
                    yield member.name.encode()[:budget[0]]
                    if member.isfile():
                        with tf.extractfile(member) as f:
                            yield f.read(budget[0])
    except (OSError, EOFError, zlib.error, zipfile.BadZipFile, tarfile.TarError, ValueError,
            RuntimeError, NotImplementedError):
        _issue(issues, "archive could not be fully decoded")
    if budget[0] > 0:
        yield from _embedded(blob, budget, issues)


def looks_like_archive(head: bytes) -> bool:
    return (
        head[:2] == b"\x1f\x8b"
        or head[:4] == b"PK\x03\x04"
        or head[:6] == b"7z\xbc\xaf\x27\x1c"
        or head[:4] == b"\x28\xb5\x2f\xfd"  # zstd
        or (len(head) > 262 and head[257:262] == b"ustar")
    )
