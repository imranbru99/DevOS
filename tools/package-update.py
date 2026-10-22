#!/usr/bin/env python3
"""Create the checksum-verified bundle consumed by devos update."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
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
    for rel in ("usr/share/applications/devos-kids-mode.desktop", "etc/xdg/kglobalshortcutsrc"):
        path = root / "build/includes.chroot" / rel
        if path.is_file() and not path.is_symlink():
            files["overlay/" + rel] = path.read_bytes()
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--output", default="out/update")
    args = parser.parse_args()
    print(package(Path(__file__).resolve().parents[1], args.output, args.version))
