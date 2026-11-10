"""Persist the installer selections inside the mounted target."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import libcalamares

KEYS = (
    "devos_selected_features",
    "packagechooser_features",
    "features",
    "packagechooser_voice",
    "packagechooser_aimodel",
    "packagechooser_usertype",
    "packagechooser_storage",
    "username",
    "hostname",
)


def pretty_name():
    return "Save installer choices"


def pretty_status_message():
    return pretty_name()


def run():
    temporary = None
    try:
        root = libcalamares.globalstorage.value("rootMountPoint")
        if not root or not os.path.ismount(root):
            raise OSError("the installed system is not mounted")
        dest = Path(root) / "var/lib/DevOS/install-choices.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        values = {key: libcalamares.globalstorage.value(key) for key in KEYS}
        data = {key: value for key, value in values.items() if value is not None}
        with tempfile.NamedTemporaryFile(
            dir=dest.parent, prefix=".install-choices-", mode="w", encoding="utf-8", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, indent=2)
        os.replace(temporary, dest)
    except (OSError, ValueError, TypeError) as exc:
        libcalamares.utils.warning(f"devospreserve: could not save target choices: {exc}")
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return None
