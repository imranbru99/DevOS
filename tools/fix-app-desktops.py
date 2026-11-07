#!/usr/bin/env python3
"""Normalize DevOS .desktop files: branded icons, StartupWMClass, non-python3 Exec.

Also guards against the launcher+desktop double-"gui" bug that made DevOS Islamic
fail to open (wrapper hardcoded "gui" and Exec also passed gui → argv = gui gui).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPS = ROOT / "build/includes.chroot/usr/share/applications"
BIN = ROOT / "build/includes.chroot/usr/local/bin"

# Map desktop id → preferred launcher on PATH (wrapper). Fallback: devos-run.
WRAPPERS = {
    "devos-clipboard": "devos-clipboard",
    "devos-emoji": "devos-emoji",
    "devos-features": "devos-features",
    "devos-files": "devos-files",
    "devos-thispc": "devos-files",
    "devos-taskman": "devos-taskman",
    "devos-security": "devos-security",
    "devos-islamic": "devos-islamic",
    "devos-familysafe": "devos-familysafe",
    "devos-ai-models": "devos-ai-models",
    "devos-code-agent": "devos-code-agent",
    "devos-ai-code-agent": "devos-code-agent",
    "devos-chat": "devos-chat",
    "devos-browser": "devos-browser",
    "devos-disk": "devos-disk-gui",
}

# Wrappers that default to the window when invoked with no args.
DEFAULT_GUI_WRAPPERS = frozenset({"devos-islamic", "devos-familysafe"})

# Hardcoded subcommand before "$@" — duplicates whatever Exec= passes.
BAD_HARDCODED_GUI = re.compile(
    r'''\.py"?\s+"gui"\s+"\$@"'''
)
WRAPPER_DEFAULT_GUI_BLOCK = """\
# Default to the window when no subcommand is given (desktop may also pass "gui").
if [ $# -eq 0 ]; then
  set -- gui
fi
"""


def rewrite_desktop(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="replace")
    original = text
    desk_id = path.stem

    # Ensure branded icon name when missing or generic.
    if re.search(r"^Icon=", text, re.M):
        def fix_icon(m):
            val = m.group(1).strip()
            if val.startswith("devos-") or "/" in val:
                return m.group(0)
            return f"Icon={desk_id}"
        text = re.sub(r"^Icon=(.*)$", fix_icon, text, count=1, flags=re.M)
    else:
        text = text.replace("[Desktop Entry]\n", f"[Desktop Entry]\nIcon={desk_id}\n", 1)

    # StartupWMClass for taskbar matching.
    if not re.search(r"^StartupWMClass=", text, re.M):
        text = re.sub(
            r"^(Type=Application\s*)$",
            rf"\1StartupWMClass={desk_id}\n",
            text,
            count=1,
            flags=re.M,
        )
        if "StartupWMClass=" not in text:
            text = text.replace("[Desktop Entry]\n", f"[Desktop Entry]\nStartupWMClass={desk_id}\n", 1)

    # Prefer wrapper /devos-run so the process is not named python3.
    wrapper = WRAPPERS.get(desk_id)
    wrapper_path = BIN / wrapper if wrapper else None

    def fix_exec(line: str) -> str:
        if not line.startswith("Exec="):
            return line
        body = line[5:].strip()

        # Already a DevOS launcher: strip redundant default "gui" so wrappers
        # that inject gui themselves cannot see argv = gui gui.
        m_wrap = re.match(
            r"(/usr/local/bin/)?(devos-[A-Za-z0-9_-]+)(?:\s+(gui))?\s*$",
            body,
        )
        if m_wrap:
            name = m_wrap.group(2)
            if name in DEFAULT_GUI_WRAPPERS or m_wrap.group(3):
                # Keep enable/disable/etc. intact; only drop a lone trailing gui.
                if m_wrap.group(3) and name in DEFAULT_GUI_WRAPPERS:
                    return f"Exec=/usr/local/bin/{name}"
                if body.startswith("/usr/local/bin/"):
                    return line
                return f"Exec=/usr/local/bin/{name}"
            if body.startswith("/usr/local/bin/"):
                return line
            return f"Exec=/usr/local/bin/{name}"

        if body.startswith("/usr/local/bin/devos-") or body.startswith("devos-"):
            return line
        if "devos-run" in body:
            return line
        # python3 /path/script.py …
        m = re.match(
            r"(?:/usr/bin/)?python3(?:\.\d+)?\s+(\S+\.py)(.*)$",
            body,
        )
        if not m:
            # bare python3 /usr/local/bin/devos-files
            m2 = re.match(r"(?:/usr/bin/)?python3(?:\.\d+)?\s+(/usr/local/bin/devos-\S+)(.*)$", body)
            if m2:
                return f"Exec={m2.group(1)}{m2.group(2)}"
            return line
        script, rest = m.group(1), m.group(2) or ""
        # Do not forward a lone "gui" into wrappers that already default to gui.
        if wrapper in DEFAULT_GUI_WRAPPERS:
            rest = re.sub(r"^\s+gui\b", "", rest)
        name_match = re.search(r"^Name=(.*)$", original, re.M)
        name = (name_match.group(1).strip() if name_match else desk_id)
        if wrapper_path and wrapper_path.is_file():
            return f"Exec=/usr/local/bin/{wrapper}{rest}"
        # Desktop Entry Exec quoting: wrap display names that contain spaces.
        quoted = f'"{name}"' if (" " in name or "\t" in name) else name
        return (
            f"Exec=/usr/local/bin/devos-run --desktop={desk_id} --name={quoted} "
            f"{script}{rest}"
        )

    text = "\n".join(fix_exec(line) for line in text.splitlines()) + ("\n" if original.endswith("\n") else "")

    # Hide from "Open with" noise but keep launchable: no change.
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def fix_gui_wrappers() -> list[str]:
    """Rewrite wrappers that hardcode gui before \"$@\" (the Islamic launch bug)."""
    fixed: list[str] = []
    if not BIN.is_dir():
        return fixed
    for path in sorted(BIN.glob("devos-*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not BAD_HARDCODED_GUI.search(text):
            continue
        new = BAD_HARDCODED_GUI.sub('.py" "$@"', text)
        # Ensure empty-argv still opens the GUI for known apps.
        if path.name in DEFAULT_GUI_WRAPPERS and "set -- gui" not in new:
            new = new.replace(
                'export DEVOS_DESKTOP_FILE=',
                WRAPPER_DEFAULT_GUI_BLOCK + "export DEVOS_DESKTOP_FILE=",
                1,
            )
            # Prefer placing the default block after the export line when possible
            if WRAPPER_DEFAULT_GUI_BLOCK + "export DEVOS_DESKTOP_FILE=" in new:
                new = new.replace(
                    WRAPPER_DEFAULT_GUI_BLOCK + "export DEVOS_DESKTOP_FILE=",
                    "export DEVOS_DESKTOP_FILE=",
                    1,
                )
                new = re.sub(
                    r"(export DEVOS_DESKTOP_FILE=\S+\n)",
                    r"\1" + WRAPPER_DEFAULT_GUI_BLOCK,
                    new,
                    count=1,
                )
        if new != text:
            path.write_text(new, encoding="utf-8")
            fixed.append(path.name)
    return fixed


def assert_no_double_gui() -> list[str]:
    """Return human-readable violations (empty list = healthy)."""
    problems: list[str] = []
    if BIN.is_dir():
        for path in sorted(BIN.glob("devos-*")):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if BAD_HARDCODED_GUI.search(text):
                problems.append(f"{path.name}: hardcodes gui before \"$@\"")
    if APPS.is_dir():
        for desk_id in sorted(DEFAULT_GUI_WRAPPERS):
            path = APPS / f"{desk_id}.desktop"
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if re.search(rf"^Exec=.*/{desk_id}\s+gui\s*$", text, re.M):
                problems.append(f"{path.name}: Exec passes gui to a default-gui wrapper")
    return problems


def main() -> int:
    changed = 0
    for path in sorted(APPS.glob("devos-*.desktop")):
        if rewrite_desktop(path):
            changed += 1
            print("updated", path.name)
    for name in fix_gui_wrappers():
        changed += 1
        print("fixed wrapper", name)
    problems = assert_no_double_gui()
    if problems:
        print("ERROR: double-gui launch risk still present:", file=sys.stderr)
        for p in problems:
            print(" -", p, file=sys.stderr)
        return 1
    print(f"done; updated={changed}; double-gui-check=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
