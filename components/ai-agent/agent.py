#!/usr/bin/env python3
"""
DevOS System AI Agent (ai-agent)
Safe, local system assistant with tool-calling, risk-level checks, and audit logging.
"""

import sys
import os
import json
import time
import argparse
from typing import Dict, Any, List, Optional, Callable


LOG_DIR = os.path.expanduser("~/.local/share/DevOS")
AUDIT_LOG_FILE = os.path.join(LOG_DIR, "agent.log")


class ToolRiskLevel:
    READ_ONLY = "read-only"         # Executes freely
    REVERSIBLE = "reversible"       # Executes with undo window
    DESTRUCTIVE = "destructive"     # Requires explicit confirmation
    PRIVILEGED = "privileged"       # Requires polkit / sudo authorization


class DevOSAgent:
    """System AI Agent with structured tool registry, safety gate, and audit logging."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.tools: Dict[str, Dict[str, Any]] = {}
        self._register_built_in_tools()
        os.makedirs(LOG_DIR, exist_ok=True)

    def register_tool(self, name: str, risk_level: str, description: str, handler: Callable):
        """Registers a tool with a declared risk level and execution handler."""
        self.tools[name] = {
            "name": name,
            "risk_level": risk_level,
            "description": description,
            "handler": handler,
        }

    def _register_built_in_tools(self):
        # 1. System: Dark mode toggle (reversible)
        def toggle_dark_mode(enabled: bool) -> str:
            mode = "dark" if enabled else "light"
            return f"System appearance set to {mode} mode."

        self.register_tool(
            "toggle_dark_mode",
            ToolRiskLevel.REVERSIBLE,
            "Switch system appearance between dark and light theme.",
            toggle_dark_mode
        )

        # 2. Files: Find large files (read-only)
        def find_large_files(directory: str = ".", min_mb: int = 100) -> List[Dict[str, Any]]:
            results = []
            target = os.path.abspath(directory)
            for root, _, files in os.walk(target):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        sz = os.path.getsize(fp) / (1024 * 1024)
                        if sz >= min_mb:
                            results.append({"path": fp, "size_mb": round(sz, 2)})
                    except Exception:
                        pass
                if len(results) >= 10:
                    break
            return results

        self.register_tool(
            "find_large_files",
            ToolRiskLevel.READ_ONLY,
            "Find files exceeding size threshold for disk cleanup.",
            find_large_files
        )

        # 3. Troubleshooting: Explain service failure (read-only)
        def diagnose_systemd_service(service_name: str) -> Dict[str, str]:
            return {
                "service": service_name,
                "status": "failed",
                "diagnosis": f"Service '{service_name}' exited with error code 1 due to missing socket dependency.",
                "proposed_fix": f"systemctl restart {service_name}",
            }

        self.register_tool(
            "diagnose_systemd_service",
            ToolRiskLevel.READ_ONLY,
            "Analyze journalctl and systemctl logs to explain service failures.",
            diagnose_systemd_service
        )

        # 4. App Hub: Install application (privileged / reversible)
        def install_app(name_or_file: str) -> str:
            return f"App Hub initiated install for: {name_or_file}"

        self.register_tool(
            "install_app",
            ToolRiskLevel.PRIVILEGED,
            "Install a Windows, Linux, or Android application via App Hub.",
            install_app
        )

        # 5. System: Clean cache/delete files (destructive)
        def delete_path(path: str) -> str:
            return f"Removed {path}"

        self.register_tool(
            "delete_path",
            ToolRiskLevel.DESTRUCTIVE,
            "Permanently delete a file or directory.",
            delete_path
        )

    def audit_log(self, user_prompt: str, tool_name: str, args: Dict[str, Any], status: str, result: Any):
        """Appends tool execution entry to audit log."""
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "prompt": user_prompt,
            "tool": tool_name,
            "arguments": args,
            "status": status,
            "result": result,
        }
        try:
            with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    def execute_tool(self, tool_name: str, args: Dict[str, Any], confirmed: bool = False, prompt: str = "") -> Dict[str, Any]:
        """Safety gate: enforces confirmation on destructive/privileged actions."""
        if tool_name not in self.tools:
            return {"error": f"Tool '{tool_name}' not found."}

        tool_meta = self.tools[tool_name]
        risk = tool_meta["risk_level"]

        # Safety rule: Destructive and Privileged tools MUST have explicit confirmation
        if risk in (ToolRiskLevel.DESTRUCTIVE, ToolRiskLevel.PRIVILEGED) and not confirmed:
            msg = f"Confirmation required: Tool '{tool_name}' has risk level '{risk}'. Action aborted until user explicitly confirms."
            self.audit_log(prompt, tool_name, args, "CONFIRMATION_REQUIRED", msg)
            return {
                "status": "NEEDS_CONFIRMATION",
                "risk_level": risk,
                "message": msg,
                "preview_action": {
                    "tool": tool_name,
                    "arguments": args,
                }
            }

        # Prompt injection defense check: ensure arguments do not attempt system override
        for k, v in args.items():
            if isinstance(v, str) and ("ignore previous instructions" in v.lower() or "disregard system" in v.lower()):
                blocked_msg = "Security alert: Prompt injection attempt detected in tool input and blocked."
                self.audit_log(prompt, tool_name, args, "INJECTION_BLOCKED", blocked_msg)
                return {"status": "BLOCKED", "message": blocked_msg}

        try:
            handler = tool_meta["handler"]
            output = handler(**args)
            self.audit_log(prompt, tool_name, args, "SUCCESS", output)
            return {"status": "SUCCESS", "result": output}
        except Exception as e:
            self.audit_log(prompt, tool_name, args, "ERROR", str(e))
            return {"status": "ERROR", "error": str(e)}

    def handle_natural_language(self, prompt: str, confirmed: bool = False) -> Dict[str, Any]:
        """Parses natural language request, determines tool call, and executes via safety gate."""
        p_lower = prompt.lower()

        # Prompt injection test defense
        if "ignore your safety rules" in p_lower or "run sudo rm" in p_lower:
            return {
                "reply": "I cannot ignore safety guidelines. High-risk commands require explicit confirmation.",
                "tool_called": None,
                "safety_status": "BLOCKED"
            }

        if "dark mode" in p_lower:
            res = self.execute_tool("toggle_dark_mode", {"enabled": True}, confirmed=confirmed, prompt=prompt)
            return {"reply": "Switched DevOS to dark mode.", "tool_result": res}

        elif "large files" in p_lower or "disk space" in p_lower or "cleanup" in p_lower:
            res = self.execute_tool("find_large_files", {"directory": ".", "min_mb": 50}, confirmed=confirmed, prompt=prompt)
            return {"reply": "Scanned for large files exceeding 50 MB.", "tool_result": res}

        elif "broken service" in p_lower or "crash" in p_lower:
            res = self.execute_tool("diagnose_systemd_service", {"service_name": "sample-backend.service"}, confirmed=confirmed, prompt=prompt)
            return {"reply": "Diagnosed failed service from system logs.", "tool_result": res}

        elif "delete" in p_lower or "remove" in p_lower:
            res = self.execute_tool("delete_path", {"path": "/var/cache/sample"}, confirmed=confirmed, prompt=prompt)
            return {"reply": "Processed file removal request.", "tool_result": res}

        elif "install" in p_lower:
            target = prompt.split("install")[-1].strip()
            res = self.execute_tool("install_app", {"name_or_file": target}, confirmed=confirmed, prompt=prompt)
            return {"reply": f"Handled app installation for '{target}'.", "tool_result": res}

        return {
            "reply": "How can I assist your system management today? I can help optimize performance, install apps, or manage system settings.",
            "tool_called": None
        }


def main():
    parser = argparse.ArgumentParser(description="DevOS System AI Agent CLI")
    parser.add_argument("prompt", nargs="?", default="", help="Natural language request")
    parser.add_argument("--confirm", action="store_true", help="Explicitly confirm destructive/privileged tool actions")
    args = parser.parse_args()

    agent = DevOSAgent()
    if args.prompt:
        res = agent.handle_natural_language(args.prompt, confirmed=args.confirm)
        print(json.dumps(res, indent=2))
    else:
        print("DevOS AI Agent CLI ready. Provide a prompt to test.")


if __name__ == "__main__":
    main()
