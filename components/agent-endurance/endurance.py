#!/usr/bin/env python3
"""Keep DevOS awake and AI-warm for multi-day coding-agent runs (24–72h).

Detects local coding agents (Cursor Agent, Claude Code, Codex, Aider, DevOS
Code Agent, etc.) or an explicit sticky enable, then:
  * holds a systemd sleep/idle/lid inhibit so overnight runs are not suspended
  * writes a runtime marker so local AI keeps the model warm for hours
  * prefers performance CPU policy while on AC power
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

APP = "devos-agent-endurance"
POLL_SECONDS = 20
# After the last agent process exits, keep the inhibit a bit longer so
# restart loops / brief gaps do not drop overnight sessions.
HOLD_AFTER_EXIT_SECONDS = 15 * 60
# Manual sticky enable lasts until the user turns it off (multi-day runs).
STICKY_NAME = "sticky"

AGENT_NAMES = (
    "cursor-agent",
    "cursor",
    "agent",
    "claude",
    "claude-code",
    "codex",
    "aider",
    "goose",
    "amp",
    "openhands",
    "devos-ai-code-agent",
    "devos-code-agent",
    "devos-ai-pipeline",
    "devos-antigravity",
    "code_agent.py",
    "agent_gui.py",
    "pipeline_gui.py",
    "pipeline_worker.py",
)

AGENT_CMDLINE_HINTS = (
    "cursor-agent",
    "claude-code",
    "@anthropic-ai/claude-code",
    "openai codex",
    "openai-codex",
    "aider",
    "devos/components/code-agent",
    "devos/components/ai-agent",
    "code_agent.py",
    "agent_gui.py",
    "pipeline_worker.py",
    "antigravity",
)


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    path = Path(base) / "devos"
    path.mkdir(parents=True, exist_ok=True)
    return path


def marker_path() -> Path:
    return runtime_dir() / "agent-endurance.json"


def sticky_path() -> Path:
    return Path(os.path.expanduser("~/.config/devos/agent-endurance.sticky"))


def write_marker(active: bool, reason: str, agents: list[str]) -> None:
    payload = {
        "active": bool(active),
        "reason": reason,
        "agents": agents,
        "updated": int(time.time()),
        "idle_timeout_seconds": 14400 if active else 0,
    }
    path = marker_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_marker() -> dict:
    path = marker_path()
    if not path.is_file():
        return {"active": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"active": False}
    except (OSError, json.JSONDecodeError):
        return {"active": False}


def is_active() -> bool:
    data = read_marker()
    if not data.get("active"):
        return False
    # Stale marker (daemon died) → treat as inactive after 3 minutes.
    updated = int(data.get("updated") or 0)
    return (time.time() - updated) < 180


def sticky_enabled() -> bool:
    return sticky_path().is_file()


def set_sticky(enabled: bool) -> None:
    path = sticky_path()
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"enabled {int(time.time())}\n", encoding="utf-8")
    elif path.exists():
        path.unlink()


def _cmdline(pid: str) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", "replace").lower()


def _comm(pid: str) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip().lower()
    except OSError:
        return ""


def discover_agents() -> list[str]:
    found: list[str] = []
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return found
    for entry in entries:
        if not entry.name.isdigit():
            continue
        name = _comm(entry.name)
        cmd = _cmdline(entry.name)
        hit = False
        if name == "cursor":
            # Cursor IDE / Electron — treat as a long-run coding host.
            hit = True
        elif name == "agent":
            hit = ("cursor" in cmd or "cursor-agent" in cmd or "devos" in cmd
                   or any(h in cmd for h in AGENT_CMDLINE_HINTS))
        elif name in AGENT_NAMES:
            hit = True
        if not hit:
            hit = any(h in cmd for h in AGENT_CMDLINE_HINTS)
        if hit:
            label = name or entry.name
            if label not in found:
                found.append(label)
    return found


def set_performance_hint(on_ac: bool) -> None:
    if not on_ac:
        return
    try:
        subprocess.run(
            ["powerprofilesctl", "set", "performance"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def on_ac_power() -> bool:
    power = Path("/sys/class/power_supply")
    if not power.is_dir():
        return True
    saw_battery = False
    for entry in power.iterdir():
        try:
            ptype = (entry / "type").read_text(encoding="utf-8").strip().lower()
        except OSError:
            continue
        if ptype == "mains":
            try:
                online = (entry / "online").read_text(encoding="utf-8").strip()
                if online == "1":
                    return True
            except OSError:
                pass
        elif ptype == "battery":
            saw_battery = True
            try:
                status = (entry / "status").read_text(encoding="utf-8").strip().lower()
                if status in ("charging", "full"):
                    return True
            except OSError:
                pass
    return not saw_battery


def start_inhibit() -> subprocess.Popen | None:
    """Block sleep / idle / lid-triggered sleep for the life of this child."""
    try:
        return subprocess.Popen(
            [
                "systemd-inhibit",
                "--what=sleep:idle:handle-lid-switch",
                "--who=DevOS Agent Endurance",
                "--why=Multi-day AI coding agent run",
                "--mode=block",
                "sleep",
                "infinity",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        print(f"[{APP}] inhibit unavailable: {exc}", file=sys.stderr)
        return None


def stop_inhibit(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_daemon() -> int:
    print(f"[{APP}] watching for multi-day coding agents")
    inhibit: subprocess.Popen | None = None
    last_seen = 0.0
    stopping = False

    def _stop(signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while not stopping:
        agents = discover_agents()
        sticky = sticky_enabled()
        want = bool(agents) or sticky
        if want:
            last_seen = time.time()
        elif last_seen and (time.time() - last_seen) < HOLD_AFTER_EXIT_SECONDS:
            want = True
            agents = agents or ["hold-after-exit"]

        if want:
            reason = "sticky" if sticky and not agents else ("agents:" + ",".join(agents[:6]))
            write_marker(True, reason, agents)
            if inhibit is None or inhibit.poll() is not None:
                inhibit = start_inhibit()
            set_performance_hint(on_ac_power())
        else:
            write_marker(False, "idle", [])
            stop_inhibit(inhibit)
            inhibit = None
            last_seen = 0.0

        for _ in range(POLL_SECONDS):
            if stopping:
                break
            time.sleep(1)

    write_marker(False, "stopped", [])
    stop_inhibit(inhibit)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DevOS multi-day AI coding agent endurance")
    parser.add_argument("command", nargs="?", default="status",
                        choices=("status", "daemon", "enable", "disable", "on", "off"))
    args = parser.parse_args(argv)

    cmd = args.command
    if cmd == "daemon":
        return run_daemon()
    if cmd in ("enable", "on"):
        set_sticky(True)
        write_marker(True, STICKY_NAME, [STICKY_NAME])
        print("Agent endurance ON — PC will not sleep for multi-day AI coding runs.")
        print("Run: systemctl --user restart devos-agent-endurance.service")
        return 0
    if cmd in ("disable", "off"):
        set_sticky(False)
        write_marker(False, "disabled", [])
        print("Agent endurance OFF.")
        return 0

    data = read_marker()
    print(json.dumps({
        "active": is_active(),
        "sticky": sticky_enabled(),
        "agents": discover_agents(),
        "marker": data,
        "on_ac": on_ac_power(),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
