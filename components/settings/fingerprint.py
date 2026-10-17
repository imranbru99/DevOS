#!/usr/bin/env python3
"""
Fingerprint sign-in for laptops that have a reader.

Uses fprintd (the same stack Ubuntu uses). Enabling login runs
pam-auth-update so the fingerprint can unlock the session. It does not
replace the password: the password still works.
"""

import os
import sys
import json
import shutil
import argparse
import subprocess
from typing import Any, Callable, Dict, List, Optional


PACKAGES = ["fprintd", "libpam-fprintd"]


def _euid() -> int:
    fn = getattr(os, "geteuid", None)
    return fn() if fn else 0


class Fingerprint:
    def __init__(self, runner: Optional[Callable] = None, euid: Optional[int] = None,
                 which: Optional[Callable[[str], str]] = None):
        self.runner = runner or self._default_run
        self._euid = _euid() if euid is None else euid
        self._which = which or (lambda name: shutil.which(name) or "")

    @staticmethod
    def _default_run(argv: List[str], timeout: int = 120):
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
            return proc.returncode, proc.stdout or "", proc.stderr or ""
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, "", str(exc)

    def status(self) -> Dict[str, Any]:
        enrolled = ""
        if self._which("fprintd-list"):
            code, out, _err = self.runner(["fprintd-list", os.environ.get("USER", "")])
            if code == 0:
                enrolled = out.strip()
        return {
            "installed": bool(self._which("fprintd-enroll")),
            "packages": PACKAGES,
            "enrolled": enrolled,
            "message": "Fingerprint sign-in is available." if self._which("fprintd-enroll")
            else "Install fingerprint sign-in from DevOS Features (fprintd).",
        }

    def enroll(self, user: str = "") -> Dict[str, Any]:
        if not self._which("fprintd-enroll"):
            return {"status": "NEEDS_PACKAGE", "packages": PACKAGES,
                    "message": "The fingerprint service is not installed."}
        who = user or os.environ.get("USER", "")
        code, out, err = self.runner(["fprintd-enroll", who] if who else ["fprintd-enroll"])
        if code != 0:
            return {"status": "FAILED", "error": (err or out or "The reader did not enroll a finger.").strip()}
        return {"status": "ENROLLED", "message": "Fingerprint saved. Turn on sign-in if you also want it at the lock screen."}

    def enable_login(self) -> Dict[str, Any]:
        if not self._which("pam-auth-update"):
            return {"status": "NEEDS_PACKAGE", "packages": PACKAGES,
                    "message": "libpam-fprintd is not installed, so the lock screen cannot ask for a finger."}
        if self._euid != 0:
            return {
                "status": "NEEDS_ROOT",
                "message": "Turning on fingerprint sign-in changes system login and needs an administrator password.",
                "command": ["pkexec", sys.executable, os.path.abspath(__file__), "enable-login"],
            }
        code, out, err = self.runner(["pam-auth-update", "--enable", "fprintd"])
        if code != 0:
            return {"status": "FAILED", "error": (err or out or "pam-auth-update did not enable fprintd.").strip()}
        return {
            "status": "ENABLED",
            "message": "The lock screen can use the fingerprint. Your password still works if the reader fails.",
        }


def main():
    parser = argparse.ArgumentParser(description="DevOS fingerprint sign-in")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status")
    sub.add_parser("enroll")
    sub.add_parser("enable-login")
    sub.add_parser("gui")
    args = parser.parse_args()
    fp = Fingerprint()
    if args.command == "gui":
        if not shutil.which("kdialog"):
            print(json.dumps(fp.status(), indent=2))
            return
        choice = subprocess.run(
            ["kdialog", "--menu", "Fingerprint sign-in", "status", "Status",
             "enroll", "Save a fingerprint", "enable", "Use it at the lock screen"],
            capture_output=True, text=True)
        if choice.returncode != 0:
            return
        action = {"status": "status", "enroll": "enroll", "enable": "enable-login"}.get(choice.stdout.strip(), "status")
        if action == "enable-login" and _euid() != 0 and shutil.which("pkexec"):
            os.execvp("pkexec", ["pkexec", sys.executable, os.path.abspath(__file__), "enable-login"])
        args.command = action
        fp = Fingerprint()
    if args.command == "enroll":
        res = fp.enroll()
    elif args.command == "enable-login":
        res = fp.enable_login()
        if res.get("status") == "NEEDS_ROOT" and shutil.which("pkexec") and os.environ.get("DEVOS_NO_PKEXEC") != "1":
            os.execvp("pkexec", ["pkexec", sys.executable, os.path.abspath(__file__), "enable-login"])
    else:
        res = fp.status()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res.get("status", "OK") in ("ENROLLED", "ENABLED", "NEEDS_PACKAGE") or "installed" in res else 1)


if __name__ == "__main__":
    main()
