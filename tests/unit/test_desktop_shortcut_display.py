"""File Explorer must show .desktop shortcuts as Name= + Icon= like Windows."""

import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = ROOT / "build/includes.chroot/usr/local/bin/devos-files"


def _extract_def(src: str, name: str) -> str:
    start = src.index(f"def {name}")
    rest = src[start + 4 :]
    nxt = rest.index("\ndef ")
    return src[start : start + 4 + nxt]


def test_devos_files_has_desktop_shortcut_helpers():
    text = FILES.read_text(encoding="utf-8")
    assert "def parse_desktop_entry" in text
    assert "def resolve_desktop_icon" in text
    assert "def entry_display_name" in text
    assert "entry_display_name(" in text


def test_parse_desktop_entry_reads_name_and_icon():
    src = FILES.read_text(encoding="utf-8")
    ns = {"os": os, "_DESKTOP_ENTRY_CACHE": {}}
    exec(_extract_def(src, "parse_desktop_entry"), ns)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "browser.desktop")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=DevOS Browser\n"
                "Icon=devos-browser\n"
                "Comment=Browse the web\n"
                "Exec=/usr/local/bin/devos-browser\n"
            )
        info = ns["parse_desktop_entry"](path)
        assert info["name"] == "DevOS Browser"
        assert info["icon"] == "devos-browser"


def test_entry_display_name_prefers_desktop_name():
    src = FILES.read_text(encoding="utf-8")
    ns = {"os": os, "_DESKTOP_ENTRY_CACHE": {}}
    exec(_extract_def(src, "parse_desktop_entry"), ns)
    exec(_extract_def(src, "entry_display_name"), ns)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "chat.desktop")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[Desktop Entry]\nName=DevOS AI\nIcon=devos-chat\n")
        assert ns["entry_display_name"](path, "chat.desktop", True) == "DevOS AI"
        readme = os.path.join(tmp, "readme.txt")
        open(readme, "w", encoding="utf-8").write("hi")
        assert ns["entry_display_name"](readme, "readme.txt", True) == "readme.txt"
        assert ns["entry_display_name"](readme, "readme.txt", False) == "readme"
