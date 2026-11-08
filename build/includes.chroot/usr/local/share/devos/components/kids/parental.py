#!/usr/bin/env python3
"""Parent PIN for Kids Mode exit (and optional Family Safety linkage).

Stored hashed under ~/.config/devos/parental.json for the current user.
When a PIN is set, Kids Mode requires it before exiting the overlay.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import secrets
import sys
from typing import Optional


CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "devos")
CONFIG_PATH = os.path.join(CONFIG_DIR, "parental.json")


def _load() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_PATH)


def _hash_pin(pin: str, salt: str) -> str:
    raw = (salt + ":" + pin).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def pin_is_set() -> bool:
    data = _load()
    return bool(data.get("kids_exit_pin_hash") and data.get("kids_exit_salt"))


def verify_pin(pin: str) -> bool:
    data = _load()
    salt = data.get("kids_exit_salt") or ""
    expected = data.get("kids_exit_pin_hash") or ""
    if not salt or not expected:
        return True
    if not pin or len(pin) < 4:
        return False
    return secrets.compare_digest(_hash_pin(pin, salt), expected)


def set_pin(pin: str) -> None:
    pin = (pin or "").strip()
    if len(pin) < 4 or len(pin) > 12 or not pin.isdigit():
        raise ValueError("PIN must be 4–12 digits.")
    salt = secrets.token_hex(16)
    data = _load()
    data["kids_exit_pin_hash"] = _hash_pin(pin, salt)
    data["kids_exit_salt"] = salt
    data["kids_exit_enabled"] = True
    _save(data)


def clear_pin() -> None:
    data = _load()
    data.pop("kids_exit_pin_hash", None)
    data.pop("kids_exit_salt", None)
    data["kids_exit_enabled"] = False
    _save(data)


def status() -> dict:
    return {
        "pin_set": pin_is_set(),
        "kids_exit_enabled": bool(_load().get("kids_exit_enabled")) and pin_is_set(),
        "config": CONFIG_PATH,
    }


def prompt_gtk_pin(parent=None) -> bool:
    """Modal GTK PIN prompt. Returns True if exit is allowed."""
    if not pin_is_set():
        return True
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    dialog = Gtk.Dialog(title="Parent PIN", transient_for=parent, modal=True)
    dialog.set_default_size(360, 160)
    dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
    dialog.add_button("Unlock", Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)
    box = dialog.get_content_area()
    box.set_margin_top(16)
    box.set_margin_bottom(8)
    box.set_margin_start(16)
    box.set_margin_end(16)
    box.set_spacing(8)
    label = Gtk.Label(label="Enter the parent PIN to leave Kids Mode.")
    label.set_line_wrap(True)
    box.add(label)
    entry = Gtk.Entry()
    entry.set_visibility(False)
    entry.set_input_purpose(Gtk.InputPurpose.PIN)
    entry.set_max_length(12)
    entry.set_activates_default(True)
    box.add(entry)
    hint = Gtk.Label(label="Set or change with:  devos parental set-pin")
    hint.get_style_context().add_class("dim-label")
    box.add(hint)
    dialog.show_all()
    while True:
        response = dialog.run()
        if response != Gtk.ResponseType.OK:
            dialog.destroy()
            return False
        if verify_pin(entry.get_text().strip()):
            dialog.destroy()
            return True
        entry.set_text("")
        label.set_text("Incorrect PIN. Try again, or Cancel.")


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="DevOS parental PIN for Kids Mode")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("status")
    setp = sub.add_parser("set-pin")
    setp.add_argument("pin", nargs="?", help="4–12 digit PIN (prompted if omitted)")
    sub.add_parser("clear-pin")
    args = parser.parse_args(argv)

    if args.cmd == "status" or args.cmd is None:
        print(json.dumps(status(), indent=2))
        return 0
    if args.cmd == "set-pin":
        pin = args.pin or getpass.getpass("New Kids Mode exit PIN (digits): ")
        confirm = getpass.getpass("Repeat PIN: ")
        if pin != confirm:
            print("PINs do not match.", file=sys.stderr)
            return 1
        try:
            set_pin(pin)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print("Kids Mode exit PIN saved. Children need this PIN to leave Kids Mode.")
        return 0
    if args.cmd == "clear-pin":
        clear_pin()
        print("Kids Mode exit PIN cleared.")
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
