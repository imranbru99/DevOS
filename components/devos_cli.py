#!/usr/bin/env python3
"""
DevOS Master Unified CLI
Dispatcher for all DevOS subsystems:
  devos app       - Universal App Hub (Windows, Linux, Android)
  devos code      - Local Code Agent & repo assistant
  devos serve     - Local server manager (Laragon-style)
  devos ai        - System AI Assistant
  devos win       - WinLayer compatibility manager
  devos android   - Android & Waydroid manager
  devos doctor    - System health, heavy load & storage check
"""

import sys
import os
import subprocess


COMPONENTS_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print("DevOS Unified Command Line Interface")
        print("=====================================")
        print("Usage: devos <subsystem> [arguments...]")
        print("\nSubsystems:")
        print("  app       Manage Windows, Linux, and Android applications")
        print("  code      Local AI code assistant and repository generator")
        print("  serve     Local developer server manager (Caddy, PHP, DB, Redis)")
        print("  ai        System assistant with safe tool calling")
        print("  win       WinLayer prefix manager and compatibility doctor")
        print("  android   Waydroid container manager and APK runner")
        print("  watchdog  System memory pressure and storage audit")
        sys.exit(0)

    sub = sys.argv[1]
    args = sys.argv[2:]

    dispatch_map = {
        "app": os.path.join(COMPONENTS_DIR, "apphub", "hub.py"),
        "code": os.path.join(COMPONENTS_DIR, "code-agent", "code_agent.py"),
        "serve": os.path.join(COMPONENTS_DIR, "devserver", "server_manager.py"),
        "ai": os.path.join(COMPONENTS_DIR, "ai-agent", "agent.py"),
        "win": os.path.join(COMPONENTS_DIR, "winlayer", "prefix_manager.py"),
        "android": os.path.join(COMPONENTS_DIR, "androidlayer", "waydroid_manager.py"),
        "watchdog": os.path.join(COMPONENTS_DIR, "ai-agent", "system_watchdog.py"),
    }

    if sub in dispatch_map:
        target_script = dispatch_map[sub]
        cmd = [sys.executable, target_script] + args
        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            pass
    else:
        print(f"Unknown subsystem '{sub}'. Run 'devos help' for available commands.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
