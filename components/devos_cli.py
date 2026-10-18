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
  devos link      - Phone Link: control this PC from a phone
  devos share     - Make a local app reachable from the internet
  devos backup    - Optional Google Drive / OneDrive backup
  devos models    - Choose DevOS AI models and share the local AI API
  devos auto      - Local-model automations (commit message, review, explain)
  devos agents    - One browser per AI agent, as many as this PC can keep smooth
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
        print("  dashboard Open Luxury System Dashboard & PIN/Security Hub")
        print("  setup     Launch Interactive First-Boot Configuration Wizard")
        print("  app       Manage Windows, Linux, and Android applications")
        print("  code      DevOS AI Code Agent: local coding assistant and autonomous agent")
        print("  serve     Local developer server manager (Caddy, PHP, DB, Redis)")
        print("  ai        System assistant with safe tool calling")
        print("  win       WinLayer prefix manager and compatibility doctor")
        print("  android   Waydroid container manager and APK runner")
        print("  watchdog  System memory pressure and storage audit")
        print("  net       Wi-Fi and Ethernet connection manager")
        print("  sound     PipeWire audio and volume controller")
        print("  driver    GPU, Wi-Fi, Bluetooth, and printer drivers")
        print("  disk      Storage devices, MBR/GPT partition tables & formatting")
        print("  link      Phone Link: control and manage this PC from your phone")
        print("  share     Make a local app public: devos share start 3000")
        print("  backup    Optional Google Drive / OneDrive backup of your folders")
        print("  models    DevOS AI models for this PC, and the local AI API (devos models api)")
        print("  auto      Local AI automations: commit, review, explain, summarize, hook")
        print("  agents    One browser per AI agent (devos agents open research --url https://...)")
        print("  features  Add or remove apps and features (Office, browsers, games…)")
        print("  restore   btrfs restore points (create, list, rollback)")
        print("  vault     Encrypt a folder after install")
        print("  finger    Fingerprint sign-in")
        print("  domain    Join an Active Directory domain")
        print("  updates   Security updates and Flatpak updates, after a restore point")
        print("  task      Task Manager: processes, performance, startup apps, services")
        sys.exit(0)

    sub = sys.argv[1]
    args = sys.argv[2:]

    hardware_script = os.path.join(COMPONENTS_DIR, "settings", "hardware_manager.py")
    dashboard_script = os.path.join(COMPONENTS_DIR, "dashboard", "dashboard_server.py")
    disk_script = os.path.join(COMPONENTS_DIR, "settings", "disk_manager.py")

    dispatch_map = {
        "dashboard": dashboard_script,
        "setup": dashboard_script,
        "app": os.path.join(COMPONENTS_DIR, "apphub", "hub.py"),
        "code": os.path.join(COMPONENTS_DIR, "code-agent", "code_agent.py"),
        "code-agent": os.path.join(COMPONENTS_DIR, "code-agent", "code_agent.py"),
        "agent": os.path.join(COMPONENTS_DIR, "code-agent", "code_agent.py"),
        "serve": os.path.join(COMPONENTS_DIR, "devserver", "server_manager.py"),
        "ai": os.path.join(COMPONENTS_DIR, "ai-agent", "agent.py"),
        "win": os.path.join(COMPONENTS_DIR, "winlayer", "prefix_manager.py"),
        "android": os.path.join(COMPONENTS_DIR, "androidlayer", "waydroid_manager.py"),
        "watchdog": os.path.join(COMPONENTS_DIR, "ai-agent", "system_watchdog.py"),
        "net": hardware_script,
        "sound": hardware_script,
        "driver": hardware_script,
        "disk": disk_script,
        "storage": disk_script,
        "link": os.path.join(COMPONENTS_DIR, "phonelink", "phonelink.py"),
        "phone": os.path.join(COMPONENTS_DIR, "phonelink", "phonelink.py"),
        "share": os.path.join(COMPONENTS_DIR, "share", "share.py"),
        "backup": os.path.join(COMPONENTS_DIR, "backup", "cloud_backup.py"),
        "models": os.path.join(COMPONENTS_DIR, "ai-core", "models_cli.py"),
        "auto": os.path.join(COMPONENTS_DIR, "ai-core", "automate.py"),
        "agents": os.path.join(COMPONENTS_DIR, "ai-agent", "agent_browser.py"),
        "features": os.path.join(COMPONENTS_DIR, "features", "features_cli.py"),
        "restore": os.path.join(COMPONENTS_DIR, "settings", "snapshot_manager.py"),
        "vault": os.path.join(COMPONENTS_DIR, "settings", "vault.py"),
        "finger": os.path.join(COMPONENTS_DIR, "settings", "fingerprint.py"),
        "fingerprint": os.path.join(COMPONENTS_DIR, "settings", "fingerprint.py"),
        "domain": os.path.join(COMPONENTS_DIR, "settings", "domain.py"),
        "updates": os.path.join(COMPONENTS_DIR, "security", "updates.py"),
        "task": os.path.join(COMPONENTS_DIR, "taskman", "taskman.py"),
        "tasks": os.path.join(COMPONENTS_DIR, "taskman", "taskman.py"),
    }

    if sub == "setup" and "--first-boot" not in args:
        args.append("--first-boot")

    # Normalize subcommands for hardware manager
    if sub == "net" and not args:
        args = ["net-status"]
    elif sub == "sound" and not args:
        args = ["sound-status"]
    elif sub == "driver" and not args:
        args = ["driver-status"]
    elif sub in ("disk", "storage") and "--gui" in args:
        disk_script = os.path.join(COMPONENTS_DIR, "settings", "disk_doctor_gui.py")
        args = [a for a in args if a != "--gui"]
        dispatch_map["disk"] = disk_script
        dispatch_map["storage"] = disk_script

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
