"""Soft copy of installer choices into the new system.

Replaces stock preservefiles for DevOS app/voice picks. Always succeeds so a
JSON write glitch cannot abort after GRUB is already installed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import libcalamares

DEST = Path("/var/lib/DevOS/install-choices.json")


def pretty_name():
    return "Save installer choices (auto fallback)"


def pretty_status_message():
    return pretty_name()


def run():
    try:
        DEST.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        # Prefer dumping the whole global storage; fall back to known keys.
        try:
            raw = libcalamares.globalstorage.value("json") or None
        except Exception:
            raw = None
        if isinstance(raw, dict):
            data = raw
        else:
            for key in (
                "packagechooser_features",
                "packagechooser_voice",
                "packagechooser_aimodel",
                "packagechooser_usertype",
                "packagechooser_storage",
                "username",
                "hostname",
            ):
                try:
                    val = libcalamares.globalstorage.value(key)
                except Exception:
                    val = None
                if val is not None and val != "":
                    data[key] = val
        DEST.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
        try:
            os.chmod(DEST, 0o400)
        except OSError:
            pass
        try:
            libcalamares.utils.debug("devospreserve: wrote %s (%s keys)" % (DEST, len(data)))
        except Exception:
            pass
    except Exception as exc:
        try:
            libcalamares.utils.warning("devospreserve: %s (continuing)" % exc)
        except Exception:
            pass
        try:
            DEST.parent.mkdir(parents=True, exist_ok=True)
            if not DEST.is_file():
                DEST.write_text("{}\n", encoding="utf-8")
        except OSError:
            pass
    return None
