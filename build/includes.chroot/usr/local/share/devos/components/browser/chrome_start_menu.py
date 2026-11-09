"""Keep the Start menu free of raw Chrome URL apps and duplicate web apps.

Chrome writes ~/.local/share/applications/chrome-<id>-Default.desktop with
Name= often set to the start URL (https://onedrive.live.com/). DevOS already
ships friendly companions (OneDrive, Windows App, …). This module:

1. Renames URL Names to popular titles people understand
2. Hides Chrome launchers that duplicate a DevOS companion (never show twice)
3. Hides leftover secondary-profile PWA launchers
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_CHROME_DESKTOP = re.compile(
    r"^chrome-([a-p]{32})-(Default|Profile_\d+)\.desktop$"
)

# Start-URL fragments → Start-menu Name people recognize.
_URL_FRIENDLY = (
    ("onedrive.live.com", "OneDrive"),
    ("onedrive.microsoft.com", "OneDrive"),
    ("office.com", "Microsoft 365"),
    ("www.office.com", "Microsoft 365"),
    ("outlook.office.com", "Outlook"),
    ("outlook.live.com", "Outlook"),
    ("windows.cloud.microsoft", "Windows App"),
    ("youtube.com", "YouTube"),
    ("youtu.be", "YouTube"),
    ("maps.bing.com", "Maps"),
    ("bing.com/maps", "Maps"),
    ("weather.microsoft.com", "Weather"),
    ("msn.com/en-us/weather", "Weather"),
    ("web.whatsapp.com", "WhatsApp"),
    ("drive.google.com", "Google Drive"),
    ("docs.google.com", "Google Docs"),
    ("mail.google.com", "Gmail"),
    ("calendar.google.com", "Google Calendar"),
    ("github.com", "GitHub"),
    ("chatgpt.com", "ChatGPT"),
    ("claude.ai", "Claude"),
    ("gemini.google.com", "Gemini"),
)

# If a DevOS companion exists with this Name, hide the Chrome PWA copy.
# Keys are Start-menu Name=; values are Features companion desktop ids.
_COMPANION_BY_NAME = {
    "windows app": "devos-web-winapp.desktop",
    "onedrive": "devos-web-onedrive.desktop",
    "microsoft 365": "devos-web-m365web.desktop",
    "office": "devos-web-m365web.desktop",
    "microsoft office": "devos-web-m365web.desktop",
    "outlook": "devos-web-outlookweb.desktop",
    "weather": "devos-web-weather.desktop",
    "maps": "devos-web-maps.desktop",
}

_SYSTEM_APP_DIRS = (
    Path("/usr/local/share/applications"),
    Path("/usr/share/applications"),
)


def friendly_url_name(name: str) -> str | None:
    """Return a popular name when Name= is a raw http(s) URL."""
    s = (name or "").strip()
    if not (s.startswith("http://") or s.startswith("https://")):
        return None
    low = s.lower()
    for needle, title in _URL_FRIENDLY:
        if needle in low:
            return title
    # Last resort: host only (never leave the full URL in the Start menu).
    host = re.sub(r"^https?://(www\.)?", "", low).split("/")[0]
    if not host:
        return "Web App"
    parts = [p for p in host.split(".") if p not in ("com", "org", "net", "io", "co", "uk", "us")]
    label = parts[0] if parts else host
    return label[:1].upper() + label[1:]


def _parse_desktop(text: str) -> tuple[list[str], dict[str, str], int, int]:
    lines = text.splitlines()
    start = lines.index("[Desktop Entry]") + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("[")), len(lines))
    values = {}
    for line in lines[start:end]:
        if "=" in line and not line.startswith("#"):
            key, _, val = line.partition("=")
            values[key] = val
    return lines, values, start, end


def _companion_visible(name_key: str) -> bool:
    desk = _COMPANION_BY_NAME.get(name_key)
    if not desk:
        return False
    for root in _SYSTEM_APP_DIRS:
        path = root / desk
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "NoDisplay=true" in text or "Hidden=true" in text:
            continue
        if "Name=" in text:
            return True
    # Windows App companion is always the canonical one when present.
    if name_key == "windows app":
        for root in _SYSTEM_APP_DIRS:
            if (root / "devos-web-winapp.desktop").is_file():
                return True
    return False


def _write_atomic(path: Path, text: str, mode: int) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".devos-chrome-menu-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text if text.endswith("\n") else text + "\n")
        os.chmod(temporary, mode & 0o777)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass


def clean_chrome_start_menu(directory: Path | None = None) -> int:
    """Rewrite user Chrome .desktop files. Returns number of files changed."""
    directory = Path(
        directory
        or Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications"
    )
    if not directory.is_dir():
        return 0
    changed = 0
    try:
        uid = os.getuid()
    except AttributeError:
        uid = -1

    for path in sorted(directory.glob("chrome-*.desktop")):
        match = _CHROME_DESKTOP.fullmatch(path.name)
        if not match or path.is_symlink():
            continue
        try:
            info = path.stat()
            if uid >= 0 and info.st_uid != uid:
                continue
            if info.st_size > 65536:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            lines, values, start, end = _parse_desktop(text)
        except (OSError, UnicodeError, ValueError):
            continue

        name = values.get("Name", "")
        profile = match.group(2)
        hide = values.get("NoDisplay", "").lower() == "true"
        new_name = None
        force_hide = False

        # Secondary Chrome profiles never belong in All Applications.
        if profile.startswith("Profile_"):
            force_hide = True

        friendly = friendly_url_name(name)
        if friendly:
            new_name = friendly
            name = friendly

        name_key = name.strip().lower()
        # Duplicate of a DevOS companion → keep only the DevOS entry.
        if _companion_visible(name_key):
            force_hide = True
        # Still a raw URL after mapping failure → hide rather than confuse.
        if name.startswith("http://") or name.startswith("https://"):
            force_hide = True
            new_name = friendly_url_name(name) or "Web App"

        if not force_hide and not new_name:
            continue
        if force_hide and hide and (new_name is None or values.get("Name") == new_name):
            if values.get("X-DevOS-StartMenu") == "clean":
                continue

        body = []
        saw_name = False
        saw_nodisplay = False
        saw_marker = False
        for line in lines[start:end]:
            if line.startswith("Name=") and new_name:
                body.append(f"Name={new_name}")
                saw_name = True
                continue
            if line.startswith("NoDisplay="):
                if force_hide:
                    body.append("NoDisplay=true")
                    saw_nodisplay = True
                else:
                    body.append(line)
                    saw_nodisplay = True
                continue
            if line.startswith("X-DevOS-StartMenu="):
                body.append("X-DevOS-StartMenu=clean")
                saw_marker = True
                continue
            if line.startswith("Name["):
                continue  # drop translated URL names
            body.append(line)
        if new_name and not saw_name:
            body.insert(0, f"Name={new_name}")
        if force_hide and not saw_nodisplay:
            body.append("NoDisplay=true")
        if not saw_marker:
            body.append("X-DevOS-StartMenu=clean")

        new_text = "\n".join(lines[:start] + body + lines[end:]) + "\n"
        if new_text == text if text.endswith("\n") else text + "\n":
            continue
        try:
            _write_atomic(path, new_text, info.st_mode)
            changed += 1
        except OSError:
            continue
    return changed


if __name__ == "__main__":
    print(clean_chrome_start_menu())
