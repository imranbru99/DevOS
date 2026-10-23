#!/usr/bin/env python3
"""
DevOS Power & Sleep Settings Manager (Windows 11 Fluent Power & Battery Hub).

Controls:
  * Screen timeout (Turn off screen after X minutes of idle) via X11 DPMS
  * Device sleep timeout (Put PC to sleep after X minutes) with background idle monitor
  * Power modes: Best power efficiency, Balanced (Recommended), Best performance
  * Hardware power controls: Power off (Shut down), Restart, Sleep (Suspend), Lock
  * Real-time hardware telemetry: AC/Battery status, CPU governor & energy preferences

CLI:
  power_settings.py             Launch Windows 11 Power & Sleep GUI
  power_settings.py --daemon    Run background sleep/idle monitor service
  power_settings.py --status    Output current power and timeout status as JSON
  power_settings.py --apply     Apply saved timeout configuration
"""

import argparse
import ctypes
import json
import os
import re
import subprocess
import sys
import time
from typing import Dict, Any, Optional, Tuple

APP_NAME = "Power & sleep"
CONFIG_DIR = os.path.expanduser("~/.config/devos")
CONFIG_FILE = os.path.join(CONFIG_DIR, "power.json")

# Standard Windows 11 Timeout Choices (seconds -> label)
TIMEOUT_CHOICES = [
    (60, "1 minute"),
    (120, "2 minutes"),
    (180, "3 minutes"),
    (300, "5 minutes"),
    (600, "10 minutes (Recommended)"),
    (900, "15 minutes"),
    (1200, "20 minutes"),
    (1500, "25 minutes"),
    (1800, "30 minutes"),
    (2700, "45 minutes"),
    (3600, "1 hour"),
    (7200, "2 hours"),
    (10800, "3 hours"),
    (14400, "4 hours"),
    (18000, "5 hours"),
    (0, "Never"),
]

TIMEOUT_MAP = dict(TIMEOUT_CHOICES)

DEFAULT_CONFIG: Dict[str, Any] = {
    "screen_timeout_plugged": 600,     # 10 minutes
    "screen_timeout_battery": 300,     # 5 minutes
    "sleep_timeout_plugged": 1800,     # 30 minutes
    "sleep_timeout_battery": 900,      # 15 minutes
    "power_mode": "balanced",          # "power_saver", "balanced", "performance"
    "power_button": "poweroff",        # "poweroff", "suspend", "screen_off", "ignore"
    "lid_close": "suspend",            # "suspend", "ignore", "poweroff"
}


# ---------------------------------------------------------------------------
# Core Power & Telemetry Logic (Headless / Testable)
# ---------------------------------------------------------------------------

def load_config(path: str = CONFIG_FILE) -> Dict[str, Any]:
    """Load user power configuration, falling back to defaults."""
    cfg = dict(DEFAULT_CONFIG)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    cfg.update(data)
        except Exception:
            pass
    return cfg


def save_config(cfg: Dict[str, Any], path: str = CONFIG_FILE) -> bool:
    """Save user power configuration to JSON file."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception:
        return False


def get_power_source() -> Dict[str, Any]:
    """Detect AC or Battery power source and charging status from sysfs."""
    power_dir = "/sys/class/power_supply"
    has_battery = False
    battery_pct = 100
    charging = True
    status = "Plugged in (AC Power)"

    if os.path.isdir(power_dir):
        for entry in os.listdir(power_dir):
            epath = os.path.join(power_dir, entry)
            type_file = os.path.join(epath, "type")
            if os.path.isfile(type_file):
                try:
                    with open(type_file, "r", encoding="utf-8") as f:
                        ptype = f.read().strip().lower()
                    if ptype == "battery":
                        has_battery = True
                        cap_file = os.path.join(epath, "capacity")
                        stat_file = os.path.join(epath, "status")
                        if os.path.isfile(cap_file):
                            with open(cap_file, "r", encoding="utf-8") as f:
                                battery_pct = int(f.read().strip())
                        if os.path.isfile(stat_file):
                            with open(stat_file, "r", encoding="utf-8") as f:
                                st = f.read().strip()
                                charging = st.lower() in ("charging", "full")
                                status = f"Battery: {battery_pct}% ({st})"
                        break
                except Exception:
                    pass

    return {
        "has_battery": has_battery,
        "battery_pct": battery_pct,
        "charging": charging,
        "status": status,
    }


def get_current_screen_timeout() -> Tuple[bool, int]:
    """Read current X11 DPMS screen timeout via xset."""
    try:
        res = subprocess.run(["xset", "q"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            enabled = "DPMS is Enabled" in res.stdout
            m = re.search(r"Standby:\s*(\d+)", res.stdout)
            sec = int(m.group(1)) if m else 600
            return enabled, (sec if enabled else 0)
    except Exception:
        pass
    return False, 0


def apply_screen_timeout(seconds: int) -> bool:
    """Apply screen timeout to X11 display (DPMS) and KDE Plasma Screen Locker."""
    try:
        if seconds > 0:
            subprocess.run(["xset", "+dpms"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["xset", "dpms", str(seconds), str(seconds), str(seconds)],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["xset", "s", str(seconds), str(seconds)],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(["xset", "-dpms"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["xset", "s", "off"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Sync to KDE Plasma ScreenLocker (~/.config/kscreenlockerrc)
        # Timeout in kscreenlockerrc is measured in minutes
        autolock = "true" if seconds > 0 else "false"
        minutes = max(1, seconds // 60) if seconds > 0 else 0
        subprocess.run(["kwriteconfig5", "--file", "kscreenlockerrc", "--group", "Daemon", "--key", "Autolock", autolock],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if seconds > 0:
            subprocess.run(["kwriteconfig5", "--file", "kscreenlockerrc", "--group", "Daemon", "--key", "Timeout", str(minutes)],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Notify KDE ScreenSaver daemon to reload its configuration immediately
        subprocess.run(["qdbus", "org.freedesktop.ScreenSaver", "/ScreenSaver", "configure"],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def turn_off_screen_now() -> bool:
    """Instantly put display into standby/off until key or mouse event."""
    try:
        subprocess.run(["xset", "+dpms"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        res = subprocess.run(["xset", "dpms", "force", "off"], check=False,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return res.returncode == 0
    except Exception:
        return False


def get_cpu_power_mode() -> str:
    """Read current CPU energy performance preference or governor."""
    pref_path = "/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference"
    gov_path = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
    try:
        if os.path.isfile(pref_path):
            with open(pref_path, "r", encoding="utf-8") as f:
                pref = f.read().strip()
                if "performance" in pref and "balance" not in pref:
                    return "performance"
                if "power" in pref and "balance" not in pref:
                    return "power_saver"
                return "balanced"
        elif os.path.isfile(gov_path):
            with open(gov_path, "r", encoding="utf-8") as f:
                gov = f.read().strip()
                if gov == "performance":
                    return "performance"
                if gov in ("powersave", "conservative"):
                    return "power_saver"
                return "balanced"
    except Exception:
        pass
    return "balanced"


def set_cpu_power_mode(mode: str) -> bool:
    """Apply power mode to CPU sysfs parameters where writable."""
    mapping = {
        "performance": ("performance", "performance"),
        "balanced": ("balance_performance", "schedutil"),
        "power_saver": ("power", "powersave"),
    }
    epp_val, _gov_val = mapping.get(mode, ("balance_performance", "schedutil"))
    applied = False

    # Attempt to write EPP for each online CPU core
    cpu_dir = "/sys/devices/system/cpu"
    if os.path.isdir(cpu_dir):
        for entry in os.listdir(cpu_dir):
            if re.match(r"^cpu\d+$", entry):
                epp_path = os.path.join(cpu_dir, entry, "cpufreq", "energy_performance_preference")
                if os.path.isfile(epp_path) and os.access(epp_path, os.W_OK):
                    try:
                        with open(epp_path, "w", encoding="utf-8") as f:
                            f.write(epp_val + "\n")
                        applied = True
                    except Exception:
                        pass
    return applied


def suspend_pc() -> bool:
    """Put PC to sleep (Suspend to RAM)."""
    try:
        res = subprocess.run(["systemctl", "suspend"], check=False)
        return res.returncode == 0
    except Exception:
        return False


def reboot_pc() -> bool:
    """Reboot PC into DevOS."""
    try:
        res = subprocess.run(["systemctl", "reboot"], check=False)
        return res.returncode == 0
    except Exception:
        return False


def poweroff_pc() -> bool:
    """Power off PC completely."""
    try:
        res = subprocess.run(["systemctl", "poweroff"], check=False)
        return res.returncode == 0
    except Exception:
        return False


def lock_pc() -> bool:
    """Lock user session."""
    try:
        res = subprocess.run(["loginctl", "lock-session"], check=False)
        return res.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Native X11 Idle Detection (Zero external CLI dependencies)
# ---------------------------------------------------------------------------

class _XScreenSaverInfo(ctypes.Structure):
    _fields_ = [
        ("window", ctypes.c_ulong),
        ("state", ctypes.c_int),
        ("kind", ctypes.c_int),
        ("til_or_since", ctypes.c_ulong),
        ("idle", ctypes.c_ulong),
        ("eventMask", ctypes.c_ulong),
    ]


def get_x11_idle_ms() -> Optional[int]:
    """Returns user idle time in milliseconds using libXss via ctypes."""
    try:
        x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
        xss = ctypes.cdll.LoadLibrary("libXss.so.1")
        dpy = x11.XOpenDisplay(None)
        if not dpy:
            return None
        root = x11.XDefaultRootWindow(dpy)
        info = _XScreenSaverInfo()
        xss.XScreenSaverQueryInfo(dpy, root, ctypes.byref(info))
        idle_ms = int(info.idle)
        x11.XCloseDisplay(dpy)
        return idle_ms
    except Exception:
        pass

    # Fallback to xprintidle if available
    try:
        res = subprocess.run(["xprintidle"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            return int(res.stdout.strip())
    except Exception:
        pass
    return None


def run_sleep_daemon(check_interval: int = 15):
    """Background idle service that puts PC to sleep when sleep_timeout is reached."""
    print(f"[{APP_NAME}] Power and sleep daemon started (interval: {check_interval}s)")
    while True:
        try:
            cfg = load_config()
            pwr = get_power_source()
            sleep_timeout = cfg.get("sleep_timeout_battery" if pwr["has_battery"] and not pwr["charging"]
                                   else "sleep_timeout_plugged", 1800)
            if sleep_timeout > 0:
                idle_ms = get_x11_idle_ms()
                if idle_ms is not None:
                    idle_sec = idle_ms // 1000
                    if idle_sec >= sleep_timeout:
                        print(f"[{APP_NAME}] Idle timeout reached ({idle_sec}s >= {sleep_timeout}s). Suspending PC...")
                        suspend_pc()
                        time.sleep(30)  # Post-wake cooldown
        except Exception as e:
            print(f"[{APP_NAME}] Daemon loop error: {e}", file=sys.stderr)
        time.sleep(check_interval)


# ---------------------------------------------------------------------------
# Windows 11 Fluent GUI
# ---------------------------------------------------------------------------

def run_gui() -> int:
    from PyQt5 import QtCore, QtGui, QtWidgets

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("devos-power")
    app.setApplicationDisplayName("Power & sleep")
    if hasattr(app, "setDesktopFileName"):
        app.setDesktopFileName("devos-power")

    class WindowsCard(QtWidgets.QFrame):
        """Card matching Windows 11 Fluent container styling."""
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("WindowsCard")
            self.setStyleSheet("""
                QFrame#WindowsCard {
                    background-color: #2b2b2b;
                    border: 1px solid #383838;
                    border-radius: 8px;
                }
            """)

    class ModeCard(QtWidgets.QFrame):
        """Interactive selectable card for Power Mode."""
        clicked = QtCore.pyqtSignal(str)

        def __init__(self, mode_id: str, title: str, subtitle: str, icon_symbol: str, parent=None):
            super().__init__(parent)
            self.mode_id = mode_id
            self.selected = False
            self.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
            self.setFixedHeight(72)

            layout = QtWidgets.QHBoxLayout(self)
            layout.setContentsMargins(14, 10, 14, 10)
            layout.setSpacing(12)

            icon_lbl = QtWidgets.QLabel(icon_symbol)
            icon_lbl.setStyleSheet("font-size: 22px; background: transparent;")
            layout.addWidget(icon_lbl)

            text_layout = QtWidgets.QVBoxLayout()
            text_layout.setSpacing(2)
            self.title_lbl = QtWidgets.QLabel(title)
            self.title_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #ffffff; background: transparent;")
            self.sub_lbl = QtWidgets.QLabel(subtitle)
            self.sub_lbl.setStyleSheet("font-size: 11px; color: #a0a0a0; background: transparent;")
            text_layout.addWidget(self.title_lbl)
            text_layout.addWidget(self.sub_lbl)
            layout.addLayout(text_layout)
            layout.addStretch()

            self.indicator = QtWidgets.QLabel()
            self.indicator.setFixedSize(18, 18)
            layout.addWidget(self.indicator)

            self.update_style()

        def set_selected(self, sel: bool):
            self.selected = sel
            self.update_style()

        def update_style(self):
            if self.selected:
                self.setStyleSheet("""
                    ModeCard {
                        background-color: #333333;
                        border: 2px solid #0078d4;
                        border-radius: 6px;
                    }
                """)
                self.indicator.setStyleSheet("""
                    background-color: #0078d4;
                    border: 4px solid #ffffff;
                    border-radius: 9px;
                """)
            else:
                self.setStyleSheet("""
                    ModeCard {
                        background-color: #262626;
                        border: 1px solid #383838;
                        border-radius: 6px;
                    }
                    ModeCard:hover {
                        background-color: #2f2f2f;
                        border: 1px solid #484848;
                    }
                """)
                self.indicator.setStyleSheet("""
                    background-color: transparent;
                    border: 2px solid #5a5a5a;
                    border-radius: 9px;
                """)

        def mousePressEvent(self, ev):
            self.clicked.emit(self.mode_id)
            super().mousePressEvent(ev)

    class PowerDialog(QtWidgets.QMainWindow):
        def __init__(self):
            super().__init__()
            self.cfg = load_config()
            self.pwr = get_power_source()
            self.init_ui()

        def init_ui(self):
            self.setWindowTitle("Power & sleep")
            self.resize(760, 680)
            self.setMinimumSize(680, 560)
            self.setStyleSheet("""
                QMainWindow {
                    background-color: #1e1e1e;
                }
                QWidget {
                    color: #ffffff;
                    font-family: 'Segoe UI', 'Ubuntu', sans-serif;
                }
                QScrollArea {
                    background: transparent;
                    border: none;
                }
                QComboBox {
                    background-color: #383838;
                    color: #ffffff;
                    border: 1px solid #484848;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 13px;
                    min-width: 200px;
                }
                QComboBox:hover {
                    background-color: #424242;
                    border-color: #585858;
                }
                QComboBox::drop-down {
                    subcontrol-origin: padding;
                    subcontrol-position: top right;
                    width: 24px;
                    border-left: none;
                }
                QComboBox QAbstractItemView {
                    background-color: #2b2b2b;
                    color: #ffffff;
                    selection-background-color: #0078d4;
                    selection-color: #ffffff;
                    border: 1px solid #383838;
                    outline: none;
                }
                QPushButton {
                    background-color: #333333;
                    border: 1px solid #444444;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-size: 13px;
                    font-weight: 500;
                    color: #ffffff;
                }
                QPushButton:hover {
                    background-color: #3d3d3d;
                    border-color: #555555;
                }
                QPushButton:pressed {
                    background-color: #282828;
                }
            """)

            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            container = QtWidgets.QWidget()
            scroll.setWidget(container)
            self.setCentralWidget(scroll)

            main_layout = QtWidgets.QVBoxLayout(container)
            main_layout.setContentsMargins(32, 28, 32, 28)
            main_layout.setSpacing(20)

            # 1. Header Bar
            header_layout = QtWidgets.QHBoxLayout()
            header_layout.setSpacing(14)
            icon_lbl = QtWidgets.QLabel("⚡")
            icon_lbl.setStyleSheet("font-size: 28px; color: #0078d4;")
            header_layout.addWidget(icon_lbl)

            titles_layout = QtWidgets.QVBoxLayout()
            titles_layout.setSpacing(2)
            title = QtWidgets.QLabel("Power & sleep")
            title.setStyleSheet("font-size: 22px; font-weight: 700; color: #ffffff;")
            subtitle = QtWidgets.QLabel("Screen and sleep timeouts, power modes, and energy controls")
            subtitle.setStyleSheet("font-size: 12px; color: #a0a0a0;")
            titles_layout.addWidget(title)
            titles_layout.addWidget(subtitle)
            header_layout.addLayout(titles_layout)
            header_layout.addStretch()

            # Power Source Badge
            badge = QtWidgets.QLabel(self.pwr["status"])
            badge_bg = "#1b3a24" if self.pwr["charging"] else "#383838"
            badge_color = "#4ade80" if self.pwr["charging"] else "#cccccc"
            badge.setStyleSheet(f"""
                background-color: {badge_bg};
                color: {badge_color};
                font-size: 11px;
                font-weight: 600;
                padding: 6px 12px;
                border-radius: 12px;
                border: 1px solid #484848;
            """)
            header_layout.addWidget(badge)
            main_layout.addLayout(header_layout)

            # 2. Screen & Sleep Section
            sec_title1 = QtWidgets.QLabel("Screen and sleep")
            sec_title1.setStyleSheet("font-size: 15px; font-weight: 600; color: #ffffff; margin-top: 6px;")
            main_layout.addWidget(sec_title1)

            card_sleep = WindowsCard()
            card_sleep_layout = QtWidgets.QVBoxLayout(card_sleep)
            card_sleep_layout.setContentsMargins(20, 16, 20, 16)
            card_sleep_layout.setSpacing(16)

            # Row 1: Screen timeout
            row1 = QtWidgets.QHBoxLayout()
            row1_info = QtWidgets.QVBoxLayout()
            lbl_scr = QtWidgets.QLabel("Turn off my screen after")
            lbl_scr.setStyleSheet("font-size: 13px; font-weight: 500; color: #ffffff;")
            lbl_scr_sub = QtWidgets.QLabel("Display powers down into energy-saving standby mode")
            lbl_scr_sub.setStyleSheet("font-size: 11px; color: #8c8c8c;")
            row1_info.addWidget(lbl_scr)
            row1_info.addWidget(lbl_scr_sub)
            row1.addLayout(row1_info)
            row1.addStretch()

            self.combo_screen = QtWidgets.QComboBox()
            for sec, label in TIMEOUT_CHOICES:
                self.combo_screen.addItem(label, sec)
            cur_scr = self.cfg.get("screen_timeout_plugged", 600)
            idx = self.combo_screen.findData(cur_scr)
            if idx >= 0:
                self.combo_screen.setCurrentIndex(idx)
            self.combo_screen.currentIndexChanged.connect(self.on_screen_timeout_changed)
            row1.addWidget(self.combo_screen)
            card_sleep_layout.addLayout(row1)

            # Divider line
            card_sleep_layout.addWidget(self._make_divider())

            # Row 2: Sleep timeout
            row2 = QtWidgets.QHBoxLayout()
            row2_info = QtWidgets.QVBoxLayout()
            lbl_slp = QtWidgets.QLabel("Put my device to sleep after")
            lbl_slp.setStyleSheet("font-size: 13px; font-weight: 500; color: #ffffff;")
            lbl_slp_sub = QtWidgets.QLabel("Saves open apps and state to RAM; wakes instantly on keypress")
            lbl_slp_sub.setStyleSheet("font-size: 11px; color: #8c8c8c;")
            row2_info.addWidget(lbl_slp)
            row2_info.addWidget(lbl_slp_sub)
            row2.addLayout(row2_info)
            row2.addStretch()

            self.combo_sleep = QtWidgets.QComboBox()
            for sec, label in TIMEOUT_CHOICES:
                self.combo_sleep.addItem(label, sec)
            cur_slp = self.cfg.get("sleep_timeout_plugged", 1800)
            idx_slp = self.combo_sleep.findData(cur_slp)
            if idx_slp >= 0:
                self.combo_sleep.setCurrentIndex(idx_slp)
            self.combo_sleep.currentIndexChanged.connect(self.on_sleep_timeout_changed)
            row2.addWidget(self.combo_sleep)
            card_sleep_layout.addLayout(row2)

            main_layout.addWidget(card_sleep)

            # 3. Power Mode Section
            sec_title2 = QtWidgets.QLabel("Power mode")
            sec_title2.setStyleSheet("font-size: 15px; font-weight: 600; color: #ffffff; margin-top: 6px;")
            main_layout.addWidget(sec_title2)

            card_modes = WindowsCard()
            card_modes_layout = QtWidgets.QVBoxLayout(card_modes)
            card_modes_layout.setContentsMargins(16, 16, 16, 16)
            card_modes_layout.setSpacing(10)

            self.mode_cards = {}
            modes_def = [
                ("power_saver", "Best power efficiency", "Lowers CPU power draw and reduces heat & fan noise", "🔋"),
                ("balanced", "Balanced (Recommended)", "Automatically balances energy efficiency with full performance", "⚖️"),
                ("performance", "Best performance", "Locks high CPU turbo clocks for heavy builds and coding", "🚀"),
            ]
            current_mode = self.cfg.get("power_mode", get_cpu_power_mode())

            for m_id, m_title, m_sub, m_ico in modes_def:
                mc = ModeCard(m_id, m_title, m_sub, m_ico)
                mc.clicked.connect(self.on_mode_selected)
                if m_id == current_mode:
                    mc.set_selected(True)
                self.mode_cards[m_id] = mc
                card_modes_layout.addWidget(mc)

            main_layout.addWidget(card_modes)

            # 4. Power Controls & Actions (Power off, Restart, Sleep, Screen Off)
            sec_title3 = QtWidgets.QLabel("Power controls")
            sec_title3.setStyleSheet("font-size: 15px; font-weight: 600; color: #ffffff; margin-top: 6px;")
            main_layout.addWidget(sec_title3)

            card_actions = WindowsCard()
            actions_layout = QtWidgets.QGridLayout(card_actions)
            actions_layout.setContentsMargins(16, 16, 16, 16)
            actions_layout.setSpacing(12)

            btn_screen = QtWidgets.QPushButton("  Turn off screen now")
            btn_screen.setIcon(QtGui.QIcon.fromTheme("display"))
            btn_screen.setStyleSheet("text-align: left; padding: 12px 16px; font-weight: 600;")
            btn_screen.clicked.connect(turn_off_screen_now)
            actions_layout.addWidget(btn_screen, 0, 0)

            btn_sleep = QtWidgets.QPushButton("  Sleep (Suspend)")
            btn_sleep.setIcon(QtGui.QIcon.fromTheme("system-suspend"))
            btn_sleep.setStyleSheet("text-align: left; padding: 12px 16px; font-weight: 600;")
            btn_sleep.clicked.connect(self.action_sleep)
            actions_layout.addWidget(btn_sleep, 0, 1)

            btn_lock = QtWidgets.QPushButton("  Lock PC")
            btn_lock.setIcon(QtGui.QIcon.fromTheme("system-lock-screen"))
            btn_lock.setStyleSheet("text-align: left; padding: 12px 16px; font-weight: 600;")
            btn_lock.clicked.connect(lock_pc)
            actions_layout.addWidget(btn_lock, 0, 2)

            btn_restart = QtWidgets.QPushButton("  Restart")
            btn_restart.setIcon(QtGui.QIcon.fromTheme("system-reboot"))
            btn_restart.setStyleSheet("text-align: left; padding: 12px 16px; font-weight: 600; color: #60a5fa;")
            btn_restart.clicked.connect(self.action_restart)
            actions_layout.addWidget(btn_restart, 1, 0)

            btn_poweroff = QtWidgets.QPushButton("  Shut down (Power off)")
            btn_poweroff.setIcon(QtGui.QIcon.fromTheme("system-shutdown"))
            btn_poweroff.setStyleSheet("text-align: left; padding: 12px 16px; font-weight: 600; color: #f87171;")
            btn_poweroff.clicked.connect(self.action_poweroff)
            actions_layout.addWidget(btn_poweroff, 1, 1, 1, 2)

            main_layout.addWidget(card_actions)

            # Status footer
            self.status_lbl = QtWidgets.QLabel("Settings saved automatically.")
            self.status_lbl.setStyleSheet("font-size: 11px; color: #6e6e6e; margin-top: 4px;")
            main_layout.addWidget(self.status_lbl)

        def _make_divider(self):
            div = QtWidgets.QFrame()
            div.setFrameShape(QtWidgets.QFrame.HLine)
            div.setFrameShadow(QtWidgets.QFrame.Plain)
            div.setStyleSheet("color: #383838; background-color: #383838; height: 1px; border: none;")
            return div

        def on_screen_timeout_changed(self, idx):
            sec = self.combo_screen.currentData()
            self.cfg["screen_timeout_plugged"] = sec
            self.cfg["screen_timeout_battery"] = sec
            save_config(self.cfg)
            apply_screen_timeout(sec)
            self.show_toast(f"Screen timeout set to {self.combo_screen.currentText()}.")

        def on_sleep_timeout_changed(self, idx):
            sec = self.combo_sleep.currentData()
            self.cfg["sleep_timeout_plugged"] = sec
            self.cfg["sleep_timeout_battery"] = sec
            save_config(self.cfg)
            self.show_toast(f"Device sleep timeout set to {self.combo_sleep.currentText()}.")

        def on_mode_selected(self, mode_id: str):
            for mid, card in self.mode_cards.items():
                card.set_selected(mid == mode_id)
            self.cfg["power_mode"] = mode_id
            save_config(self.cfg)
            set_cpu_power_mode(mode_id)
            label = {"power_saver": "Best power efficiency", "balanced": "Balanced", "performance": "Best performance"}.get(mode_id, mode_id)
            self.show_toast(f"Power mode changed to {label}.")

        def show_toast(self, msg: str):
            self.status_lbl.setText(f"✓ {msg}")
            self.status_lbl.setStyleSheet("font-size: 12px; color: #0078d4; font-weight: 500;")

        def action_sleep(self):
            suspend_pc()

        def action_restart(self):
            reply = QtWidgets.QMessageBox.question(
                self, "Restart PC", "Are you sure you want to restart your PC? Unsaved work will be lost.",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No
            )
            if reply == QtWidgets.QMessageBox.Yes:
                reboot_pc()

        def action_poweroff(self):
            reply = QtWidgets.QMessageBox.question(
                self, "Shut Down PC", "Are you sure you want to shut down your PC? Unsaved work will be lost.",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No
            )
            if reply == QtWidgets.QMessageBox.Yes:
                poweroff_pc()

    win = PowerDialog()
    win.show()
    return app.exec_()


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="DevOS Power & Sleep Manager")
    parser.add_argument("--daemon", action="store_true", help="Run background sleep timeout daemon")
    parser.add_argument("--status", action="store_true", help="Print power status and configuration as JSON")
    parser.add_argument("--apply", action="store_true", help="Apply saved screen timeout immediately")
    parser.add_argument("--screen-timeout", type=int, default=None, help="Set screen timeout in seconds (0 = never)")
    parser.add_argument("--sleep-timeout", type=int, default=None, help="Set system sleep timeout in seconds (0 = never)")
    parser.add_argument("--power-mode", choices=["power_saver", "balanced", "performance"], help="Set CPU power mode")
    parser.add_argument("--screen-off", action="store_true", help="Turn off screen immediately")
    parser.add_argument("--sleep", action="store_true", help="Put PC to sleep immediately")
    parser.add_argument("--poweroff", action="store_true", help="Power off (shut down) PC")
    parser.add_argument("--reboot", action="store_true", help="Restart PC")

    args = parser.parse_args(argv)

    if args.daemon:
        run_sleep_daemon()
        return 0

    if args.apply:
        cfg = load_config()
        sec = cfg.get("screen_timeout_plugged", 600)
        apply_screen_timeout(sec)
        set_cpu_power_mode(cfg.get("power_mode", "balanced"))
        return 0

    if args.screen_off:
        return 0 if turn_off_screen_now() else 1

    if args.sleep:
        return 0 if suspend_pc() else 1

    if args.poweroff:
        return 0 if poweroff_pc() else 1

    if args.reboot:
        return 0 if reboot_pc() else 1

    if args.screen_timeout is not None:
        cfg = load_config()
        cfg["screen_timeout_plugged"] = args.screen_timeout
        save_config(cfg)
        apply_screen_timeout(args.screen_timeout)
        print(f"Screen timeout set to {args.screen_timeout}s")
        return 0

    if args.sleep_timeout is not None:
        cfg = load_config()
        cfg["sleep_timeout_plugged"] = args.sleep_timeout
        save_config(cfg)
        print(f"Sleep timeout set to {args.sleep_timeout}s")
        return 0

    if args.power_mode:
        cfg = load_config()
        cfg["power_mode"] = args.power_mode
        save_config(cfg)
        set_cpu_power_mode(args.power_mode)
        print(f"Power mode set to {args.power_mode}")
        return 0

    if args.status:
        cfg = load_config()
        pwr = get_power_source()
        dpms_on, scr_sec = get_current_screen_timeout()
        cpu_mode = get_cpu_power_mode()
        print(json.dumps({
            "config": cfg,
            "power_source": pwr,
            "screen_timeout_seconds": scr_sec,
            "dpms_enabled": dpms_on,
            "cpu_power_mode": cpu_mode,
        }, indent=2))
        return 0

    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
