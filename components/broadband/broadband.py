#!/usr/bin/env python3
"""DevOS Broadband Dial-up (PPPoE / Direct ONU Connection).

Windows-familiar broadband dial-up GUI for direct ONU / fiber modem
connections using PPPoE credentials (ISP Username & Password).

Chrome is authored dark; devos_appearance converts it for light mode and
keeps text/background contrast correct when the user toggles theme.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Dict, List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets


# Dark source stylesheet — Appearance rewrites for light mode.
STYLE = """
QMainWindow, QWidget#root {
    background: #0b101e;
    color: #f1f5f9;
    font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif;
}
QLabel {
    color: #e2e8f0;
    font-size: 13px;
    background: transparent;
}
QLabel#brand {
    font-size: 22px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: -0.3px;
}
QLabel#lead {
    font-size: 13px;
    color: #94a3b8;
}
QLabel#fieldLabel {
    font-size: 12px;
    font-weight: 600;
    color: #cbd5e1;
}
QFrame#card {
    background: #111827;
    border: 1px solid #1e293b;
    border-radius: 14px;
}
QFrame#statusCard {
    background: #111a2f;
    border: 1px solid #1e293b;
    border-radius: 12px;
}
QLabel#statusText {
    font-size: 13px;
    font-weight: 600;
    color: #cbd5e1;
}
QLineEdit, QComboBox {
    background: #0f1525;
    border: 1px solid #334155;
    border-radius: 10px;
    padding: 10px 12px;
    color: #f8fafc;
    font-size: 14px;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
    min-height: 20px;
}
QLineEdit:focus, QComboBox:focus {
    border: 1.5px solid #38bdf8;
    background: #111827;
}
QLineEdit::placeholder {
    color: #94a3b8;
}
QComboBox::drop-down {
    border: none;
    width: 28px;
}
QComboBox QAbstractItemView {
    background: #111827;
    color: #f8fafc;
    border: 1px solid #334155;
    selection-background-color: #1e3a5f;
    selection-color: #ffffff;
    outline: 0;
}
QCheckBox {
    color: #cbd5e1;
    font-size: 13px;
    spacing: 10px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1.5px solid #475569;
    background: #0f1525;
}
QCheckBox::indicator:checked {
    background: #2563eb;
    border-color: #38bdf8;
}
QPushButton#dialBtn {
    background: #2563eb;
    color: #ffffff;
    font-weight: 700;
    font-size: 14px;
    padding: 12px 18px;
    border-radius: 10px;
    border: none;
    min-height: 44px;
}
QPushButton#dialBtn:hover { background: #1d4ed8; }
QPushButton#dialBtn:pressed { background: #1e40af; }
QPushButton#dialBtn:disabled { background: #1e3a5f; color: #94a3b8; }
QPushButton#hangupBtn {
    background: #dc2626;
    color: #ffffff;
    font-weight: 700;
    font-size: 14px;
    padding: 12px 18px;
    border-radius: 10px;
    border: none;
    min-height: 44px;
}
QPushButton#hangupBtn:hover { background: #b91c1c; }
QToolButton#eyeBtn {
    background: transparent;
    border: none;
    color: #94a3b8;
    padding: 4px 8px;
    font-size: 12px;
    font-weight: 600;
}
QToolButton#eyeBtn:hover { color: #f8fafc; }
QScrollArea { border: none; background: transparent; }
"""


def get_ethernet_interfaces() -> List[str]:
    interfaces = []
    try:
        out = subprocess.check_output(["nmcli", "-t", "-f", "DEVICE,TYPE", "device"], text=True)
        for line in out.strip().splitlines():
            if ":" in line:
                dev, dev_type = line.split(":", 1)
                if dev_type.strip() == "ethernet":
                    interfaces.append(dev.strip())
    except Exception:
        pass

    if not interfaces:
        net_dir = "/sys/class/net"
        if os.path.isdir(net_dir):
            for iface in os.listdir(net_dir):
                if iface.startswith(("en", "eth")):
                    interfaces.append(iface)

    return sorted(interfaces) or ["enp0s31f6"]


def get_pppoe_connections() -> List[Dict[str, str]]:
    conns = []
    try:
        out = subprocess.check_output(
            ["nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show"],
            text=True,
            errors="replace",
        )
        for line in out.strip().splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[2].strip() in ("pppoe", "dsl"):
                conns.append({
                    "name": parts[0].strip(),
                    "uuid": parts[1].strip(),
                    "type": parts[2].strip(),
                    "device": parts[3].strip() if len(parts) > 3 else "",
                })
    except Exception:
        pass
    return conns


def get_active_pppoe_info() -> Optional[Dict[str, str]]:
    try:
        out = subprocess.check_output(
            ["nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show", "--active"],
            text=True,
            errors="replace",
        )
        for line in out.strip().splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[2].strip() in ("pppoe", "dsl"):
                name = parts[0].strip()
                dev = parts[3].strip() if len(parts) > 3 else ""
                ip = ""
                if dev:
                    try:
                        ip_out = subprocess.check_output(
                            ["nmcli", "-t", "-f", "IP4.ADDRESS", "device", "show", dev],
                            text=True,
                            errors="replace",
                        )
                        for ipline in ip_out.splitlines():
                            if ipline.startswith("IP4.ADDRESS"):
                                ip = ipline.split(":", 1)[1].strip()
                                break
                    except Exception:
                        pass
                return {"name": name, "device": dev, "ip": ip}
    except Exception:
        pass
    return None


class BroadbandWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Broadband Dial-up")
        self.setMinimumSize(420, 520)
        self.resize(520, 600)
        self.setStyleSheet(STYLE)
        self._build_ui()
        self.poll_timer = QtCore.QTimer(self)
        self.poll_timer.timeout.connect(self.update_status)
        self.poll_timer.start(3000)
        self.update_status()

    def _field_label(self, text: str) -> QtWidgets.QLabel:
        lbl = QtWidgets.QLabel(text)
        lbl.setObjectName("fieldLabel")
        return lbl

    def _build_ui(self):
        root = QtWidgets.QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QtWidgets.QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        body = QtWidgets.QWidget()
        scroll.setWidget(body)
        layout = QtWidgets.QVBoxLayout(body)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        brand = QtWidgets.QLabel("Broadband Dial-up")
        brand.setObjectName("brand")
        lead = QtWidgets.QLabel("Connect through your ONU / fiber modem with ISP PPPoE login.")
        lead.setObjectName("lead")
        lead.setWordWrap(True)
        layout.addWidget(brand)
        layout.addWidget(lead)

        self.status_card = QtWidgets.QFrame()
        self.status_card.setObjectName("statusCard")
        status_layout = QtWidgets.QHBoxLayout(self.status_card)
        status_layout.setContentsMargins(14, 12, 14, 12)
        self.status_dot = QtWidgets.QLabel("●")
        self.status_label = QtWidgets.QLabel("Disconnected")
        self.status_label.setObjectName("statusText")
        status_layout.addWidget(self.status_dot)
        status_layout.addWidget(self.status_label, 1)
        layout.addWidget(self.status_card)

        card = QtWidgets.QFrame()
        card.setObjectName("card")
        form = QtWidgets.QVBoxLayout(card)
        form.setContentsMargins(18, 18, 18, 18)
        form.setSpacing(12)

        form.addWidget(self._field_label("Connection name"))
        self.txt_conn = QtWidgets.QLineEdit()
        self.txt_conn.setText("Broadband")
        self.txt_conn.setClearButtonEnabled(True)
        form.addWidget(self.txt_conn)

        form.addWidget(self._field_label("ISP username (User ID)"))
        self.txt_user = QtWidgets.QLineEdit()
        self.txt_user.setPlaceholderText("e.g. client_10482")
        self.txt_user.setClearButtonEnabled(True)
        form.addWidget(self.txt_user)

        form.addWidget(self._field_label("ISP password"))
        pass_row = QtWidgets.QHBoxLayout()
        self.txt_pass = QtWidgets.QLineEdit()
        self.txt_pass.setEchoMode(QtWidgets.QLineEdit.Password)
        self.txt_pass.setPlaceholderText("Enter password")
        self.btn_eye = QtWidgets.QToolButton()
        self.btn_eye.setObjectName("eyeBtn")
        self.btn_eye.setText("Show")
        self.btn_eye.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.btn_eye.clicked.connect(self._toggle_password)
        pass_row.addWidget(self.txt_pass, 1)
        pass_row.addWidget(self.btn_eye)
        form.addLayout(pass_row)

        form.addWidget(self._field_label("LAN / Ethernet port"))
        self.cmb_iface = QtWidgets.QComboBox()
        for iface in get_ethernet_interfaces():
            self.cmb_iface.addItem(iface)
        form.addWidget(self.cmb_iface)

        self.chk_auto = QtWidgets.QCheckBox("Connect automatically when this computer starts")
        self.chk_auto.setChecked(True)
        form.addWidget(self.chk_auto)
        layout.addWidget(card)

        existing = get_pppoe_connections()
        if existing:
            self.txt_conn.setText(existing[0]["name"])

        btn_row = QtWidgets.QHBoxLayout()
        self.btn_dial = QtWidgets.QPushButton("Connect / Dial")
        self.btn_dial.setObjectName("dialBtn")
        self.btn_dial.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.btn_dial.clicked.connect(self.on_dial_clicked)
        self.btn_hangup = QtWidgets.QPushButton("Disconnect")
        self.btn_hangup.setObjectName("hangupBtn")
        self.btn_hangup.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.btn_hangup.clicked.connect(self.on_hangup_clicked)
        self.btn_hangup.setVisible(False)
        btn_row.addWidget(self.btn_dial, 1)
        btn_row.addWidget(self.btn_hangup, 1)
        layout.addLayout(btn_row)
        layout.addStretch(1)

    def _toggle_password(self):
        if self.txt_pass.echoMode() == QtWidgets.QLineEdit.Password:
            self.txt_pass.setEchoMode(QtWidgets.QLineEdit.Normal)
            self.btn_eye.setText("Hide")
        else:
            self.txt_pass.setEchoMode(QtWidgets.QLineEdit.Password)
            self.btn_eye.setText("Show")

    def _set_status(self, text: str, color: str, dot: str):
        # Semantic colors stay readable after light/dark adaptation.
        self.status_dot.setStyleSheet(f"font-size: 14px; color: {dot}; background: transparent;")
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"font-weight: 600; font-size: 13px; color: {color}; background: transparent;"
        )

    def update_status(self):
        active = get_active_pppoe_info()
        if active:
            ip_str = f"  ·  {active['ip']}" if active.get("ip") else ""
            self._set_status(f"Connected — {active['name']}{ip_str}", "#34d399", "#10b981")
            self.btn_dial.setVisible(False)
            self.btn_hangup.setVisible(True)
        else:
            self._set_status("Disconnected — ready to dial", "#94a3b8", "#94a3b8")
            self.btn_dial.setVisible(True)
            self.btn_dial.setText("Connect / Dial")
            self.btn_dial.setEnabled(True)
            self.btn_hangup.setVisible(False)

    def on_dial_clicked(self):
        conn_name = self.txt_conn.text().strip() or "Broadband"
        user = self.txt_user.text().strip()
        pwd = self.txt_pass.text()
        iface = self.cmb_iface.currentText().strip()
        if not user:
            QtWidgets.QMessageBox.warning(self, "Missing username", "Enter your ISP username / User ID.")
            return

        self._set_status("Dialing ONU…", "#fbbf24", "#f59e0b")
        self.btn_dial.setEnabled(False)
        self.btn_dial.setText("Dialing…")
        QtWidgets.QApplication.processEvents()

        existing_names = [c["name"] for c in get_pppoe_connections()]
        try:
            if conn_name in existing_names:
                args = [
                    "nmcli", "connection", "modify", conn_name,
                    "username", user,
                    "connection.interface-name", iface,
                    "connection.autoconnect", "yes" if self.chk_auto.isChecked() else "no",
                ]
                if pwd:
                    args = [
                        "nmcli", "connection", "modify", conn_name,
                        "username", user, "password", pwd,
                        "connection.interface-name", iface,
                        "connection.autoconnect", "yes" if self.chk_auto.isChecked() else "no",
                    ]
                subprocess.run(args, check=True)
            else:
                cmd = [
                    "nmcli", "connection", "add",
                    "type", "pppoe", "con-name", conn_name, "ifname", iface,
                    "username", user,
                    "connection.autoconnect", "yes" if self.chk_auto.isChecked() else "no",
                ]
                if pwd:
                    cmd.extend(["password", pwd])
                subprocess.run(cmd, check=True)

            res = subprocess.run(
                ["nmcli", "connection", "up", conn_name],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                self.update_status()
                QtWidgets.QMessageBox.information(
                    self, "Connected", f"Connected to {conn_name}.\nInternet is active."
                )
            else:
                err_msg = res.stderr or res.stdout or "Connection timed out."
                if "pppd" in err_msg.lower() or "ppp" in err_msg.lower():
                    err_msg += "\n\nTip: install PPP support with:\nsudo apt install ppp"
                QtWidgets.QMessageBox.critical(self, "Dial failed", f"Could not connect:\n{err_msg}")
                self.update_status()
        except subprocess.CalledProcessError as exc:
            QtWidgets.QMessageBox.critical(self, "Error", f"Could not configure connection:\n{exc}")
            self.update_status()

    def on_hangup_clicked(self):
        active = get_active_pppoe_info()
        name = active["name"] if active else self.txt_conn.text().strip() or "Broadband"
        subprocess.run(["nmcli", "connection", "down", name])
        self.update_status()


def main():
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app_identity import apply as apply_identity, prepare as prepare_identity, show_window
    from devos_dialogs import install as install_dialog_style

    prepare_identity("devos-broadband")
    app = QtWidgets.QApplication(sys.argv)
    install_dialog_style(app)
    apply_identity(app, "devos-broadband")
    win = BroadbandWindow()
    show_window(win, "devos-broadband")
    raise SystemExit(app.exec_())


if __name__ == "__main__":
    main()
