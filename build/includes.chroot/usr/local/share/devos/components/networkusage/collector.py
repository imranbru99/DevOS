#!/usr/bin/env python3
"""
DevOS Network Usage collector.

Samples /proc/net/dev, accumulates per-interface daily rx/tx bytes, keeps only
the last 12 months, and exposes helpers for the GUI.
"""

from __future__ import annotations

import json
import os
import time
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

RETENTION_DAYS = 366  # ~12 months; prune anything older
SKIP_IFACES = frozenset({"lo", "docker0", "podman0", "virbr0"})
DATA_DIR_NAME = "network-usage"
DATA_FILE = "usage.json"


def data_dir() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    path = os.path.join(base, "devos", DATA_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def data_path() -> str:
    return os.path.join(data_dir(), DATA_FILE)


def read_counters() -> Dict[str, Dict[str, int]]:
    """iface -> {rx, tx} from /proc/net/dev (skip loopback / virtual bridges)."""
    out: Dict[str, Dict[str, int]] = {}
    try:
        with open("/proc/net/dev", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return out
    for line in lines[2:]:
        if ":" not in line:
            continue
        name, rest = line.split(":", 1)
        iface = name.strip()
        if not iface or iface in SKIP_IFACES or iface.startswith(("veth", "br-", "tun", "tap", "wg")):
            continue
        parts = rest.split()
        if len(parts) < 9:
            continue
        try:
            rx, tx = int(parts[0]), int(parts[8])
        except ValueError:
            continue
        out[iface] = {"rx": rx, "tx": tx}
    return out


def iface_meta(name: str) -> Dict[str, str]:
    """Best-effort type / operstate / address for the GUI."""
    base = f"/sys/class/net/{name}"
    kind = "Ethernet"
    friendly = "Ethernet (cable)"
    if name.startswith(("wl", "wlan")):
        kind = "Wi‑Fi"
        friendly = "Wi‑Fi"
    elif name.startswith("ww"):
        kind = "Mobile"
        friendly = "Mobile data"
    elif name.startswith(("en", "eth")):
        kind = "Ethernet"
        friendly = "Ethernet (cable)"
    elif name.startswith(("usb", "rndis", "cdc")):
        kind = "USB"
        friendly = "USB network"
    oper = _read_sys(f"{base}/operstate") or "unknown"
    mac = _read_sys(f"{base}/address") or ""
    speed = _read_sys(f"{base}/speed") or ""
    state_label = {
        "up": "Connected",
        "down": "Disconnected",
        "dormant": "Sleeping",
        "unknown": "Unknown",
    }.get(oper, oper)
    return {
        "name": name,
        "kind": kind,
        "friendly": friendly,
        "state": oper,
        "state_label": state_label,
        "mac": mac,
        "speed": (speed + " Mb/s") if speed.lstrip("-").isdigit() and int(speed) > 0 else "",
    }


def friendly_iface_title(meta: Dict[str, str]) -> str:
    """Human label people understand — not enp0s31f6."""
    return meta.get("friendly") or meta.get("kind") or "Network"


def _read_sys(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def load_store(path: Optional[str] = None) -> dict:
    path = path or data_path()
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and "ifaces" in data:
            return data
    except (OSError, ValueError):
        pass
    return {"version": 1, "ifaces": {}}


def save_store(data: dict, path: Optional[str] = None) -> None:
    path = path or data_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def prune_old_days(days: Dict[str, dict], today: Optional[date] = None) -> Dict[str, dict]:
    today = today or date.today()
    cutoff = today - timedelta(days=RETENTION_DAYS)
    keep = {}
    for key, val in days.items():
        try:
            d = date.fromisoformat(key)
        except ValueError:
            continue
        if d >= cutoff:
            keep[key] = val
    return keep


def sample_once(path: Optional[str] = None, now: Optional[datetime] = None) -> dict:
    """Read counters, add deltas to today's totals, prune >12 months, save."""
    now = now or datetime.now()
    today = now.date().isoformat()
    store = load_store(path)
    ifaces = store.setdefault("ifaces", {})
    counters = read_counters()
    for name, cur in counters.items():
        slot = ifaces.setdefault(name, {"last_rx": 0, "last_tx": 0, "days": {}})
        days = slot.setdefault("days", {})
        last_rx = int(slot.get("last_rx") or 0)
        last_tx = int(slot.get("last_tx") or 0)
        rx, tx = int(cur["rx"]), int(cur["tx"])
        # Counter reset (reboot / iface recreated): start fresh from this sample.
        d_rx = max(0, rx - last_rx) if rx >= last_rx else 0
        d_tx = max(0, tx - last_tx) if tx >= last_tx else 0
        if d_rx or d_tx:
            day = days.setdefault(today, {"rx": 0, "tx": 0})
            day["rx"] = int(day.get("rx") or 0) + d_rx
            day["tx"] = int(day.get("tx") or 0) + d_tx
        slot["last_rx"] = rx
        slot["last_tx"] = tx
        slot["days"] = prune_old_days(days, now.date())
        slot["updated"] = now.isoformat(timespec="seconds")
    # Drop ifaces that disappeared and have no recent days
    for name in list(ifaces.keys()):
        if name not in counters and not ifaces[name].get("days"):
            del ifaces[name]
    store["sampled_at"] = now.isoformat(timespec="seconds")
    save_store(store, path)
    return store


def human_bytes(n: int) -> str:
    n = max(0, int(n or 0))
    for unit, div in (("TB", 1024 ** 4), ("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if n >= div:
            val = n / div
            return f"{val:.2f} {unit}" if val < 10 or unit == "TB" else f"{val:.1f} {unit}"
    return f"{n} B"


def day_range(n: int = 30, end: Optional[date] = None) -> List[date]:
    end = end or date.today()
    return [end - timedelta(days=i) for i in range(n - 1, -1, -1)]


def daily_totals(store: dict, iface: Optional[str] = None, days: int = 30) -> List[Dict]:
    """Per-day rx/tx for the last `days` (zeros when missing)."""
    ifaces = store.get("ifaces") or {}
    names = [iface] if iface and iface in ifaces else list(ifaces.keys())
    out = []
    for d in day_range(days):
        key = d.isoformat()
        rx = tx = 0
        for name in names:
            day = ((ifaces.get(name) or {}).get("days") or {}).get(key) or {}
            rx += int(day.get("rx") or 0)
            tx += int(day.get("tx") or 0)
        out.append({"date": key, "rx": rx, "tx": tx, "total": rx + tx})
    return out


def weekly_totals(store: dict, iface: Optional[str] = None) -> List[Dict]:
    """Last 7 days (weekday labels) — default opening view."""
    rows = daily_totals(store, iface, days=7)
    for row in rows:
        try:
            d = date.fromisoformat(row["date"])
            row["label"] = d.strftime("%a %d")  # e.g. Sat 08
        except ValueError:
            row["label"] = row["date"][5:]
    return rows


def current_month_days(store: dict, iface: Optional[str] = None) -> List[Dict]:
    """Per-day rows for the current calendar month only (1 … today)."""
    ifaces = store.get("ifaces") or {}
    names = [iface] if iface and iface in ifaces else list(ifaces.keys())
    today = date.today()
    out = []
    for day_n in range(1, today.day + 1):
        d = date(today.year, today.month, day_n)
        key = d.isoformat()
        rx = tx = 0
        for name in names:
            day = ((ifaces.get(name) or {}).get("days") or {}).get(key) or {}
            rx += int(day.get("rx") or 0)
            tx += int(day.get("tx") or 0)
        out.append({
            "date": key,
            "label": d.strftime("%d"),
            "rx": rx,
            "tx": tx,
            "total": rx + tx,
        })
    return out


def sum_rows(rows: List[Dict]) -> Dict[str, int]:
    rx = sum(int(r.get("rx") or 0) for r in rows)
    tx = sum(int(r.get("tx") or 0) for r in rows)
    return {"rx": rx, "tx": tx, "total": rx + tx}


def month_focus_summary(store: dict, iface: Optional[str] = None) -> List[Dict]:
    """Premium Monthly table: This week + This month only."""
    week = sum_rows(weekly_totals(store, iface))
    month = sum_rows(current_month_days(store, iface))
    today = date.today()
    return [
        {
            "label": "This week",
            "sub": "Last 7 days",
            "rx": week["rx"],
            "tx": week["tx"],
            "total": week["total"],
        },
        {
            "label": "This month",
            "sub": today.strftime("%B %Y"),
            "rx": month["rx"],
            "tx": month["tx"],
            "total": month["total"],
        },
    ]


def monthly_totals(store: dict, iface: Optional[str] = None, months: int = 12) -> List[Dict]:
    """Last `months` calendar months of usage (oldest first) — Yearly panel content."""
    ifaces = store.get("ifaces") or {}
    names = [iface] if iface and iface in ifaces else list(ifaces.keys())
    today = date.today()
    out = []
    for i in range(months - 1, -1, -1):
        y = today.year
        m = today.month - i
        while m <= 0:
            m += 12
            y -= 1
        prefix = f"{y:04d}-{m:02d}-"
        rx = tx = 0
        for name in names:
            for key, day in ((ifaces.get(name) or {}).get("days") or {}).items():
                if key.startswith(prefix):
                    rx += int(day.get("rx") or 0)
                    tx += int(day.get("tx") or 0)
        label = date(y, m, 1).strftime("%b %Y")
        out.append({
            "date": f"{y:04d}-{m:02d}",
            "month": f"{y:04d}-{m:02d}",
            "label": label,
            "rx": rx,
            "tx": tx,
            "total": rx + tx,
        })
    return out


def list_tracked_ifaces(store: Optional[dict] = None) -> List[Dict[str, str]]:
    store = store or load_store()
    live = read_counters()
    names = sorted(set(live) | set(store.get("ifaces") or {}))
    rows = []
    for name in names:
        meta = iface_meta(name)
        slot = (store.get("ifaces") or {}).get(name) or {}
        today = ((slot.get("days") or {}).get(date.today().isoformat()) or {})
        meta["today_rx"] = int(today.get("rx") or 0)
        meta["today_tx"] = int(today.get("tx") or 0)
        meta["today_total"] = meta["today_rx"] + meta["today_tx"]
        meta["online"] = name in live
        rows.append(meta)
    return rows


if __name__ == "__main__":
    store = sample_once()
    print(json.dumps({"sampled_at": store.get("sampled_at"), "ifaces": list(store.get("ifaces") or {})}, indent=2))
