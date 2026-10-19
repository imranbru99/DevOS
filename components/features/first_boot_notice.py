#!/usr/bin/env python3
"""
DevOS first-boot apps notice (user autostart).

The installer only removes unticked built-ins; the apps people picked are
downloaded by devos-features.service once the PC is online. This script tells
the person what is going on with one notification, waits quietly, and sends
one more when the downloads are done (or which ones failed).

Exits at once when nothing is pending, so it costs nothing on normal logins.
The message builders are pure functions so they can be unit-tested anywhere.
"""

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import feature_catalog as catalog  # noqa: E402

STATE_FILE = "/var/lib/DevOS/features/state.json"
POLL_SECONDS = 30
MAX_WAIT_SECONDS = 3 * 3600
APP_LABEL = "DevOS"
ICON = "system-software-install"
DONE_MARKER = os.path.expanduser("~/.config/devos/first_boot_notice.done")


def mark_done() -> None:
    try:
        os.makedirs(os.path.dirname(DONE_MARKER), exist_ok=True)
        with open(DONE_MARKER, "w", encoding="utf-8") as handle:
            handle.write(str(int(time.time())))
    except OSError:
        pass


def read_state(path: str = STATE_FILE) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def names(ids):
    out = []
    for fid in ids:
        feature = catalog.feature(fid)
        out.append(feature["name"] if feature else fid)
    return out


def pending_ids(state: dict):
    return [p for p in (state.get("pending") or []) if isinstance(p, str)]


def failed_ids(state: dict):
    failed = state.get("failed") or {}
    return list(failed) if isinstance(failed, dict) else []


def needs_notice(state: dict) -> bool:
    if os.path.exists(DONE_MARKER) and not state.get("running"):
        return False
    return bool(state.get("running")) or bool(pending_ids(state))


def is_finished(state: dict, start_state: dict, seen_running: bool) -> bool:
    """Done once the service is idle again after having had a go: it was seen
    running, or state.json changed since we started, or nothing is left."""
    if state.get("running"):
        return False
    if not pending_ids(state):
        return True
    changed = state.get("updated") != start_state.get("updated")
    return seen_running or changed or bool(failed_ids(state))


def start_message(state: dict):
    count = len(pending_ids(state))
    if count:
        what = f"{count} app{'s' if count != 1 else ''} you picked during install"
    else:
        what = "the apps you picked during install"
    return ("Setting up your apps",
            f"DevOS is downloading {what}. You can keep using your PC; "
            "we'll let you know when everything is ready.")


def done_message(state: dict):
    missing = []
    for fid in failed_ids(state) + pending_ids(state):
        if fid not in missing:
            missing.append(fid)
    if missing:
        return ("Some apps didn't install",
                "These apps couldn't be downloaded: " + ", ".join(names(missing)) +
                ". Open DevOS Features to try again.")
    return ("Your apps are ready", "Everything you picked during install is now installed.")


def notify(title: str, body: str) -> None:
    try:
        subprocess.run(["notify-send", "-a", APP_LABEL, "-i", ICON, title, body], timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass


def refresh_menu() -> None:
    """Show newly installed apps in the Start menu right away. KDE only rebuilds
    its menu cache when it notices a change, and apps downloaded after sign-in
    (Flatpaks especially) stayed missing until the next login."""
    for cmd in (["kbuildsycoca5", "--noincremental"], ["kbuildsycoca6", "--noincremental"]):
        try:
            subprocess.run(cmd, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except (OSError, subprocess.SubprocessError):
            continue


def installed_count(state: dict) -> int:
    return len(state.get("installed") or [])


def main() -> int:
    start = read_state()
    if not needs_notice(start):
        return 0
    notify(*start_message(start))
    seen_running = bool(start.get("running"))
    pending = len(start.get("pending") or [])
    deadline = time.time() + MAX_WAIT_SECONDS
    while time.time() < deadline:
        time.sleep(POLL_SECONDS)
        state = read_state()
        seen_running = seen_running or bool(state.get("running"))
        now_pending = len(state.get("pending") or [])
        if now_pending < pending:
            refresh_menu()        # some apps just finished: show them now
        pending = now_pending
        if is_finished(state, start, seen_running):
            refresh_menu()
            notify(*done_message(state))
            mark_done()
            return 0
    mark_done()
    return 0


if __name__ == "__main__":
    sys.exit(main())
