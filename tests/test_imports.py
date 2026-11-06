"""Lightweight entry points must stay usable without loading proxy/process stacks."""
import subprocess
import sys

import pytest


@pytest.mark.parametrize('command', ['--version', 'board', 'check', 'selftest'])
def test_light_entry_points_do_not_load_proxy_or_psutil(command, tmp_path):
    script = '''
import importlib.abc, sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('mitmproxy', 'psutil'):
            raise AssertionError('unexpected heavy import: ' + fullname)
sys.meta_path.insert(0, Guard())
from whatsent.cli import main
main(sys.argv[1:])
'''
    args = [command]
    if command == 'board':
        args += ['examples/results', '-o', str(tmp_path / 'board')]
    elif command == 'check':
        args += ['examples/results']
    proc = subprocess.run([sys.executable, '-c', script, *args], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
