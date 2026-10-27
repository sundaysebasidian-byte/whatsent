"""The mitmproxy addon on synthetic flows shaped like real agent traffic (e.g. Codex CLI:
Responses API over WebSocket, or HTTP POST with a zstd-compressed body)."""

from __future__ import annotations

import importlib
import json

import pytest

pytest.importorskip("mitmproxy")
from mitmproxy import websocket  # noqa: E402
from mitmproxy.test import tflow, tutils  # noqa: E402
from wsproto.frame_protocol import Opcode  # noqa: E402

from whatsent.detect import _zstd_module  # noqa: E402

TOKEN = "wsc0deadbeefcafef00d"
PROMPT = json.dumps({"type": "response.create", "input": [
    {"type": "function_call_output", "output": f"def add(a, b):\n    return a - b  # build-id: {TOKEN}\n"}]})


def zstd_compress(data: bytes) -> bytes:
    mod = _zstd_module()
    if mod is None:
        pytest.skip("no zstd module")
    if hasattr(mod, "ZstdCompressor") and hasattr(mod.ZstdCompressor, "compressobj"):  # zstandard
        return mod.ZstdCompressor().compress(data)
    return mod.compress(data)


@pytest.fixture
def recorder(tmp_path, monkeypatch):
    canaries = tmp_path / "canaries.json"
    canaries.write_text(json.dumps([{"id": "task_file", "token": TOKEN}]), encoding="utf-8")
    events = tmp_path / "events.jsonl"
    monkeypatch.setenv("WHATSENT_CANARIES", str(canaries))
    monkeypatch.setenv("WHATSENT_EVENTS", str(events))
    monkeypatch.delenv("WHATSENT_REMAP", raising=False)
    addon = importlib.import_module("whatsent._addon")
    rec = addon.Recorder()

    def read() -> list[dict]:
        rec.out.flush()
        return [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]

    yield rec, read
    rec.out.close()


def post(body: bytes, encoding: str | None) -> object:
    headers = [(b"content-type", b"application/json")]
    if encoding:
        headers.append((b"content-encoding", encoding.encode()))
    req = tutils.treq(method=b"POST", host="chatgpt.com", port=443, scheme=b"https",
                      path=b"/backend-api/codex/responses", headers=headers, content=body)
    return tflow.tflow(req=req, resp=True)


def test_zstd_request_body(recorder):
    rec, read = recorder
    rec.response(post(zstd_compress(PROMPT.encode()), "zstd"))
    (ev,) = read()
    assert ev["canaries"] == ["task_file"] and not ev["undecoded"]
    assert ev["bytes_out"] < len(PROMPT) + 400  # counts what went over the wire, compressed


def test_unknown_encoding_is_flagged(recorder):
    rec, read = recorder
    rec.response(post(b"\x8b\x05\x80opaque", "x-custom"))
    rec.response(post(b"not really gzip", "gzip"))
    assert [ev["undecoded"] for ev in read()] == ["x-custom", "gzip"]


def test_websocket_messages(recorder):
    rec, read = recorder
    flow = tflow.twebsocketflow(messages=False)
    for content, opcode, from_client in (
        (PROMPT.encode(), Opcode.TEXT, True),  # Codex: response.create as a JSON text frame
        (zstd_compress(PROMPT.encode()), Opcode.BINARY, True),  # a compressed binary frame
        (PROMPT.encode(), Opcode.TEXT, False),  # the server echoing it back is not an upload
    ):
        flow.websocket.messages.append(websocket.WebSocketMessage(opcode, from_client, content))
        rec.websocket_message(flow)
    assert [(ev["type"], ev["canaries"]) for ev in read()] == [("websocket", ["task_file"])] * 2
