#!/usr/bin/env python3
"""
Visual Network Interfaces page for DevOS Info Center + Network Usage.

Emits table-based HTML (Qt Info Center / QTextBrowser does not support CSS grid/flex).
"""

from __future__ import annotations

import html
import json
import os
import subprocess
import sys
from typing import Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import collector  # noqa: E402

INCLUDE_LOOPBACK = True


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _human(n: int) -> str:
    return collector.human_bytes(n)


def _addrs_for(name: str) -> Dict[str, List[str]]:
    ipv4: List[str] = []
    ipv6: List[str] = []
    try:
        out = subprocess.check_output(
            ["ip", "-j", "address", "show", "dev", name],
            text=True, stderr=subprocess.DEVNULL, timeout=5,
        )
        data = json.loads(out)
    except (OSError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError):
        data = []
    for block in data if isinstance(data, list) else []:
        for addr in block.get("addr_info") or []:
            local = addr.get("local") or ""
            prefix = addr.get("prefixlen")
            if not local:
                continue
            label = f"{local}/{prefix}" if prefix is not None else local
            fam = addr.get("family")
            if fam == "inet":
                ipv4.append(label)
            elif fam == "inet6":
                ipv6.append(label)
    return {"ipv4": ipv4, "ipv6": ipv6}


def _proc_stats(name: str) -> Dict[str, int]:
    try:
        with open("/proc/net/dev", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return {}
    for line in lines[2:]:
        if ":" not in line:
            continue
        iface, rest = line.split(":", 1)
        if iface.strip() != name:
            continue
        parts = rest.split()
        if len(parts) < 16:
            return {}
        try:
            return {
                "rx_bytes": int(parts[0]),
                "rx_packets": int(parts[1]),
                "rx_errs": int(parts[2]),
                "rx_drop": int(parts[3]),
                "tx_bytes": int(parts[8]),
                "tx_packets": int(parts[9]),
                "tx_errs": int(parts[10]),
                "tx_drop": int(parts[11]),
            }
        except ValueError:
            return {}
    return {}


def list_interface_cards(include_loopback: bool = INCLUDE_LOOPBACK) -> List[Dict]:
    try:
        names = sorted(os.listdir("/sys/class/net"))
    except OSError:
        return []
    cards = []
    for name in names:
        if name.startswith(("veth", "br-", "tun", "tap", "docker", "podman", "virbr")):
            continue
        if name == "lo" and not include_loopback:
            continue
        meta = collector.iface_meta(name)
        addrs = _addrs_for(name)
        stats = _proc_stats(name)
        mtu = _read(f"/sys/class/net/{name}/mtu")
        online = meta.get("state") == "up" or (name == "lo")
        cards.append({
            **meta,
            "title": "Loopback (this PC only)" if name == "lo" else collector.friendly_iface_title(meta),
            "mtu": mtu,
            "ipv4": addrs["ipv4"],
            "ipv6": addrs["ipv6"],
            "rx_bytes": stats.get("rx_bytes", 0),
            "tx_bytes": stats.get("tx_bytes", 0),
            "rx_packets": stats.get("rx_packets", 0),
            "tx_packets": stats.get("tx_packets", 0),
            "rx_drop": stats.get("rx_drop", 0),
            "online": online,
        })
    cards.sort(key=lambda c: (c["name"] == "lo", c["name"]))
    return cards


def _stat_cell(label: str, value: str, accent: bool = False) -> str:
    color = "#7dd3fc" if accent else "#e2e8f0"
    return (
        f'<td width="50%" style="padding:8px 10px; vertical-align:top;">'
        f'<div style="color:#64748b; font-size:10px; font-weight:700; '
        f'letter-spacing:0.6px; text-transform:uppercase;">{html.escape(label)}</div>'
        f'<div style="margin-top:4px; color:{color}; font-size:13px; font-weight:600; '
        f'word-wrap:break-word;">{html.escape(value)}</div></td>'
    )


def render_info_center_html(dark: bool = True) -> str:
    """Table-based HTML cards — works inside Info Center’s QTextBrowser."""
    cards = list_interface_cards()
    bg = "#0b1220" if dark else "#f8fafc"
    fg = "#e2e8f0" if dark else "#0f172a"
    muted = "#94a3b8" if dark else "#64748b"
    card_bg = "#0f172a" if dark else "#ffffff"
    border = "#1e293b" if dark else "#cbd5e1"

    parts = [
        f'<html><head><meta charset="utf-8"></head>'
        f'<body style="margin:0; padding:16px 18px 24px; background:{bg}; color:{fg}; '
        f'font-family:\'Noto Sans\',\'Segoe UI\',sans-serif; font-size:13px;">'
        f'<h1 style="margin:0 0 4px; font-size:22px; color:{fg};">Network Interfaces</h1>'
        f'<p style="margin:0 0 16px; color:{muted}; font-size:12px;">'
        f'Visual overview — friendly names, IP addresses, and traffic since boot.</p>'
    ]

    if not cards:
        parts.append(
            f'<div style="padding:16px; background:{card_bg}; border:1px solid {border}; '
            f'border-radius:12px; color:{muted};">No network interfaces found.</div>'
        )

    for c in cards:
        on = bool(c.get("online"))
        status = "Connected" if on else (c.get("state_label") or "Down")
        status_color = "#4ade80" if on else "#f87171"
        ipv4 = ", ".join(c.get("ipv4") or []) or "—"
        ipv6 = ", ".join(c.get("ipv6") or []) or "—"
        mac = c.get("mac") or "—"
        speed = c.get("speed") or ("Loopback" if c["name"] == "lo" else "—")
        mtu = c.get("mtu") or "—"
        title = html.escape(c.get("title") or c["name"])
        tech = html.escape(c.get("name") or "")

        parts.append(
            f'<table width="100%" cellspacing="0" cellpadding="0" '
            f'style="margin:0 0 14px; background:{card_bg}; border:1px solid {border}; '
            f'border-radius:14px; border-collapse:separate;">'
            f'<tr><td style="padding:14px 16px 8px;">'
            f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td style="width:14px; vertical-align:middle;">'
            f'<div style="width:10px; height:10px; border-radius:5px; '
            f'background:{status_color};"></div></td>'
            f'<td style="vertical-align:middle; padding-left:8px;">'
            f'<div style="font-size:16px; font-weight:700; color:{fg};">{title}</div>'
            f'<div style="font-size:11px; color:{muted}; margin-top:2px;">'
            f'ID: {tech} · MTU {html.escape(str(mtu))}</div></td>'
            f'<td align="right" style="vertical-align:middle;">'
            f'<span style="color:{status_color}; font-size:11px; font-weight:700; '
            f'text-transform:uppercase; letter-spacing:0.5px; '
            f'border:1px solid {status_color}; border-radius:999px; '
            f'padding:3px 10px;">{html.escape(status)}</span></td>'
            f'</tr></table></td></tr>'
            f'<tr><td style="padding:4px 10px 14px;">'
            f'<table width="100%" cellspacing="6" cellpadding="0">'
            f'<tr>{_stat_cell("IPv4 address", ipv4, True)}'
            f'{_stat_cell("IPv6 address", ipv6)}</tr>'
            f'<tr>{_stat_cell("MAC address", mac)}'
            f'{_stat_cell("Link speed", speed, True)}</tr>'
            f'<tr>{_stat_cell("Downloaded (RX)", _human(c.get("rx_bytes") or 0), True)}'
            f'{_stat_cell("Uploaded (TX)", _human(c.get("tx_bytes") or 0), True)}</tr>'
            f'<tr>{_stat_cell("RX packets", format(c.get("rx_packets") or 0, ","))}'
            f'{_stat_cell("TX packets", format(c.get("tx_packets") or 0, ","))}</tr>'
            f'</table></td></tr></table>'
        )

    parts.append(
        f'<p style="margin:8px 0 0; color:{muted}; font-size:11px;">'
        f'Open <b>Network Usage</b> for weekly / monthly / yearly graphs. '
        f'Traffic totals above are since last boot.</p></body></html>'
    )
    return "".join(parts)


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    dark = True
    if argv:
        if argv[0] in ("0", "light", "--light"):
            dark = False
        elif argv[0] in ("1", "dark", "--dark") or (argv[0].isdigit() and argv[0] == "1"):
            dark = True
        elif argv[0].isdigit():
            dark = argv[0] != "0"
    sys.stdout.write(render_info_center_html(dark=dark))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
