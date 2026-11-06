"""Find canary tokens in raw bytes, including common encodings and archives."""

from __future__ import annotations

import base64
import binascii
import importlib
import io
import re
import tarfile
import zipfile
import zlib
from collections.abc import Iterator
from urllib.parse import unquote_to_bytes

MAX_EXPANDED = 200 * 1024 * 1024  # stop unpacking past this many bytes in total
MAX_WINDOW = 128 * 1024 * 1024  # zstd history buffer, separate from the returned output limit
MAX_MEMBERS = 4096  # archive entries, including empty files
MAX_EMBEDDED = 64  # compressed streams to try per blob when they do not start at byte 0
MAX_BASE64_CANDIDATES = 4096  # plausible candidates per blob, separate from embedded streams
GZIP_MAGIC = b"\x1f\x8b\x08"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


BASE64_RUN = re.compile(rb"[A-Za-z0-9+/_-]{16,}+={0,2}")
JSON_ESCAPE = re.compile(rb"\\(?:u00([0-9a-fA-F]{2})|([\\/]))")
BINARY_CONTROL = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
BASE64_LINE = re.compile(rb"[A-Za-z0-9+/_-]++={0,2}")


class Matcher:
    def __init__(self, tokens: dict[str, str]):
        """``tokens`` maps canary id -> token string. Match complete tokens only."""
        self.patterns = {
            cid: [tok.encode(), tok.encode("utf-16le"), tok.encode("utf-16be"),
                  tok.encode().hex().encode(), tok.encode().hex().upper().encode()]
            for cid, tok in tokens.items()
        }
        self.min_token_bytes = min((len(tok.encode()) for tok in tokens.values()), default=1)
        # JSON escaping is the longest supported textual spelling (six bytes per byte).
        self.overlap = max((len(tok.encode()) * 6 for tok in tokens.values()), default=1) - 1

    def scan(self, data: bytes, *, issues: list[str] | None = None) -> set[str]:
        hits = set()
        for blob in expand(data, issues=issues, min_token_bytes=self.min_token_bytes):
            for cid, pats in self.patterns.items():
                if cid not in hits and any(p in blob for p in pats):
                    hits.add(cid)
        return hits


class StreamMatcher:
    """Outbound byte overlap for one connection; never mix connections or directions."""

    def __init__(self, matcher: Matcher):
        self.matcher = matcher
        self.tail = b""

    def scan(self, data: bytes, *, issues: list[str] | None = None) -> set[str]:
        hits = self.matcher.scan(data, issues=issues)
        combined = self.tail + data
        if self.tail:
            hits |= self.matcher.scan(combined, issues=issues)
        start = max(0, len(combined) - self.matcher.overlap)
        for match in BASE64_RUN.finditer(combined):
            if match.end() == len(combined) and match.start() < start:
                # Retained base64 must start at a quartet boundary of the original run.
                start += -(start - match.start()) % 4
        self.tail = combined[start:] if self.matcher.overlap else b""
        return hits


def _is_text(blob: bytes) -> bool:
    if BINARY_CONTROL.search(blob):
        return False
    if not blob.isascii():
        try:
            blob.decode("utf-8")
        except UnicodeDecodeError:
            return False
    return True


def _base64_runs(blob: bytes) -> Iterator[tuple[int, int]]:
    pos = 0
    while match := BASE64_RUN.search(blob, pos):
        start, end = match.span()
        width = end - start
        # MIME/PEM wraps complete quartets. Only join adjacent full lines, never JSON fields.
        if width in (64, 76) and (start == 0 or blob[start - 1] == 10):
            line = match
            while blob[line.end() - 1:line.end()] != b"=":
                next_start = line.end()
                if blob[next_start:next_start + 2] == b"\r\n":
                    next_start += 2
                elif blob[next_start:next_start + 1] == b"\n":
                    next_start += 1
                else:
                    break
                following = BASE64_LINE.match(blob, next_start)
                if (following is None or following.end() - next_start > width
                        or blob[following.end():following.end() + 1] not in (b"", b"\r", b"\n")):
                    break
                end = following.end()
                line = following
                if end - next_start != width:
                    break
        yield start, end
        pos = end


def _text_decodings(blob: bytes, budget: list[int], issues: list[str] | None,
                    min_token_bytes: int) -> Iterator[bytes]:
    if (b"%" in blob or JSON_ESCAPE.search(blob)) and _is_text(blob):
        # Both transforms only shrink input. Bound allocation before invoking them.
        prefix = blob[:budget[0]]
        if len(prefix) < len(blob):
            _issue(issues, "text decoding expanded data limit reached")
        if b"%" in prefix:
            decoded = unquote_to_bytes(prefix)
            if decoded != prefix:
                yield decoded
        if JSON_ESCAPE.search(prefix):
            yield JSON_ESCAPE.sub(lambda m: bytes([int(m[1], 16)]) if m[1] else m[2], prefix[:budget[0]])
    candidates = 0
    for start, stop in _base64_runs(blob):
        if budget[0] <= 0:
            break
        # Include line separators in this bound: joining must not allocate an unbounded copy.
        end = min(stop, start + (budget[0] // 3) * 4)
        if end < stop:
            _issue(issues, "base64 expanded data limit reached")
        encoded = blob[start:end].translate(None, b"\r\n")
        if not encoded:
            break
        try:
            decoded = base64.b64decode(encoded + b"=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
        except binascii.Error:
            # A split stream may end with one sextet; retain its complete quartets.
            # Ordinary alphanumeric text can also land here, so only decode, never infer a hit.
            prefix = encoded[:len(encoded) // 4 * 4]
            try:
                decoded = base64.b64decode(prefix, altchars=b"-_", validate=True)
            except binascii.Error:
                continue
        if len(decoded) < min_token_bytes and not (looks_like_archive(decoded) or _is_zlib(decoded)):
            continue
        if candidates >= MAX_BASE64_CANDIDATES:
            _issue(issues, "base64 candidate limit reached")
            break
        candidates += 1
        yield decoded


def expand(data: bytes, depth: int = 4, *, issues: list[str] | None = None,
           min_token_bytes: int = 1) -> list[bytes]:
    """Unpack lazily with one shared output budget, including nested archives."""
    out = [data]
    budget = [MAX_EXPANDED]

    def walk(blob: bytes, level: int) -> None:
        if level == 0:
            if (looks_like_archive(blob) or _is_zlib(blob) or BASE64_RUN.search(blob)
                    or JSON_ESCAPE.search(blob) or b"%" in blob
                    or GZIP_MAGIC in blob or ZSTD_MAGIC in blob):
                _issue(issues, "decoding nesting limit reached")
            return
        for child in _children(blob, budget, issues, min_token_bytes):
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


def _children(blob: bytes, budget: list[int], issues: list[str] | None, min_token_bytes: int) -> Iterator[bytes]:
    yield from _unpack(blob, budget, issues)
    if budget[0] > 0:
        yield from _text_decodings(blob, budget, issues, min_token_bytes)


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
            data = inflate(blob[pos:], budget[0], issues=issues, allow_trailing=True)
            if data:
                yield data
            pos = blob.find(magic, pos + 1)


def _decode_frames(blob: bytes, factory, limit: int, magic: bytes | None, label: str,
                   issues: list[str] | None, allow_trailing: bool = False,
                   errors: tuple[type[Exception], ...] = (zlib.error, ValueError)) -> bytes:
    """Both zlib and stdlib zstd expose bounded output, EOF and unused input."""
    # Only the zlib label is a two-byte heuristic; declared HTTP deflate uses its own label.
    probe = label == "zlib"
    out = bytearray()
    for _ in range(MAX_MEMBERS):
        if len(out) >= limit:
            _issue(issues, f"{label} expanded data limit reached")
            break
        decoder = factory()
        try:
            out.extend(decoder.decompress(blob, max_length=limit - len(out)))
        except errors:
            if not probe:
                _issue(issues, f"{label} stream could not be decoded")
            break
        if not decoder.eof:
            if not probe or out:
                _issue(issues, f"{label} stream not fully decoded")
            break
        blob = decoder.unused_data
        if not blob:
            break
        if magic is None or not blob.startswith(magic):
            if not allow_trailing:
                _issue(issues, f"{label} trailing data not decoded")
            break
    else:
        _issue(issues, f"{label} compressed member limit reached")
    return bytes(out)


def _gunzip_prefix(blob: bytes, limit: int | None = None, *, issues: list[str] | None = None,
                   allow_trailing: bool = False) -> bytes:
    try:
        return _decode_frames(blob, lambda: zlib.decompressobj(31), MAX_EXPANDED if limit is None else limit,
                              GZIP_MAGIC, "gzip", issues, allow_trailing)
    except zlib.error:
        _issue(issues, "gzip stream could not be decoded")
        return b""


def decode_body(data: bytes, encoding: str, issues: list[str], *, limit: int | None = None) -> bytes:
    """Bound HTTP content decoding as well as the archive expansion that follows it."""
    if not data:
        return data
    limit = MAX_EXPANDED if limit is None else limit
    encoding = encoding.strip().lower()
    if "," in encoding:
        remaining = limit
        encodings = encoding.split(",")
        if len(encodings) > MAX_EMBEDDED:
            _issue(issues, "content encoding count limit reached")
            return data
        for part in reversed(encodings):
            if remaining <= 0:
                _issue(issues, "content decoding expanded data limit reached")
                break
            data = decode_body(data, part, issues, limit=remaining)
            remaining -= len(data)
        return data
    if not encoding or encoding == "identity":
        return data
    try:
        if encoding == "gzip":
            decoded = _gunzip_prefix(data, limit, issues=issues)
            return data if not decoded and issues else decoded
        if encoding == "deflate":
            try:
                decoded = _decode_frames(data, zlib.decompressobj, limit, None, encoding, issues, errors=())
            except zlib.error:
                decoded = _decode_frames(data, lambda: zlib.decompressobj(-15), limit, None, encoding, issues)
            return data if not decoded and issues else decoded
        if encoding == "zstd":
            decoded = _unzstd_prefix(data, limit, issues=issues)
            return data if not decoded and issues else decoded
        if encoding == "br":
            import brotli  # installed with mitmproxy

            decoder = brotli.Decompressor()
            if not hasattr(decoder, "can_accept_more_data"):
                _issue(issues, "bounded brotli decoding unavailable")
                return data
            try:
                decoded = decoder.process(data, output_buffer_limit=limit)
            except brotli.error:
                _issue(issues, "br body could not be decoded")
                return data
            if not decoder.is_finished() or len(decoded) > limit:
                _issue(issues, "br body not fully decoded")
            return decoded[:limit]
    except ImportError:
        _issue(issues, f"{encoding} decoder unavailable")
        return data
    except zlib.error:
        _issue(issues, f"{encoding} body could not be decoded")
        return data
    _issue(issues, f"unsupported content encoding: {encoding}")
    return data


def decode_framed(data: bytes, encoding: str, issues: list[str]) -> bytes:
    """gRPC/Connect envelopes, including base64 gRPC-web-text; use the message encoding header."""
    # A binary envelope's flags cannot be an ASCII base64 character.
    if data and data[0] & ~0x83:
        end = min(len(data), (MAX_EXPANDED // 3) * 4)
        encoded = data[:end].translate(None, b" \t\r\n")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except binascii.Error:
            pass  # The envelope parser reports the malformed body below.
        else:
            if end < len(data):
                _issue(issues, "RPC text expanded data limit reached")
            data = decoded
    out = bytearray()
    pos = 0
    for _ in range(MAX_MEMBERS):
        if pos == len(data):
            return bytes(out)
        if len(data) - pos < 5:
            _issue(issues, "truncated RPC frame header")
            break
        flags, size = data[pos], int.from_bytes(data[pos + 1:pos + 5], "big")
        pos += 5
        if flags & ~0x83 or size > len(data) - pos:
            _issue(issues, "invalid or truncated RPC frame")
            break
        remaining = MAX_EXPANDED - len(out)
        if remaining <= 0:
            _issue(issues, "RPC expanded data limit reached")
            break
        payload = data[pos:pos + min(size, remaining)]
        if size > remaining:
            _issue(issues, "RPC input limit reached")
        pos += size
        if flags & 1:
            if not encoding or encoding == "identity":
                _issue(issues, "compressed RPC frame has no message encoding")
            else:
                payload = decode_body(payload, encoding, issues, limit=remaining)
        out.extend(payload[:remaining])
    else:
        _issue(issues, "RPC frame count limit reached")
    return bytes(out)


def _zstd_module():
    # Python 3.14 has zstd in the standard library; mitmproxy installs a backport or zstandard.
    for name in ("compression.zstd", "backports.zstd", "zstandard"):
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    return None


def _unzstd_prefix(blob: bytes, limit: int | None = None, *, issues: list[str] | None = None,
                   allow_trailing: bool = False) -> bytes:
    mod = _zstd_module()
    if mod is None:
        _issue(issues, "zstd decoder unavailable")
        return b""
    limit = MAX_EXPANDED if limit is None else limit
    try:
        if hasattr(mod.ZstdDecompressor, "stream_reader"):  # zstandard
            decoder = mod.ZstdDecompressor(max_window_size=MAX_WINDOW // 1024)
            size = mod.frame_content_size(blob)
            # The one-shot API checks EOF, but only bounds allocation when the
            # declared frame size was checked first. The streaming API has no EOF flag.
            # zstandard's one-shot decoder can accept truncated zero-size frames.
            if 0 < size <= limit:
                try:
                    return decoder.decompress(blob, max_output_size=limit, allow_extra_data=allow_trailing)
                except mod.ZstdError:
                    pass  # keep a bounded readable prefix, with an explicit coverage warning
            _issue(issues, "zstd stream completeness could not be verified")
            with decoder.stream_reader(io.BytesIO(blob), read_across_frames=True) as reader:
                return reader.read(limit)
        options = {mod.DecompressionParameter.window_log_max: MAX_WINDOW.bit_length() - 1}
        return _decode_frames(blob, lambda: mod.ZstdDecompressor(options=options), limit,
                              ZSTD_MAGIC, "zstd", issues, allow_trailing, errors=(mod.ZstdError,))
    except (mod.ZstdError, EOFError):
        _issue(issues, "zstd stream could not be decoded")
        return b""


def _unpack(blob: bytes, budget: list[int], issues: list[str] | None) -> Iterator[bytes]:
    try:
        if blob[:2] == b"\x1f\x8b":
            yield _gunzip_prefix(blob, budget[0], issues=issues)
        elif blob[:4] == ZSTD_MAGIC:
            yield _unzstd_prefix(blob, budget[0], issues=issues)
        elif _is_zlib(blob):
            yield _decode_frames(blob, zlib.decompressobj, budget[0], None, "zlib", issues)
        elif blob[:4] == b"PK\x03\x04":
            # Reuse the stdlib's bounded EOCD/ZIP64 reader before ZipFile allocates ZipInfo objects.
            endrec = zipfile._EndRecData(io.BytesIO(blob))
            if endrec and endrec[zipfile._ECD_ENTRIES_TOTAL] > MAX_MEMBERS:
                _issue(issues, "archive entry limit reached")
                return
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
        elif blob[:6] == b"7z\xbc\xaf\x27\x1c":
            _issue(issues, "unsupported archive format: 7z")
        else:
            yield from _embedded(blob, budget, issues)
    except (OSError, EOFError, zlib.error, zipfile.BadZipFile, tarfile.TarError, ValueError,
            RuntimeError, NotImplementedError):
        _issue(issues, "archive could not be fully decoded")


def looks_like_archive(head: bytes) -> bool:
    return (
        head[:2] == b"\x1f\x8b"
        or head[:4] == b"PK\x03\x04"
        or head[:6] == b"7z\xbc\xaf\x27\x1c"
        or head[:4] == b"\x28\xb5\x2f\xfd"  # zstd
        or (len(head) > 262 and head[257:262] == b"ustar")
    )


def _is_zlib(blob: bytes) -> bool:
    return (len(blob) > 2 and blob[0] & 0x0f == 8 and blob[0] >> 4 <= 7
            and (blob[0] * 256 + blob[1]) % 31 == 0)
