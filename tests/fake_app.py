"""Stands in for an Electron IDE: ignores HTTP(S)_PROXY and only uses --proxy-server, like
Chromium's network stack. Sends the task file to the URL in FAKE_APP_URL."""

import json
import os
import sys
import urllib.request
from pathlib import Path

args = sys.argv[1:]
proxy = next(a.split("=", 1)[1] for a in args if a.startswith("--proxy-server="))
assert any(a.startswith("--ignore-certificate-errors-spki-list=") for a in args)
assert "--ignore-certificate-errors" not in args
workspace = Path(args[-1])
body = json.dumps({"file": (workspace / "src/app.py").read_text()}).encode()
opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
opener.open(urllib.request.Request(os.environ["FAKE_APP_URL"], data=body, method="POST"), timeout=10).read()
