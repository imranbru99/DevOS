#!/usr/bin/env python3
"""Clear application names for every DevOS surface.

Recent Files (System Settings), Task Manager, Apps, and menus must never show
raw IDs like ``/usr/bin/spectacle``, ``dolphin``, or ``org.kde.krunner``.
This module is the single map those places share.

``ALIASES`` keys are the exact ``initiatingAgent`` / desktop-name strings
KService and KActivities use. Values are (Name, Icon, GenericName).
"""

from __future__ import annotations

import os
import re
from typing import Dict, Optional, Tuple

# Desktop-name / agent id → (clear Name, Icon, GenericName)
ALIASES: Dict[str, Tuple[str, str, str]] = {
    # --- apps from the Recent Files screenshot and everyday tools ---
    "spectacle": ("Snipping Tool", "spectacle", "Screenshot"),
    "org.kde.spectacle": ("Snipping Tool", "spectacle", "Screenshot"),
    "dolphin": ("File Explorer", "system-file-manager", "Files"),
    "org.kde.dolphin": ("File Explorer", "system-file-manager", "Files"),
    "gwenview": ("Photos", "gwenview", "Photo Viewer"),
    "org.kde.gwenview": ("Photos", "gwenview", "Photo Viewer"),
    "systemsettings": ("Settings", "preferences-system", "Control Panel"),
    "org.kde.systemsettings": ("Settings", "preferences-system", "Control Panel"),
    "kdesystemsettings": ("Settings", "preferences-system", "Control Panel"),
    "konsole": ("Terminal", "utilities-terminal", "Command Prompt"),
    "org.kde.konsole": ("Terminal", "utilities-terminal", "Command Prompt"),
    "kate": ("Text Editor", "accessories-text-editor", "Edit documents"),
    "org.kde.kate": ("Text Editor", "accessories-text-editor", "Edit documents"),
    "kwrite": ("Text Editor", "accessories-text-editor", "Edit documents"),
    "org.kde.kwrite": ("Text Editor", "accessories-text-editor", "Edit documents"),
    "okular": ("PDF Viewer", "application-pdf", "Document Viewer"),
    "org.kde.okular": ("PDF Viewer", "application-pdf", "Document Viewer"),
    "ark": ("Zip Folders", "utilities-file-archiver", "Archive Manager"),
    "org.kde.ark": ("Zip Folders", "utilities-file-archiver", "Archive Manager"),
    "kcalc": ("Calculator", "accessories-calculator", "Calculator"),
    "org.kde.kcalc": ("Calculator", "accessories-calculator", "Calculator"),
    "krunner": ("Search", "system-search", "Search"),
    "org.kde.krunner": ("Search", "system-search", "Search"),
    "plasmashell": ("Desktop", "user-desktop", "DevOS Desktop"),
    "org.kde.plasmashell": ("Desktop", "user-desktop", "DevOS Desktop"),
    "org.kde.plasma.kicker": ("Start Menu", "start-here-kde", "Application Menu"),
    "org.kde.plasma.kickoff": ("Start Menu", "start-here-kde", "Application Menu"),
    "org.kde.libtaskmanager": ("Taskbar", "preferences-system-windows", "Window list"),
    "org.kde.plasma.taskmanager": ("Taskbar", "preferences-system-windows", "Window list"),
    "org.kde.plasma.icontasks": ("Taskbar", "preferences-system-windows", "Window list"),
    "org.kde.klipper": ("Clipboard", "edit-paste", "Clipboard History"),
    "klipper": ("Clipboard", "edit-paste", "Clipboard History"),
    "filelight": ("Storage Sense", "filelight", "Disk usage"),
    "org.kde.filelight": ("Storage Sense", "filelight", "Disk usage"),
    "discover": ("Store", "plasmadiscover", "App Store"),
    "org.kde.discover": ("Store", "plasmadiscover", "App Store"),
    "kinfocenter": ("About this PC", "hwinfo", "System information"),
    "org.kde.kinfocenter": ("About this PC", "hwinfo", "System information"),
    "plasma-systemmonitor": ("Performance", "utilities-system-monitor", "Resource Monitor"),
    "org.kde.plasma-systemmonitor": ("Performance", "utilities-system-monitor", "Resource Monitor"),
    "partitionmanager": ("Disk Management", "partitionmanager", "Partitions"),
    "org.kde.partitionmanager": ("Disk Management", "partitionmanager", "Partitions"),
    "elisa": ("Music", "elisa", "Music Player"),
    "org.kde.elisa": ("Music", "elisa", "Music Player"),
    "dragon": ("Videos", "dragonplayer", "Video Player"),
    "org.kde.dragonplayer": ("Videos", "dragonplayer", "Video Player"),
    "kfind": ("Find Files", "edit-find", "File Search"),
    "org.kde.kfind": ("Find Files", "edit-find", "File Search"),
    "kolourpaint": ("Paint", "kolourpaint", "Drawing"),
    "org.kde.kolourpaint": ("Paint", "kolourpaint", "Drawing"),
    "skanlite": ("Scanner", "scanner", "Scan"),
    "org.kde.skanlite": ("Scanner", "scanner", "Scan"),
    "kcharselect": ("Character Map", "accessories-character-map", "Symbols"),
    "org.kde.kcharselect": ("Character Map", "accessories-character-map", "Symbols"),
    "kmag": ("Magnifier", "kmag", "Zoom"),
    "org.kde.kmag": ("Magnifier", "kmag", "Zoom"),
    "kdeconnectd": ("Phone Link", "smartphone", "Phone"),
    "kdeconnect-app": ("Phone Link", "smartphone", "Phone"),
    "org.kde.kdeconnect.app": ("Phone Link", "smartphone", "Phone"),
    "org.kde.kdeconnect.kcm": ("Phone Link", "smartphone", "Phone"),
    "filezilla": ("File Transfer", "filezilla", "FTP"),
    "org.filezilla.FileZilla": ("File Transfer", "filezilla", "FTP"),
    "keepassxc": ("Password Manager", "keepassxc", "Passwords"),
    "org.keepassxc.KeePassXC": ("Password Manager", "keepassxc", "Passwords"),
    "btop": ("Resource Monitor", "utilities-system-monitor", "CPU and memory"),
    "btop++": ("Resource Monitor", "utilities-system-monitor", "CPU and memory"),
    "htop": ("Resource Monitor", "utilities-system-monitor", "CPU and memory"),
    # DevOS first-party
    "devos-files": ("File Explorer", "devos-thispc", "Files"),
    "devos-thispc": ("File Explorer", "devos-thispc", "Files"),
    "devos-snip": ("Snipping Tool", "spectacle", "Screenshot"),
    "devos-photos": ("Photos", "gwenview", "Photo Viewer"),
    "devos-settings": ("Settings", "preferences-system", "Control Panel"),
    "devos-search": ("Search", "devos-search", "Search"),
    "devos-taskman": ("Task Manager", "devos-taskman", "Processes"),
    "devos-chat": ("DevOS AI", "devos-chat", "Assistant"),
    "devos-browser": ("Browser", "devos-browser", "Web browser"),
    "devos-calculator": ("Calculator", "accessories-calculator", "Calculator"),
    "devos-pdf": ("PDF Viewer", "application-pdf", "Documents"),
    "devos-zip": ("Zip Folders", "utilities-file-archiver", "Archives"),
    "devos-phonelink": ("Phone Link", "smartphone", "Phone"),
    "devos-resources": ("Resource Monitor", "devos-resources", "Performance"),
}

# Absolute paths KActivities sometimes stores instead of a desktop id.
PATH_AGENTS = {
    "/usr/bin/spectacle": "spectacle",
    "/usr/bin/dolphin": "dolphin",
    "/usr/bin/gwenview": "gwenview",
    "/usr/bin/systemsettings": "systemsettings",
    "/usr/bin/systemsettings5": "systemsettings",
    "/usr/bin/systemsettings6": "systemsettings",
    "/usr/bin/konsole": "konsole",
    "/usr/bin/kate": "kate",
    "/usr/bin/okular": "okular",
    "/usr/bin/ark": "ark",
    "/usr/bin/kcalc": "kcalc",
    "/usr/bin/krunner": "krunner",
    "/usr/local/bin/devos-files": "devos-files",
    "/usr/local/bin/dolphin": "dolphin",
}

_PATH_TAIL = re.compile(r"[\\/]([^\\/]+)$")
_DESKTOP_SUFFIX = re.compile(r"\.desktop$", re.I)


def canonical_agent(agent: str) -> str:
    """Map a stored agent id to the desktop-name we ship an alias for."""
    text = (agent or "").strip()
    if not text:
        return text
    if text in PATH_AGENTS:
        return PATH_AGENTS[text]
    if text in ALIASES:
        return text
    bare = _DESKTOP_SUFFIX.sub("", text)
    if bare in ALIASES:
        return bare
    if "/" in text or "\\" in text:
        base = os.path.basename(text)
        bare = _DESKTOP_SUFFIX.sub("", base)
        if bare in ALIASES or bare in PATH_AGENTS.values():
            return bare
        mapped = PATH_AGENTS.get(text) or PATH_AGENTS.get("/usr/bin/" + bare)
        if mapped:
            return mapped
        return bare
    return text


def friendly_app_name(agent: str) -> str:
    """Human label for any agent / desktop / path id. Never returns a raw path."""
    text = (agent or "").strip()
    if not text:
        return "App"
    key = canonical_agent(text)
    if key in ALIASES:
        return ALIASES[key][0]
    # org.kde.foo.bar → last segment, titled, when unknown
    if key.startswith("org."):
        tail = key.rsplit(".", 1)[-1]
        if tail and tail not in ("kde", "plasma", "qt"):
            return tail.replace("-", " ").replace("_", " ").title()
    if "/" in key or key.startswith("."):
        return "App"
    if key.islower() and key.isalpha() and len(key) <= 24:
        return key.title()
    return key


def alias_desktop_body(agent: str) -> Optional[str]:
    """Minimal ``.desktop`` so KService::serviceByDesktopName resolves a clear Name."""
    key = canonical_agent(agent)
    info = ALIASES.get(key)
    if not info:
        return None
    name, icon, generic = info
    # Keep NoDisplay so Start menu stays clean; Recent Files still reads Name=.
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={name}\n"
        f"GenericName={generic}\n"
        f"Comment={generic}\n"
        f"Icon={icon}\n"
        "Exec=true\n"
        "Terminal=false\n"
        "NoDisplay=true\n"
        "X-DevOS-FriendlyAlias=true\n"
    )


def looks_technical(name: str) -> bool:
    """True when a label looks like a path, org.kde id, or bare binary."""
    text = (name or "").strip()
    if not text:
        return True
    if "/" in text or text.startswith("org."):
        return True
    if text.lower() in ALIASES and ALIASES[text.lower()][0] != text:
        return True
    if re.fullmatch(r"[a-z0-9_+-]+", text) and text == text.lower() and len(text) < 32:
        return text in ALIASES or text in PATH_AGENTS.values()
    return False
