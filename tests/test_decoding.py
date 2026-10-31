"""Incomplete compressed data must not look like a complete negative inspection."""

import gzip
import zlib

import pytest

from whatsent import detect

TOKEN = "wsc0deadbeefcafef00d"


def zstd_compress(data):
    mod = detect._zstd_module()
    return mod.compress(data) if hasattr(mod, "compress") else mod.ZstdCompressor().compress(data)


@pytest.mark.parametrize("compress", [gzip.compress, zlib.compress, zstd_compress])
def test_truncated_archives_warn(compress):
    issues = []
    detect.Matcher({"x": TOKEN}).scan(compress(TOKEN.encode())[:-1], issues=issues)
    assert issues


@pytest.mark.parametrize("data", [b"\x1f\x8b\x08invalid", b"7z\xbc\xaf\x27\x1copaque"])
def test_broken_or_unsupported_archives_warn(data):
    issues = []
    detect.Matcher({}).scan(data, issues=issues)
    assert issues


@pytest.mark.parametrize("encoding,compress", [("gzip", gzip.compress), ("deflate", zlib.compress),
                                               ("zstd", zstd_compress)])
def test_empty_encoded_body_has_no_false_confidence(encoding, compress):
    issues = []
    packed = compress(b"")
    decoded = detect.decode_body(packed, encoding, issues)
    if encoding == "zstd" and hasattr(detect._zstd_module().ZstdDecompressor, "stream_reader"):
        assert issues  # the legacy backend cannot verify empty-frame completeness
    else:
        assert decoded == b"" and not issues


@pytest.mark.parametrize("encoding,compress", [("gzip", gzip.compress), ("zstd", zstd_compress)])
def test_later_compressed_members_are_scanned(encoding, compress):
    payload = compress(b"ordinary") + compress(TOKEN.encode())
    issues = []
    decoded = detect.decode_body(payload, encoding, issues)
    assert TOKEN.encode() in decoded
    assert detect.Matcher({"x": TOKEN}).scan(payload) == {"x"}


@pytest.mark.parametrize("encoding,compress", [("gzip", gzip.compress), ("zstd", zstd_compress)])
def test_multiple_members_share_the_output_limit(monkeypatch, encoding, compress):
    monkeypatch.setattr(detect, "MAX_EXPANDED", 100)
    issues = []
    decoded = detect.decode_body(compress(b"a" * 80) + compress(b"b" * 80), encoding, issues)
    assert len(decoded) <= 100 and issues


def test_empty_gzip_member_count_is_bounded(monkeypatch):
    monkeypatch.setattr(detect, "MAX_MEMBERS", 3)
    issues = []
    decoded = detect.decode_body(gzip.compress(b"") * 4 + gzip.compress(TOKEN.encode()), "gzip", issues)
    assert TOKEN.encode() not in decoded and issues


@pytest.mark.parametrize("compress", [gzip.compress, zstd_compress])
def test_framed_stream_allows_protocol_trailer(compress):
    issues = []
    assert detect.Matcher({"x": TOKEN}).scan(b"frame:" + compress(TOKEN.encode()) + b"trailer", issues=issues) == {"x"}
    assert not issues


def test_truncated_zstd_http_body_warns():
    issues = []
    detect.decode_body(zstd_compress(b"hello")[:-1], "zstd", issues)
    assert issues


@pytest.mark.parametrize("encoding", ["gzip", "zstd"])
def test_invalid_content_encoding_preserves_raw_matches(encoding):
    issues = []
    decoded = detect.decode_body(TOKEN.encode(), encoding, issues)
    assert detect.Matcher({"x": TOKEN}).scan(decoded) == {"x"} and issues


@pytest.mark.parametrize("content", [b"", TOKEN.encode()])
def test_zstandard_backend_checks_eof(monkeypatch, content):
    mod = pytest.importorskip("zstandard")
    monkeypatch.setattr(detect, "_zstd_module", lambda: mod)
    packed = mod.ZstdCompressor().compress(content)
    issues = []
    decoded = detect.decode_body(packed, "zstd", issues)
    if content:
        assert decoded == content and not issues
    else:
        assert issues
    issues.clear()
    detect.decode_body(packed[:-1], "zstd", issues)
    assert issues


def test_zstandard_backend_multiple_frames_and_size_limit(monkeypatch):
    mod = pytest.importorskip("zstandard")
    monkeypatch.setattr(detect, "_zstd_module", lambda: mod)
    packed = mod.ZstdCompressor().compress(b"ordinary") + mod.ZstdCompressor().compress(TOKEN.encode())
    issues = []
    assert TOKEN.encode() in detect.decode_body(packed, "zstd", issues)
    # This backend exposes no EOF flag on its bounded streaming reader.
    assert issues
    monkeypatch.setattr(detect, "MAX_EXPANDED", 64)
    issues = []
    decoded = detect.decode_body(mod.ZstdCompressor().compress(b"x" * 4096), "zstd", issues)
    assert len(decoded) <= 64 and issues
