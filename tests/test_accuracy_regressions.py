"""Exact matches and visible bounds for encoded and streamed synthetic canaries."""
import base64
import gzip
import json
import zlib

import pytest

from whatsent import detect

TOKEN = 'wsc0deadbeefcafef00d'


@pytest.mark.parametrize('encode', [
    lambda b: base64.b64encode(gzip.compress(b)),
    lambda b: base64.urlsafe_b64encode(gzip.compress(b)).rstrip(b'='),
    lambda b: b.hex().encode(), lambda b: b.hex().upper().encode(),
    lambda b: b.decode().encode('utf-16le'), lambda b: b.decode().encode('utf-16be'),
    lambda b: ''.join(f'\\u{c:04x}' for c in b).encode(),
    lambda b: b''.join(f'%{c:02x}'.encode() for c in gzip.compress(b)),
])
def test_encoded_payloads(encode):
    assert detect.Matcher({'x': TOKEN}).scan(encode(TOKEN.encode())) == {'x'}


@pytest.mark.parametrize('pad', range(3))
def test_base64_near_miss_never_matches(pad):
    matcher = detect.Matcher({'x': TOKEN})
    for i in range(len(TOKEN)):
        changed = TOKEN[:i] + ('e' if TOKEN[i] != 'e' else 'f') + TOKEN[i + 1:]
        assert not matcher.scan(base64.b64encode(b'a' * pad + changed.encode())), (pad, i)


def test_text_decoding_shares_expansion_budget(monkeypatch):
    monkeypatch.setattr(detect, 'MAX_EXPANDED', 50)
    issues = []
    blobs = detect.expand(base64.b64encode(gzip.compress(b'a' * 1000)), issues=issues)
    assert sum(map(len, blobs[1:])) <= 50 and issues


def test_base64_candidate_limit_is_visible(monkeypatch):
    monkeypatch.setattr(detect, 'MAX_EMBEDDED', 2)
    issues = []
    data = b'"' + b'" "'.join([base64.b64encode(gzip.compress(b'a'))] * 3) + b'"'
    detect.Matcher({}).scan(data, issues=issues)
    assert any('base64' in issue and 'limit' in issue for issue in issues)


def test_raw_deflate_with_context():
    compressor = zlib.compressobj(wbits=-15)
    data = compressor.compress(TOKEN.encode()) + compressor.flush()
    issues = []
    assert detect.decode_body(data, 'deflate', issues) == TOKEN.encode()
    assert not issues


def test_stacked_content_encoding():
    issues = []
    data = gzip.compress(zlib.compress(TOKEN.encode()))
    decoded = detect.decode_body(data, 'deflate, gzip', issues)
    assert decoded == TOKEN.encode() and not issues


def test_corrupt_later_gzip_member_keeps_first_member():
    data = gzip.compress(TOKEN.encode()) + gzip.compress(b'ordinary')[:-5] + b'broken'
    issues = []
    assert detect.Matcher({'x': TOKEN}).scan(data, issues=issues) == {'x'}
    assert issues


@pytest.mark.parametrize('encoding', ['gzip', 'deflate', 'br'])
def test_contextual_compressed_rpc_frames(encoding):
    import brotli
    compressors = {'gzip': gzip.compress, 'deflate': zlib.compress, 'br': brotli.compress}
    packed = compressors[encoding](TOKEN.encode())
    frame = b'\x01' + len(packed).to_bytes(4, 'big') + packed
    issues = []
    decoded = detect.decode_framed(frame, encoding, issues)
    assert detect.Matcher({'x': TOKEN}).scan(decoded) == {'x'} and not issues


@pytest.mark.parametrize('offset', range(3))
def test_streaming_base64_keeps_alignment_after_long_messages(offset):
    payload = base64.b64encode(b'x' * (1000 + offset) + TOKEN.encode() + b'suffix')
    for cut in range(len(payload) - 30, len(payload) - 6):
        stream = detect.StreamMatcher(detect.Matcher({'x': TOKEN}))
        hits = stream.scan(payload[:cut]) | stream.scan(payload[cut:])
        assert hits == {'x'}, cut


def test_nesting_limit_is_visible_for_text_encodings():
    data = TOKEN.encode()
    for _ in range(8):
        data = base64.b64encode(data)
    issues = []
    detect.Matcher({'x': TOKEN}).scan(data, issues=issues)
    assert any('nesting' in issue for issue in issues)


def test_missing_brotli_is_uninspected(monkeypatch):
    import builtins
    original = builtins.__import__
    def import_module(name, *args, **kwargs):
        if name == 'brotli':
            raise ImportError('synthetic missing codec')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', import_module)
    issues = []
    assert detect.decode_body(b'opaque', 'br', issues) == b'opaque' and issues


def test_size_limit_in_chromium_store_is_still_incomplete(tmp_path, monkeypatch):
    from whatsent import diskwatch
    folder = tmp_path / 'Cache_Data'
    folder.mkdir()
    path = folder / 'large'
    path.write_bytes(b'x' * 64 + TOKEN.encode())
    monkeypatch.setattr(diskwatch, 'MAX_SCAN_BYTES', 32)
    snapshot, _ = diskwatch.snapshot([tmp_path], [])
    result = diskwatch.diff({}, snapshot, detect.Matcher({'x': TOKEN}))
    assert result['incomplete_files'] == [str(path)]


@pytest.mark.parametrize('split', [1, 2, 17, 1000])
def test_split_compressed_stream_cannot_silently_miss(split):
    import random
    data = base64.b64encode(gzip.compress(random.Random(5).randbytes(2048) + TOKEN.encode()))
    stream = detect.StreamMatcher(detect.Matcher({'x': TOKEN}))
    issues = []
    hits = stream.scan(data[:split], issues=issues) | stream.scan(data[split:], issues=issues)
    assert hits == {'x'} or issues
