"""User-facing failures must preserve files and respect the caller's launch directory."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from whatsent import cli


@pytest.mark.parametrize("mode", ["run", "demo", "board"])
def test_output_path_is_a_file_returns_an_error_without_overwriting(tmp_path, capsys, mode):
    output = tmp_path / "keep.txt"
    output.write_text("keep this")
    if mode == "run":
        args = ["run", "--out", str(output), "--no-default-watch", "--agent-version", "test",
                "--", sys.executable, "-c", "pass"]
    elif mode == "demo":
        args = ["demo", "--out", str(output)]
    else:
        example = Path(__file__).parents[1] / "examples/results/example-agent-a.json"
        args = ["board", str(example), "--out", str(output)]
    assert cli.main(args) == 1
    assert output.read_text() == "keep this"
    assert "whatsent:" in capsys.readouterr().err


def test_relative_executable_survives_the_workspace_directory_change(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    try:
        executable = os.path.relpath(sys.executable, tmp_path)
    except ValueError:
        pytest.skip("executable and temp directory are on different Windows drives")
    command = [executable, "-c", "import os,json,sys;print(json.dumps([os.getcwd(),sys.prefix]))"]
    args = cli.build_parser().parse_args(["run", "--out", str(tmp_path / "out"), "--", *command])
    session = cli.Session(args, command)
    session.workspace.mkdir(parents=True)
    session.proxy = SimpleNamespace(local_spec="test")
    session.env = dict(os.environ)
    session.launch(lambda command, cwd, env: subprocess.Popen(command, cwd=cwd, env=env,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
    stdout, stderr = session.agent.communicate(timeout=10)
    assert session.agent.returncode == 0, stderr
    cwd, prefix = json.loads(stdout)
    assert Path(cwd) == session.workspace
    assert prefix == sys.prefix


def test_relative_path_lookup_is_fixed_before_changing_directories(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "tools/agent.exe")
    args = cli.build_parser().parse_args(["run", "--", "agent", "--input", "src/app.py"])
    session = cli.Session(args, ["agent", "--input", "src/app.py"])
    assert session.command == [str(tmp_path / "tools/agent.exe"), "--input", "src/app.py"]
