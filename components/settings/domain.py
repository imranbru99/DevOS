#!/usr/bin/env python3
"""
Join a workplace Active Directory domain (realmd / sssd).

DevOS does not join a domain by itself. This runs `realm join` when the
packages are installed and the administrator asks for it.
"""

import os
import sys
import json
import shutil
import argparse
import subprocess
from typing import Any, Callable, Dict, List, Optional


PACKAGES = ["realmd", "sssd", "adcli", "oddjob", "oddjob-mkhomedir", "packagekit"]


def _euid() -> int:
    fn = getattr(os, "geteuid", None)
    return fn() if fn else 0


class DomainJoin:
    def __init__(self, runner: Optional[Callable] = None, euid: Optional[int] = None,
                 which: Optional[Callable[[str], str]] = None):
        self.runner = runner or self._default_run
        self._euid = _euid() if euid is None else euid
        self._which = which or (lambda name: shutil.which(name) or "")

    @staticmethod
    def _default_run(argv: List[str], timeout: int = 300):
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
            return proc.returncode, proc.stdout or "", proc.stderr or ""
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, "", str(exc)

    def status(self) -> Dict[str, Any]:
        joined = ""
        if self._which("realm"):
            code, out, _err = self.runner(["realm", "list"])
            if code == 0:
                joined = out.strip()
        return {
            "installed": bool(self._which("realm")),
            "packages": PACKAGES,
            "joined": joined,
        }

    def join(self, domain: str, user: str) -> Dict[str, Any]:
        domain = (domain or "").strip()
        user = (user or "").strip()
        if not domain or not user or any(c in domain for c in " /\\"):
            return {"status": "ERROR", "error": "Pass a domain name and the account that may join PCs."}
        if not self._which("realm"):
            return {"status": "NEEDS_PACKAGE", "packages": PACKAGES,
                    "message": "Install “Company network (Active Directory)” in DevOS Features."}
        if self._euid != 0:
            return {
                "status": "NEEDS_ROOT",
                "message": "Joining a domain changes system login and needs an administrator password.",
                "command": ["pkexec", sys.executable, os.path.abspath(__file__), "join", domain, user],
            }
        code, out, err = self.runner(["realm", "join", "--user", user, domain])
        if code != 0:
            return {"status": "FAILED", "error": (err or out or "realm join failed").strip()}
        return {"status": "JOINED", "domain": domain,
                "message": f"This PC joined {domain}. Sign out and use your work account."}


def main():
    parser = argparse.ArgumentParser(description="DevOS Active Directory join")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status")
    join_p = sub.add_parser("join")
    join_p.add_argument("domain")
    join_p.add_argument("user")
    args = parser.parse_args()
    dom = DomainJoin()
    if args.command == "join":
        res = dom.join(args.domain, args.user)
        if res.get("status") == "NEEDS_ROOT" and shutil.which("pkexec") and os.environ.get("DEVOS_NO_PKEXEC") != "1":
            os.execvp("pkexec", ["pkexec", sys.executable, os.path.abspath(__file__), "join", args.domain, args.user])
    else:
        res = dom.status()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res.get("status", "OK") in ("JOINED", "NEEDS_PACKAGE") or "installed" in res else 1)


if __name__ == "__main__":
    main()
