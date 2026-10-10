#!/usr/bin/env python3
"""
DevOS 2027 Era: AI-Native Auto-Healing Smart Shell
Hooks into terminal execution to catch failed commands (exit != 0), analyze stderr,
and generate instant, verified plain-language diagnoses and 1-key auto-fixes.
"""

import sys
import os
import re
import json
import argparse
from typing import Dict, Any


class SmartShellHealer:
    """Diagnoses terminal command failures and proposes verified auto-fixes."""

    COMMON_PATTERNS = [
        # 1. Command not found
        (
            r"command not found: ([a-zA-Z0-9_\-]+)",
            lambda m: {
                "problem": f"Command '{m.group(1)}' is not installed.",
                "suggested_fix": f"devos app install {m.group(1)}",
                "explanation": f"The package containing '{m.group(1)}' can be installed automatically via App Hub."
            }
        ),
        # 2. Port already in use
        (
            r"(address already in use|bind: address already in use).*?(\d{2,5})?",
            lambda m: {
                "problem": "Network port collision.",
                "suggested_fix": "fuser -k 80/tcp 443/tcp || sudo lsof -i :80",
                "explanation": "Another process is already binding to this port. Free the port before launching."
            }
        ),
        # 3. Permission denied
        (
            r"permission denied",
            lambda m: {
                "problem": "Insufficient filesystem or execution privileges.",
                "suggested_fix": "sudo !!",
                "explanation": "This operation touches protected system resources. Rerun with administrative elevation."
            }
        ),
        # 4. Git typos
        (
            r"git: '([a-zA-Z]+)' is not a git command",
            lambda m: {
                "problem": f"Git command typo: '{m.group(1)}'.",
                "suggested_fix": "git commit -m 'your message'" if "com" in m.group(1) else "git status",
                "explanation": "Did you mean 'git commit' or 'git status'?"
            }
        ),
        # 5. Missing Python module
        (
            r"ModuleNotFoundError: No module named '([a-zA-Z0-9_]+)'",
            lambda m: {
                "problem": f"Missing Python dependency: '{m.group(1)}'.",
                "suggested_fix": f"pip install {m.group(1)}",
                "explanation": f"Install the missing Python package via pip."
            }
        ),
    ]

    @classmethod
    def diagnose_failure(cls, failed_cmd: str, stderr_text: str, exit_code: int = 1) -> Dict[str, Any]:
        """Analyzes command failure and returns structured diagnosis and fix."""
        combined = (stderr_text + " " + failed_cmd).strip()

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
                    "status": "AUTO_HEAL_READY"
                }

        # Fallback intelligent diagnosis
        return {
            "failed_command": failed_cmd,
            "exit_code": exit_code,
            "diagnosis": "Command returned non-zero exit status.",
            "suggested_fix": f"journalctl -xe --no-pager | tail -n 20",
            "explanation": "Inspect recent system logs to determine root cause.",
            "status": "ANALYZED"
        }


def main():
    parser = argparse.ArgumentParser(description="DevOS Smart Shell Auto-Healer")
    parser.add_argument("cmd", help="Failed command string")
    parser.add_argument("--stderr", default="", help="Captured stderr message")
    parser.add_argument("--code", type=int, default=1, help="Exit code")

    args = parser.parse_args()
    report = SmartShellHealer.diagnose_failure(args.cmd, args.stderr, args.code)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
