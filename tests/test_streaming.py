"""Exercise the real mitmproxy streaming hooks, including unknown-length uploads."""
from contextlib import contextmanager
import http.server
import json
import threading
import urllib.request

import pytest

from whatsent.capture import Proxy


@contextmanager
def sink():
    class Sink(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            if self.headers.get('Transfer-Encoding') == 'chunked':
                while size := int(self.rfile.readline().strip(), 16):
                    self.rfile.read(size)
                    self.rfile.read(2)
                self.rfile.readline()
            else:
                self.rfile.read(int(self.headers.get('Content-Length', '0')))
            self.send_response(200)
            self.send_header('Content-Length', '0')
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Sink)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize('chunked', [False, True])
def test_large_upload_remains_inspected_with_mitm_streaming_option(tmp_path, chunked):
    token = 'wsc00123456789abcdef'
    canaries = tmp_path / 'canaries.json'
    canaries.write_text(json.dumps([{'id': 'task_file', 'token': token}]))
    events = tmp_path / 'events.jsonl'
    with sink() as port:
        proxy = Proxy(tmp_path, canaries, events, mitm_options=['stream_large_bodies=1'],
                      extra_env={'WHATSENT_REMAP': json.dumps({'upload.test': ['127.0.0.1', port]})})
        try:
            proxy.start()
            body = b'x' * 8192 + token.encode()
            data = iter([body[:8200], body[8200:]]) if chunked else body
            request = urllib.request.Request('http://upload.test/upload', data=data, method='POST')
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({'http': f'http://127.0.0.1:{proxy.port}'}))
            with opener.open(request, timeout=10) as response:
                assert response.status == 200
        finally:
            proxy.stop()
            assert not proxy.forget_keys()
    records = [json.loads(line) for line in events.read_text().splitlines()]
    assert records and all(r['canaries'] == ['task_file'] and not r['undecoded'] for r in records)
    assert all(r['bytes_out'] >= len(body) for r in records)
