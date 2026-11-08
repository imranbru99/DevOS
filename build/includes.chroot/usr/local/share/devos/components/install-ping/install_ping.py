#!/usr/bin/env python3
"""Anonymous DevOS install ping (GitHub download count) — deferred if offline.

During install we create a pending stamp and enable a systemd oneshot. This
script GETs a tiny Release asset once; GitHub increments download_count.
No machine-id, hostname, or user data is sent — only a plain HTTP download.

  devos-install-ping --mark-pending   # installer: queue + enable service
  devos-install-ping --once           # try now; exit 1 if offline (retry later)
  devos-install-ping --status
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

STATE_DIR = Path(os.environ.get("DEVOS_INSTALL_PING_DIR", "/var/lib/DevOS"))
PENDING = STATE_DIR / "install-ping.pending"
DONE = STATE_DIR / "install-ping.done"
# Tiny asset on a fixed tag — each successful GET ≈ one install.
DEFAULT_URL = (
    os.environ.get("DEVOS_INSTALL_PING_URL")
    or "https://github.com/imranbru99/DevOS/releases/download/install-ping/devos-install.ping"
)
SERVICE = "devos-install-ping.service"
UA = "DevOS-install-ping/1"


def _online_hint() -> bool:
    """Cheap check: default route or NetworkManager connectivity."""
    try:
        with open("/proc/net/route", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        # destination 00000000 = default route
        for line in lines[1:]:
            parts = line.split()
            if parts and parts[1] == "00000000":
                return True
    except OSError:
        pass
    return False


def mark_pending() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if DONE.is_file():
        return
    PENDING.write_text("pending\n", encoding="utf-8")
    try:
        subprocess.run(
            ["systemctl", "enable", SERVICE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    except OSError:
        pass


def mark_done() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        PENDING.unlink(missing_ok=True)
    except TypeError:
        # py3.7 compat
        if PENDING.is_file():
            PENDING.unlink()
    except OSError:
        pass
    DONE.write_text("done\n", encoding="utf-8")
    try:
        subprocess.run(
            ["systemctl", "disable", "--now", SERVICE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    except OSError:
        pass


def send_ping(url: str = DEFAULT_URL, timeout: float = 25.0) -> bool:
    """Download the ping asset once. Returns True on HTTP success."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "*/*"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # Drain a little so proxies count a completed transfer.
            resp.read(64)
            code = getattr(resp, "status", None) or resp.getcode()
            return 200 <= int(code) < 400
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return False


def run_once(url: str = DEFAULT_URL) -> int:
    if DONE.is_file():
        return 0
    if not PENDING.is_file():
        # Not queued (e.g. upgraded systems) — do nothing.
        return 0
    if not send_ping(url):
        return 1
    mark_done()
    return 0


def status() -> int:
    if DONE.is_file():
        print("done")
        return 0
    if PENDING.is_file():
        print("pending" + (" (route ok)" if _online_hint() else " (waiting for network)"))
        return 0
    print("idle")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="DevOS anonymous install ping")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--mark-pending", action="store_true", help="queue ping (installer)")
    g.add_argument("--once", action="store_true", help="send if pending; fail if offline")
    g.add_argument("--status", action="store_true", help="print pending/done/idle")
    g.add_argument("--force-send", action="store_true", help="send even without pending (test)")
    p.add_argument("--url", default=DEFAULT_URL, help="override ping URL")
    args = p.parse_args(argv)

    if args.status:
        return status()
    if args.mark_pending:
        mark_pending()
        # Best-effort immediate try; ignore failure (service retries later).
        if PENDING.is_file() and not DONE.is_file():
            run_once(args.url)
        return 0
    if args.force_send:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if not PENDING.is_file() and not DONE.is_file():
            PENDING.write_text("pending\n", encoding="utf-8")
        return run_once(args.url)
    if args.once:
        return run_once(args.url)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
