"""Regression cases reproduced during the v0.4 detection review."""
import base64
import gzip
import io
import json
import random
import struct
import zipfile
import zlib
from urllib.parse import quote_from_bytes

import pytest

from whatsent import detect
from whatsent.report import summarize

TOKEN = 'wsc00123456789abcdef'


@pytest.mark.parametrize('width', [64, 76])
@pytest.mark.parametrize('newline', [b'\n', b'\r\n'])
def test_wrapped_base64_at_every_offset(width, newline):
    matcher = detect.Matcher({'x': TOKEN})
    for offset in range(width):
        raw = b'x' * offset + TOKEN.encode() + b'suffix'
        encoded = base64.b64encode(raw)
        wrapped = newline.join(encoded[i:i + width] for i in range(0, len(encoded), width))
        body = b'Content-Transfer-Encoding: base64' + newline * 2 + wrapped + newline
        assert matcher.scan(body) == {'x'}, offset


def test_wrapped_base64_shares_output_budget(monkeypatch):
    monkeypatch.setattr(detect, 'MAX_EXPANDED', 80)
    encoded = base64.b64encode(b'x' * 40 + TOKEN.encode() + b'x' * 200)
    data = b'\r\n'.join(encoded[i:i + 64] for i in range(0, len(encoded), 64))
    issues = []
    blobs = detect.expand(data, issues=issues)
    assert any(TOKEN.encode() in blob for blob in blobs)
    assert sum(map(len, blobs[1:])) <= 80 and issues


@pytest.mark.parametrize('escape', [lambda b: b.replace(b'/', b'\\/'),
                                   lambda b: b.replace(b'/', b'\\u002f')])
def test_json_escaped_base64_gzip(escape):
    encoded = base64.b64encode(gzip.compress(b'x' * 200 + TOKEN.encode() + b'tail', mtime=0))
    assert b'/' in encoded
    assert detect.Matcher({'x': TOKEN}).scan(b'{"blob":"' + escape(encoded) + b'"}') == {'x'}


def test_json_escaped_backslash_then_slash():
    # The outer JSON string contains another JSON string with an escaped slash.
    encoded = base64.b64encode(gzip.compress(b'x' * 200 + TOKEN.encode() + b'tail', mtime=0))
    inner = '{"blob":"' + encoded.decode().replace('/', '\\/') + '"}'
    data = json.dumps({'nested': inner}).encode()
    assert b'\\\\/' in data
    assert detect.Matcher({'x': TOKEN}).scan(data) == {'x'}


@pytest.mark.parametrize('prefix', [
    b' '.join(b'"' + base64.b64encode(b'ordinary-%02d-padding' % i) + b'"' for i in range(64)),
    b'\n'.join(b'index a1b2c3d4e5f6071801..0f1e2d3c4b5a697801' for _ in range(40)),
])
def test_base64_after_ordinary_runs(prefix):
    data = prefix + b'\n"' + base64.b64encode(b'xxx' + TOKEN.encode()) + b'"'
    assert detect.Matcher({'x': TOKEN}).scan(data) == {'x'}


def test_short_non_container_runs_do_not_consume_base64_candidates():
    data = b'"YWJjZGVmZ2hpamts" ' * 5000 + base64.b64encode(TOKEN.encode())
    issues = []
    assert detect.Matcher({'x': TOKEN}).scan(data, issues=issues) == {'x'}
    assert 'base64 candidate limit reached' not in issues


def test_zip_entry_count_checked_before_directory_materialization(monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as archive:
        for i in range(4):
            archive.writestr(str(i), b'')
    monkeypatch.setattr(detect, 'MAX_MEMBERS', 3)
    def no_materialization(*args, **kwargs):
        pytest.fail('oversized central directory was materialized')
    monkeypatch.setattr(zipfile.ZipFile, '_RealGetContents', no_materialization)
    issues = []
    detect.Matcher({}).scan(buf.getvalue(), issues=issues)
    assert 'archive entry limit reached' in issues


def test_zip64_entry_count_checked_before_directory_materialization(monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as archive:
        archive.writestr('payload.txt', TOKEN)
    packed = buf.getvalue()
    eocd = packed[-22:]
    cd_size, cd_offset = struct.unpack_from('<II', eocd, 12)
    count = 200000
    zip64 = struct.pack('<4sQ2H2I4Q', b'PK\x06\x06', 44, 45, 45, 0, 0,
                        count, count, cd_size, cd_offset)
    locator = struct.pack('<4sIQI', b'PK\x06\x07', 0, len(packed) - 22, 1)
    data = packed[:-22] + zip64 + locator + eocd
    def no_materialization(*args, **kwargs):
        pytest.fail('ZIP64 central directory was materialized')
    monkeypatch.setattr(zipfile.ZipFile, '_RealGetContents', no_materialization)
    issues = []
    detect.Matcher({}).scan(data, issues=issues)
    assert 'archive entry limit reached' in issues


def test_sniffed_invalid_zlib_in_text_decodings_does_not_warn():
    rng = random.Random(7)
    matcher = detect.Matcher({'x': TOKEN})
    for _ in range(500):
        blob = b'\x78' + rng.randbytes(63)
        if not detect._is_zlib(blob):
            continue
        for encoded in (base64.b64encode(blob), quote_from_bytes(blob, safe='').encode()):
            issues = []
            assert not matcher.scan(encoded, issues=issues)
            assert not issues, issues


@pytest.mark.parametrize('encoding', ['', 'gzip', 'deflate', 'zstd', 'br', 'gzip, br', 'unknown'])
def test_empty_http_body_has_nothing_to_decode(encoding):
    issues = []
    assert detect.decode_body(b'', encoding, issues) == b''
    assert not issues


def test_percent_sequences_in_binary_zip_are_not_text_decoded():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_STORED) as archive:
        archive.writestr('payload.bin', b'\x00\xff%41' + TOKEN.encode())
    issues = []
    assert detect.Matcher({'x': TOKEN}).scan(buf.getvalue(), issues=issues) == {'x'}
    assert not issues


def test_report_keeps_semicolon_reasons_atomic_when_deduplicating():
    reasons = ['gzip; x stream could not be decoded', 'gzip',
               'body capture limit reached', 'gzip; x stream could not be decoded']
    events = [{'type': 'http', 'host': 'h.test', 'undecoded': reason, 'canaries': []}
              for reason in reasons]
    (entry,) = summarize({}, [], events, None, [])['not_inspected']['undecoded']
    assert entry == {'host': 'h.test', 'encoding': '; '.join(reasons[:3]), 'count': 4}


@pytest.mark.parametrize('limit', [1, 2, 8, 18])
def test_base64_prefix_too_short_for_token_still_reports_exhausted_budget(monkeypatch, limit):
    monkeypatch.setattr(detect, 'MAX_EXPANDED', limit)
    issues = []
    detect.Matcher({'x': TOKEN}).scan(base64.b64encode(TOKEN.encode()), issues=issues)
    assert any('limit' in issue for issue in issues)


def test_sniffed_zlib_errors_are_distinct_from_declared_http_deflate():
    blob = b'\x78\x9c' + b'\xff' * 32
    issues = []
    detect._decode_frames(blob, zlib.decompressobj, detect.MAX_EXPANDED, None, 'zlib', issues)
    assert not issues
    detect.decode_body(blob, 'deflate', issues)
    assert issues
