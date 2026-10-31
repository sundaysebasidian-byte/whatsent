"""Runs a CLI agent inside a terminal window that ``whatsent ui`` opened.

Interactive agents need a real terminal, which a local web server cannot give them, so
the UI opens a new terminal window running ``python -m whatsent.child SPEC``. SPEC is a
JSON file with the command, its folder, the proxy environment to add, and two files:
one this process writes its PID to, one it writes the agent's exit code to.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def write_status(path: Path, value: int) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(str(value), encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    spec = json.loads(Path((argv or sys.argv[1:])[0]).read_text(encoding="utf-8"))
    write_status(Path(spec["pidfile"]), os.getpid())
    if (time.monotonic() >= spec.get("launch_deadline", float("inf"))
            or (spec.get("cancel_file") and Path(spec["cancel_file"]).exists())):
        write_status(Path(spec["exitfile"]), 125)
        print("whatsent: terminal startup expired or was cancelled; the agent was not started.", file=sys.stderr)
        return 125
    env = {**os.environ, **spec["env"]}
    command = spec["command"]
    print(f"whatsent: recording {spec.get('name', command[0])}. Paste this prompt, let the agent finish, then exit it:\n\n"
          f"    {spec.get('prompt', '')}\n", flush=True)
    try:
        code = subprocess.call([shutil.which(command[0], path=env.get("PATH")) or command[0], *command[1:]],
                               cwd=spec["cwd"], env=env)
    except OSError as exc:
        print(f"whatsent: could not start {command[0]}: {exc}", file=sys.stderr)
        code = 127
    except KeyboardInterrupt:
        code = 130
    write_status(Path(spec["exitfile"]), code)
    print("\nwhatsent: done. The report opens in your browser; you can close this window.", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
