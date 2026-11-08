"""Release and unmount the install target without failing the install.

Calamares' stock umount job can mark a successful install as failed when any
process still holds /tmp/calamares-root-* (open files, cwd, bind mounts, or a
log copy still flushing). By this point GRUB and the root filesystem are
already written — so we force-release, lazy-unmount, and always succeed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time


import libcalamares


def pretty_name():
    return "Unmount file systems"


def pretty_status_message():
    return "Releasing the new system disk…"


def _run(cmd, timeout=30):
    try:
        return subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _preserve_log(root: str) -> None:
    """Best-effort copy of the installer log onto the new disk."""
    candidates = [
        "/tmp/calamares.log",
        "/root/.cache/Calamares/session.log",
        "/home/devos/.cache/Calamares/session.log",
        "/var/log/Calamares.log",
    ]
    # Also pick up any live-user Calamares session log.
    for base in ("/home", "/root"):
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            if "Calamares" in dirpath and "session.log" in files:
                candidates.append(os.path.join(dirpath, "session.log"))
            if dirpath.count(os.sep) - base.count(os.sep) > 6:
                break

    src = next((p for p in candidates if os.path.isfile(p)), None)
    if not src:
        return
    dest_dir = os.path.join(root, "var", "log")
    try:
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(src, os.path.join(dest_dir, "Calamares.log"))
    except OSError:
        pass


def _mounts_under(root: str):
    """Return mount points under root, deepest first."""
    root = os.path.realpath(root)
    found = []
    try:
        with open("/proc/self/mountinfo", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 5:
                    continue
                mp = (
                    parts[4]
                    .replace("\\040", " ")
                    .replace("\\011", "\t")
                    .replace("\\012", "\n")
                    .replace("\\134", "\\")
                )
                real = os.path.realpath(mp) if os.path.exists(mp) else mp
                if real == root or real.startswith(root + os.sep):
                    found.append(real)
    except OSError:
        return [root]
    # Unique, deepest first
    found = sorted(set(found), key=lambda p: p.count(os.sep), reverse=True)
    if root not in found:
        found.append(root)
    return found


def _kill_users(path: str) -> None:
    # TERM then KILL anything with open files / cwd under the target.
    _run(["fuser", "-k", "-TERM", "-m", path], timeout=10)
    time.sleep(0.4)
    _run(["fuser", "-k", "-KILL", "-m", path], timeout=10)


def _release(root: str) -> None:
    root = os.path.realpath(root)
    _run(["sync"], timeout=60)
    _kill_users(root)
    time.sleep(0.5)

    for mp in _mounts_under(root):
        _kill_users(mp)
        # Lazy detach first — never block the installer on a busy mount.
        _run(["umount", "-l", mp], timeout=20)
        # Retry a normal unmount in case lazy left a stale entry briefly.
        _run(["umount", "-R", mp], timeout=15)

    # Final sweep: any remaining mounts still named under the tmp root.
    for mp in _mounts_under(root):
        _run(["umount", "-lf", mp], timeout=15)

    _run(["sync"], timeout=60)
    # Remove the empty mount directory when possible (non-fatal).
    try:
        if os.path.isdir(root) and not os.listdir(root):
            os.rmdir(root)
    except OSError:
        pass


def run():
    root = libcalamares.globalstorage.value("rootMountPoint") or ""
    if not root or not isinstance(root, str):
        # Nothing mounted — treat as already clean.
        return None
    if not os.path.isdir(root):
        return None

    try:
        libcalamares.utils.debug("devosumount: releasing " + root)
    except Exception:
        pass

    try:
        _preserve_log(root)
    except Exception:
        pass

    try:
        _release(root)
    except Exception as exc:
        try:
            libcalamares.utils.warning("devosumount: " + str(exc))
        except Exception:
            pass

    # Always succeed: the OS is already installed; a busy unmount must not
    # show "Installation Failed" after a working GRUB write.
    return None
