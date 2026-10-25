#!/usr/bin/env python3
"""
DevOS Visual Disk & Boot Doctor (PyQt5 GUI)
Provides a visual interface showing disks, partition schemes (MBR vs GPT),
used/free size breakdown, and Windows-Setup-style partition formatting and wipe tools.
"""

import sys
import os

try:
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtGui import QFont, QColor
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QFrame, QScrollArea, QMessageBox, QGroupBox,
        QTableWidget, QTableWidgetItem, QHeaderView, QDialog, QComboBox,
        QLineEdit, QFormLayout, QDialogButtonBox
    )
except ImportError:
    print("PyQt5 not installed. Run 'devos disk' in CLI mode.")
    sys.exit(1)

# Import backend DiskManager
SYS_PATH = os.path.dirname(os.path.abspath(__file__))
if SYS_PATH not in sys.path:
    sys.path.insert(0, SYS_PATH)

from disk_manager import DiskManager, is_live_system


class FormatPartitionDialog(QDialog):
    """Dialog to choose filesystem type and label when formatting a partition."""

    def __init__(self, device: str, default_label: str = "Storage", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Format Partition — {device}")
        self.resize(420, 240)
        self.setStyleSheet("""
            QDialog { background-color: #0f172a; color: #f8fafc; }
            QLabel { color: #f8fafc; font-size: 13px; }
            QComboBox, QLineEdit { background: #1e293b; color: #f8fafc; border: 1px solid #334155; border-radius: 6px; padding: 6px 10px; font-size: 13px; }
            QComboBox:focus, QLineEdit:focus { border: 1px solid #38bdf8; }
            QPushButton { border-radius: 6px; padding: 8px 16px; font-weight: bold; font-size: 13px; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel(f"<b>Format {device}</b>")
        title.setStyleSheet("font-size: 16px; color: #38bdf8;")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(12)

        self.fs_combo = QComboBox()
        self.fs_combo.addItem("ext4 (DevOS Standard - Fast & Stable)", "ext4")
        self.fs_combo.addItem("btrfs (Modern CoW & Snapper Snapshots)", "btrfs")
        self.fs_combo.addItem("exfat (Universal Windows & macOS)", "exfat")
        self.fs_combo.addItem("ntfs (Windows Compatible)", "ntfs")
        self.fs_combo.addItem("vfat (FAT32 Universal)", "vfat")
        form.addRow("Filesystem:", self.fs_combo)

        self.label_edit = QLineEdit(default_label)
        form.addRow("Volume Label:", self.label_edit)
        layout.addLayout(form)

        warn = QLabel("⚠️ Formatting will erase all data currently on this partition.")
        warn.setStyleSheet("color: #f59e0b; font-size: 12px;")
        layout.addWidget(warn)

        btn_box = QHBoxLayout()
        btn_box.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("background: #334155; color: #f8fafc;")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        format_btn = QPushButton("Format Partition")
        format_btn.setStyleSheet("background: #0284c7; color: #ffffff;")
        format_btn.clicked.connect(self.accept)
        btn_box.addWidget(format_btn)

        layout.addLayout(btn_box)

    def get_values(self):
        fs = self.fs_combo.currentData()
        label = self.label_edit.text().strip() or "Storage"
        return fs, label


class FormatDiskDialog(QDialog):
    """Dialog to choose filesystem and label when initializing an entire disk."""

    def __init__(self, device: str, model: str, size: str, mode: str = "storage", parent=None):
        super().__init__(parent)
        self.mode = mode
        title_text = "Setup as DevOS System Disk" if mode == "devos" else "Format Entire Disk as Storage"
        self.setWindowTitle(f"{title_text} — {device}")
        self.resize(450, 260)
        self.setStyleSheet("""
            QDialog { background-color: #0f172a; color: #f8fafc; }
            QLabel { color: #f8fafc; font-size: 13px; }
            QComboBox, QLineEdit { background: #1e293b; color: #f8fafc; border: 1px solid #334155; border-radius: 6px; padding: 6px 10px; font-size: 13px; }
            QComboBox:focus, QLineEdit:focus { border: 1px solid #38bdf8; }
            QPushButton { border-radius: 6px; padding: 8px 16px; font-weight: bold; font-size: 13px; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QLabel(f"<b>{title_text}</b>")
        header.setStyleSheet("font-size: 16px; color: #38bdf8;")
        layout.addWidget(header)

        desc = QLabel(f"Drive: <b>{device}</b> ({model} · {size})")
        desc.setStyleSheet("color: #94a3b8;")
        layout.addWidget(desc)

        form = QFormLayout()
        form.setSpacing(12)

        self.fs_combo = QComboBox()
        if mode == "devos":
            self.fs_combo.addItem("ext4 (Recommended standard for DevOS root)", "ext4")
            self.fs_combo.addItem("btrfs (For snapshot and subvolume rollbacks)", "btrfs")
            form.addRow("System Filesystem:", self.fs_combo)
            self.label_edit = QLineEdit("DevOS")
            form.addRow("System Label:", self.label_edit)
        else:
            self.fs_combo.addItem("ext4 (Fast & Reliable DevOS Storage)", "ext4")
            self.fs_combo.addItem("btrfs (CoW Storage)", "btrfs")
            self.fs_combo.addItem("exfat (Shared with Windows & Mac)", "exfat")
            self.fs_combo.addItem("ntfs (Windows Native)", "ntfs")
            form.addRow("Storage Filesystem:", self.fs_combo)
            self.label_edit = QLineEdit("Storage")
            form.addRow("Storage Label:", self.label_edit)

        layout.addLayout(form)

        if mode == "devos":
            note = QLabel("ℹ️ Creates a modern GPT table, a 512 MB FAT32 EFI partition (/boot/efi), and formats the remaining drive for DevOS.")
        else:
            note = QLabel("ℹ️ Creates a modern GPT table and formats 100% of the drive as a clean data storage volume.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #cbd5e1; font-size: 12px;")
        layout.addWidget(note)

        btn_box = QHBoxLayout()
        btn_box.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("background: #334155; color: #f8fafc;")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        action_btn = QPushButton("Erase & Setup Disk")
        action_btn.setStyleSheet("background: #e11d48; color: #ffffff;")
        action_btn.clicked.connect(self.accept)
        btn_box.addWidget(action_btn)

        layout.addLayout(btn_box)

    def get_values(self):
        fs = self.fs_combo.currentData()
        label = self.label_edit.text().strip() or ("DevOS" if self.mode == "devos" else "Storage")
        return fs, label


class DiskDoctorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DevOS Storage & Boot Doctor")
        self.resize(960, 680)
        self.setStyleSheet("""
            QMainWindow { background-color: #0b0f19; color: #f8fafc; }
            QLabel { color: #f8fafc; font-family: 'Inter', sans-serif; }
            QGroupBox { border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 12px; margin-top: 14px; padding: 14px; color: #38bdf8; font-weight: bold; background: #0f172a; }
            QPushButton { border-radius: 6px; padding: 6px 14px; font-weight: bold; font-size: 12px; }
            QTableWidget { background-color: #131d33; border: 1px solid rgba(56, 189, 248, 0.2); border-radius: 8px; color: #f8fafc; gridline-color: rgba(255, 255, 255, 0.06); }
            QHeaderView::section { background-color: #1e293b; color: #94a3b8; padding: 6px; font-weight: bold; border: none; font-size: 12px; }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setContentsMargins(20, 16, 20, 16)
        self.main_layout.setSpacing(12)

        # Header Title
        title_box = QHBoxLayout()
        header_text = QVBoxLayout()
        title = QLabel("DevOS Storage & Boot Doctor")
        title.setStyleSheet("font-size: 22px; font-weight: 800; color: #38bdf8;")
        sub = QLabel("Visual disk manager: inspect drives, view sizes & free space, format disks for DevOS or storage, like Windows Setup.")
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
        self.fw_banner.setStyleSheet("background: rgba(14, 165, 233, 0.1); border-left: 4px solid #0284c7; border-radius: 6px; padding: 8px 12px;")
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
        self.card_layout.setSpacing(14)
        scroll.setWidget(self.card_container)
        self.main_layout.addWidget(scroll, 1)

        # Bottom Bar Buttons
        bottom_box = QHBoxLayout()
        self.installer_btn = QPushButton("🚀 Open Calamares Installer")
        self.installer_btn.setStyleSheet("background: linear-gradient(135deg, #0284c7, #38bdf8); color: #041018; font-size: 13px; padding: 8px 16px;")
        self.installer_btn.clicked.connect(lambda: DiskManager.apply_solution("", "launch_installer"))

        self.reboot_btn = QPushButton("⏻ Safely Reboot & Eject USB")
        self.reboot_btn.setStyleSheet("background: #334155; color: #f8fafc; padding: 8px 16px;")
        self.reboot_btn.clicked.connect(self.confirm_reboot)

        bottom_box.addWidget(self.installer_btn)
        bottom_box.addStretch()
        bottom_box.addWidget(self.reboot_btn)

        if not is_live_system():
            self.installer_btn.hide()
            self.reboot_btn.hide()

        self.main_layout.addLayout(bottom_box)
        self.refresh_disks()

    def refresh_disks(self):
        # Update Firmware Banner
        is_uefi = DiskManager.is_uefi_system()
        if is_uefi:
            self.fw_label.setText("🛡️ System Boot Mode: Modern UEFI (Requires GPT & 512MB EFI System Partition)")
            self.fw_banner.setStyleSheet("background: rgba(16, 185, 129, 0.12); border-left: 4px solid #10b981; border-radius: 6px; padding: 8px 12px;")
        else:
            self.fw_label.setText("⚙️ System Boot Mode: Legacy BIOS / CSM (Supports MBR or GPT with bios_grub)")
            self.fw_banner.setStyleSheet("background: rgba(245, 158, 11, 0.12); border-left: 4px solid #f59e0b; border-radius: 6px; padding: 8px 12px;")

        # Clear existing disk cards
        for i in reversed(range(self.card_layout.count())):
            widget = self.card_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        disks = DiskManager.get_storage_info()
        for idx, disk in enumerate(disks):
            card = self.create_disk_card(disk, idx)
            self.card_layout.addWidget(card)

    def create_disk_card(self, disk: dict, drive_idx: int):
        group = QGroupBox()
        vbox = QVBoxLayout(group)
        vbox.setSpacing(10)

        # Drive Card Top Bar (Title + Badges + Drive Actions)
        header_row = QHBoxLayout()
        drive_icon = "🔌" if disk.get("is_live_media") else ("🖥️" if disk.get("is_system_disk") else "💽")
        title_text = f"{drive_icon} Drive {drive_idx}: {disk['device']}  —  {disk['model']}  ({disk['size_human']})"
        drive_title = QLabel(title_text)
        drive_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #38bdf8;")
        header_row.addWidget(drive_title)
        header_row.addStretch()

        is_sys = disk.get("is_system_disk") and not is_live_system()
        is_usb = disk.get("is_live_media")

        if is_usb:
            badge = QLabel("Installer Live USB (Protected)")
            badge.setStyleSheet("background: #0284c7; color: #ffffff; padding: 3px 8px; border-radius: 4px; font-size: 11px;")
            header_row.addWidget(badge)
        elif is_sys:
            badge = QLabel("Running System Drive (Protected)")
            badge.setStyleSheet("background: #10b981; color: #022c22; font-weight: bold; padding: 3px 8px; border-radius: 4px; font-size: 11px;")
            header_row.addWidget(badge)
        else:
            # Secondary / Target Disk Action Buttons (Windows Setup Style)
            setup_devos_btn = QPushButton("⚙️ Setup for DevOS")
            setup_devos_btn.setStyleSheet("background: #0284c7; color: #ffffff; font-size: 11px; padding: 4px 10px;")
            setup_devos_btn.setToolTip("Initialize GPT and create standard DevOS EFI + System Root partition")
            setup_devos_btn.clicked.connect(lambda _, d=disk: self.open_format_disk_dialog(d, "devos"))
            header_row.addWidget(setup_devos_btn)

            format_storage_btn = QPushButton("💾 Format as Storage")
            format_storage_btn.setStyleSheet("background: #059669; color: #ffffff; font-size: 11px; padding: 4px 10px;")
            format_storage_btn.setToolTip("Format 100% of this drive as clean storage volume (ext4 / btrfs / exfat)")
            format_storage_btn.clicked.connect(lambda _, d=disk: self.open_format_disk_dialog(d, "storage"))
            header_row.addWidget(format_storage_btn)

            wipe_btn = QPushButton("🧹 Wipe Disk")
            wipe_btn.setStyleSheet("background: #334155; color: #f8fafc; font-size: 11px; padding: 4px 10px;")
            wipe_btn.setToolTip("Erase all partitions and initialize a clean GPT table")
            wipe_btn.clicked.connect(lambda _, d=disk['device']: self.confirm_wipe_disk(d))
            header_row.addWidget(wipe_btn)

        vbox.addLayout(header_row)

        # Scheme & Unallocated info
        info_row = QHBoxLayout()
        pt_label = QLabel(f"Partition Scheme: {disk['partition_table']}")
        pt_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        info_row.addWidget(pt_label)

        if disk.get("unallocated_bytes", 0) > 1024 * 1024:
            unalloc_label = QLabel(f"Unallocated Free Space: {disk['unallocated_human']}")
            unalloc_label.setStyleSheet("color: #f59e0b; font-size: 12px; font-weight: bold;")
            info_row.addSpacing(16)
            info_row.addWidget(unalloc_label)
        info_row.addStretch()
        vbox.addLayout(info_row)

        # Partitions Table (Windows Setup Style with size, used/free, and actions)
        table = QTableWidget()
        table.setColumnCount(7)
        table.setHorizontalHeaderLabels(["Partition", "Label", "Filesystem", "Size", "Used / Free", "Mount Point", "Actions"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.setRowCount(len(disk["partitions"]))

        for row, part in enumerate(disk["partitions"]):
            table.setItem(row, 0, QTableWidgetItem(part["device"]))
            table.setItem(row, 1, QTableWidgetItem(part.get("label") or ""))
            table.setItem(row, 2, QTableWidgetItem(part["fstype"]))
            table.setItem(row, 3, QTableWidgetItem(part["size_human"]))
            table.setItem(row, 4, QTableWidgetItem(part.get("used_free_human") or "-"))

            mount_text = part["mountpoint"] or "[unmounted]"
            table.setItem(row, 5, QTableWidgetItem(mount_text))

            # Action Buttons cell
            action_cell = QWidget()
            cell_layout = QHBoxLayout(action_cell)
            cell_layout.setContentsMargins(4, 2, 4, 2)
            cell_layout.setSpacing(6)

            is_root_part = any(m in ("/", "/boot", "/boot/efi") for m in part.get("mountpoint", "").split(", "))
            protected_part = (is_sys and is_root_part) or is_usb

            if protected_part:
                prot_lbl = QLabel("Protected")
                prot_lbl.setStyleSheet("color: #64748b; font-size: 11px;")
                cell_layout.addWidget(prot_lbl)
            else:
                fmt_btn = QPushButton("🪄 Format...")
                fmt_btn.setStyleSheet("background: #0284c7; color: #ffffff; padding: 3px 8px; font-size: 11px;")
                fmt_btn.clicked.connect(lambda _, p=part: self.open_format_partition_dialog(p))
                cell_layout.addWidget(fmt_btn)

                del_btn = QPushButton("❌ Delete")
                del_btn.setStyleSheet("background: #be123c; color: #ffffff; padding: 3px 8px; font-size: 11px;")
                del_btn.clicked.connect(lambda _, p=part["device"]: self.confirm_delete_partition(p))
                cell_layout.addWidget(del_btn)

                if part.get("mounted"):
                    unmount_btn = QPushButton("⏏️ Unmount")
                    unmount_btn.setStyleSheet("background: #334155; color: #f8fafc; padding: 3px 6px; font-size: 11px;")
                    unmount_btn.clicked.connect(lambda _, p=part["device"]: self.toggle_mount(p, "unmount"))
                    cell_layout.addWidget(unmount_btn)
                else:
                    mount_btn = QPushButton("📂 Mount")
                    mount_btn.setStyleSheet("background: #1e293b; color: #38bdf8; border: 1px solid #38bdf8; padding: 3px 6px; font-size: 11px;")
                    mount_btn.clicked.connect(lambda _, p=part["device"]: self.toggle_mount(p, "mount"))
                    cell_layout.addWidget(mount_btn)

            table.setCellWidget(row, 6, action_cell)

        table.setFixedHeight(min(180, max(75, (len(disk["partitions"]) + 1) * 36)))
        vbox.addWidget(table)

        # Issues & Diagnostics Box
        for issue in disk.get("issues", []):
            if issue.get("type") in ("live_media", "system_disk"):
                continue  # already badged in header
            alert = QFrame()
            if issue["severity"] == "success":
                alert.setStyleSheet("background: rgba(16, 185, 129, 0.12); border: 1px solid #10b981; border-radius: 8px; padding: 8px;")
            elif issue["severity"] == "warning":
                alert.setStyleSheet("background: rgba(245, 158, 11, 0.12); border: 1px solid #f59e0b; border-radius: 8px; padding: 8px;")
            else:
                alert.setStyleSheet("background: rgba(56, 189, 248, 0.12); border: 1px solid #38bdf8; border-radius: 8px; padding: 8px;")

            alert_box = QHBoxLayout(alert)
            info_box = QVBoxLayout()
            ititle = QLabel(f"<b>{issue['title']}</b>")
            ititle.setStyleSheet("font-size: 12px;")
            idesc = QLabel(issue["description"])
            idesc.setStyleSheet("color: #cbd5e1; font-size: 11px;")
            info_box.addWidget(ititle)
            info_box.addWidget(idesc)
            alert_box.addLayout(info_box)
            alert_box.addStretch()

            if issue.get("action_id") and not is_sys and not is_usb:
                action_btn = QPushButton(issue["action_label"])
                if issue["severity"] == "warning":
                    action_btn.setStyleSheet("background: #f59e0b; color: #020617; font-weight: bold; font-size: 11px;")
                else:
                    action_btn.setStyleSheet("background: #0284c7; color: #f8fafc; font-weight: bold; font-size: 11px;")

                dev_path = disk['device']
                act_id = issue['action_id']
                action_btn.clicked.connect(lambda _, d=dev_path, a=act_id: self.run_action(d, a))
                alert_box.addWidget(action_btn)

            vbox.addWidget(alert)

        return group

    def open_format_partition_dialog(self, part: dict):
        dialog = FormatPartitionDialog(part["device"], default_label=part.get("label") or "Storage", parent=self)
        if dialog.exec_() == QDialog.Accepted:
            fs, label = dialog.get_values()
            res = DiskManager.apply_solution(part["device"], "format_partition", fs_type=fs, label=label)
            if res.get("success"):
                QMessageBox.information(self, "Success", res.get("message", "Partition formatted successfully."))
                self.refresh_disks()
            else:
                QMessageBox.critical(self, "Formatting Error", res.get("error", "Formatting failed."))

    def open_format_disk_dialog(self, disk: dict, mode: str):
        dialog = FormatDiskDialog(disk["device"], disk["model"], disk["size_human"], mode=mode, parent=self)
        if dialog.exec_() == QDialog.Accepted:
            fs, label = dialog.get_values()
            action_id = "format_devos" if mode == "devos" else "format_storage"
            res = DiskManager.apply_solution(disk["device"], action_id, fs_type=fs, label=label)
            if res.get("success"):
                QMessageBox.information(self, "Success", res.get("message", "Disk formatted successfully."))
                self.refresh_disks()
            else:
                QMessageBox.critical(self, "Disk Format Error", res.get("error", "Disk format failed."))

    def confirm_wipe_disk(self, device: str):
        confirm = QMessageBox.warning(
            self, "Wipe Entire Disk",
            f"Are you sure you want to completely erase {device}?\n\n"
            "This will permanently delete all partitions and initialize a clean GPT partition table.",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            res = DiskManager.apply_solution(device, "wipe_disk")
            if res.get("success"):
                QMessageBox.information(self, "Success", res.get("message", "Disk wiped successfully."))
                self.refresh_disks()
            else:
                QMessageBox.critical(self, "Error", res.get("error", "Wipe failed."))

    def confirm_delete_partition(self, device: str):
        confirm = QMessageBox.warning(
            self, "Delete Partition",
            f"Are you sure you want to delete partition {device}?\n\nAll data on this partition will be lost.",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            res = DiskManager.apply_solution(device, "delete_partition")
            if res.get("success"):
                QMessageBox.information(self, "Success", res.get("message", "Partition deleted."))
                self.refresh_disks()
            else:
                QMessageBox.critical(self, "Error", res.get("error", "Deletion failed."))

    def toggle_mount(self, device: str, action: str):
        res = DiskManager.apply_solution(device, f"{action}_partition")
        if res.get("success"):
            self.refresh_disks()
        else:
            QMessageBox.critical(self, "Mount Error", res.get("error", f"Failed to {action} partition."))

    def run_action(self, device: str, action_id: str):
        confirm = QMessageBox.question(
            self, "Confirm Disk Action",
            f"Are you sure you want to perform action '{action_id}' on {device}?",
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
    app.setFont(QFont("Inter", 10))
    window = DiskDoctorWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
