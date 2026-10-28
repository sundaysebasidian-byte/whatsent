"""Stands in for Codex CLI: posts the conversation as zstd-compressed JSON over HTTPS, then
fixes the bug. With --silent it fixes the bug without sending the task file, like an agent
that edits blind or sends its traffic in a form whatsent cannot read."""

import argparse
import json
import ssl
import urllib.request
from pathlib import Path

from whatsent.detect import _zstd_module

ap = argparse.ArgumentParser()
ap.add_argument("--api", required=True)
ap.add_argument("--silent", action="store_true")
a = ap.parse_args()

app = Path("src/app.py")
text = app.read_text(encoding="utf-8")
output = "(nothing)" if a.silent else text
body = json.dumps({"type": "response.create", "input": [{"type": "function_call_output", "output": output}]})
mod = _zstd_module()
data = mod.ZstdCompressor().compress(body.encode()) if hasattr(mod, "ZstdCompressor") and hasattr(
    mod.ZstdCompressor, "compressobj") else mod.compress(body.encode())
req = urllib.request.Request(a.api, data=data, method="POST",
                             headers={"Content-Type": "application/json", "Content-Encoding": "zstd"})
opener = urllib.request.build_opener(urllib.request.ProxyHandler(),
                                     urllib.request.HTTPSHandler(context=ssl.create_default_context()))
with opener.open(req, timeout=10) as resp:
    resp.read()
app.write_text(text.replace("a - b", "a + b"), encoding="utf-8")
