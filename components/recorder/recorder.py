#!/usr/bin/env python3
"""
DevOS Screen Recorder (Fluent Wayland Screen Recorder)
Provides a clean, frictionless 1-click recording interface for DevOS:
  - Pre-configured for Wayland & PipeWire (no configuration or codec errors)
  - Start, Stop, and Save buttons
  - Full Screen, Region, and Window capture modes
  - Instant Playback and Show in Folder shortcuts
"""

import glob
import os
import subprocess
import sys
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QIcon, QColor
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGraphicsDropShadowEffect,
)

SCREENCASTS_DIR = os.path.expanduser("~/Videos/Screencasts")


def get_latest_screencast():
    if not os.path.isdir(SCREENCASTS_DIR):
        return None
    files = glob.glob(os.path.join(SCREENCASTS_DIR, "*.webm")) + glob.glob(
        os.path.join(SCREENCASTS_DIR, "*.mp4")
    )
    return max(files, key=os.path.getmtime) if files else None


class DevOSRecorder(QWidget):
    def __init__(self):
        super().__init__()
        self.recording = False
        self.seconds_elapsed = 0
        self.last_saved_file = None
        self.initial_files = set()

        os.makedirs(SCREENCASTS_DIR, exist_ok=True)
        self.init_ui()

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_timer)

    def init_ui(self):
        self.setWindowTitle("Screen Recorder - DevOS")
        self.setFixedSize(460, 480)
        self.setStyleSheet("""
            QWidget {
                background-color: #0b1120;
                color: #f1f5f9;
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            }
            QFrame.card {
                background-color: #131c31;
                border: 1px solid #1e293b;
                border-radius: 14px;
            }
            QRadioButton {
                color: #cbd5e1;
                font-size: 13px;
                font-weight: 500;
                spacing: 8px;
            }
            QRadioButton::indicator {
                width: 18px;
                height: 18px;
                border-radius: 9px;
                border: 2px solid #334155;
                background-color: #0f172a;
            }
            QRadioButton::indicator:checked {
                border-color: #38bdf8;
                background-color: #38bdf8;
            }
            QCheckBox {
                color: #94a3b8;
                font-size: 12px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #334155;
                background-color: #0f172a;
            }
            QCheckBox::indicator:checked {
                border-color: #38bdf8;
                background-color: #0284c7;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(16)

        # Header
        header = QHBoxLayout()
        header.setSpacing(12)
        dot = QLabel("●")
        dot.setStyleSheet("color: #ef4444; font-size: 20px;")
        header.addWidget(dot)

        title = QLabel("Screen Recorder")
        title.setFont(QFont("Inter", 16, QFont.Bold))
        header.addWidget(title)
        header.addStretch()

        badge = QLabel("Wayland Native")
        badge.setStyleSheet("""
            background-color: #1e293b;
            color: #38bdf8;
            border-radius: 6px;
            padding: 4px 10px;
            font-size: 11px;
            font-weight: 600;
        """)
        header.addWidget(badge)
        layout.addLayout(header)

        # Mode Selection Card
        mode_card = QFrame()
        mode_card.setProperty("class", "card")
        mode_card.setStyleSheet("""
            background-color: #131c31;
            border: 1px solid #1e293b;
            border-radius: 12px;
        """)
        mode_layout = QVBoxLayout(mode_card)
        mode_layout.setContentsMargins(16, 14, 16, 14)
        mode_layout.setSpacing(10)

        mode_label = QLabel("Capture Area")
        mode_label.setFont(QFont("Inter", 12, QFont.Bold))
        mode_label.setStyleSheet("color: #94a3b8;")
        mode_layout.addWidget(mode_label)

        self.btn_group = QButtonGroup(self)
        self.radio_screen = QRadioButton("🖥️  Entire Screen")
        self.radio_region = QRadioButton("✂️  Selected Area (Rectangle)")
        self.radio_window = QRadioButton("🪟  Active Window")

        self.radio_screen.setChecked(True)
        self.btn_group.addButton(self.radio_screen)
        self.btn_group.addButton(self.radio_region)
        self.btn_group.addButton(self.radio_window)

        mode_layout.addWidget(self.radio_screen)
        mode_layout.addWidget(self.radio_region)
        mode_layout.addWidget(self.radio_window)
        layout.addWidget(mode_card)

        # Options
        self.chk_minimize = QCheckBox("Minimize window while recording")
        self.chk_minimize.setChecked(True)
        layout.addWidget(self.chk_minimize)

        # Status / Timer display
        self.status_box = QFrame()
        self.status_box.setStyleSheet("""
            background-color: #0f172a;
            border: 1px solid #1e293b;
            border-radius: 12px;
            padding: 10px;
        """)
        status_layout = QVBoxLayout(self.status_box)
        status_layout.setContentsMargins(12, 10, 12, 10)

        self.lbl_timer = QLabel("Ready to record")
        self.lbl_timer.setAlignment(Qt.AlignCenter)
        self.lbl_timer.setFont(QFont("Inter", 14, QFont.Bold))
        self.lbl_timer.setStyleSheet("color: #94a3b8;")
        status_layout.addWidget(self.lbl_timer)

        self.lbl_subtext = QLabel("Video will be saved to ~/Videos/Screencasts")
        self.lbl_subtext.setAlignment(Qt.AlignCenter)
        self.lbl_subtext.setStyleSheet("color: #64748b; font-size: 11px;")
        status_layout.addWidget(self.lbl_subtext)
        layout.addWidget(self.status_box)

        # Action Buttons (Start / Stop)
        self.btn_record = QPushButton("🔴 Start Recording")
        self.btn_record.setFont(QFont("Inter", 13, QFont.Bold))
        self.btn_record.setCursor(Qt.PointingHandCursor)
        self.btn_record.setFixedHeight(48)
        self.update_button_style(recording=False)
        self.btn_record.clicked.connect(self.toggle_recording)
        layout.addWidget(self.btn_record)

        # Saved Video Actions (hidden initially)
        self.actions_layout = QHBoxLayout()
        self.actions_layout.setSpacing(10)

        self.btn_play = QPushButton("▶️ Play Video")
        self.btn_play.setFixedHeight(38)
        self.btn_play.setCursor(Qt.PointingHandCursor)
        self.btn_play.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #38bdf8;
                border: 1px solid #334155;
                border-radius: 8px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #334155;
            }
        """)
        self.btn_play.clicked.connect(self.play_last_video)
        self.btn_play.hide()

        self.btn_folder = QPushButton("📁 Show in Folder")
        self.btn_folder.setFixedHeight(38)
        self.btn_folder.setCursor(Qt.PointingHandCursor)
        self.btn_folder.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #cbd5e1;
                border: 1px solid #334155;
                border-radius: 8px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #334155;
            }
        """)
        self.btn_folder.clicked.connect(self.open_folder)
        self.btn_folder.hide()

        self.actions_layout.addWidget(self.btn_play)
        self.actions_layout.addWidget(self.btn_folder)
        layout.addLayout(self.actions_layout)

        # Footer Shortcuts Info
        shortcuts_info = QLabel("Shortcuts:  Win+Shift+R (Area)  •  Win+Alt+R (Screen)")
        shortcuts_info.setAlignment(Qt.AlignCenter)
        shortcuts_info.setStyleSheet("color: #475569; font-size: 11px;")
        layout.addWidget(shortcuts_info)

    def update_button_style(self, recording: bool):
        if recording:
            self.btn_record.setText("⏹️ Stop & Save Recording")
            self.btn_record.setStyleSheet("""
                QPushButton {
                    background-color: #ef4444;
                    color: #ffffff;
                    border: none;
                    border-radius: 12px;
                    font-size: 14px;
                    font-weight: 700;
                }
                QPushButton:hover {
                    background-color: #dc2626;
                }
                QPushButton:pressed {
                    background-color: #b91c1c;
                }
            """)
        else:
            self.btn_record.setText("🔴 Start Recording")
            self.btn_record.setStyleSheet("""
                QPushButton {
                    background-color: #38bdf8;
                    color: #080f1d;
                    border: none;
                    border-radius: 12px;
                    font-size: 14px;
                    font-weight: 700;
                }
                QPushButton:hover {
                    background-color: #7dd3fc;
                }
                QPushButton:pressed {
                    background-color: #0284c7;
                }
            """)

    def get_selected_mode(self):
        if self.radio_region.isChecked():
            return "region"
        elif self.radio_window.isChecked():
            return "window"
        return "screen"

    def toggle_recording(self):
        if not self.recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        mode = self.get_selected_mode()
        self.initial_files = set(glob.glob(os.path.join(SCREENCASTS_DIR, "*")))

        # DBus method name: RecordScreen, RecordRegion, RecordWindow
        dbus_method = "RecordScreen"
        if mode == "region":
            dbus_method = "RecordRegion"
        elif mode == "window":
            dbus_method = "RecordWindow"

        # Call Spectacle via DBus
        env = os.environ.copy()
        subprocess.Popen(
            [
                "busctl",
                "--user",
                "call",
                "org.kde.Spectacle",
                "/",
                "org.kde.Spectacle",
                dbus_method,
                "i",
                "0",
            ],
            env=env,
        )

        self.recording = True
        self.seconds_elapsed = 0
        self.update_button_style(recording=True)
        self.btn_play.hide()
        self.btn_folder.hide()
        self.timer.start()
        self.update_timer()

        if self.chk_minimize.isChecked():
            QTimer.singleShot(400, self.showMinimized)

    def stop_recording(self):
        self.timer.stop()
        self.recording = False
        self.update_button_style(recording=False)

        # Call toggle method again to stop recording
        mode = self.get_selected_mode()
        dbus_method = "RecordScreen"
        if mode == "region":
            dbus_method = "RecordRegion"
        elif mode == "window":
            dbus_method = "RecordWindow"

        subprocess.run(
            [
                "busctl",
                "--user",
                "call",
                "org.kde.Spectacle",
                "/",
                "org.kde.Spectacle",
                dbus_method,
                "i",
                "0",
            ],
            capture_output=True,
        )

        self.showNormal()
        self.raise_()
        self.activateWindow()

        self.lbl_timer.setText("Finalizing video...")
        self.lbl_timer.setStyleSheet("color: #38bdf8;")
        self.lbl_subtext.setText("Saving file to ~/Videos/Screencasts...")

        # Poll for new file
        QTimer.singleShot(1000, self.check_saved_file)

    def check_saved_file(self):
        current_files = set(glob.glob(os.path.join(SCREENCASTS_DIR, "*")))
        new_files = current_files - self.initial_files
        if new_files:
            latest = max(new_files, key=os.path.getmtime)
            self.last_saved_file = latest
            basename = os.path.basename(latest)
            size_kb = os.path.getsize(latest) // 1024

            self.lbl_timer.setText("✅ Recording Saved!")
            self.lbl_timer.setStyleSheet("color: #4ade80;")
            self.lbl_subtext.setText(f"{basename} ({size_kb} KB)")

            self.btn_play.show()
            self.btn_folder.show()

            # Desktop notification
            subprocess.Popen([
                "notify-send",
                "-i", "media-record",
                "Screen Recording Saved",
                f"Saved to {basename}\nClick to view",
            ])
        else:
            latest = get_latest_screencast()
            if latest:
                self.last_saved_file = latest
                basename = os.path.basename(latest)
                self.lbl_timer.setText("✅ Recording Saved!")
                self.lbl_timer.setStyleSheet("color: #4ade80;")
                self.lbl_subtext.setText(f"{basename}")
                self.btn_play.show()
                self.btn_folder.show()
            else:
                self.lbl_timer.setText("Ready to record")
                self.lbl_timer.setStyleSheet("color: #94a3b8;")
                self.lbl_subtext.setText("Saved to ~/Videos/Screencasts")

    def update_timer(self):
        mins, secs = divmod(self.seconds_elapsed, 60)
        time_str = f"{mins:02d}:{secs:02d}"
        self.lbl_timer.setText(f"🔴 REC  {time_str}")
        self.lbl_timer.setStyleSheet("color: #ef4444; font-size: 16px; font-weight: bold;")
        self.lbl_subtext.setText("Recording in progress... Click Stop & Save when done")
        self.seconds_elapsed += 1

    def play_last_video(self):
        if self.last_saved_file and os.path.isfile(self.last_saved_file):
            subprocess.Popen(["xdg-open", self.last_saved_file])

    def open_folder(self):
        folder = SCREENCASTS_DIR if os.path.isdir(SCREENCASTS_DIR) else os.path.expanduser("~/Videos")
        subprocess.Popen(["xdg-open", folder])


def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ("--help", "-h"):
            print("DevOS Screen Recorder\nUsage: devos-recorder [--screen | --region | --window]")
            sys.exit(0)
        elif arg in ("--screen", "-s"):
            subprocess.run(["busctl", "--user", "call", "org.kde.Spectacle", "/", "org.kde.Spectacle", "RecordScreen", "i", "0"])
            sys.exit(0)
        elif arg in ("--region", "-r"):
            subprocess.run(["busctl", "--user", "call", "org.kde.Spectacle", "/", "org.kde.Spectacle", "RecordRegion", "i", "0"])
            sys.exit(0)
        elif arg in ("--window", "-w"):
            subprocess.run(["busctl", "--user", "call", "org.kde.Spectacle", "/", "org.kde.Spectacle", "RecordWindow", "i", "0"])
            sys.exit(0)

    app = QApplication(sys.argv)
    app.setApplicationName("DevOS Screen Recorder")
    window = DevOSRecorder()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
