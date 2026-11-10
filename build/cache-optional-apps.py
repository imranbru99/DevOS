#!/usr/bin/env python3
"""Archive the legacy optional DEBs without installing them in the base system."""

import hashlib
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "components/features"))
import feature_catalog as catalog

REPO = "/usr/local/share/devos/offline-apt"
VENDOR = {
    "chrome": ("chrome.deb", "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb"),
    "vscode": ("vscode.deb", "https://code.visualstudio.com/sha/download?build=stable&os=linux-deb-x64"),
}


def main(root):
    repo = root / REPO.lstrip("/")
    repo.mkdir(parents=True, exist_ok=True)
    for path in repo.glob("*.deb"):
        path.unlink()
    (repo / "Packages").unlink(missing_ok=True)
    (repo / "partial").mkdir(exist_ok=True)
    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive", LC_ALL="C")
    apt = [
        "chroot", str(root), "apt-get", "-o", f"Dir::Cache::archives={REPO}",
        "install", "--download-only", "--no-install-recommends", "-y",
    ]
    legacy = {
        line.partition("#")[0].strip().split(":", 1)[0]
        for path in (HERE / "package-lists").glob("*.list.chroot")
        for line in path.read_text(encoding="utf-8").splitlines()
    }
    groups = {
        feature["id"]: feature["apt"] for feature in catalog.FEATURES
        if feature["id"] not in catalog.BASE_FEATURE_IDS
        and any(package.split(":", 1)[0] in legacy for package in feature["apt"])
    }
    for feature, (name, url) in VENDOR.items():
        subprocess.run(["curl", "-fL", "--retry", "2", "--max-time", "300",
                        "-o", str(repo / name), url], check=True)
        groups[feature] = [f"{REPO}/{name}"]

    missing = []
    for feature, packages in groups.items():
        print(f"==> Caching optional app: {feature}", flush=True)
        if subprocess.run([*apt, *packages], env=env, timeout=300).returncode:
            missing.append(feature)

    with (repo / "Packages").open("w", encoding="utf-8") as index:
        for deb in sorted(repo.glob("*.deb")):
            control = subprocess.check_output(["dpkg-deb", "-f", str(deb)], text=True).rstrip()
            with deb.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            index.write(f"{control}\nFilename: ./{deb.name}\nSize: {deb.stat().st_size}\nSHA256: {digest}\n\n")
    print(f"Cached {len(list(repo.glob('*.deb')))} DEBs for {len(groups) - len(missing)} optional features.")
    if missing:
        print("Optional features still requiring an online source: " + ", ".join(missing), flush=True)
    (repo / "devos.list").write_text(f"deb [trusted=yes] file:{REPO} ./\n", encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
