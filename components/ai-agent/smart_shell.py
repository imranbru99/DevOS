#!/usr/bin/env python3
"""
DevOS Smart Shell — diagnose failed commands and suggest verified fixes.

Usage:
  devos heal --stderr '...' --code 127 -- my-command args
  echo "$errmsg" | devos heal --stdin -- last-command

Optional shell hook (install once):
  echo 'eval "$(devos heal --hook)"' >> ~/.bashrc
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple


Pattern = Tuple[str, Any]


class SmartShellHealer:
    """Diagnoses terminal command failures and proposes verified auto-fixes."""

    COMMON_PATTERNS: List[Pattern] = [
        (
            r"command not found:?\s*([a-zA-Z0-9_\-\.]+)",
            lambda m: {
                "problem": f"Command '{m.group(1)}' is not installed.",
                "suggested_fix": f"devos app search {m.group(1)} || sudo apt install {m.group(1)}",
                "explanation": "Search DevOS Apps / apt for the missing command.",
            },
        ),
        (
            r"(address already in use|bind: address already in use)",
            lambda m: {
                "problem": "Network port collision.",
                "suggested_fix": "ss -ltnp | head -40",
                "explanation": "Another process is already binding this port. Free it before launching.",
            },
        ),
        (
            r"permission denied",
            lambda m: {
                "problem": "Insufficient privileges.",
                "suggested_fix": "sudo !!",
                "explanation": "Retry with administrator elevation when the path is trusted.",
            },
        ),
        (
            r"git: '([a-zA-Z]+)' is not a git command",
            lambda m: {
                "problem": f"Git command typo: '{m.group(1)}'.",
                "suggested_fix": "git status",
                "explanation": "Check `git help -a` for the intended subcommand.",
            },
        ),
        (
            r"ModuleNotFoundError: No module named '([a-zA-Z0-9_\.]+)'",
            lambda m: {
                "problem": f"Missing Python module: '{m.group(1)}'.",
                "suggested_fix": f"pip install {m.group(1).split('.')[0]}",
                "explanation": "Install into the active venv when possible.",
            },
        ),
        (
            r"E: Unable to locate package ([a-zA-Z0-9\.\-\+]+)",
            lambda m: {
                "problem": f"APT package not found: '{m.group(1)}'.",
                "suggested_fix": f"devos app search {m.group(1)}",
                "explanation": "Try Flatpak/native catalog via DevOS Apps.",
            },
        ),
        (
            r"docker: command not found|podman: command not found",
            lambda m: {
                "problem": "Container engine missing.",
                "suggested_fix": "sudo apt install podman podman-compose",
                "explanation": "DevOS uses Podman as the Docker-compatible engine.",
            },
        ),
        (
            r"Could not resolve host|Temporary failure in name resolution",
            lambda m: {
                "problem": "DNS / network name resolution failed.",
                "suggested_fix": "nmcli networking on; nmcli general status",
                "explanation": "Check Wi-Fi/Ethernet or Broadband Connection for PPPoE.",
            },
        ),
        (
            r"snap\b.*is not available|unsupported|blocked",
            lambda m: {
                "problem": "Snap packages are not used on DevOS.",
                "suggested_fix": "devos app search <name>",
                "explanation": "Prefer apt, Flatpak, or DevOS native installers.",
            },
        ),
    ]

    @classmethod
    def diagnose_failure(cls, failed_cmd: str, stderr_text: str, exit_code: int = 1) -> Dict[str, Any]:
        combined = f"{stderr_text}\n{failed_cmd}".strip()
        for pattern, handler in cls.COMMON_PATTERNS:
            match = re.search(pattern, combined, re.IGNORECASE)
            if match:
                res = handler(match)
                return {
                    "failed_command": failed_cmd,
                    "exit_code": exit_code,
                    "diagnosis": res["problem"],
                    "suggested_fix": res["suggested_fix"],
                    "explanation": res["explanation"],
                    "status": "AUTO_HEAL_READY",
                }
        return {
            "failed_command": failed_cmd,
            "exit_code": exit_code,
            "diagnosis": "Command returned a non-zero exit status.",
            "suggested_fix": "journalctl --user -xe --no-pager | tail -n 30",
            "explanation": "Inspect recent logs, then retry or ask DevOS AI.",
            "status": "ANALYZED",
        }


def bash_hook() -> str:
    """Print a bash snippet that offers heal hints after failures."""
    healer = os.path.abspath(__file__)
    return f"""
# DevOS Smart Shell (optional). Disable: unset PROMPT_COMMAND / remove this block.
__devos_smart_shell() {{
  local ec=$?
  [ "$ec" -eq 0 ] && return
  [ -n "${{DEVOS_SMART_SHELL_OFF:-}}" ] && return
  local cmd
  cmd=$(history 1 | sed 's/^[ ]*[0-9]*[ ]*//')
  [ -z "$cmd" ] && return
  python3 "{healer}" --quiet --code "$ec" -- "$cmd" 2>/dev/null || true
}}
case ";${{PROMPT_COMMAND:-}};" in
  *__devos_smart_shell*) ;;
  *) PROMPT_COMMAND="__devos_smart_shell${{PROMPT_COMMAND:+;$PROMPT_COMMAND}}" ;;
esac
""".strip()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="DevOS Smart Shell healer")
    parser.add_argument("cmd", nargs=argparse.REMAINDER, help="Failed command (after --)")
    parser.add_argument("--stderr", default="", help="Captured stderr")
    parser.add_argument("--stdin", action="store_true", help="Read stderr from stdin")
    parser.add_argument("--code", type=int, default=1, help="Exit code")
    parser.add_argument("--hook", action="store_true", help="Print bash PROMPT_COMMAND hook")
    parser.add_argument("--quiet", action="store_true", help="One-line human hint")
    parser.add_argument("--json", action="store_true", help="Force JSON output")
    args = parser.parse_args(argv)

    if args.hook:
        print(bash_hook())
        return 0

    cmd_parts = list(args.cmd or [])
    if cmd_parts and cmd_parts[0] == "--":
        cmd_parts = cmd_parts[1:]
    failed_cmd = " ".join(cmd_parts).strip() or "(unknown)"
    stderr = args.stderr
    if args.stdin:
        stderr = sys.stdin.read()

    report = SmartShellHealer.diagnose_failure(failed_cmd, stderr, args.code)
    if args.quiet and not args.json:
        print(f"DevOS heal: {report['diagnosis']} → {report['suggested_fix']}")
        return 0
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
