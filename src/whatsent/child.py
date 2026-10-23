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
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    spec = json.loads(Path((argv or sys.argv[1:])[0]).read_text(encoding="utf-8"))
    Path(spec["pidfile"]).write_text(str(os.getpid()), encoding="utf-8")
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
    Path(spec["exitfile"]).write_text(str(code), encoding="utf-8")
    print("\nwhatsent: done. The report opens in your browser; you can close this window.", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
