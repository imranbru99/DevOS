#!/usr/bin/env python3
"""
DevOS Visual Disk & Boot Doctor (PyQt5 GUI)
Provides a visual interface showing disks, partition schemes (MBR vs GPT),
used/free size breakdown, and Windows-Setup-style partition formatting and wipe tools.
"""

import sys
import os
import shutil
import subprocess

try:
    from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
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
from storage_widgets import VolumeMap, PartitionLayoutDialog


class DiskOperation(QThread):
    result = pyqtSignal(dict)

    def __init__(self, device, action, kwargs, parent):
        super().__init__(parent)
        self.device, self.action, self.kwargs = device, action, kwargs

    def run(self):
        try:
            result = DiskManager.apply_solution(self.device, self.action, **self.kwargs)
        except Exception as exc:
            result = {"success": False, "error": str(exc)}
        self.result.emit(result)


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
            boot_space = "a 512 MiB FAT32 EFI partition" if DiskManager.is_uefi_system() else "a 2 MiB BIOS boot partition"
            note = QLabel(f"Creates a GPT table, {boot_space}, and a system partition for DevOS. This prepares the disk; use the installer to install the OS.")
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
        self.resize(1180, 780)
        self._operation = None
        self.setStyleSheet("""
            QMainWindow { background-color: #0b0f19; color: #f8fafc; }
            QLabel { color: #f8fafc; font-family: 'Inter', sans-serif; }
            QFrame#diskCard { border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 12px; margin-top: 14px; padding: 14px; color: #38bdf8; font-weight: bold; background: #0f172a; }
            QPushButton { background:#17253c; color:#e2e8f0; border:1px solid #2b3c56; border-radius:8px; padding:7px 14px; font-weight:bold; font-size:12px; }
            QPushButton:hover { border-color:#38bdf8; }
            QPushButton:focus { border:2px solid #7dd3fc; }
            QTableWidget { background-color: #131d33; alternate-background-color:#17243b; border: 1px solid rgba(56, 189, 248, 0.2); border-radius: 8px; color: #f8fafc; gridline-color: rgba(255, 255, 255, 0.06); }
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
        title = QLabel("Storage & volumes")
        title.setStyleSheet("font-size: 28px; font-weight: 700; color: #f8fafc;")
        sub = QLabel("SSD · HDD · USB  |  Clear volume maps, custom sizes and Windows-compatible data formats.")
        sub.setWordWrap(True)
        sub.setStyleSheet("font-size: 13px; color: #94a3b8;")
        header_text.addWidget(title)
        header_text.addWidget(sub)
        title_box.addLayout(header_text)
        title_box.addStretch()
        advanced_btn = QPushButton("Partition editor…")
        advanced_btn.setToolTip("Create, resize and manage partitions in KDE Partition Manager")
        advanced_btn.clicked.connect(self.open_partition_editor)
        title_box.addWidget(advanced_btn)

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
            item = self.card_layout.takeAt(i)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        disks = DiskManager.get_storage_info()
        if not disks:
            empty = QLabel(DiskManager.last_error or "No physical drives detected. Connect a drive and refresh.")
            empty.setWordWrap(True)
            self.card_layout.addWidget(empty)
        for idx, disk in enumerate(disks):
            card = self.create_disk_card(disk, idx)
            self.card_layout.addWidget(card)

    def create_disk_card(self, disk: dict, drive_idx: int):
        group = QFrame()
        group.setObjectName("diskCard")
        vbox = QVBoxLayout(group)
        vbox.setSpacing(10)

        # Drive Card Top Bar (Title + Badges + Drive Actions)
        header_row = QHBoxLayout()
        drive_icon = "🔌" if disk.get("is_live_media") else ("🖥️" if disk.get("is_system_disk") else "💽")
        title_text = f"{drive_icon} Drive {drive_idx}: {disk['device']}  —  {disk['model']}  ({disk['size_human']})"
        drive_title = QLabel(title_text)
        drive_title.setWordWrap(True)
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
        elif disk.get("read_only"):
            header_row.addWidget(QLabel("Read-only drive · inspect before editing"))
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
        if not is_sys and not is_usb and not disk.get("read_only"):
            layout_btn = QPushButton("Create A / B / C volumes…")
            layout_btn.setStyleSheet("background:#1e3a5f; color:#bae6fd; padding:9px 16px;")
            layout_btn.clicked.connect(lambda _, d=disk: self.open_layout_dialog(d))
            vbox.addWidget(layout_btn)
        vbox.addWidget(VolumeMap(disk['size_bytes'], disk['partitions']))

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
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
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
            protected_part = is_sys or is_usb or disk.get("read_only") or part.get("read_only")

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
            idesc.setWordWrap(True)
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

    def start_disk_action(self, device, action, **kwargs):
        if self._operation is not None:
            return
        self.centralWidget().setEnabled(False)
        self.statusBar().showMessage("Applying storage changes… Keep this computer powered on.")
        self._operation = DiskOperation(device, action, kwargs, self)
        self._operation.result.connect(self.disk_action_finished)
        self._operation.finished.connect(self.disk_thread_finished)
        self._operation.start()

    def disk_action_finished(self, result):
        self.statusBar().showMessage("Storage updated" if result.get("success") else "Storage change stopped")
        if result.get("success"):
            QMessageBox.information(self, "Storage updated", result.get("message", "Done."))
        else:
            QMessageBox.critical(self, "Storage change stopped", result.get("error", "No successful result was reported."))
        self.refresh_disks()

    def disk_thread_finished(self):
        self._operation.deleteLater()
        self._operation = None
        self.centralWidget().setEnabled(True)

    def closeEvent(self, event):
        if self._operation is not None:
            QMessageBox.information(self, "Storage changes in progress", "Wait for the current operation to finish before closing this window.")
            event.ignore()
        else:
            event.accept()

    def open_partition_editor(self):
        executable = shutil.which("partitionmanager")
        if not executable:
            QMessageBox.information(self, "Partition editor", "KDE Partition Manager is not installed.")
            return
        subprocess.Popen([executable])

    def open_layout_dialog(self, disk):
        dialog = PartitionLayoutDialog(disk, self)
        if dialog.exec_() == QDialog.Accepted:
            self.start_disk_action(disk["device"], "partition_storage", volumes=dialog.get_volumes(), expected_identity=disk)

    def open_format_partition_dialog(self, part):
        dialog = FormatPartitionDialog(part["device"], part.get("label") or "Storage", self)
        if dialog.exec_() == QDialog.Accepted:
            fs, label = dialog.get_values()
            self.start_disk_action(part["device"], "format_partition", fs_type=fs, label=label)

    def open_format_disk_dialog(self, disk, mode):
        dialog = FormatDiskDialog(disk["device"], disk["model"], disk["size_human"], mode, self)
        if dialog.exec_() == QDialog.Accepted:
            fs, label = dialog.get_values()
            self.start_disk_action(disk["device"], "format_devos" if mode == "devos" else "format_storage", fs_type=fs, label=label, expected_identity=disk)

    def confirm_wipe_disk(self, device):
        if QMessageBox.warning(self, "Erase entire disk", f"Erase every partition on {device}? Other disks are unchanged.",
                               QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.start_disk_action(device, "wipe_disk")

    def confirm_delete_partition(self, device):
        if QMessageBox.warning(self, "Delete partition", f"Delete {device}? Its data will be lost.",
                               QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.start_disk_action(device, "delete_partition")

    def toggle_mount(self, device, action):
        self.start_disk_action(device, action + "_partition")

    def run_action(self, device, action):
        description = (f"Erase every partition on {device} and create an MBR table? All data on that disk will be lost."
                       if action == "convert_mbr" else f"Apply {action} to {device}? Review your backup before changing its layout.")
        if QMessageBox.warning(self, "Confirm storage change", description,
                               QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.start_disk_action(device, action)

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
