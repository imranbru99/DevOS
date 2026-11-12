#!/usr/bin/env python3
"""Archive optional DEBs without installing them in the base system.

Default mode caches legacy apt packages plus vendor Chrome/VS Code DEBs.
``--vendor-only`` ships only Chrome/VS Code so slim ISOs can still install
apps the user ticked in the installer without waiting on first-boot curl.
"""

import argparse
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


def write_index(repo: Path) -> None:
    with (repo / "Packages").open("w", encoding="utf-8") as index:
        for deb in sorted(repo.glob("*.deb")):
            control = subprocess.check_output(["dpkg-deb", "-f", str(deb)], text=True).rstrip()
            with deb.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            index.write(
                f"{control}\nFilename: ./{deb.name}\nSize: {deb.stat().st_size}\nSHA256: {digest}\n\n"
            )
    (repo / "devos.list").write_text(f"deb [trusted=yes] file:{REPO} ./\n", encoding="utf-8")


def download_vendor(repo: Path) -> dict:
    groups = {}
    for feature, (name, url) in VENDOR.items():
        print(f"==> Caching vendor app: {feature}", flush=True)
        subprocess.run(
            ["curl", "-fL", "--retry", "3", "--retry-delay", "5", "--max-time", "300",
             "-o", str(repo / name), url],
            check=True,
        )
        groups[feature] = [f"{REPO}/{name}"]
    return groups


def main(root: Path, vendor_only: bool = False) -> None:
    repo = root / REPO.lstrip("/")
    repo.mkdir(parents=True, exist_ok=True)
    for path in repo.glob("*.deb"):
        path.unlink()
    (repo / "Packages").unlink(missing_ok=True)
    (repo / "partial").mkdir(exist_ok=True)

    groups = download_vendor(repo)
    missing = []

    if not vendor_only:
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
        groups.update({
            feature["id"]: feature["apt"] for feature in catalog.FEATURES
            if feature["id"] not in catalog.BASE_FEATURE_IDS
            and any(package.split(":", 1)[0] in legacy for package in feature["apt"])
        })
        for feature, packages in groups.items():
            print(f"==> Caching optional app: {feature}", flush=True)
            if subprocess.run([*apt, *packages], env=env, timeout=300).returncode:
                missing.append(feature)

    write_index(repo)
    print(
        f"Cached {len(list(repo.glob('*.deb')))} DEBs for "
        f"{len(groups) - len(missing)} optional features.",
        flush=True,
    )
    if missing:
        print("Optional features still requiring an online source: " + ", ".join(missing), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="chroot path to populate")
    parser.add_argument(
        "--vendor-only",
        action="store_true",
        help="only download Chrome and VS Code DEBs (slim ISO)",
    )
    args = parser.parse_args()
    main(args.root.resolve(), vendor_only=args.vendor_only)
