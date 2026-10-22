#!/usr/bin/env python3
"""DevOS Broadband Dial-up (PPPoE / Direct ONU Connection).

Provides a Windows-familiar broadband dial-up GUI for direct ONU / fiber modem
connections using PPPoE credentials (ISP Username & Password).
"""

import os
import re
import shutil
import subprocess
import sys
from typing import Dict, List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets


def get_ethernet_interfaces() -> List[str]:
    """Lists physical ethernet interfaces on the system."""
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
        # Fallback to sysfs
        net_dir = "/sys/class/net"
        if os.path.isdir(net_dir):
            for iface in os.listdir(net_dir):
                if iface.startswith(("en", "eth")):
                    interfaces.append(iface)

    return sorted(interfaces) or ["enp0s31f6"]


def get_pppoe_connections() -> List[Dict[str, str]]:
    """Gets existing PPPoE / DSL connections from NetworkManager."""
    conns = []
    try:
        out = subprocess.check_output(
            ["nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show"],
            text=True,
            errors="replace"
        )
        for line in out.strip().splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[2].strip() in ("pppoe", "dsl"):
                conns.append({
                    "name": parts[0].strip(),
                    "uuid": parts[1].strip(),
                    "type": parts[2].strip(),
                    "device": parts[3].strip() if len(parts) > 3 else ""
                })
    except Exception:
        pass
    return conns


def get_active_pppoe_info() -> Optional[Dict[str, str]]:
    """Checks if any PPPoE connection is currently active."""
    try:
        out = subprocess.check_output(
            ["nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show", "--active"],
            text=True,
            errors="replace"
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
                            errors="replace"
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


class BroadbandWindow(QtWidgets.QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Broadband Connection (PPPoE / Direct ONU)")
        self.setFixedSize(480, 420)
        self.setStyleSheet("""
            QDialog {
                background-color: #0b101e;
                color: #f1f5f9;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }
            QLabel {
                color: #e2e8f0;
                font-size: 13px;
            }
            QLabel#heading {
                font-size: 18px;
                font-weight: 700;
                color: #ffffff;
            }
            QLabel#subheading {
                font-size: 12px;
                color: #94a3b8;
            }
            QLineEdit, QComboBox {
                background-color: #172138;
                border: 1px solid #2d3d63;
                border-radius: 8px;
                padding: 9px 12px;
                color: #ffffff;
                font-size: 13px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #38bdf8;
                background-color: #1c2844;
            }
            QCheckBox {
                color: #cbd5e1;
                font-size: 12px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #334155;
                background: #172138;
            }
            QCheckBox::indicator:checked {
                background: #0284c7;
                border-color: #38bdf8;
            }
            QPushButton#dialBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #00f2fe);
                color: #030712;
                font-weight: 700;
                font-size: 14px;
                padding: 12px;
                border-radius: 8px;
                border: none;
            }
            QPushButton#dialBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0369a1, stop:1 #38bdf8);
            }
            QPushButton#dialBtn:pressed {
                background: #0284c7;
            }
            QPushButton#hangupBtn {
                background: #ef4444;
                color: #ffffff;
                font-weight: 700;
                font-size: 14px;
                padding: 12px;
                border-radius: 8px;
                border: none;
            }
            QPushButton#hangupBtn:hover {
                background: #dc2626;
            }
            QFrame#statusCard {
                background: #111a2f;
                border: 1px solid #1e293b;
                border-radius: 8px;
                padding: 8px;
            }
        """)

        self.init_ui()
        self.poll_timer = QtCore.QTimer(self)
        self.poll_timer.timeout.connect(self.update_status)
        self.poll_timer.start(3000)
        self.update_status()

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        # Header with network icon
        header_row = QtWidgets.QHBoxLayout()
        header_text = QtWidgets.QVBoxLayout()
        title = QtWidgets.QLabel("Broadband Dial-up (ONU)", self)
        title.setObjectName("heading")
        sub = QtWidgets.QLabel("Connect directly via ONU / Fiber Cable (PPPoE)", self)
        sub.setObjectName("subheading")
        header_text.addWidget(title)
        header_text.addWidget(sub)
        header_row.addLayout(header_text)
        header_row.addStretch()
        layout.addLayout(header_row)

        # Status Card
        self.status_card = QtWidgets.QFrame(self)
        self.status_card.setObjectName("statusCard")
        status_layout = QtWidgets.QHBoxLayout(self.status_card)
        status_layout.setContentsMargins(12, 10, 12, 10)
        self.status_dot = QtWidgets.QLabel("●", self.status_card)
        self.status_dot.setStyleSheet("font-size: 16px; color: #94a3b8;")
        self.status_label = QtWidgets.QLabel("Disconnected", self.status_card)
        self.status_label.setStyleSheet("font-weight: 600; font-size: 13px; color: #cbd5e1;")
        status_layout.addWidget(self.status_dot)
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        layout.addWidget(self.status_card)

        # Form
        form_layout = QtWidgets.QVBoxLayout()
        form_layout.setSpacing(10)

        # Connection Name
        lbl_conn = QtWidgets.QLabel("Connection Name:", self)
        self.txt_conn = QtWidgets.QLineEdit(self)
        self.txt_conn.setText("Broadband")
        form_layout.addWidget(lbl_conn)
        form_layout.addWidget(self.txt_conn)

        # Username
        lbl_user = QtWidgets.QLabel("ISP Username (User ID):", self)
        self.txt_user = QtWidgets.QLineEdit(self)
        self.txt_user.setPlaceholderText("e.g. client_10482")
        form_layout.addWidget(lbl_user)
        form_layout.addWidget(self.txt_user)

        # Password
        lbl_pass = QtWidgets.QLabel("ISP Password:", self)
        self.txt_pass = QtWidgets.QLineEdit(self)
        self.txt_pass.setEchoMode(QtWidgets.QLineEdit.Password)
        self.txt_pass.setPlaceholderText("••••••••")
        form_layout.addWidget(lbl_pass)
        form_layout.addWidget(self.txt_pass)

        # Ethernet Interface
        lbl_iface = QtWidgets.QLabel("LAN / Ethernet Port:", self)
        self.cmb_iface = QtWidgets.QComboBox(self)
        interfaces = get_ethernet_interfaces()
        for iface in interfaces:
            self.cmb_iface.addItem(iface)
        form_layout.addWidget(lbl_iface)
        form_layout.addWidget(self.cmb_iface)

        layout.addLayout(form_layout)

        # Load existing connection values if present
        existing = get_pppoe_connections()
        if existing:
            first = existing[0]
            self.txt_conn.setText(first["name"])

        # Checkboxes
        self.chk_auto = QtWidgets.QCheckBox("Connect automatically when computer starts", self)
        self.chk_auto.setChecked(True)
        layout.addWidget(self.chk_auto)

        # Action Buttons
        btn_row = QtWidgets.QHBoxLayout()
        self.btn_dial = QtWidgets.QPushButton("Connect / Dial", self)
        self.btn_dial.setObjectName("dialBtn")
        self.btn_dial.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.btn_dial.clicked.connect(self.on_dial_clicked)

        self.btn_hangup = QtWidgets.QPushButton("Disconnect", self)
        self.btn_hangup.setObjectName("hangupBtn")
        self.btn_hangup.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.btn_hangup.clicked.connect(self.on_hangup_clicked)
        self.btn_hangup.setVisible(False)

        btn_row.addWidget(self.btn_dial)
        btn_row.addWidget(self.btn_hangup)
        layout.addLayout(btn_row)

    def update_status(self):
        active = get_active_pppoe_info()
        if active:
            ip_str = f" • IP: {active['ip']}" if active.get("ip") else ""
            self.status_dot.setStyleSheet("font-size: 16px; color: #10b981;")
            self.status_label.setText(f"Connected to {active['name']}{ip_str}")
            self.status_label.setStyleSheet("font-weight: 600; font-size: 13px; color: #34d399;")
            self.btn_dial.setVisible(False)
            self.btn_hangup.setVisible(True)
        else:
            self.status_dot.setStyleSheet("font-size: 16px; color: #94a3b8;")
            self.status_label.setText("Disconnected")
            self.status_label.setStyleSheet("font-weight: 600; font-size: 13px; color: #cbd5e1;")
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
            QtWidgets.QMessageBox.warning(self, "Missing Username", "Please enter your ISP Username / User ID.")
            return

        self.status_dot.setStyleSheet("font-size: 16px; color: #f59e0b;")
        self.status_label.setText("Dialing / Connecting to ONU...")
        self.status_label.setStyleSheet("font-weight: 600; font-size: 13px; color: #fbbf24;")
        self.btn_dial.setEnabled(False)
        self.btn_dial.setText("Dialing...")
        QtWidgets.QApplication.processEvents()

        # Check if connection already exists in NetworkManager
        existing_names = [c["name"] for c in get_pppoe_connections()]
        try:
            if conn_name in existing_names:
                # Update existing
                if pwd:
                    subprocess.run(["nmcli", "connection", "modify", conn_name,
                                    "username", user,
                                    "password", pwd,
                                    "connection.interface-name", iface,
                                    "connection.autoconnect", "yes" if self.chk_auto.isChecked() else "no"],
                                   check=True)
                else:
                    subprocess.run(["nmcli", "connection", "modify", conn_name,
                                    "username", user,
                                    "connection.interface-name", iface,
                                    "connection.autoconnect", "yes" if self.chk_auto.isChecked() else "no"],
                                   check=True)
            else:
                # Create new PPPoE connection
                cmd = [
                    "nmcli", "connection", "add",
                    "type", "pppoe",
                    "con-name", conn_name,
                    "ifname", iface,
                    "username", user,
                    "connection.autoconnect", "yes" if self.chk_auto.isChecked() else "no"
                ]
                if pwd:
                    cmd.extend(["password", pwd])
                subprocess.run(cmd, check=True)

            # Bring connection up (Dial)
            res = subprocess.run(["nmcli", "connection", "up", conn_name], capture_output=True, text=True)
            if res.returncode == 0:
                self.update_status()
                QtWidgets.QMessageBox.information(
                    self, "Connected",
                    f"Successfully connected to Broadband ({conn_name})!\nInternet is now active."
                )
            else:
                err_msg = res.stderr or res.stdout or "Connection timed out."
                if "pppd" in err_msg.lower() or "ppp" in err_msg.lower():
                    err_msg += "\n\nNote: The 'ppp' package may need to be installed. Run: sudo apt install ppp"
                QtWidgets.QMessageBox.critical(self, "Dial Failed", f"Could not connect:\n{err_msg}")
                self.update_status()

        except subprocess.CalledProcessError as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to configure connection:\n{e}")
            self.update_status()

    def on_hangup_clicked(self):
        active = get_active_pppoe_info()
        name = active["name"] if active else self.txt_conn.text().strip() or "Broadband"
        subprocess.run(["nmcli", "connection", "down", name])
        self.update_status()


def main():
    app = QtWidgets.QApplication(sys.argv)
    win = BroadbandWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
