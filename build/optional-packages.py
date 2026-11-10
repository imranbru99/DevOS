#!/usr/bin/env python3
"""Keep optional app packages out of fresh and reused live filesystems."""

import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "components/features"))
import feature_catalog as catalog

OPTIONAL = {package.split(":", 1)[0] for package in catalog.optional_system_packages()}


def prune(root: str) -> None:
    base = {
        line.split("#", 1)[0].strip().split(":", 1)[0]
        for path in (HERE / "package-lists").glob("*.list.chroot")
        for line in path.read_text(encoding="utf-8").splitlines()
    } - OPTIONAL
    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive", LC_ALL="C")
    query = subprocess.check_output(
        ["chroot", root, "dpkg-query", "-W", "-f=${binary:Package}\t${db:Status-Abbrev}\n"],
        env=env, text=True,
    )
    installed = []
    for line in query.splitlines():
        package, _, status = line.partition("\t")
        if package.split(":", 1)[0] in OPTIONAL and status.startswith("ii"):
            installed.append(package)
    flatpak = ["chroot", root, "flatpak"]
    if (Path(root) / "var/lib/flatpak/app").is_dir():
        bundled = subprocess.check_output(
            [*flatpak, "list", "--system", "--app", "--columns=application"], env=env, text=True
        ).splitlines()
        optional_apps = {app for feature in catalog.FEATURES for app in feature["flatpak"]}
        unwanted = sorted(optional_apps.intersection(bundled))
        if unwanted:
            subprocess.run([*flatpak, "uninstall", "--system", "-y", "--noninteractive", *unwanted],
                           env=env, check=True, timeout=300)
    if installed:
        command = ["chroot", root, "apt-get"]
        simulation = subprocess.check_output([*command, "-s", "purge", *installed], env=env, text=True)
        removed = {p.split(":", 1)[0] for p in re.findall(r"^(?:Purg|Remv) (\S+)", simulation, re.M)}
        if removed & base:
            raise SystemExit("Optional packages would remove required image packages: " + ", ".join(sorted(removed & base)))
        print("Removing optional packages from the cached image: " + ", ".join(installed), flush=True)
        subprocess.run([*command, "-y", "purge", *installed], env=env, check=True, timeout=600)
    # A previous build may have added this wrapper outside dpkg's ownership.
    path = "/opt/google/chrome/google-chrome"
    chrome = Path(root) / path.lstrip("/")
    wrapper = Path(root) / "usr/local/lib/devos/chrome-app-windows"
    if chrome.is_file() and wrapper.is_file() and chrome.read_bytes() == wrapper.read_bytes():
        chrome.unlink()
    # Chrome's postinst requires the regular launcher for update-alternatives.
    # Re-create the DevOS diversion only after the selected package configures.
    diversion = ["chroot", root, "dpkg-divert"]
    real = subprocess.check_output([*diversion, "--truename", path], text=True).strip()
    if real == path + ".devos-real":
        subprocess.run([*diversion, "--local", "--remove", "--rename", "--divert", real, path],
                       check=True, env=env)


if __name__ == "__main__":
    if len(sys.argv) == 2:
        prune(sys.argv[1])
    else:
        print(" ".join(sorted(OPTIONAL)))
