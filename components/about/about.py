#!/usr/bin/env python3
"""DevOS About this PC — visual system information (replaces stock KInfoCenter)."""

from __future__ import annotations

import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import QRectF, Qt, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

APP_ID = "devos-about"
APP_TITLE = "About this PC"

# Public Help Center contacts — keep in sync with assistant ABOUT_TEXT / DEVOS_CONTACTS.
HELP_CONTACTS = (
    ("Contact form", "https://imrandev.bd/contact", "imrandev.bd/contact"),
    ("Email", "mailto:me@imrandev.bd", "me@imrandev.bd"),
    ("LinkedIn", "https://linkedin.com/in/imranbru99", "linkedin.com/in/imranbru99"),
    ("GitHub", "https://github.com/imranbru99", "github.com/imranbru99"),
    ("WhatsApp", "https://wa.me/+8801576918420", "wa.me/+8801576918420"),
    ("Portfolio", "https://imrandev.bd/", "imrandev.bd"),
    ("DevOS source", "https://github.com/imranbru99/DevOS", "github.com/imranbru99/DevOS"),
)

BG = "#0b1220"
SIDE = "#0f172a"
CARD = "#111827"
CARD_BORDER = "#1f2937"
TEXT = "#f8fafc"
MUTED = "#94a3b8"
ACCENT = "#38bdf8"
GOOD = "#34d399"
WARN = "#fbbf24"
BAD = "#f87171"


def _run(cmd: List[str], timeout: float = 4.0) -> str:
    try:
        return subprocess.check_output(
            cmd, stderr=subprocess.DEVNULL, timeout=timeout, text=True, errors="replace"
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _human(n: int) -> str:
    n = max(0, int(n or 0))
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    size = float(n)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{n} B"


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def gather() -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "os_name": "DevOS",
        "os_version": "",
        "kernel": platform.release(),
        "hostname": socket.gethostname() or "DevOS-PC",
        "arch": platform.machine() or "",
        "cpu_model": "Processor",
        "cpu_cores": 0,
        "cpu_threads": 0,
        "cpu_mhz": 0.0,
        "ram_total": 0,
        "ram_available": 0,
        "ram_used": 0,
        "gpus": [],
        "disks": [],
        "volumes": [],
        "usb": [],
        "network": [],
        "battery": None,
        "power": [],
        "audio_sinks": [],
        "audio_sources": [],
        "cameras": [],
        "pci": [],
        "sensors": [],
        "interrupts": [],
        "firmware_devices": [],
        "samba": {"installed": False, "active": False, "shares": [], "note": ""},
        "edid": [],
        "secure_boot": None,
        "uptime_sec": 0.0,
        "displays": [],
    }

    osr = _read("/etc/os-release")
    for line in osr.splitlines():
        if line.startswith("PRETTY_NAME="):
            data["os_name"] = line.split("=", 1)[1].strip().strip('"') or "DevOS"
        elif line.startswith("VERSION="):
            data["os_version"] = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("VERSION_ID=") and not data["os_version"]:
            data["os_version"] = line.split("=", 1)[1].strip().strip('"')

    cpu = _read("/proc/cpuinfo")
    models = re.findall(r"^model name\s*:\s*(.+)$", cpu, re.M)
    if models:
        data["cpu_model"] = models[0].strip()
    siblings = re.findall(r"^siblings\s*:\s*(\d+)", cpu, re.M)
    cores = re.findall(r"^cpu cores\s*:\s*(\d+)", cpu, re.M)
    processors = re.findall(r"^processor\s*:", cpu, re.M)
    data["cpu_threads"] = int(siblings[0]) if siblings else len(processors)
    data["cpu_cores"] = int(cores[0]) if cores else data["cpu_threads"]
    mhz = re.findall(r"^cpu MHz\s*:\s*([\d.]+)", cpu, re.M)
    if mhz:
        data["cpu_mhz"] = float(mhz[0])

    mem = _read("/proc/meminfo")
    def mem_kb(key: str) -> int:
        m = re.search(rf"^{key}:\s+(\d+)", mem, re.M)
        return int(m.group(1)) * 1024 if m else 0

    data["ram_total"] = mem_kb("MemTotal")
    data["ram_available"] = mem_kb("MemAvailable")
    data["ram_used"] = max(0, data["ram_total"] - data["ram_available"])

    up = _read("/proc/uptime").split()
    if up:
        try:
            data["uptime_sec"] = float(up[0])
        except ValueError:
            pass

    # Volumes
    for path, label in (("/", "System"), (os.path.expanduser("~"), "Home")):
        try:
            usage = shutil.disk_usage(path)
            data["volumes"].append(
                {
                    "label": label,
                    "path": path,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                }
            )
        except OSError:
            pass

    # Physical disks
    lsblk = _run(["lsblk", "-J", "-b", "-d", "-o", "NAME,SIZE,MODEL,ROTA,TYPE,TRAN"])
    if lsblk:
        try:
            import json

            payload = json.loads(lsblk)
            for blk in payload.get("blockdevices") or []:
                if blk.get("type") != "disk":
                    continue
                size = int(blk.get("size") or 0)
                rota = blk.get("rota")
                kind = "HDD" if str(rota) in ("1", "true", "True") else "SSD"
                tran = (blk.get("tran") or "").upper()
                data["disks"].append(
                    {
                        "name": blk.get("name") or "disk",
                        "model": (blk.get("model") or "").strip() or "Storage device",
                        "size": size,
                        "kind": kind,
                        "bus": tran or "—",
                    }
                )
        except Exception:
            pass

    # PCI + GPUs
    lspci = _run(["lspci"])
    for line in lspci.splitlines():
        line = line.strip()
        if not line:
            continue
        slot, _, desc = line.partition(" ")
        desc = desc.strip() or line
        data["pci"].append({"slot": slot, "desc": desc})
        if re.search(r"\b(VGA|3D|Display)\b", line):
            data["gpus"].append(desc or "Graphics adapter")
    if not data["gpus"]:
        data["gpus"] = ["No discrete/PCI display adapter reported"]

    # USB
    lsusb = _run(["lsusb"])
    for line in lsusb.splitlines():
        m = re.match(r"Bus (\d+) Device (\d+):\s+ID\s+([0-9a-fA-F:]+)\s+(.*)$", line)
        if not m:
            continue
        data["usb"].append(
            {
                "bus": m.group(1),
                "device": m.group(2),
                "id": m.group(3),
                "name": m.group(4).strip() or "USB device",
            }
        )

    # Network
    if shutil.which("nmcli"):
        out = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"])
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 4 and parts[1] in ("wifi", "ethernet", "gsm", "bt"):
                data["network"].append(
                    {
                        "device": parts[0],
                        "type": parts[1],
                        "state": parts[2],
                        "connection": parts[3] or "—",
                    }
                )
    if not data["network"]:
        for iface in os.listdir("/sys/class/net") if os.path.isdir("/sys/class/net") else []:
            if iface == "lo":
                continue
            oper = _read(f"/sys/class/net/{iface}/operstate").strip() or "unknown"
            data["network"].append(
                {"device": iface, "type": "link", "state": oper, "connection": iface}
            )

    # Energy / power supplies
    power = "/sys/class/power_supply"
    if os.path.isdir(power):
        for name in sorted(os.listdir(power)):
            base = os.path.join(power, name)
            typ = _read(os.path.join(base, "type")).strip() or "Unknown"
            status = _read(os.path.join(base, "status")).strip() or "—"
            online = _read(os.path.join(base, "online")).strip()
            cap = _read(os.path.join(base, "capacity")).strip()
            try:
                capacity = int(cap) if cap else None
            except ValueError:
                capacity = None
            entry = {
                "name": name,
                "type": typ,
                "status": status,
                "online": online,
                "capacity": capacity,
            }
            data["power"].append(entry)
            if typ == "Battery" and data["battery"] is None:
                data["battery"] = {
                    "name": name,
                    "capacity": capacity,
                    "status": status if status != "—" else "Unknown",
                }

    # Audio (PipeWire / Pulse)
    if shutil.which("pactl"):
        for kind, key in (("sinks", "audio_sinks"), ("sources", "audio_sources")):
            out = _run(["pactl", "list", "short", kind])
            for line in out.splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    data[key].append(
                        {
                            "id": parts[0],
                            "name": parts[1],
                            "state": parts[4] if len(parts) > 4 else (parts[3] if len(parts) > 3 else "—"),
                        }
                    )
    elif shutil.which("wpctl"):
        out = _run(["wpctl", "status"])
        section = None
        for line in out.splitlines():
            low = line.strip().lower()
            if low.startswith("sinks:"):
                section = "audio_sinks"
                continue
            if low.startswith("sources:"):
                section = "audio_sources"
                continue
            if section and re.match(r"^\s*\*?\.?\s*\d+\.", line):
                name = re.sub(r"^\s*\*?\.?\s*\d+\.\s*", "", line).strip()
                data[section].append({"id": "", "name": name, "state": "—"})

    # Cameras (V4L2) — always-on OS basic
    try:
        components = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if components not in sys.path:
            sys.path.insert(0, components)
        from audio.camera_defaults import list_cameras
        for cam in list_cameras():
            data["cameras"].append(
                {
                    "name": cam.get("name") or cam.get("device") or "Camera",
                    "device": cam.get("device") or "",
                    "usb": bool(cam.get("usb")),
                }
            )
    except Exception:
        pass

    # Sensors (thermal zones + optional lm-sensors)
    thermal = "/sys/class/thermal"
    if os.path.isdir(thermal):
        for name in sorted(os.listdir(thermal)):
            if not name.startswith("thermal_zone"):
                continue
            base = os.path.join(thermal, name)
            typ = _read(os.path.join(base, "type")).strip() or name
            raw = _read(os.path.join(base, "temp")).strip()
            try:
                temp_c = int(raw) / 1000.0
            except ValueError:
                continue
            data["sensors"].append({"name": typ, "value": f"{temp_c:.1f} °C", "kind": "thermal"})
    if shutil.which("sensors"):
        sens = _run(["sensors", "-A"])
        chip = "Sensors"
        for line in sens.splitlines():
            if not line.strip():
                continue
            if ":" not in line and not line.startswith(" "):
                chip = line.strip()
                continue
            m = re.match(r"^\s*([^:]+):\s*([+\-]?\d+(?:\.\d+)?\s*°C)", line)
            if m:
                label = f"{chip} · {m.group(1).strip()}"
                if not any(s["name"] == label for s in data["sensors"]):
                    data["sensors"].append(
                        {"name": label, "value": m.group(2).strip(), "kind": "sensor"}
                    )

    # Interrupts (top by total count)
    irq_lines = _read("/proc/interrupts").splitlines()
    irq_rows = []
    for line in irq_lines[1:]:
        parts = line.split()
        if len(parts) < 3:
            continue
        name = parts[0].rstrip(":")
        nums = []
        for p in parts[1:]:
            if p.isdigit():
                nums.append(int(p))
            else:
                break
        if not nums:
            continue
        label = " ".join(parts[1 + len(nums) :]) or name
        irq_rows.append({"irq": name, "count": sum(nums), "label": label})
    irq_rows.sort(key=lambda r: r["count"], reverse=True)
    data["interrupts"] = irq_rows[:24]

    # Firmware devices (optional fwupd — never required for a useful page)
    if shutil.which("fwupdmgr"):
        fw = _run(["fwupdmgr", "get-devices"], timeout=8.0)
        block_name = None
        for line in fw.splitlines():
            if not line.startswith(" ") and line.strip().endswith(":"):
                block_name = line.strip().rstrip(":")
            elif "Device ID:" in line and block_name:
                data["firmware_devices"].append(block_name)
                block_name = None
            elif re.match(r"^[│├└].*─\s+\S", line):
                name = re.sub(r"^.*─\s+", "", line).strip()
                if name and name not in data["firmware_devices"]:
                    data["firmware_devices"].append(name)

    # Samba / file sharing status
    samba = data["samba"]
    samba["installed"] = bool(shutil.which("smbd") or shutil.which("samba"))
    if shutil.which("systemctl"):
        st = _run(["systemctl", "is-active", "smbd"]).strip().lower()
        samba["active"] = st == "active"
        if not samba["active"]:
            st2 = _run(["systemctl", "is-active", "nmbd"]).strip().lower()
            samba["active"] = st2 == "active"
    if samba["installed"] and shutil.which("smbstatus"):
        shares = _run(["smbstatus", "-S"], timeout=3.0)
        for line in shares.splitlines()[1:]:
            parts = line.split()
            if parts:
                samba["shares"].append(parts[0])
    if not samba["installed"]:
        samba["note"] = (
            "Windows-style file sharing (Samba) is not installed. "
            "Use Settings → Network or DevOS Features if you need shared folders."
        )
    elif samba["active"]:
        samba["note"] = "Samba is running — this PC can share folders on the local network."
    else:
        samba["note"] = "Samba is installed but not running right now."

    # Secure Boot
    efi = os.path.isdir("/sys/firmware/efi")
    sb = None
    mok = _run(["mokutil", "--sb-state"]).lower()
    if "enabled" in mok:
        sb = True
    elif "disabled" in mok:
        sb = False
    data["secure_boot"] = {"efi": efi, "enabled": sb}

    # Displays + EDID presence
    xrandr = _run(["xrandr", "--query"])
    for line in xrandr.splitlines():
        if " connected" in line:
            name = line.split()[0]
            res = ""
            m = re.search(r"(\d+x\d+)\+", line)
            if m:
                res = m.group(1)
            data["displays"].append({"name": name, "resolution": res or "Active"})
    drm = "/sys/class/drm"
    if os.path.isdir(drm):
        for name in sorted(os.listdir(drm)):
            if not name.startswith("card") or "-" not in name:
                continue
            status = _read(os.path.join(drm, name, "status")).strip()
            if status != "connected":
                continue
            edid_path = os.path.join(drm, name, "edid")
            size = 0
            try:
                size = os.path.getsize(edid_path)
            except OSError:
                pass
            data["edid"].append(
                {
                    "connector": name,
                    "status": status,
                    "edid_bytes": size,
                    "has_edid": size > 0,
                }
            )

    return data


def format_uptime(seconds: float) -> str:
    sec = int(seconds or 0)
    days, rem = divmod(sec, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{mins}m")
    return " ".join(parts)


class RingGauge(QWidget):
    def __init__(self, title: str = "", color: str = ACCENT, parent=None):
        super().__init__(parent)
        self.title = title
        self.color = QColor(color)
        self.value = 0.0
        self.caption = ""
        self.setMinimumSize(140, 150)

    def set_progress(self, ratio: float, caption: str = ""):
        self.value = max(0.0, min(1.0, float(ratio or 0.0)))
        self.caption = caption
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height() - 28)
        rect = QRectF((self.width() - side) / 2 + 10, 10, side - 20, side - 20)
        track = QPen(QColor("#1e293b"), 10)
        track.setCapStyle(Qt.RoundCap)
        p.setPen(track)
        p.drawArc(rect, 0, 360 * 16)
        pen = QPen(self.color, 10)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 90 * 16, int(-self.value * 360 * 16))
        p.setPen(QColor(TEXT))
        font = QFont(self.font())
        font.setPointSize(16)
        font.setBold(True)
        p.setFont(font)
        pct = f"{int(self.value * 100)}%"
        p.drawText(rect, Qt.AlignCenter, pct)
        p.setPen(QColor(MUTED))
        font.setPointSize(10)
        font.setBold(False)
        p.setFont(font)
        p.drawText(QRectF(0, self.height() - 24, self.width(), 20), Qt.AlignCenter, self.caption or self.title)
        p.end()


class BarMeter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ratio = 0.0
        self.setFixedHeight(10)

    def set_ratio(self, ratio: float):
        self.ratio = max(0.0, min(1.0, float(ratio or 0.0)))
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()), 5, 5)
        p.fillPath(path, QColor("#1e293b"))
        color = QColor(GOOD if self.ratio < 0.75 else (WARN if self.ratio < 0.9 else BAD))
        fill = QPainterPath()
        fill.addRoundedRect(QRectF(0, 0, max(6, self.width() * self.ratio), self.height()), 5, 5)
        p.fillPath(fill, color)
        p.end()


class Card(QFrame):
    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        lay.addWidget(self.title)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        lay.addLayout(self.body)
        lay.addStretch(1)

    def add_row(self, label: str, value: str):
        row = QHBoxLayout()
        left = QLabel(label)
        left.setObjectName("muted")
        right = QLabel(value or "—")
        right.setObjectName("value")
        right.setWordWrap(True)
        right.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(left, 1)
        row.addWidget(right, 2)
        self.body.addLayout(row)

    def add_widget(self, widget: QWidget):
        self.body.addWidget(widget)


class EmptyState(QFrame):
    """Premium placeholder — never a blank void that looks like a failed load."""

    def __init__(self, text: str, parent=None, title: str = "Nothing to show here", cta: str = ""):
        super().__init__(parent)
        self.setObjectName("emptyPanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 32, 28, 32)
        lay.setSpacing(10)
        icon = QLabel("◇")
        icon.setObjectName("emptyIcon")
        icon.setAlignment(Qt.AlignCenter)
        head = QLabel(title)
        head.setObjectName("emptyTitle")
        head.setAlignment(Qt.AlignCenter)
        body = QLabel(text)
        body.setObjectName("empty")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignCenter)
        lay.addWidget(icon)
        lay.addWidget(head)
        lay.addWidget(body)
        if cta:
            tip = QLabel(cta)
            tip.setObjectName("muted")
            tip.setWordWrap(True)
            tip.setAlignment(Qt.AlignCenter)
            lay.addWidget(tip)


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class ContactButton(QPushButton):
    def __init__(self, label: str, url: str, display: str, parent=None):
        super().__init__(parent)
        self.setObjectName("contactBtn")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(56)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # Two-line chip: title + address — readable in both light and dark.
        self.setText(f"{label}\n{display}")
        self.setToolTip(url.replace("mailto:", ""))
        self.clicked.connect(lambda _=False, u=url: open_url(u))


class AboutWindow(QMainWindow):
    refreshed = pyqtSignal()

    def __init__(self, start_page: str = "overview"):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1080, 720)
        self.setMinimumSize(880, 560)
        self.data = gather()
        self._start_page = (start_page or "overview").strip().lower()
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_live)
        self._timer.start(2500)

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(220)
        side_l = QVBoxLayout(side)
        side_l.setContentsMargins(14, 18, 14, 18)
        side_l.setSpacing(6)
        brand = QLabel("DevOS")
        brand.setObjectName("brand")
        side_l.addWidget(brand)
        sub = QLabel("About this PC")
        sub.setObjectName("sideSub")
        side_l.addWidget(sub)
        side_l.addSpacing(10)

        self.nav_btns: List[QPushButton] = []
        self.stack = QStackedWidget()
        pages = [
            ("Overview", self._page_overview),
            ("Help Center", self._page_help),
            ("Energy", self._page_energy),
            ("Network", self._page_network),
            ("File sharing", self._page_samba),
            ("Audio", self._page_audio),
            ("Storage", self._page_storage),
            ("Processor", self._page_cpu),
            ("Firmware security", self._page_security),
            ("System interrupts", self._page_interrupts),
            ("Memory", self._page_memory),
            ("Connected devices", self._page_pci),
            ("Sensors", self._page_sensors),
            ("USB devices", self._page_usb),
            ("Graphics", self._page_graphics),
            ("Displays", self._page_display),
        ]
        self._page_keys = [
            "overview",
            "help",
            "energy",
            "network",
            "samba",
            "audio",
            "storage",
            "processor",
            "security",
            "interrupts",
            "memory",
            "pci",
            "sensors",
            "usb",
            "graphics",
            "display",
        ]
        for i, (name, factory) in enumerate(pages):
            btn = QPushButton(name)
            btn.setObjectName("nav")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, idx=i: self._goto(idx))
            side_l.addWidget(btn)
            self.nav_btns.append(btn)
            page = QScrollArea()
            page.setWidgetResizable(True)
            page.setFrameShape(QFrame.NoFrame)
            host = QWidget()
            host.setObjectName("pageHost")
            factory(host)
            page.setWidget(host)
            self.stack.addWidget(page)
        side_l.addStretch(1)
        adv = QPushButton("Classic details…")
        adv.setObjectName("linkBtn")
        adv.setCursor(Qt.PointingHandCursor)
        adv.clicked.connect(self._open_classic)
        side_l.addWidget(adv)

        layout.addWidget(side)
        layout.addWidget(self.stack, 1)
        start_idx = 0
        aliases = {
            "help": "help",
            "help-center": "help",
            "helpcenter": "help",
            "contact": "help",
            "about-me": "help",
            "aboutme": "help",
            "support": "help",
            "battery": "energy",
            "power": "energy",
            "firmware": "security",
            "firmware-security": "security",
            "sharing": "samba",
            "smb": "samba",
            "edid": "display",
            "cpu": "processor",
            "block": "storage",
            "disks": "storage",
        }
        key = aliases.get(self._start_page, self._start_page)
        if key in self._page_keys:
            start_idx = self._page_keys.index(key)
        if key == "help":
            self.setWindowTitle("Help Center")
        self._goto(start_idx)
        try:
            from devos_appearance import adapt_stylesheet, current_mode
            self.setStyleSheet(adapt_stylesheet(STYLE, current_mode()))
        except Exception:
            self.setStyleSheet(STYLE)

    def _goto(self, index: int):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_btns):
            btn.setChecked(i == index)

    def _open_classic(self):
        # Prefer the real KDE binary — /usr/local/bin/kinfocenter is a DevOS shim.
        classic = "/usr/bin/kinfocenter"
        if os.path.isfile(classic) and os.access(classic, os.X_OK):
            env = os.environ.copy()
            env["DEVOS_CLASSIC_INFO"] = "1"
            subprocess.Popen([classic], env=env)
        elif shutil.which("kinfocenter"):
            subprocess.Popen(["kinfocenter"])

    def refresh_live(self):
        # Light refresh for RAM / uptime / battery gauges
        mem = _read("/proc/meminfo")

        def mem_kb(key: str) -> int:
            m = re.search(rf"^{key}:\s+(\d+)", mem, re.M)
            return int(m.group(1)) * 1024 if m else 0

        self.data["ram_total"] = mem_kb("MemTotal") or self.data["ram_total"]
        self.data["ram_available"] = mem_kb("MemAvailable")
        self.data["ram_used"] = max(0, self.data["ram_total"] - self.data["ram_available"])
        up = _read("/proc/uptime").split()
        if up:
            try:
                self.data["uptime_sec"] = float(up[0])
            except ValueError:
                pass
        if self.data.get("battery"):
            name = self.data["battery"]["name"]
            cap = _read(f"/sys/class/power_supply/{name}/capacity").strip()
            status = _read(f"/sys/class/power_supply/{name}/status").strip()
            try:
                self.data["battery"]["capacity"] = int(cap)
            except ValueError:
                pass
            if status:
                self.data["battery"]["status"] = status
        if hasattr(self, "ram_ring"):
            total = self.data["ram_total"] or 1
            used = self.data["ram_used"]
            self.ram_ring.set_progress(used / total, f"{_human(used)} used")
        if hasattr(self, "overview_ram_ring"):
            total = self.data["ram_total"] or 1
            used = self.data["ram_used"]
            self.overview_ram_ring.set_progress(used / total, "Memory")
        if hasattr(self, "bat_ring") and self.data.get("battery") and self.data["battery"].get("capacity") is not None:
            self.bat_ring.set_progress(
                self.data["battery"]["capacity"] / 100.0,
                self.data["battery"].get("status") or "Battery",
            )
        if hasattr(self, "uptime_label"):
            self.uptime_label.setText(format_uptime(self.data["uptime_sec"]))

    def _page_overview(self, host: QWidget):
        lay = QVBoxLayout(host)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)
        hero = QFrame()
        hero.setObjectName("hero")
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(22, 20, 22, 20)
        left = QVBoxLayout()
        title = QLabel(self.data["os_name"])
        title.setObjectName("heroTitle")
        left.addWidget(title)
        ver = QLabel(self.data["os_version"] or "Desktop")
        ver.setObjectName("heroSub")
        left.addWidget(ver)
        host_l = QLabel(f"{self.data['hostname']}  ·  {self.data['arch']}  ·  Linux {self.data['kernel']}")
        host_l.setObjectName("muted")
        left.addWidget(host_l)
        up_row = QHBoxLayout()
        up_row.addWidget(QLabel("Up for"))
        self.uptime_label = QLabel(format_uptime(self.data["uptime_sec"]))
        self.uptime_label.setObjectName("value")
        up_row.addWidget(self.uptime_label)
        up_row.addStretch(1)
        left.addLayout(up_row)
        left.addStretch(1)
        hl.addLayout(left, 2)
        self.overview_ram_ring = RingGauge("Memory", ACCENT)
        total = self.data["ram_total"] or 1
        self.overview_ram_ring.set_progress(self.data["ram_used"] / total, "Memory")
        hl.addWidget(self.overview_ram_ring, 1)
        lay.addWidget(hero)

        grid = QHBoxLayout()
        grid.setSpacing(12)
        for title, body, accent in (
            ("Processor", self.data["cpu_model"], ACCENT),
            (
                "Memory",
                f"{_human(self.data['ram_total'])} total · {_human(self.data['ram_available'])} free",
                GOOD,
            ),
            (
                "Graphics",
                self.data["gpus"][0] if self.data["gpus"] else "Not detected",
                WARN,
            ),
        ):
            card = Card(title)
            val = QLabel(body)
            val.setObjectName("cardBig")
            val.setWordWrap(True)
            card.add_widget(val)
            grid.addWidget(card, 1)
        lay.addLayout(grid)

        storage = Card("Storage")
        for vol in self.data["volumes"] or []:
            row = QVBoxLayout()
            top = QHBoxLayout()
            top.addWidget(QLabel(f"{vol['label']} ({vol['path']})"))
            top.addStretch(1)
            pct = int(vol["used"] * 100 / vol["total"]) if vol["total"] else 0
            top.addWidget(QLabel(f"{_human(vol['free'])} free of {_human(vol['total'])} · {pct}%"))
            row.addLayout(top)
            bar = BarMeter()
            bar.set_ratio(vol["used"] / vol["total"] if vol["total"] else 0)
            row.addWidget(bar)
            storage.add_widget(self._wrap(row))
        if not self.data["volumes"]:
            storage.add_widget(EmptyState("No volumes reported."))
        lay.addWidget(storage)

        help_card = Card("Need help?")
        tip = QLabel(
            "DevOS is made by Imran Ahmed (Imran Dev). Open Help Center for email, "
            "WhatsApp, LinkedIn, GitHub, and the contact form."
        )
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        help_card.add_widget(tip)
        open_help = QPushButton("Open Help Center")
        open_help.setObjectName("primaryBtn")
        open_help.setCursor(Qt.PointingHandCursor)
        open_help.clicked.connect(lambda: self._goto(self._page_keys.index("help")))
        help_card.add_widget(open_help)
        lay.addWidget(help_card)
        lay.addStretch(1)

    def _wrap(self, layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    @staticmethod
    def _page_help(host: QWidget):
        lay = QVBoxLayout(host)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)

        hero = QFrame()
        hero.setObjectName("hero")
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(22, 20, 22, 20)
        hl.setSpacing(8)
        title = QLabel("Help Center")
        title.setObjectName("heroTitle")
        hl.addWidget(title)
        sub = QLabel("Support, documentation and feedback")
        sub.setObjectName("heroSub")
        hl.addWidget(sub)
        body = QLabel(
            "DevOS and DevOS AI are made by Imran Ahmed (Imran Dev). "
            "If you need help, found a bug, or want to reach the developer, use any link below."
        )
        body.setObjectName("muted")
        body.setWordWrap(True)
        hl.addWidget(body)
        lay.addWidget(hero)

        card = Card("Contact")
        grid = QVBoxLayout()
        grid.setSpacing(10)
        for label, url, display in HELP_CONTACTS:
            grid.addWidget(ContactButton(label, url, display))
        wrap = QWidget()
        wrap.setLayout(grid)
        card.add_widget(wrap)
        lay.addWidget(card)

        note = EmptyState(
            "Prefer chat on this PC? Open DevOS AI from the Start menu and ask for help — "
            "it can also share these contact links."
        )
        lay.addWidget(note)
        lay.addStretch(1)

    def _page_cpu(self, host: QWidget):
        lay = QVBoxLayout(host)
        lay.setContentsMargins(28, 24, 28, 24)
        card = Card("Processor")
        card.add_row("Model", self.data["cpu_model"])
        card.add_row("Cores", str(self.data["cpu_cores"] or "—"))
        card.add_row("Threads", str(self.data["cpu_threads"] or "—"))
        if self.data["cpu_mhz"]:
            card.add_row("Clock", f"{self.data['cpu_mhz']:.0f} MHz")
        card.add_row("Architecture", self.data["arch"] or "—")
        lay.addWidget(card)
        tip = EmptyState("Live CPU activity graphs live in Task Manager (Ctrl+Shift+Esc).")
        lay.addWidget(tip)
        lay.addStretch(1)

    def _page_memory(self, host: QWidget):
        lay = QVBoxLayout(host)
        lay.setContentsMargins(28, 24, 28, 24)
        row = QHBoxLayout()
        self.ram_ring = RingGauge("In use", GOOD)
        total = self.data["ram_total"] or 1
        self.ram_ring.set_progress(self.data["ram_used"] / total, f"{_human(self.data['ram_used'])} used")
        row.addWidget(self.ram_ring)
        card = Card("Memory")
        card.add_row("Installed", _human(self.data["ram_total"]))
        card.add_row("In use", _human(self.data["ram_used"]))
        card.add_row("Available", _human(self.data["ram_available"]))
        row.addWidget(card, 1)
        lay.addLayout(row)
        lay.addStretch(1)

    def _page_storage(self, host: QWidget):
        lay = QVBoxLayout(host)
        lay.setContentsMargins(28, 24, 28, 24)
        disks = Card("Drives")
        for d in self.data["disks"] or []:
            disks.add_row(
                d["model"],
                f"{_human(d['size'])} · {d['kind']} · {d['bus']} · /dev/{d['name']}",
            )
        if not self.data["disks"]:
            disks.add_widget(EmptyState("No physical disks reported (VM or filtered view)."))
        lay.addWidget(disks)
        vols = Card("Volumes")
        for vol in self.data["volumes"] or []:
            box = QVBoxLayout()
            top = QHBoxLayout()
            top.addWidget(QLabel(f"{vol['label']} — {vol['path']}"))
            top.addStretch(1)
            pct = int(vol["used"] * 100 / vol["total"]) if vol["total"] else 0
            top.addWidget(QLabel(f"{pct}% used"))
            box.addLayout(top)
            bar = BarMeter()
            bar.set_ratio(vol["used"] / vol["total"] if vol["total"] else 0)
            box.addWidget(bar)
            box.addWidget(QLabel(f"{_human(vol['used'])} used · {_human(vol['free'])} free · {_human(vol['total'])} total"))
            vols.add_widget(self._wrap(box))
        lay.addWidget(vols)
        lay.addStretch(1)

    def _page_graphics(self, host: QWidget):
        lay = QVBoxLayout(host)
        lay.setContentsMargins(28, 24, 28, 24)
        card = Card("Graphics")
        for i, gpu in enumerate(self.data["gpus"] or ["Not detected"], 1):
            card.add_row(f"Adapter {i}", gpu)
        lay.addWidget(card)
        tip = EmptyState("For Vulkan / OpenGL probes use Classic details, or install GPU tooling.")
        lay.addWidget(tip)
        lay.addStretch(1)

    def _page_display(self, host: QWidget):
        lay = QVBoxLayout(host)
        lay.setContentsMargins(28, 24, 28, 24)
        card = Card("Displays")
        for d in self.data["displays"] or []:
            card.add_row(d["name"], d.get("resolution") or "Connected")
        if not self.data["displays"]:
            card.add_widget(EmptyState("No active displays reported (Wayland session or headless)."))
        lay.addWidget(card)
        edid = Card("EDID (monitor identity)")
        for e in self.data.get("edid") or []:
            detail = (
                f"EDID present · {e.get('edid_bytes', 0)} bytes"
                if e.get("has_edid")
                else "Connected · EDID not reported"
            )
            edid.add_row(e.get("connector") or "Display", detail)
        if not self.data.get("edid"):
            edid.add_widget(
                EmptyState(
                    "No DRM connectors reported EDID yet. Display resolution above still shows active screens."
                )
            )
        lay.addWidget(edid)
        lay.addStretch(1)

    def _page_network(self, host: QWidget):
        lay = QVBoxLayout(host)
        lay.setContentsMargins(28, 24, 28, 24)
        card = Card("Network interfaces")
        for n in self.data["network"] or []:
            state = n.get("state") or "—"
            color_hint = "Connected" if "connect" in state.lower() else state
            card.add_row(
                f"{n.get('device')} ({n.get('type')})",
                f"{color_hint} · {n.get('connection') or '—'}",
            )
        if not self.data["network"]:
            card.add_widget(EmptyState("No network interfaces found."))
        lay.addWidget(card)
        tip = EmptyState("Change Wi‑Fi or Ethernet in Settings → Network, or ask DevOS AI.")
        lay.addWidget(tip)
        lay.addStretch(1)

    def _page_samba(self, host: QWidget):
        lay = QVBoxLayout(host)
        lay.setContentsMargins(28, 24, 28, 24)
        samba = self.data.get("samba") or {}
        card = Card("File sharing (Samba)")
        card.add_row("Samba installed", "Yes" if samba.get("installed") else "No")
        card.add_row("Service", "Running" if samba.get("active") else "Stopped / not running")
        shares = samba.get("shares") or []
        card.add_row("Shared folders", ", ".join(shares) if shares else "None listed")
        lay.addWidget(card)
        lay.addWidget(EmptyState(samba.get("note") or "File sharing status unavailable."))
        lay.addStretch(1)

    def _page_audio(self, host: QWidget):
        lay = QVBoxLayout(host)
        lay.setContentsMargins(28, 24, 28, 24)
        sinks = Card("Playback devices")
        for s in self.data.get("audio_sinks") or []:
            sinks.add_row(s.get("name") or "Sink", s.get("state") or "—")
        if not self.data.get("audio_sinks"):
            sinks.add_widget(EmptyState("No playback devices reported yet."))
        lay.addWidget(sinks)
        sources = Card("Recording devices")
        for s in self.data.get("audio_sources") or []:
            sources.add_row(s.get("name") or "Source", s.get("state") or "—")
        if not self.data.get("audio_sources"):
            sources.add_widget(EmptyState("No microphones / input devices reported."))
        lay.addWidget(sources)
        cameras = Card("Cameras")
        for c in self.data.get("cameras") or []:
            kind = "USB" if c.get("usb") else "Camera"
            cameras.add_row(c.get("name") or "Camera", f"{kind} · {c.get('device') or '—'}")
        if not self.data.get("cameras"):
            cameras.add_widget(EmptyState("No camera detected. Plug in a USB webcam to use Camera."))
        lay.addWidget(cameras)
        tip = EmptyState("Adjust volume in the taskbar speaker icon, or open Sound settings. Cameras open in Camera.")
        lay.addWidget(tip)
        lay.addStretch(1)

    def _page_usb(self, host: QWidget):
        lay = QVBoxLayout(host)
        lay.setContentsMargins(28, 24, 28, 24)
        card = Card(f"USB devices ({len(self.data['usb'])})")
        for u in self.data["usb"] or []:
            card.add_row(u["name"], f"Bus {u['bus']} · {u['id']}")
        if not self.data["usb"]:
            card.add_widget(EmptyState("No USB devices detected right now."))
        lay.addWidget(card)
        lay.addStretch(1)

    def _page_energy(self, host: QWidget):
        lay = QVBoxLayout(host)
        lay.setContentsMargins(28, 24, 28, 24)
        bat = self.data.get("battery")
        if bat and bat.get("capacity") is not None:
            row = QHBoxLayout()
            self.bat_ring = RingGauge("Battery", GOOD)
            self.bat_ring.set_progress(
                bat["capacity"] / 100.0, bat.get("status") or "Battery"
            )
            row.addWidget(self.bat_ring)
            bcard = Card("Battery")
            bcard.add_row("Charge", f"{bat['capacity']}%")
            bcard.add_row("Status", bat.get("status") or "—")
            bcard.add_row("Device", bat.get("name") or "—")
            row.addWidget(bcard, 1)
            lay.addLayout(row)
        supplies = Card("Power supplies")
        for p in self.data.get("power") or []:
            bits = [p.get("type") or "Power", p.get("status") or "—"]
            if p.get("capacity") is not None:
                bits.append(f"{p['capacity']}%")
            if p.get("online") in ("1", "0"):
                bits.append("Plugged in" if p["online"] == "1" else "Unplugged")
            supplies.add_row(p.get("name") or "Supply", " · ".join(bits))
        if not self.data.get("power"):
            supplies.add_widget(
                EmptyState(
                    "No battery or AC adapter reported — typical for many desktop PCs. "
                    "Power comes straight from the wall."
                )
            )
        lay.addWidget(supplies)
        lay.addStretch(1)

    def _page_pci(self, host: QWidget):
        lay = QVBoxLayout(host)
        lay.setContentsMargins(28, 24, 28, 24)
        card = Card(f"PCI devices ({len(self.data.get('pci') or [])})")
        for p in self.data.get("pci") or []:
            card.add_row(p.get("slot") or "PCI", p.get("desc") or "—")
        if not self.data.get("pci"):
            card.add_widget(
                EmptyState(
                    "No PCI list available. Install pciutils (lspci) on the next DevOS image for full device names."
                )
            )
        lay.addWidget(card)
        lay.addStretch(1)

    def _page_sensors(self, host: QWidget):
        lay = QVBoxLayout(host)
        lay.setContentsMargins(28, 24, 28, 24)
        card = Card("Temperatures & sensors")
        for s in self.data.get("sensors") or []:
            card.add_row(s.get("name") or "Sensor", s.get("value") or "—")
        if not self.data.get("sensors"):
            card.add_widget(
                EmptyState(
                    "No thermal sensors reported yet. Many desktops only expose sensors after lm-sensors is configured."
                )
            )
        lay.addWidget(card)
        lay.addStretch(1)

    def _page_interrupts(self, host: QWidget):
        lay = QVBoxLayout(host)
        lay.setContentsMargins(28, 24, 28, 24)
        card = Card("Top interrupts")
        for row in self.data.get("interrupts") or []:
            card.add_row(
                f"IRQ {row.get('irq')}",
                f"{row.get('count', 0):,} · {row.get('label') or ''}".strip(" ·"),
            )
        if not self.data.get("interrupts"):
            card.add_widget(EmptyState("Could not read /proc/interrupts on this system."))
        lay.addWidget(card)
        tip = EmptyState("High counts on network or storage IRQs are normal while the PC is busy.")
        lay.addWidget(tip)
        lay.addStretch(1)

    def _page_security(self, host: QWidget):
        lay = QVBoxLayout(host)
        lay.setContentsMargins(28, 24, 28, 24)
        sb = self.data.get("secure_boot") or {}
        card = Card("Firmware security")
        card.add_row("UEFI firmware", "Yes" if sb.get("efi") else "Legacy BIOS / not detected")
        enabled = sb.get("enabled")
        if enabled is True:
            card.add_row("Secure Boot", "On")
        elif enabled is False:
            card.add_row("Secure Boot", "Off")
        else:
            card.add_row("Secure Boot", "Unknown")
        card.add_row(
            "Firmware tool",
            "fwupdmgr available" if shutil.which("fwupdmgr") else "Built-in status (no fwupd required)",
        )
        lay.addWidget(card)

        devices = Card("Firmware devices")
        for name in self.data.get("firmware_devices") or []:
            devices.add_row("Device", name)
        if not self.data.get("firmware_devices"):
            devices.add_widget(
                EmptyState(
                    "Secure Boot and UEFI status are shown above. "
                    "Device firmware update lists appear when fwupd is installed — "
                    "DevOS still shows this page without that tool."
                )
            )
        lay.addWidget(devices)
        tip = EmptyState(
            "DevOS custom ISOs are not universally Secure Boot signed. "
            "Enable Secure Boot only with a verified boot chain."
        )
        lay.addWidget(tip)
        lay.addStretch(1)


STYLE = f"""
QMainWindow, QWidget#pageHost {{ background: {BG}; color: {TEXT};
  font-family: "Inter", "Segoe UI", "Noto Sans", sans-serif; font-size: 13px; }}
QFrame#side {{ background: {SIDE}; border-right: 1px solid {CARD_BORDER}; }}
QLabel#brand {{ font-size: 22px; font-weight: 800; color: {ACCENT}; letter-spacing: 0.5px; }}
QLabel#sideSub {{ color: {MUTED}; font-size: 12px; margin-bottom: 6px; }}
QPushButton#nav {{
  text-align: left; padding: 10px 12px; border: none; border-radius: 10px;
  color: {MUTED}; font-weight: 600; background: transparent;
}}
QPushButton#nav:hover {{ background: #1e293b; color: {TEXT}; }}
QPushButton#nav:checked {{
  background: rgba(14, 165, 233, 0.14); color: {ACCENT}; border: 1px solid rgba(14, 165, 233, 0.35);
}}
QPushButton#linkBtn {{
  text-align: left; border: none; background: transparent; color: {MUTED}; padding: 8px 4px;
}}
QPushButton#linkBtn:hover {{ color: {ACCENT}; }}
QPushButton#primaryBtn {{
  text-align: center; padding: 10px 14px; border-radius: 10px; border: 1px solid rgba(14, 165, 233, 0.35);
  background: rgba(14, 165, 233, 0.14); color: {ACCENT}; font-weight: 700;
}}
QPushButton#primaryBtn:hover {{ background: rgba(14, 165, 233, 0.22); }}
QPushButton#contactBtn {{
  text-align: left; padding: 14px 16px; border-radius: 12px; min-height: 52px;
  border: 1px solid {CARD_BORDER}; background: #334155; color: {TEXT}; font-weight: 650;
}}
QPushButton#contactBtn:hover {{
  border-color: rgba(14, 165, 233, 0.55); background: rgba(14, 165, 233, 0.16); color: {ACCENT};
}}
QFrame#hero, QFrame#card {{
  background: {CARD}; border: 1px solid {CARD_BORDER}; border-radius: 16px;
}}
QLabel#heroTitle {{ font-size: 28px; font-weight: 800; color: {TEXT}; }}
QLabel#heroSub {{ font-size: 15px; color: {ACCENT}; font-weight: 600; }}
QLabel#cardTitle {{ font-size: 13px; font-weight: 700; color: {MUTED};
  text-transform: uppercase; letter-spacing: 0.8px; }}
QLabel#cardBig {{ font-size: 15px; font-weight: 650; color: {TEXT}; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#value {{ color: {TEXT}; font-weight: 600; }}
QFrame#emptyPanel {{
  background: {CARD}; border: 1px solid {CARD_BORDER}; border-radius: 16px;
}}
QLabel#emptyIcon {{ font-size: 28px; color: {ACCENT}; }}
QLabel#emptyTitle {{ font-size: 16px; font-weight: 700; color: {TEXT}; }}
QLabel#empty {{
  color: {MUTED}; padding: 4px 8px;
}}
QScrollArea {{ border: none; background: {BG}; }}
"""


def _parse_start_page(argv: List[str]) -> str:
    page = "overview"
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg in ("--help-center", "--contact", "--about-me"):
            page = "help"
        elif arg == "--page" and i + 1 < len(argv):
            page = argv[i + 1]
            i += 1
        elif arg.startswith("--page="):
            page = arg.split("=", 1)[1]
        i += 1
    return page


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    start_page = _parse_start_page(argv)
    desktop_id = "devos-help" if start_page == "help" else APP_ID
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app_identity import prepare as prepare_identity, apply as apply_identity, show_window

    prepare_identity(desktop_id)
    app = QApplication(argv)
    apply_identity(app, desktop_id)
    if desktop_id == "devos-help":
        # Support links can open immediately, independently of hardware probing.
        win = QMainWindow()
        win.resize(760, 680)
        win.setWindowTitle("Help Center")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        host.setObjectName("pageHost")
        AboutWindow._page_help(host)
        scroll.setWidget(host)
        win.setCentralWidget(scroll)
        try:
            from devos_appearance import adapt_stylesheet, current_mode
            win.setStyleSheet(adapt_stylesheet(STYLE, current_mode()))
        except Exception:
            win.setStyleSheet(STYLE)
    else:
        win = AboutWindow(start_page=start_page)
    win.setAttribute(Qt.WA_DeleteOnClose)
    show_window(win, desktop_id)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
