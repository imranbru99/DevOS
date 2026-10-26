"""Bounded automatic cleanup of explicitly disposable caches, never user data."""
import fcntl
import json
import os
from pathlib import Path
import stat
import time

DAY = 86400
# Retain shader/font/browser/build/model caches: rebuilding them can slow the PC
# or break offline use. Unknown application caches are manual-cleanup only.
ROOTS = ((".cache/thumbnails", 30 * DAY),
         (".cache/devos/temporary", 14 * DAY),
         (".cache/devos/previews", 30 * DAY))
MAX_BYTES = 512 * 1024 * 1024
MAX_FILES = 5000


def open_files(uid, seconds=2):
    """Fail closed if same-user file handles cannot be checked in time."""
    deadline = time.monotonic() + seconds
    result = set()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        if time.monotonic() > deadline:
            raise RuntimeError("Open-file check exceeded its time budget")
        try:
            if proc.stat().st_uid != uid:
                continue
            for descriptor in (proc / "fd").iterdir():
                if time.monotonic() > deadline:
                    raise RuntimeError("Open-file check exceeded its time budget")
                try:
                    s = descriptor.stat()
                    result.add((s.st_dev, s.st_ino))
                except FileNotFoundError:
                    continue  # process closed this handle
        except FileNotFoundError:
            continue  # process exited
        except PermissionError as exc:
            raise RuntimeError("Could not check an active user's files") from exc
    return result


def open_directory(home, relative, uid):
    """Anchor every component with directory fds; refuse symlinks/mount escapes."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    current = os.open(home, flags)
    try:
        initial = os.fstat(current)
        if initial.st_uid != uid:
            raise PermissionError("Home is not owned by this user")
        for part in relative.split("/"):
            next_fd = os.open(part, flags, dir_fd=current)
            s = os.fstat(next_fd)
            if s.st_uid != uid or s.st_dev != initial.st_dev:
                os.close(next_fd)
                raise PermissionError("Cache is not a local user-owned directory")
            os.close(current)
            current = next_fd
        return current
    except Exception:
        os.close(current)
        raise


def walk_files(fd, uid, device, deadline, result, depth=0):
    if depth > 16:
        return
    with os.scandir(fd) as entries:
        for entry in entries:
            if time.monotonic() >= deadline or result["scanned"] >= MAX_FILES:
                return
            result["scanned"] += 1
            try:
                metadata = entry.stat(follow_symlinks=False)
                if metadata.st_uid != uid or metadata.st_dev != device:
                    continue
                if stat.S_ISDIR(metadata.st_mode):
                    child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        current = os.fstat(child)
                        if (current.st_dev, current.st_ino) == (metadata.st_dev, metadata.st_ino):
                            yield from walk_files(child, uid, device, deadline, result, depth + 1)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(metadata.st_mode):
                    yield entry.name, fd, metadata
            except OSError:
                continue


def auto_clean(home=None, dry_run=False, now=None, held_inodes=None):
    home = os.path.abspath(home or os.path.expanduser("~"))
    uid = os.getuid()
    result = {"bytes": 0, "files": 0, "scanned": 0, "dry_run": dry_run, "skipped": ""}
    if uid == 0:
        result["skipped"] = "Automatic cleanup runs as the desktop user, never root"
        return result
    now = time.time() if now is None else now
    try:
        held = open_files(uid) if held_inodes is None else held_inodes
    except (OSError, RuntimeError) as exc:
        result["skipped"] = str(exc)
        return result
    deadline = time.monotonic() + 5
    for relative, age in ROOTS:
        try:
            root_fd = open_directory(home, relative, uid)
        except OSError:
            continue
        try:
            device = os.fstat(root_fd).st_dev
            for name, fd, metadata in walk_files(root_fd, uid, device, deadline, result):
                if metadata.st_nlink != 1:
                    continue
                if now - max(metadata.st_mtime, metadata.st_atime, metadata.st_ctime) < age:
                    continue
                if (metadata.st_dev, metadata.st_ino) in held:
                    continue
                size = metadata.st_blocks * 512
                if result["bytes"] + size > MAX_BYTES:
                    continue
                try:
                    current = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if current != metadata:
                        continue
                    if not dry_run:
                        os.unlink(name, dir_fd=fd)
                    result["bytes"] += size
                    result["files"] += 1
                except OSError:
                    continue
        finally:
            os.close(root_fd)
    return result


def run_scheduled(home=None, dry_run=False):
    """One lock shared by scheduled/manual auto runs; preserve only last report."""
    home = home or os.path.expanduser("~")
    if dry_run:
        return auto_clean(home, dry_run=True)
    if os.getuid() == 0:
        return auto_clean(home, dry_run)
    state = os.path.join(home, ".local", "state", "devos", "optimizer")
    try:
        os.makedirs(state, mode=0o700, exist_ok=True)
        fd = os.open(os.path.join(state, "auto-clean.lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        return {"skipped": "Cannot save maintenance state: " + str(exc), "bytes": 0, "files": 0}
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"skipped": "Cleanup already running", "bytes": 0, "files": 0}
        result = auto_clean(home, dry_run)
        if not dry_run:
            import tempfile
            temporary_fd, temporary = tempfile.mkstemp(prefix=".auto-clean-", dir=state)
            try:
                with os.fdopen(temporary_fd, "w") as stream:
                    json.dump(dict(result, finished_at=time.time()), stream)
                os.replace(temporary, os.path.join(state, "auto-clean-last.json"))
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return result
    finally:
        os.close(fd)
