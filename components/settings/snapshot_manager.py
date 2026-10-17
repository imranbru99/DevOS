#!/usr/bin/env python3
"""
DevOS restore points.

Creates a real btrfs snapshot (Snapper when it is configured, otherwise a
read-only snapshot under /.snapshots) and can copy one back. A JSON file is
only a cache of successful snapshots. Nothing is reported as created unless
the snapshot command exits 0.
"""

import os
import sys
import time
import shutil
import argparse
import subprocess
from typing import Any, Callable, Dict, List, Optional


def _euid() -> int:
    fn = getattr(os, "geteuid", None)
    return fn() if fn else 0


EXCLUDES = (
    "/.snapshots", "/home", "/dev", "/proc", "/sys", "/run", "/tmp",
    "/mnt", "/media", "/var/log", "/var/cache", "/boot/efi",
)


def parse_snapper_list(text: str) -> List[Dict[str, Any]]:
    """Turn `snapper list` table output into restore-point records."""
    points = []
    for line in (text or "").splitlines():
        if "|" not in line or line.strip().startswith("#") or set(line.strip()) <= set("+-| "):
            continue
        cols = [c.strip() for c in line.split("|")]
        if not cols or not cols[0].isdigit():
            continue
        # number, type, pre, date, user, cleanup, description, userdata
        points.append({
            "id": int(cols[0]),
            "timestamp": cols[3] if len(cols) > 3 else "",
            "description": cols[6] if len(cols) > 6 else "",
            "backend": "snapper",
            "path": f"/.snapshots/{cols[0]}/snapshot",
        })
    return points


class SnapshotManager:
    """Creates and rolls back btrfs restore points. Needs root to change the disk."""

    def __init__(self, runner: Optional[Callable] = None, euid: Optional[int] = None,
                 isdir: Optional[Callable[[str], bool]] = None, fstype: Optional[str] = None,
                 tools: Optional[Dict[str, bool]] = None):
        self.runner = runner or self._default_run
        self._euid = _euid() if euid is None else euid
        self._isdir = isdir or os.path.isdir
        self._fstype_override = fstype
        self._tools = tools

    @staticmethod
    def _default_run(argv: List[str], timeout: int = 3600):
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
            return proc.returncode, proc.stdout or "", proc.stderr or ""
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, "", str(exc)

    def _has(self, name: str) -> bool:
        if self._tools is not None:
            return bool(self._tools.get(name))
        return shutil.which(name) is not None

    def filesystem(self) -> str:
        if self._fstype_override is not None:
            return self._fstype_override
        code, out, _err = self.runner(["findmnt", "-n", "-o", "FSTYPE", "/"])
        if code != 0:
            return ""
        return (out or "").strip().splitlines()[0].strip() if out.strip() else ""

    def _needs_root(self, description: str, command: str, snapshot_id: str = "") -> Dict[str, Any]:
        argv = [sys.executable, os.path.abspath(__file__), command]
        if command == "create":
            argv.append(description)
        elif command == "rollback":
            argv.append(str(snapshot_id))
        return {
            "status": "NEEDS_ROOT",
            "message": "Restore points change the disk, so DevOS asks for an administrator password.",
            "command": ["pkexec"] + argv,
        }

    def create_restore_point(self, description: str = "Manual Restore Point") -> Dict[str, Any]:
        description = " ".join((description or "Manual Restore Point").split())[:80]
        kind = self.filesystem()
        if kind != "btrfs":
            return {
                "status": "UNAVAILABLE",
                "backend": None,
                "message": "This disk is not btrfs, so a DevOS restore point cannot be created. "
                           "Timeshift (DevOS Features) can snapshot other disks.",
            }
        if self._euid != 0:
            return self._needs_root(description, "create")
        if self._has("snapper"):
            code, out, err = self.runner(
                ["snapper", "-c", "root", "create", "--description", description,
                 "--cleanup-algorithm", "number"])
            if code == 0:
                _lc, listing, _le = self.runner(["snapper", "-c", "root", "list"])
                points = parse_snapper_list(listing)
                snap_id = points[-1]["id"] if points else 0
                return {
                    "status": "CREATED",
                    "id": snap_id,
                    "description": description,
                    "backend": "snapper",
                    "path": f"/.snapshots/{snap_id}/snapshot" if snap_id else "/.snapshots",
                    "message": f"Restore point '{description}' is on the disk.",
                }
            snapper_error = (err or out or "snapper create failed").strip()
        else:
            snapper_error = ""
        if not self._has("btrfs"):
            return {"status": "FAILED", "error": snapper_error or "btrfs and snapper are not installed."}
        snap_id = int(time.time())
        dest = f"/.snapshots/devos-{snap_id}"
        code, out, err = self.runner(["btrfs", "subvolume", "snapshot", "-r", "/", dest])
        if code != 0:
            detail = (err or out or "btrfs snapshot failed").strip()
            if snapper_error:
                detail = snapper_error + " " + detail
            return {"status": "FAILED", "error": detail}
        return {
            "status": "CREATED",
            "id": snap_id,
            "description": description,
            "backend": "btrfs",
            "path": dest,
            "message": f"Restore point '{description}' is on the disk at {dest}.",
        }

    def _snapshot_path(self, snapshot_id: str) -> Optional[str]:
        token = str(snapshot_id).strip()
        if not token or token.startswith(".") or "/" in token or "\\" in token:
            return None
        candidates = []
        if token.isdigit():
            candidates.append(f"/.snapshots/{token}/snapshot")
            candidates.append(f"/.snapshots/{token}")
        candidates.append(f"/.snapshots/{token}")
        candidates.append(f"/.snapshots/devos-{token}")
        for path in candidates:
            if self._isdir(path):
                return path
        return None

    def list_restore_points(self) -> List[Dict[str, Any]]:
        points: List[Dict[str, Any]] = []
        if self._has("snapper"):
            code, out, _err = self.runner(["snapper", "-c", "root", "list"])
            if code == 0:
                points.extend(p for p in parse_snapper_list(out) if p["id"] != 0)
        if self._isdir("/.snapshots"):
            try:
                names = os.listdir("/.snapshots")
            except OSError:
                names = []
            known = {str(p["id"]) for p in points}
            for name in sorted(names):
                if not name.startswith("devos-"):
                    continue
                token = name[len("devos-"):]
                if token in known or not token.isdigit():
                    continue
                path = f"/.snapshots/{name}"
                if self._isdir(path):
                    points.append({
                        "id": int(token),
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(token))),
                        "description": name,
                        "backend": "btrfs",
                        "path": path,
                    })
        return points

    def rollback(self, snapshot_id) -> Dict[str, Any]:
        token = str(snapshot_id).strip()
        if self.filesystem() != "btrfs":
            return {"status": "UNAVAILABLE", "message": "Rollback needs a btrfs system disk."}
        if self._euid != 0:
            return self._needs_root("Before rollback", "rollback", token)
        safety = self.create_restore_point("Before rollback")
        if safety.get("status") == "FAILED":
            return {
                "status": "FAILED",
                "error": "Stopped. A safety restore point could not be created, so nothing was changed.",
                "safety": safety,
            }
        if token.isdigit() and self._has("snapper"):
            code, out, err = self.runner(["snapper", "-c", "root", "rollback", token])
            if code == 0:
                return {
                    "status": "READY_FOR_REBOOT",
                    "snapshot_id": int(token),
                    "backend": "snapper",
                    "safety": safety,
                    "message": "Snapper will boot this restore point after you restart.",
                }
        path = self._snapshot_path(token)
        if not path:
            return {"status": "FAILED", "error": f"No restore point '{token}' was found on the disk.",
                    "safety": safety}
        if not self._has("rsync"):
            return {"status": "FAILED", "error": "rsync is not installed, so files cannot be copied back.",
                    "safety": safety}
        cmd = ["rsync", "-aHAX", "--delete", "--numeric-ids"]
        cmd.extend(f"--exclude={item}" for item in EXCLUDES)
        cmd.extend([path.rstrip("/") + "/", "/"])
        code, out, err = self.runner(cmd)
        if code != 0:
            return {
                "status": "FAILED",
                "error": (err or out or "Copying the restore point back did not finish.").strip(),
                "safety": safety,
            }
        return {
            "status": "READY_FOR_REBOOT",
            "snapshot_id": token,
            "backend": "btrfs",
            "safety": safety,
            "message": "Files were restored from the snapshot. Restart the PC to finish. "
                       "A safety restore point was taken first. Home folders were left as they are.",
        }


def _reexec_root(result: Dict[str, Any]) -> bool:
    if result.get("status") != "NEEDS_ROOT":
        return False
    if os.environ.get("DEVOS_NO_PKEXEC") == "1" or not shutil.which("pkexec"):
        return False
    os.execvp("pkexec", ["pkexec", sys.executable, os.path.abspath(__file__)] + sys.argv[1:])
    return True


def gui() -> int:
    mgr = SnapshotManager()
    if mgr._euid != 0 and shutil.which("pkexec"):
        os.execvp("pkexec", ["pkexec", sys.executable, os.path.abspath(__file__), "gui"])
    if not shutil.which("kdialog"):
        print("Restore points: devos restore create|list|rollback")
        return 0
    choice = subprocess.run(
        ["kdialog", "--menu", "DevOS restore points",
         "create", "Create a restore point",
         "list", "List restore points",
         "rollback", "Roll back to a restore point"],
        capture_output=True, text=True)
    if choice.returncode != 0:
        return 0
    action = choice.stdout.strip()
    if action == "create":
        desc = subprocess.run(["kdialog", "--inputbox", "Name this restore point", "Manual restore point"],
                              capture_output=True, text=True)
        if desc.returncode != 0:
            return 0
        result = mgr.create_restore_point(desc.stdout.strip() or "Manual restore point")
    elif action == "list":
        points = mgr.list_restore_points()
        text = "\n".join(f"{p['id']}  {p.get('description', '')}" for p in points) or "No restore points yet."
        subprocess.run(["kdialog", "--msgbox", text])
        return 0
    else:
        ident = subprocess.run(["kdialog", "--inputbox", "Restore point number"],
                               capture_output=True, text=True)
        if ident.returncode != 0 or not ident.stdout.strip():
            return 0
        confirm = subprocess.run(
            ["kdialog", "--yesno",
             "Roll back system files to this restore point? Your Home folder is kept. "
             "The PC should be restarted afterwards."])
        if confirm.returncode != 0:
            return 0
        result = mgr.rollback(ident.stdout.strip())
    subprocess.run(["kdialog", "--msgbox", result.get("message") or result.get("error") or result.get("status")])
    return 0 if result.get("status") in ("CREATED", "READY_FOR_REBOOT", "UNAVAILABLE") else 1


def main():
    parser = argparse.ArgumentParser(description="DevOS restore points")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list", help="List restore points on disk")
    sub.add_parser("gui", help="Restore-point window")
    create_p = sub.add_parser("create", help="Create a restore point")
    create_p.add_argument("description", nargs="?", default="Manual restore point")
    roll_p = sub.add_parser("rollback", help="Roll system files back to a restore point")
    roll_p.add_argument("id", help="Restore point number")
    args = parser.parse_args()
    mgr = SnapshotManager()
    if args.command == "gui":
        sys.exit(gui())
    if args.command == "create":
        res = mgr.create_restore_point(args.description)
        if _reexec_root(res):
            return
        print(res.get("message") or res.get("error") or res["status"])
        sys.exit(0 if res["status"] in ("CREATED", "UNAVAILABLE") else 1)
    if args.command == "rollback":
        res = mgr.rollback(args.id)
        if _reexec_root(res):
            return
        print(res.get("message") or res.get("error") or res["status"])
        sys.exit(0 if res["status"] == "READY_FOR_REBOOT" else 1)
    for point in mgr.list_restore_points():
        print(f"{point['id']}\t{point.get('timestamp', '')}\t{point.get('description', '')}")


if __name__ == "__main__":
    main()
