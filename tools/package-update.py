#!/usr/bin/env python3
"""Create the checksum-verified (and optionally signed) bundle consumed by devos update."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile


def package(root, output, version):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", version):
        raise ValueError("Invalid release tag")
    root, output = Path(root), Path(output)
    files = {}
    sources = [(root / "components", "components")]
    for folder in ("bin", "sbin"):
        sources.append((root / "build/includes.chroot/usr/local" / folder, "overlay/usr/local/" + folder))
    for source, prefix in sources:
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Release source contains a symlink: {path}")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo"):
                files[prefix + "/" + path.relative_to(source).as_posix()] = path.read_bytes()
    for rel in ("usr/share/applications/devos-kids-mode.desktop", "etc/xdg/kglobalshortcutsrc", "etc/systemd/user/plasma-polkit-agent.service.d/20-devos-style.conf"):
        path = root / "build/includes.chroot" / rel
        if path.is_file() and not path.is_symlink():
            files["overlay/" + rel] = path.read_bytes()
    overlay = root / "build/includes.chroot"
    assets = list((overlay / "usr/share/applications").glob("devos-*.desktop"))
    assets += list((overlay / "usr/share/icons/hicolor").glob("*/apps/devos-*.png"))
    assets += list((overlay / "usr/share/icons/hicolor").glob("*/apps/devos-*.svg"))
    assets += [overlay / "etc/xdg/kded6rc"]
    # Pin the update pubkey into the overlay so image + update stay aligned.
    pubkey = overlay / "usr/local/share/devos/keys/update-pubkey.pub"
    if pubkey.is_file() and not pubkey.is_symlink():
        assets.append(pubkey)
    for path in assets:
        if path.is_file() and not path.is_symlink():
            files["overlay/" + path.relative_to(overlay).as_posix()] = path.read_bytes()
    manifest = {"format": 1, "version": version, "ubuntu_series": ["24.04", "26.04"],
                "files": {name: hashlib.sha256(body).hexdigest() for name, body in files.items()}}
    files["manifest.json"] = json.dumps(manifest, sort_keys=True).encode()
    output.mkdir(parents=True, exist_ok=True)
    dest = output / "devos-update.tar.gz"
    with tarfile.open(dest, "w:gz") as archive:
        for name, body in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.size = len(body)
            member.mode = 0o755 if body.startswith(b"#!") else 0o644
            archive.addfile(member, io.BytesIO(body))
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    dest.with_suffix(dest.suffix + ".sha256").write_text(f"{digest}  {dest.name}\n")
    return dest


def sign_bundle(dest: Path, key_path: Path) -> Path:
    """Create dest.sig with OpenSSH (ssh-keygen -Y sign) or minisign."""
    dest = Path(dest)
    key_path = Path(key_path)
    if not key_path.is_file():
        raise FileNotFoundError(f"Signing key not found: {key_path}")
    sig_path = Path(str(dest) + ".sig")
    if sig_path.exists():
        sig_path.unlink()
    # minisign private keys are typically *.key; OpenSSH keys have no fixed suffix.
    if shutil.which("minisign") and key_path.suffix == ".key":
        proc = subprocess.run(
            ["minisign", "-Sm", str(dest), "-s", str(key_path), "-x", str(sig_path)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout or "minisign sign failed")
        return sig_path
    if not shutil.which("ssh-keygen"):
        raise RuntimeError("Neither minisign nor ssh-keygen is available to sign the update")
    # ssh-keygen -Y sign writes <file>.sig next to the input.
    proc = subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-f", str(key_path), "-n", "file", str(dest)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "ssh-keygen sign failed")
    produced = Path(str(dest) + ".sig")
    if not produced.is_file():
        raise RuntimeError("ssh-keygen did not write a .sig file")
    return produced


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--output", default="out/update")
    parser.add_argument(
        "--sign-key",
        default=os.environ.get("DEVOS_UPDATE_SIGN_KEY", ""),
        help="Path to OpenSSH/minisign private key (or set DEVOS_UPDATE_SIGN_KEY)",
    )
    parser.add_argument(
        "--require-signature",
        action="store_true",
        help="Fail if --sign-key is missing (CI release builds)",
    )
    args = parser.parse_args()
    dest = package(Path(__file__).resolve().parents[1], args.output, args.version)
    print(dest)
    key = (args.sign_key or "").strip()
    if key:
        sig = sign_bundle(dest, Path(key))
        print(sig)
    elif args.require_signature:
        raise SystemExit("Refusing to publish without --sign-key / DEVOS_UPDATE_SIGN_KEY")
