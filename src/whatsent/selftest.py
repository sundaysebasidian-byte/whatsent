"""Small, deterministic offline corpus; not a measurement of real-agent coverage."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import gzip
import io
import json
import random
import sys
import tarfile
from urllib.parse import quote_from_bytes
import zipfile
import zlib

from whatsent.detect import Matcher, StreamMatcher, _zstd_module, decode_body, decode_framed

TOKENS = {'task_file': 'wsc00123456789abcdef', 'dotenv': 'wsc2fedcba9876543210'}
LIMITS = (
    'This deterministic offline corpus checks exact synthetic-token detection, not real-agent capture coverage. '
    'Expansion shares a 200 MiB output budget with four recursive levels, 4,096 archive members, '
    '4,096 plausible base64 candidates and 64 embedded streams per blob; RPC envelopes also have a 4,096-frame limit. '
    'HTTP uploads retain at most 200 MiB of wire data. WebSocket reassembly retains only a token-sized '
    'outbound overlap per connection; compressed containers split beyond it and opaque application '
    'encryption remain unreadable. Independently base64-encoded application chunks (JSON arrays or separate '
    'WebSocket messages) are not joined. Unavailable codecs, damaged containers and exhausted decoding '
    'or capture limits are reported as uninspected; this table does not prove zero false positives '
    'outside the corpus.'
)


@dataclass(frozen=True)
class Case:
    name: str
    data: bytes | tuple[bytes, ...]
    expected: frozenset[str]
    encoding: str = ''
    framed: bool = False


@dataclass
class Result:
    name: str
    cases: int = 0
    failures: int = 0
    issues: tuple[str, ...] = ()


def _zip(data: bytes, name: str = 'payload.txt') -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, data)
    return buf.getvalue()


def _tar(data: bytes, name: str = 'payload.txt') -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as archive:
        member = tarfile.TarInfo(name)
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    return buf.getvalue()


def _zstd(data: bytes) -> bytes:
    mod = _zstd_module()
    if mod is None:
        raise RuntimeError('zstd codec unavailable')
    return mod.compress(data) if hasattr(mod, 'compress') else mod.ZstdCompressor().compress(data)


def encoded_cases(data: bytes, expected: frozenset[str]):
    """Reusable encoding/container generator for positive and negative input."""
    yield Case('plain', data, expected)
    yield Case('url-encoded', quote_from_bytes(data, safe='').encode(), expected)
    # Force every byte to be escaped, including otherwise URL-safe token characters.
    yield Case('url-all-bytes', b''.join(f'%{b:02X}'.encode() for b in data), expected)
    for offset in range(3):
        yield Case(f'base64 offset {offset}', base64.b64encode(b'x' * offset + data), expected)
        yield Case(f'base64url offset {offset}', base64.urlsafe_b64encode(b'\xfb\xff' * offset + data).rstrip(b'='), expected)
    yield Case('gzip', gzip.compress(data, mtime=0), expected)
    yield Case('multi-member gzip', gzip.compress(b'ordinary', mtime=0) + gzip.compress(data, mtime=0), expected)
    yield Case('zstd', _zstd(data), expected)
    yield Case('multi-frame zstd', _zstd(b'ordinary') + _zstd(data), expected)
    yield Case('zlib', zlib.compress(data), expected)
    compressor = zlib.compressobj(wbits=-15)
    yield Case('raw deflate (HTTP)', compressor.compress(data) + compressor.flush(), expected, 'deflate')
    yield Case('zip', _zip(data), expected)
    yield Case('tar', _tar(data), expected)
    yield Case('zip-in-gzip', gzip.compress(_zip(data), mtime=0), expected)
    for name, packed in [('gzip', gzip.compress(data, mtime=0)), ('zip', _zip(data)), ('zstd', _zstd(data))]:
        yield Case(f'base64({name})', b'{"blob":"' + base64.b64encode(packed) + b'"}', expected)
    yield Case('url(gzip)', b''.join(f'%{b:02x}'.encode() for b in gzip.compress(data, mtime=0)), expected)
    for name, packed in [('gzip', gzip.compress(data, mtime=0)), ('zstd', _zstd(data))]:
        frame = b'\x01' + len(packed).to_bytes(4, 'big') + packed
        yield Case(f'gRPC {name} (embedded)', frame, expected)
        yield Case(f'gRPC {name} (header)', frame, expected, name, True)
    import brotli
    packed = brotli.compress(data)
    yield Case('brotli (HTTP)', packed, expected, 'br')
    yield Case('Connect brotli (header)', b'\x01' + len(packed).to_bytes(4, 'big') + packed, expected, 'br', True)
    yield Case('stacked HTTP encodings', gzip.compress(zlib.compress(data), mtime=0), expected, 'deflate, gzip')
    yield Case('hex lower', data.hex().encode(), expected)
    yield Case('hex upper', data.hex().upper().encode(), expected)
    yield Case('UTF-16LE', data.decode().encode('utf-16le'), expected)
    yield Case('UTF-16BE', data.decode().encode('utf-16be'), expected)
    yield Case('JSON Unicode escapes', b''.join(f'\\u{b:04x}'.encode() for b in data), expected)
    yield Case('websocket-split', tuple(data[i:i + 3] for i in range(0, len(data), 3)), expected)



def _base64_gzip_with_slash(token: bytes) -> bytes:
    """base64(gzip(...)) that contains '/', whatever zlib build compressed it."""
    for pad in range(200, 456):
        encoded = base64.b64encode(gzip.compress(b'x' * pad + token + b'tail', mtime=0))
        if b'/' in encoded:
            return encoded
    raise RuntimeError('no base64 gzip payload with a slash')

def corpus():
    expected = frozenset(TOKENS)
    payload = ('KEY=' + ' '.join(TOKENS.values()) + '\n').encode()
    yield from encoded_cases(payload, expected)
    for pack, label in ((_zip, 'zip filename'), (_tar, 'tar filename')):
        yield Case(label, pack(b'ordinary', ' '.join(TOKENS.values())), expected)
    token = TOKENS['task_file'].encode()
    for split in range(1, len(token)):
        yield Case('websocket every split', (token[:split], token[split:]), frozenset({'task_file'}))
    for offset in range(3):
        data = base64.b64encode(b'x' * (1000 + offset) + TOKENS['task_file'].encode() + b'suffix')
        for split in range(len(data) - 30, len(data) - 6):
            yield Case('websocket base64 long prefix', (data[:split], data[split:]), frozenset({'task_file'}))
    for width in (64, 76):
        for newline in (b'\n', b'\r\n'):
            for offset in range(width):
                encoded = base64.b64encode(b'x' * offset + payload + b'suffix')
                wrapped = newline.join(encoded[i:i + width] for i in range(0, len(encoded), width))
                yield Case(f'base64 wrapped {width} columns', wrapped, expected)
    encoded = _base64_gzip_with_slash(token)
    escaped = encoded.replace(b'/', b'\\/')
    yield Case('JSON slash-escaped base64(gzip)', b'{"blob":"' + escaped + b'"}', frozenset({'task_file'}))
    inner = '{"blob":"' + escaped.decode() + '"}'
    yield Case('JSON backslash escapes', json.dumps({'nested': inner}).encode(), frozenset({'task_file'}))
    prefix = b'\n'.join(b'index a1b2c3d4e5f6071801..0f1e2d3c4b5a697801' for _ in range(40))
    yield Case('base64 after git diff indexes', prefix + b'\n' + base64.b64encode(payload), expected)
    runs = b' '.join(b'"' + base64.b64encode(b'ordinary-%02d-padding' % i) + b'"' for i in range(64))
    yield Case('base64 after 64 ordinary runs', runs + b' "' + base64.b64encode(payload) + b'"', expected)
    for compressed in (False, True):
        data = gzip.compress(payload, mtime=0) if compressed else payload
        frame = bytes([int(compressed)]) + len(data).to_bytes(4, 'big') + data
        yield Case('gRPC-web-text gzip' if compressed else 'gRPC-web-text plain',
                   base64.b64encode(frame), expected, 'gzip' if compressed else '', True)
    short_runs = b'"YWJjZGVmZ2hpamts" ' * 5000
    yield Case('base64 after short runs', short_runs + base64.b64encode(payload), expected)
    for encoding in ('gzip', 'deflate', 'zstd', 'br', 'gzip, br'):
        yield Case('negative empty HTTP bodies', b'', frozenset(), encoding)
    binary_payload = b'\x00\xff%41' + payload
    yield Case('zip with binary percent sequences', _zip(binary_payload), expected)
    invalid_zlib = b'\x78\x9c' + b'\xff' * 32
    yield Case('negative sniffed zlib (base64)', base64.b64encode(invalid_zlib), frozenset())
    yield Case('negative sniffed zlib (percent)', quote_from_bytes(invalid_zlib, safe='').encode(), frozenset())
    rng = random.Random(20261105)
    for size in (0, 1, 16, 128, 1024, 8192):
        for _ in range(8):
            yield Case('negative random bytes', rng.randbytes(size), frozenset())
    for token in TOKENS.values():
        for i, char in enumerate(token):
            changed = (token[:i] + ('e' if char != 'e' else 'f') + token[i + 1:]).encode()
            for case in encoded_cases(changed, frozenset()):
                yield Case('negative one-character mutations', case.data, case.expected, case.encoding, case.framed)
    for case in encoded_cases(b'wsc09999999999999999 wsc28888888888888888', frozenset()):
        yield Case('negative other-run tokens', case.data, case.expected, case.encoding, case.framed)


def evaluate(case: Case, matcher: Matcher) -> tuple[bool, tuple[str, ...]]:
    issues: list[str] = []
    if isinstance(case.data, tuple):
        stream = StreamMatcher(matcher)
        hits: set[str] = set()
        for chunk in case.data:
            hits |= stream.scan(chunk, issues=issues)
    else:
        decoded = (decode_framed(case.data, case.encoding, issues) if case.framed
                   else decode_body(case.data, case.encoding, issues))
        hits = matcher.scan(decoded, issues=issues)
    return hits == case.expected, tuple(issues)


def run_corpus() -> list[Result]:
    matcher = Matcher(TOKENS)
    results: dict[str, Result] = {}
    for case in corpus():
        result = results.setdefault(case.name, Result(case.name))
        passed, issues = evaluate(case, matcher)
        result.cases += 1
        result.failures += not passed
        result.issues = tuple(dict.fromkeys((*result.issues, *issues)))
    return list(results.values())


def render(results: list[Result], *, markdown: bool = False, ascii_only: bool = False) -> str:
    ok, bad = ('ok', 'FAIL') if ascii_only else ('✓', '✗')
    rows = [(r.name, str(r.cases), ok if not r.failures else f'{bad} ({r.failures} failed)') for r in results]
    if markdown:
        lines = ['| Encoding / corpus | Cases | Exact matches |', '| --- | ---: | :---: |']
        lines.extend(f'| {name} | {count} | {status} |' for name, count, status in rows)
        lines.extend(['', LIMITS])
    else:
        width = max(len(row[0]) for row in rows)
        lines = [f'{name:<{width}}  {status}  ({count})' for name, count, status in rows]
    warnings = sorted({issue for r in results if not r.name.startswith('negative') for issue in r.issues})
    if warnings:
        label = 'Uninspected: ' if markdown else 'Limits reported as uninspected, as intended: '
        lines.extend(['', label + '; '.join(warnings)])
    if not markdown:
        negative = sum(r.cases for r in results if r.name.startswith('negative'))
        total = sum(r.cases for r in results)
        failed = sum(r.failures for r in results)
        verdict = 'no misses, no false positives' if not failed else f'{failed} FAILED'
        lines.extend(['', f'{total:,} cases ({total - negative:,} positive, {negative:,} negative): {verdict}'])
    return '\n'.join(lines) + '\n'


def main(*, markdown: bool = False) -> int:
    results = run_corpus()
    if markdown:  # a document: always UTF-8, whatever the console encoding
        sys.stdout.flush()
        sys.stdout.buffer.write(render(results, markdown=True).encode('utf-8'))
        sys.stdout.buffer.flush()
    else:
        try:
            '✓✗'.encode(sys.stdout.encoding or 'ascii')
            ascii_only = False
        except (LookupError, UnicodeEncodeError):
            ascii_only = True  # e.g. a legacy Windows console (cp1252)
        print(render(results, ascii_only=ascii_only), end='')
    return int(any(r.failures for r in results))
