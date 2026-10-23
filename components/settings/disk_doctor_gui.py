#!/usr/bin/env python3
"""
DevOS Visual Disk & Boot Doctor (PyQt5 GUI)
Provides a visual interface showing disks, partition schemes (MBR vs GPT),
diagnostics, and click-to-solve action buttons for end users.
"""

import sys
import os

try:
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtGui import QFont, QColor
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QFrame, QScrollArea, QMessageBox, QGroupBox,
        QTableWidget, QTableWidgetItem, QHeaderView
    )
except ImportError:
    print("PyQt5 not installed. Run 'devos disk' in CLI mode.")
    sys.exit(1)

# Import backend DiskManager
SYS_PATH = os.path.dirname(os.path.abspath(__file__))
if SYS_PATH not in sys.path:
    sys.path.insert(0, SYS_PATH)

from disk_manager import DiskManager, is_live_system


class DiskDoctorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DevOS Storage & Boot Doctor")
        self.resize(850, 620)
        self.setStyleSheet("""
            QMainWindow { background-color: #0d0f18; color: #f8fafc; }
            QLabel { color: #f8fafc; font-family: 'Inter', sans-serif; }
            QGroupBox { border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; margin-top: 14px; padding: 14px; color: #38bdf8; font-weight: bold; }
            QPushButton { border-radius: 8px; padding: 10px 18px; font-weight: bold; font-size: 13px; }
            QTableWidget { background-color: #121826; border: 1px solid rgba(56, 189, 248, 0.2); border-radius: 8px; color: #f8fafc; gridline-color: rgba(255, 255, 255, 0.05); }
            QHeaderView::section { background-color: #1a2234; color: #94a3b8; padding: 6px; font-weight: bold; border: none; }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setContentsMargins(24, 20, 24, 20)
        self.main_layout.setSpacing(16)

        # Header Title
        title_box = QHBoxLayout()
        header_text = QVBoxLayout()
        title = QLabel("DevOS Storage & Boot Doctor")
        title.setStyleSheet("font-size: 22px; font-weight: 800; color: #38bdf8;")
        sub = QLabel("Visual disk manager: detect MBR vs GPT, check EFI compatibility, and solve issues.")
        sub.setStyleSheet("font-size: 13px; color: #94a3b8;")
        header_text.addWidget(title)
        header_text.addWidget(sub)
        title_box.addLayout(header_text)
        title_box.addStretch()

        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setStyleSheet("background: #1e293b; color: #38bdf8; border: 1px solid #38bdf8;")
        refresh_btn.clicked.connect(self.refresh_disks)
        title_box.addWidget(refresh_btn)
        self.main_layout.addLayout(title_box)

        # Firmware Status Banner
        self.fw_banner = QFrame()
        self.fw_banner.setStyleSheet("background: rgba(14, 165, 233, 0.1); border-left: 4px solid #0284c7; border-radius: 6px; padding: 10px;")
        fw_box = QHBoxLayout(self.fw_banner)
        self.fw_label = QLabel("Detecting Firmware Mode...")
        self.fw_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #e0f2fe;")
        fw_box.addWidget(self.fw_label)
        self.main_layout.addWidget(self.fw_banner)

        # Scroll Area for Disk Cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        self.card_container = QWidget()
        self.card_layout = QVBoxLayout(self.card_container)
        self.card_layout.setSpacing(16)
        scroll.setWidget(self.card_container)
        self.main_layout.addWidget(scroll, 1)

        # Bottom Bar Buttons
        bottom_box = QHBoxLayout()
        installer_btn = QPushButton("🚀 Open Calamares Installer")
        installer_btn.setStyleSheet("background: linear-gradient(135deg, #0284c7, #38bdf8); color: #041018; font-size: 14px;")
        installer_btn.clicked.connect(lambda: DiskManager.apply_solution("", "launch_installer"))

        reboot_btn = QPushButton("⏻ Safely Reboot & Eject USB")
        reboot_btn.setStyleSheet("background: #334155; color: #f8fafc;")
        reboot_btn.clicked.connect(self.confirm_reboot)

        bottom_box.addWidget(installer_btn)
        bottom_box.addStretch()
        bottom_box.addWidget(reboot_btn)
        # Installer and "eject USB" only make sense on the live USB.
        if not is_live_system():
            installer_btn.hide()
            reboot_btn.hide()
        self.main_layout.addLayout(bottom_box)

        self.refresh_disks()

    def refresh_disks(self):
        # Update Firmware Banner
        is_uefi = DiskManager.is_uefi_system()
        if is_uefi:
            self.fw_label.setText("🛡️ System Boot Mode: Modern UEFI (Requires GPT & 512MB EFI System Partition)")
            self.fw_banner.setStyleSheet("background: rgba(16, 185, 129, 0.12); border-left: 4px solid #10b981; border-radius: 6px; padding: 10px;")
        else:
            self.fw_label.setText("⚙️ System Boot Mode: Legacy BIOS / CSM (Supports MBR or GPT with bios_grub)")
            self.fw_banner.setStyleSheet("background: rgba(245, 158, 11, 0.12); border-left: 4px solid #f59e0b; border-radius: 6px; padding: 10px;")

        # Clear existing disk cards
        for i in reversed(range(self.card_layout.count())):
            widget = self.card_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        disks = DiskManager.get_storage_info()
        for disk in disks:
            card = self.create_disk_card(disk)
            self.card_layout.addWidget(card)

    def create_disk_card(self, disk):
        group = QGroupBox(f"Drive: {disk['device']}  —  {disk['model']}  ({disk['size_human']})")
        vbox = QVBoxLayout(group)
        vbox.setSpacing(12)

        # Partition Table status label
        pt_label = QLabel(f"Partition Scheme: {disk['partition_table']}")
        pt_label.setStyleSheet("color: #7dd3fc; font-weight: 600; font-size: 13px;")
        vbox.addWidget(pt_label)

        # Partitions Table
        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["Partition", "Size", "Filesystem", "Mount / Role"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setRowCount(len(disk["partitions"]))

        for row, part in enumerate(disk["partitions"]):
            table.setItem(row, 0, QTableWidgetItem(part["device"]))
            table.setItem(row, 1, QTableWidgetItem(part["size_human"]))
            table.setItem(row, 2, QTableWidgetItem(part["fstype"]))
            mount_text = part["mountpoint"] or (f"Label: {part['label']}" if part["label"] else "[unmounted]")
            table.setItem(row, 3, QTableWidgetItem(mount_text))

        table.setFixedHeight(min(140, max(65, (len(disk["partitions"]) + 1) * 32)))
        vbox.addWidget(table)

        # Issues & Action Buttons
        for issue in disk.get("issues", []):
            alert = QFrame()
            if issue["severity"] == "success":
                alert.setStyleSheet("background: rgba(16, 185, 129, 0.12); border: 1px solid #10b981; border-radius: 8px; padding: 10px;")
            elif issue["severity"] == "warning":
                alert.setStyleSheet("background: rgba(245, 158, 11, 0.12); border: 1px solid #f59e0b; border-radius: 8px; padding: 10px;")
            else:
                alert.setStyleSheet("background: rgba(56, 189, 248, 0.12); border: 1px solid #38bdf8; border-radius: 8px; padding: 10px;")

            alert_box = QHBoxLayout(alert)
            info_box = QVBoxLayout()
            ititle = QLabel(f"<b>{issue['title']}</b>")
            ititle.setStyleSheet("font-size: 13px;")
            idesc = QLabel(issue["description"])
            idesc.setStyleSheet("color: #cbd5e1; font-size: 12px;")
            info_box.addWidget(ititle)
            info_box.addWidget(idesc)
            alert_box.addLayout(info_box)
            alert_box.addStretch()

            if issue.get("action_id"):
                action_btn = QPushButton(issue["action_label"])
                if issue["severity"] == "warning":
                    action_btn.setStyleSheet("background: #f59e0b; color: #020617; font-weight: bold;")
                else:
                    action_btn.setStyleSheet("background: #0284c7; color: #f8fafc; font-weight: bold;")

                dev_path = disk['device']
                act_id = issue['action_id']
                action_btn.clicked.connect(lambda _, d=dev_path, a=act_id: self.run_action(d, a))
                alert_box.addWidget(action_btn)

            vbox.addWidget(alert)

        return group

    def run_action(self, device, action_id):
        confirm = QMessageBox.question(
            self, "Confirm Disk Action",
            f"Are you sure you want to perform '{action_id}' on {device}?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            res = DiskManager.apply_solution(device, action_id)
            if res.get("success"):
                QMessageBox.information(self, "Success", res.get("message", "Action completed."))
                self.refresh_disks()
            else:
                QMessageBox.critical(self, "Error", res.get("error", "Action failed."))

    def confirm_reboot(self):
        confirm = QMessageBox.question(
            self, "Reboot System",
            "Are you ready to reboot? Please unplug the installation USB when the screen turns off.",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            DiskManager.apply_solution("", "reboot_system")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("devos-disk")
    app.setApplicationDisplayName("Storage & Boot Doctor")
    if hasattr(app, "setDesktopFileName"):
        app.setDesktopFileName("devos-disk")
    app.setFont(QFont("Inter", 11))
    window = DiskDoctorWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
