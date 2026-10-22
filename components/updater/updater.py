#!/usr/bin/env python3
"""Install published DevOS component releases; OS upgrades remain explicit."""
import argparse
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import urllib.error

REPO = "imranbru99/DevOS"
ASSET = "devos-update.tar.gz"
STATE = "var/lib/devos-updater"
MAX_BYTES = 128 * 1024 * 1024
DESKTOP_FILES = {
    "overlay/usr/share/applications/devos-kids-mode.desktop",
    "overlay/etc/xdg/kglobalshortcutsrc",
}
KIDS_PACKAGES = ("python3-gi", "python3-cairo", "python3-gi-cairo", "gir1.2-gtk-3.0", "gir1.2-gtklayershell-0.1")


def fetch(url, limit=MAX_BYTES):
    req = urllib.request.Request(url, headers={"User-Agent": "DevOS-Updater/1", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Release download exceeds the size limit.")
    return data


def release(version=None):
    if version and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", version):
        raise ValueError("Invalid release tag.")
    suffix = "tags/" + version if version else "latest"
    try:
        data = json.loads(fetch(f"https://api.github.com/repos/{REPO}/releases/{suffix}", 1024 * 1024))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ValueError("No published stable DevOS release was found for this selection. A maintainer must publish an update bundle first.") from exc
        raise
    if data.get("draft") or data.get("prerelease"):
        raise ValueError("Choose a published stable release.")
    return data


def destination(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or str(path) != name or "\\" in name:
        raise ValueError(f"Unsafe update path: {name}")
    if name.startswith("components/") and len(path.parts) > 1:
        return "usr/local/share/devos/" + name
    if name.startswith(("overlay/usr/local/bin/", "overlay/usr/local/sbin/")) and len(path.parts) == 5:
        return name.removeprefix("overlay/")
    if name in DESKTOP_FILES:
        return name.removeprefix("overlay/")
    raise ValueError(f"Update cannot modify {name}")


def unpack(data):
    """Validate every member before any system file is touched; never extract links."""
    files = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive:
            if not member.isfile() or member.name in files:
                raise ValueError("Release contains a link, directory, or duplicate entry.")
            total += member.size
            if total > MAX_BYTES * 2 or len(files) >= 20000:
                raise ValueError("Expanded release exceeds limits.")
            if member.name != "manifest.json":
                destination(member.name)
            files[member.name] = (archive.extractfile(member).read(), member.mode & 0o111)
    manifest = json.loads(files.pop("manifest.json")[0])
    if manifest.get("format") != 1 or not isinstance(manifest.get("version"), str):
        raise ValueError("Unsupported update manifest.")
    if set(manifest.get("files", {})) != set(files):
        raise ValueError("Manifest does not match release contents.")
    for name, (body, _) in files.items():
        if hashlib.sha256(body).hexdigest() != manifest["files"][name]:
            raise ValueError(f"Checksum mismatch: {name}")
    return manifest, files


def ubuntu_series(root):
    for name in ("usr/lib/os-release.ubuntu", "etc/os-release"):
        path = root / name
        if path.exists():
            fields = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
            version = fields.get("VERSION_ID", "").strip('"')
            if version:
                return version
    return "unknown"


def safe_target(root, rel):
    target = root / rel
    if target.is_symlink() or any(parent.is_symlink() for parent in target.parents if parent != root):
        raise ValueError(f"Refusing symlink target: {rel}")
    return target


def atomic_write(path, body, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".devos-update-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def restore(root, backup, record):
    for rel, existed in reversed(list(record.items())):
        target = safe_target(root, rel)
        if existed:
            original = backup / rel
            atomic_write(target, original.read_bytes(), original.stat().st_mode & 0o777)
        elif target.exists():
            target.unlink()


def install(root, manifest, files):
    root = Path(root).resolve()
    if ubuntu_series(root) not in manifest.get("ubuntu_series", []):
        raise ValueError("This release needs a different Ubuntu base. Use devos update --os-upgrade first.")
    state = root / STATE
    state.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="backup-", dir=state) as temp:
        backup = Path(temp)
        record = {}
        targets = [(destination(name), body, executable) for name, (body, executable) in files.items()]
        targets.append((STATE + "/installed.json", json.dumps({"version": manifest["version"]}).encode(), 0))
        for rel, _, _ in targets:
            target = safe_target(root, rel)
            if target.exists() and not target.is_file():
                raise ValueError(f"Not a regular file: {rel}")
            record[rel] = target.exists()
            if target.exists():
                saved = backup / rel
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
        try:
            for rel, body, executable in targets:
                atomic_write(root / rel, body, 0o755 if executable else 0o644)
            atomic_write(backup / "record.json", json.dumps(record).encode(), 0o600)
            atomic_write(backup / "ubuntu-series", ubuntu_series(root).encode(), 0o600)
            previous = state / "rollback"
            if previous.exists():
                shutil.rmtree(previous)
            os.replace(backup, previous)
        except BaseException:
            restore(root, backup, record)
            raise


def rollback(root):
    root = Path(root).resolve()
    backup = root / STATE / "rollback"
    if not (backup / "record.json").exists():
        raise ValueError("No previous component update is available to restore.")
    if (backup / "ubuntu-series").read_text() != ubuntu_series(root):
        raise ValueError("The Ubuntu base changed since this update. Install a compatible component release instead of restoring old files.")
    record = json.loads((backup / "record.json").read_text())
    for rel in record:
        if rel == STATE + "/installed.json":
            continue
        if rel.startswith("usr/local/share/devos/components/"):
            name = rel.removeprefix("usr/local/share/devos/")
        else:
            name = "overlay/" + rel
        if destination(name) != rel:
            raise ValueError("Invalid rollback record.")
    restore(root, backup, record)
    shutil.rmtree(backup)


def prepare_dependencies(files):
    # Fixed, locally reviewed prerequisites, never commands from a release manifest.
    if "components/kids/kids_mode.py" not in files:
        return
    missing = []
    for package in KIDS_PACKAGES:
        check = subprocess.run(["dpkg-query", "-W", "-f=${db:Status-Status}", package],
                               capture_output=True, text=True)
        if check.returncode or check.stdout.strip() != "installed":
            missing.append(package)
    if missing:
        print("Installing the desktop libraries needed by Kids Mode…", flush=True)
        subprocess.run(["apt-get", "update", "-o", "APT::Update::Error-Mode=any"], check=True)
        subprocess.run(["apt-get", "install", "-y", "--no-install-recommends", *missing], check=True)


def refresh_enabled_features():
    state = Path("/etc/devos/modesty.json")
    if state.exists():
        settings = json.loads(state.read_text())
        if settings.get("enabled"):
            mode = settings.get("mode", "women")
            if mode not in ("women", "people"):
                raise ValueError("Unknown saved Modesty Filter mode; open its settings to refresh it.")
            command = ["/usr/local/bin/devos-modesty", "enable", "--mode", mode]
            if not settings.get("lock_private_modes", True):
                command.append("--keep-incognito")
            subprocess.run(command, check=True)
    print("Sign out and back in to load new desktop shortcuts. Restart browsers to load the refreshed filter.")


def update(version=None, check=False):
    info = release(version)
    assets = {item["name"]: item["browser_download_url"] for item in info.get("assets", [])}
    if ASSET not in assets or ASSET + ".sha256" not in assets:
        raise ValueError("This GitHub release has no DevOS update bundle. A maintainer must publish one first.")
    state = Path("/") / STATE
    installed = json.loads((state / "installed.json").read_text()) if (state / "installed.json").exists() else {}
    tag = info["tag_name"]
    print(f"Latest release: {tag}. Installed component release: {installed.get('version', 'not recorded')}.")
    if check or installed.get("version") == tag:
        return
    words = fetch(assets[ASSET + ".sha256"], 4096).decode().split()
    checksum = words[0] if words else ""
    data = fetch(assets[ASSET])
    if not re.fullmatch(r"[a-fA-F0-9]{64}", checksum) or hashlib.sha256(data).hexdigest() != checksum.lower():
        raise ValueError("Release download checksum mismatch.")
    manifest, files = unpack(data)
    if manifest["version"] != tag:
        raise ValueError("Release tag and bundle version differ.")
    if ubuntu_series(Path("/")) not in manifest.get("ubuntu_series", []):
        raise ValueError("This release needs a different Ubuntu base. Use devos update --os-upgrade first.")
    prepare_dependencies(files)
    install(Path("/"), manifest, files)
    try:
        refresh_enabled_features()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Component files were updated, but feature refresh needs attention: {exc}", file=sys.stderr)
        print("Rerun sudo devos-modesty enable with your saved mode to refresh the browser filter.", file=sys.stderr)
        return 1
    print(f"DevOS components updated to {tag}. Reopen DevOS applications to use the update.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Update DevOS from stable GitHub releases")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="Check without changing anything")
    modes.add_argument("--rollback", action="store_true", help="Restore files from the previous DevOS component update")
    parser.add_argument("--version", help="Install a specific published release tag")
    modes.add_argument("--os-upgrade", action="store_true", help="Launch the separate Ubuntu LTS upgrade")
    args = parser.parse_args(argv)
    if (args.os_upgrade or args.rollback) and args.version:
        parser.error("--version selects a DevOS component release; it cannot be combined with --os-upgrade")
    if args.os_upgrade:
        helper = Path(__file__).resolve().parents[2] / "build/includes.chroot/usr/local/sbin/devos-upgrade-os"
        if not helper.exists():
            helper = Path("/usr/local/sbin/devos-upgrade-os")
        return subprocess.call(["sudo", "bash", str(helper)])
    if not args.check and os.geteuid() != 0:
        return subprocess.call(["sudo", sys.executable, str(Path(__file__).resolve()), *(argv if argv is not None else sys.argv[1:])])
    try:
        if args.check:
            update(args.version, check=True)
        else:
            state = Path("/") / STATE
            state.mkdir(parents=True, exist_ok=True)
            with (state / "update.lock").open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if args.rollback:
                    rollback(Path("/"))
                    print("Previous DevOS component files restored. Reopen DevOS applications.")
                else:
                    return update(args.version) or 0
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        print(f"Update stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
