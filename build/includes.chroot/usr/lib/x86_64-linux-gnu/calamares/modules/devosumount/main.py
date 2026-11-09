"""Release and unmount the install target without failing the install.

Calamares' stock umount job can mark a successful install as failed when any
process still holds /tmp/calamares-root-* . By this point GRUB and the root
filesystem are already written — force-release, lazy-unmount, always succeed.

Keep this FAST: a full `sync` after unpacking a multi‑GB system can sit on
"Unmount file systems" at ~97% for many minutes. We budget a few seconds.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

import libcalamares

# Hard ceiling so the finished page always appears promptly.
RELEASE_BUDGET_S = 12.0


def pretty_name():
    return "Unmount file systems"


def pretty_status_message():
    return "Releasing the new system disk…"


def _run(cmd, timeout=8):
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
    """Best-effort copy of the installer log onto the new disk (no deep walks)."""
    candidates = [
        "/tmp/calamares.log",
        "/root/.cache/Calamares/session.log",
        "/home/devos/.cache/Calamares/session.log",
        "/var/log/Calamares.log",
    ]
    # Live user session log — shallow only (deep os.walk made 97% feel stuck).
    for home in ("/home/devos", "/root"):
        candidates.append(os.path.join(home, ".cache", "Calamares", "session.log"))

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
    found = sorted(set(found), key=lambda p: p.count(os.sep), reverse=True)
    if root not in found:
        found.append(root)
    return found


def _kill_users(path: str) -> None:
    # Short timeouts — fuser on a huge tree can stall the UI at 97%.
    _run(["fuser", "-k", "-KILL", "-m", path], timeout=3)


def _quick_sync(root: str) -> None:
    """Flush only what we can afford; never wait out a multi-minute global sync."""
    # Prefer filesystem-targeted sync when available (util-linux).
    if _run(["sync", "-f", root], timeout=4) is not None:
        return
    _run(["sync"], timeout=4)


def _release(root: str) -> None:
    root = os.path.realpath(root)
    started = time.monotonic()

    def left() -> float:
        return max(0.5, RELEASE_BUDGET_S - (time.monotonic() - started))

    _quick_sync(root)
    if time.monotonic() - started > RELEASE_BUDGET_S:
        return

    _kill_users(root)

    for mp in _mounts_under(root):
        if time.monotonic() - started > RELEASE_BUDGET_S:
            break
        _kill_users(mp)
        # Lazy detach only — never block on a busy mount.
        _run(["umount", "-l", mp], timeout=min(5, left()))

    # One more lazy sweep for anything still listed.
    if time.monotonic() - started <= RELEASE_BUDGET_S:
        for mp in _mounts_under(root):
            _run(["umount", "-lf", mp], timeout=3)

    try:
        if os.path.isdir(root) and not os.listdir(root):
            os.rmdir(root)
    except OSError:
        pass


def run():
    root = libcalamares.globalstorage.value("rootMountPoint") or ""
    if not root or not isinstance(root, str):
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

    # Always succeed: the OS is already installed.
    return None
