#!/usr/bin/env python3
"""
DevOS Security - automatic security updates (unattended-upgrades).

Ubuntu 26.04's unattended-upgrades package ships:
  20auto-upgrades       APT::Periodic::Update-Package-Lists "1";
                        APT::Periodic::Unattended-Upgrade "1";   (debconf)
  50unattended-upgrades Allowed-Origins: resolute, resolute-security and the ESM
                        security pockets (resolute-updates commented out).
Our 52devos-unattended sorts after both, so its values win. It clears the
origin list and puts back only the security pockets (plus the release
pocket, which never changes after release but holds dependencies a security
fix may need), and never reboots on its own. apt-daily-upgrade.timer runs it
once a day; when a fix needs a restart, /run/reboot-required appears and
devos-reboot-notify.path tells the signed-in user.

Not covered: Google Chrome and VS Code come from their own repositories and
update through the normal updater (Discover / apt), not this file.
"""

import os
import sys
import json
import shutil
import argparse
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import seccommon as common  # noqa: E402

CONF = "/etc/apt/apt.conf.d/52devos-unattended"
REBOOT_FLAG = "/run/reboot-required"
REBOOT_PKGS = "/run/reboot-required.pkgs"
NOTIFIED_FLAG = common.RUN_DIR + "/reboot-notified"


def unattended_conf(enabled=True):
    flag = "1" if enabled else "0"
    return """// DevOS Security: automatic security updates. Written by
// "devos-security updates on|off"; sorts after 20auto-upgrades and
// 50unattended-upgrades, so these values win.
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "{flag}";
APT::Periodic::AutocleanInterval "7";

// Security pockets only (the release pocket never changes after release
// but carries dependencies a security fix may need).
#clear Unattended-Upgrade::Allowed-Origins;
Unattended-Upgrade::Allowed-Origins {{
        "${{distro_id}}:${{distro_codename}}";
        "${{distro_id}}:${{distro_codename}}-security";
        "${{distro_id}}ESMApps:${{distro_codename}}-apps-security";
        "${{distro_id}}ESM:${{distro_codename}}-infra-security";
}};

// Never restart the PC by itself: DevOS Security tells the user instead.
// 99devos-no-automatic-power repeats this and sorts later, so it still
// wins if this file is rewritten.
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Automatic-Reboot-WithUsers "false";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-New-Unused-Dependencies "true";
// Finish installing before shutdown is not needed: install while running.
Unattended-Upgrade::InstallOnShutdown "false";
""".format(flag=flag)


def parse_enabled(text):
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith('APT::Periodic::Unattended-Upgrade'):
            return '"1"' in line
    return None


def installed():
    return os.path.exists("/usr/bin/unattended-upgrade")


def set_enabled(on, root="/"):
    path = CONF if root == "/" else os.path.join(root, CONF.lstrip("/"))
    common.write_text(path, unattended_conf(on), 0o644)
    if root == "/" and common.which("systemctl"):
        for timer in ("apt-daily.timer", "apt-daily-upgrade.timer"):
            common.run(["systemctl", "enable", "--now", timer], timeout=30)
    return 0


def status():
    text = common.read_text(CONF)
    enabled = parse_enabled(text)
    reboot = os.path.exists(REBOOT_FLAG)
    pkgs = [p for p in (common.read_text(REBOOT_PKGS, "") or "").split() if p]
    return {
        "installed": installed(),
        "configured": text is not None,
        "enabled": bool(enabled) and installed(),
        "timer": common.systemctl_state("apt-daily-upgrade.timer"),
        "reboot_required": reboot,
        "reboot_packages": sorted(set(pkgs))[:10],
    }


def notify_reboot():
    """Root, from devos-reboot-notify.service: once per boot."""
    if not os.path.exists(REBOOT_FLAG) or os.path.exists(NOTIFIED_FLAG):
        return 0
    common.notify_desktop_users("Restart to finish security updates",
                                "Security updates were installed. Restart your PC when you are "
                                "ready. DevOS leaves it running until you do.", icon="system-reboot")
    try:
        os.makedirs(common.RUN_DIR, exist_ok=True)
        open(NOTIFIED_FLAG, "w").close()
    except OSError:
        pass
    return 0


def _default_run(argv, timeout=7200):
    if not argv or shutil.which(argv[0]) is None:
        return 127, "", "not installed"
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)


def snapshot_before_changes(description="Before security updates"):
    """Take a restore point. UNAVAILABLE (not btrfs) does not block updates."""
    settings = os.path.abspath(os.path.join(HERE, "..", "settings"))
    if settings not in sys.path:
        sys.path.insert(0, settings)
    import snapshot_manager
    return snapshot_manager.SnapshotManager().create_restore_point(description)


def upgrade_now(runner=None, snapshot=None):
    """Security updates, then Flatpak updates. Stops if a btrfs snapshot fails."""
    if snapshot is None:
        snapshot = snapshot_before_changes()
    if snapshot.get("status") == "FAILED":
        return {
            "status": "ABORTED",
            "snapshot": snapshot,
            "message": "Update stopped because a restore point could not be created.",
        }
    if snapshot.get("status") == "NEEDS_ROOT":
        return {"status": "NEEDS_ROOT", "snapshot": snapshot,
                "message": snapshot.get("message")}
    run = runner or _default_run
    steps = []
    code, out, err = run(["unattended-upgrade"])
    if code == 127:
        steps.append({"step": "security", "code": 127, "skipped": True})
    elif code != 0:
        steps.append({"step": "security", "code": code, "error": (err or out).strip()[-400:]})
        return {"status": "FAILED", "snapshot": snapshot, "steps": steps,
                "message": "Security updates did not finish. The restore point is still there."}
    else:
        steps.append({"step": "security", "code": 0})
    code, out, err = run(["flatpak", "update", "-y", "--noninteractive"])
    if code == 127:
        steps.append({"step": "flatpak", "code": 127, "skipped": True})
    elif code != 0:
        steps.append({"step": "flatpak", "code": code, "error": (err or out).strip()[-400:]})
        return {"status": "FAILED", "snapshot": snapshot, "steps": steps,
                "message": "App updates did not finish. Security updates were applied. The restore point is still there."}
    else:
        steps.append({"step": "flatpak", "code": 0})
    return {
        "status": "DONE",
        "snapshot": snapshot,
        "steps": steps,
        "message": "Security updates and installed Flatpak apps were checked.",
    }


def main():
    parser = argparse.ArgumentParser(description="DevOS updates")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status")
    sub.add_parser("now", help="Snapshot, then install security and Flatpak updates")
    args = parser.parse_args()
    if args.command == "now":
        res = upgrade_now()
        print(json.dumps(res, indent=2))
        sys.exit(0 if res["status"] == "DONE" else 1)
    print(json.dumps(status(), indent=2))


if __name__ == "__main__":
    main()
