#!/usr/bin/env python3
"""Start a Linux ELF program or AppImage that the person opened."""

import os
import subprocess
from typing import Any, Dict


def launch(path: str) -> Dict[str, Any]:
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(path):
        return {"status": "ERROR", "error": f"File not found: {path}"}
    try:
        mode = os.stat(path).st_mode
        if not mode & 0o111:
            os.chmod(path, mode | 0o755)
    except OSError as exc:
        return {"status": "ERROR", "error": f"Could not make the file executable: {exc}"}
    try:
        proc = subprocess.Popen([path], cwd=os.path.dirname(path), stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
    except OSError as exc:
        return {"status": "ERROR", "error": f"Could not start the program: {exc}"}
    return {"status": "STARTED", "pid": proc.pid, "file": path,
            "message": "Linux program started."}
