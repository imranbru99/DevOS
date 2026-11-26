"""Start Menu settings that keep All Applications in place."""

from __future__ import annotations

import os
import sys
from pathlib import Path

MARKER = "devos-keep-category-while-scrolling"

MENU_KEYS = {
    "switchCategoryOnHover": "false",
    "favoritesDisplay": "0",
    "applicationsDisplay": "0",
}


def patch_appletsrc(text: str) -> str:
    """Small favorite icons, large application icons, no hover category changes."""
    lines = text.splitlines()
    headers: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if line.startswith("[") and line.endswith("]"):
            headers.append((index, line))
    kickoff_groups: list[str] = []
    for position, (index, name) in enumerate(headers):
        end = headers[position + 1][0] if position + 1 < len(headers) else len(lines)
        body = lines[index + 1:end]
        if "plugin=org.kde.plasma.kickoff" in body:
            kickoff_groups.append(name)
    if not kickoff_groups:
        return text
    for group in kickoff_groups:
        header = group + "[Configuration][General]"
        if header in lines:
            start = lines.index(header) + 1
            end = start
            while end < len(lines) and not lines[end].startswith("["):
                end += 1
            keys = lines[start:end]
            for name, value in MENU_KEYS.items():
                prefix = name + "="
                replaced = False
                for offset, key in enumerate(keys):
                    if key.startswith(prefix):
                        keys[offset] = prefix + value
                        replaced = True
                if not replaced:
                    keys.append(prefix + value)
            lines[start:end] = keys
        else:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(header)
            for name, value in MENU_KEYS.items():
                lines.append(f"{name}={value}")
    result = "\n".join(lines)
    if text.endswith("\n"):
        result += "\n"
    return result


def patch_user_configs(home: Path | None = None) -> list[str]:
    homes: list[Path] = []
    if home is not None:
        homes.append(home)
    else:
        sudo_user = os.environ.get("SUDO_USER")
        if sudo_user and sudo_user != "root":
            homes.append(Path("/home") / sudo_user)
        homes.append(Path.home())
        homes.append(Path("/etc/skel"))
    changed: list[str] = []
    seen: set[Path] = set()
    for candidate in homes:
        path = candidate / ".config" / "plasma-org.kde.plasma.desktop-appletsrc"
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        original = path.read_text(encoding="utf-8")
        updated = patch_appletsrc(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed.append(str(path))
    return changed


def main(argv: list[str]) -> int:
    home = Path(argv[1]) if len(argv) > 1 else None
    changed = patch_user_configs(home)
    if changed:
        print("Updated menu settings:")
        for path in changed:
            print(f"  {path}")
    else:
        print("Menu settings already keep All Applications in place.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
