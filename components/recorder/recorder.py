#!/usr/bin/env python3
"""DevOS Wayland recorder with live input meters and non-destructive clip editing.

Spectacle captures video, PulseAudio/PipeWire captures audio, and background
FFmpeg workers save MP4/WebM recordings and edited MP4 exports.
"""

import glob
import math
import os
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import wave
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, QThread, QProcess, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont, QIcon, QPixmap, QPainter, QColor
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
    QComboBox,
    QFrame,
    QFileDialog,
    QMessageBox,
    QSystemTrayIcon,
    QScrollArea,
)
from PyQt5 import QtDBus
from audio_meter import AudioMeter
from editor import VideoEditor
from media_edit import finalize_capture

SCREENCASTS_DIR = os.path.expanduser("~/Videos/Screencasts")

# Shared mic defaults (workspace + installed component paths)
for _audio_root in (
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),
    "/usr/local/share/devos/components",
    os.path.expanduser("~/project/dev-os/components"),
):
    if _audio_root not in sys.path and os.path.isdir(os.path.join(_audio_root, "audio")):
        sys.path.insert(0, _audio_root)
try:
    from audio import mic_defaults as _mic
except Exception:  # pragma: no cover - fallback when package missing
    _mic = None


def get_app_icon() -> QIcon:
    """Return the clean DevOS Screen Recorder icon (idle state without red recording dot)."""
    candidates = [
        os.path.expanduser("~/.local/share/icons/devos-recorder.png"),
        "/usr/share/pixmaps/devos-recorder.png",
        os.path.expanduser("~/.local/share/icons/hicolor/scalable/apps/devos-recorder.svg"),
        "/usr/share/icons/hicolor/scalable/apps/devos-recorder.svg",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return QIcon(p)
    return QIcon.fromTheme("camera-video", QIcon.fromTheme("media-record"))


def get_recording_icon() -> QIcon:
    """Return the active recording DevOS Screen Recorder icon (with glowing red dot)."""
    candidates = [
        os.path.expanduser("~/.local/share/icons/devos-recorder-recording.png"),
        os.path.expanduser("~/.local/share/icons/hicolor/scalable/apps/devos-recorder-recording.svg"),
        "/usr/share/pixmaps/devos-recorder-recording.png",
        "/usr/share/icons/hicolor/scalable/apps/devos-recorder-recording.svg",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return QIcon(p)
    return get_app_icon()


def get_default_monitor_sink() -> Optional[str]:
    """Retrieve the monitor source for system desktop audio."""
    try:
        sink = subprocess.check_output(["pactl", "get-default-sink"], text=True, timeout=2).strip()
        if sink:
            return sink + ".monitor"
    except Exception:
        pass
    return None


def get_default_mic_name() -> str:
    """Human-readable label for the active / preferred microphone."""
    if _mic:
        try:
            return _mic.get_default_mic_label()
        except Exception:
            pass
    try:
        src = subprocess.check_output(["pactl", "get-default-source"], text=True, timeout=2).strip()
        out = subprocess.check_output(["pactl", "list", "sources"], text=True, timeout=2)
        lines = out.splitlines()
        for i, line in enumerate(lines):
            if f"Name: {src}" in line:
                for j in range(i + 1, min(i + 10, len(lines))):
                    if lines[j].strip().startswith("Description:"):
                        return lines[j].split(":", 1)[1].strip()
        if src:
            return src
    except Exception:
        pass
    return "Microphone"


def get_selected_mic_source(widget=None) -> Optional[str]:
    """PipeWire source name for the mic the user picked (or system default)."""
    if widget is not None and hasattr(widget, "mic_combo"):
        data = widget.mic_combo.currentData()
        if data:
            return data
    if _mic:
        try:
            return _mic.get_default_source()
        except Exception:
            pass
    try:
        return subprocess.check_output(["pactl", "get-default-source"], text=True, timeout=2).strip() or None
    except Exception:
        return None


def play_chime():
    """Generates and plays a pleasant 2-tone test chime."""
    system_wav = "/usr/share/sounds/alsa/Front_Center.wav"
    if os.path.isfile(system_wav):
        subprocess.run(["paplay", system_wav], check=False)
        return

    sample_rate = 44100
    tones = [(523.25, 0.12), (783.99, 0.20)]
    frames = bytearray()
    for freq, dur in tones:
        num_samples = int(sample_rate * dur)
        for i in range(num_samples):
            t = i / sample_rate
            envelope = math.exp(-3.5 * (i / num_samples))
            val = int(32767.0 * 0.45 * envelope * math.sin(2.0 * math.pi * freq * t))
            frames.extend(struct.pack("<h", val))
            frames.extend(struct.pack("<h", val))

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(frames)
    subprocess.run(["paplay", tmp.name], check=False)
    try:
        os.remove(tmp.name)
    except Exception:
        pass


class FinalizeThread(QThread):
    result = pyqtSignal(str, str)

    def __init__(self, source, audio, target_format, parent):
        super().__init__(parent)
        self.source, self.audio, self.target_format = source, audio, target_format

    def run(self):
        try:
            self.result.emit(finalize_capture(self.source, self.audio, self.target_format), "")
        except Exception as exc:
            self.result.emit(self.source, str(exc))


class MicTestThread(QThread):
    status_signal = pyqtSignal(str, str)
    finished_signal = pyqtSignal()

    def __init__(self, device: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.device = device

    def run(self):
        device = self.device
        if _mic:
            try:
                if device:
                    _mic.prefer_source(device, make_system_default=True)
                else:
                    _mic.apply_preferred_source()
                    device = _mic.get_default_source()
                _mic.ensure_source_ready(device)
            except Exception:
                pass

        fd, test_wav = tempfile.mkstemp(prefix="devos-mic-test-", suffix=".wav")
        os.close(fd)
        label = device or "default"
        self.status_signal.emit(f"🎙️ Speak now (listening 3s on {label.split('.')[-1]})...", "#f59e0b")
        try:
            if shutil.which("parecord"):
                cmd = ["parecord", "--channels=1", "--rate=48000", "--file-format=wav"]
                if device:
                    cmd.append("--device=" + device)
                cmd.append(test_wav)
            elif shutil.which("pw-record"):
                cmd = ["pw-record", "--channels=1", "--rate=48000"]
                if device:
                    cmd.extend(["--target", device])
                cmd.append(test_wav)
            else:
                self.status_signal.emit("⚠️ No recorder tool (parecord/pw-record) installed", "#ef4444")
                self.finished_signal.emit()
                return
            proc = subprocess.Popen(cmd)
            time.sleep(3.0)
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=2.0)
        except Exception:
            pass

        has_sound = False
        peak = 0
        if os.path.isfile(test_wav) and os.path.getsize(test_wav) > 1000:
            try:
                with wave.open(test_wav, "rb") as wf:
                    frames = wf.getnframes()
                    if frames > 0:
                        data = wf.readframes(frames)
                        samples = struct.unpack(f"<{len(data)//2}h", data)
                        peak = max(abs(s) for s in samples)
                        has_sound = peak > 150  # non-zero audio amplitude
            except Exception:
                has_sound = True

            if has_sound:
                self.status_signal.emit("🔊 Playing back your voice...", "#38bdf8")
                subprocess.run(["paplay", test_wav], check=False)
                self.status_signal.emit("✅ Microphone working! Saved as system default for calls & apps.", "#4ade80")
                if _mic and device:
                    try:
                        _mic.prefer_source(device, make_system_default=True)
                    except Exception:
                        pass
            else:
                self.status_signal.emit(
                    "⚠️ Mic found but silent (peak 0). Unmute the hardware button, then click Fix Mic.",
                    "#ef4444",
                )

            try:
                os.remove(test_wav)
            except Exception:
                pass
        else:
            self.status_signal.emit("⚠️ Could not open the input device — pick another mic or click Fix Mic", "#ef4444")

        self.finished_signal.emit()


class ChimeTestThread(QThread):
    status_signal = pyqtSignal(str, str)
    finished_signal = pyqtSignal()

    def run(self):
        self.status_signal.emit("🔊 Playing test sound...", "#38bdf8")
        play_chime()
        self.status_signal.emit("✅ Audio output working!", "#4ade80")
        self.finished_signal.emit()


class DevOSRecorder(QWidget):
    def __init__(self):
        super().__init__()
        self.recording = False
        self.seconds_elapsed = 0
        self.last_saved_file = None
        self.initial_files = set()
        self.audio_proc: Optional[subprocess.Popen] = None
        self.temp_audio_file = None
        self.test_thread: Optional[QThread] = None
        self.finalize_thread = None

        os.makedirs(SCREENCASTS_DIR, exist_ok=True)
        self.init_ui()
        self.setup_dbus_listener()
        self.setup_recording_indicator()
        self.capture_request = QProcess(self)
        self.capture_request.finished.connect(self.capture_request_finished)
        self.capture_request.errorOccurred.connect(lambda *_: self.on_spectacle_recording_failed("Could not contact the screen capture service."))

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_timer)

    def capture_request_finished(self, code, _status):
        if code:
            message = bytes(self.capture_request.readAllStandardError()).decode(errors="replace")
            self.on_spectacle_recording_failed(message[:250] or "Screen capture request failed.")

    def setup_dbus_listener(self):
        """Connect to Spectacle DBus signals so we immediately know when recording finishes."""
        try:
            bus = QtDBus.QDBusConnection.sessionBus()
            bus.connect(
                "org.kde.Spectacle",
                "/",
                "org.kde.Spectacle",
                "RecordingTaken",
                self.on_spectacle_recording_taken,
            )
            bus.connect(
                "org.kde.Spectacle",
                "/",
                "org.kde.Spectacle",
                "RecordingFailed",
                self.on_spectacle_recording_failed,
            )
        except Exception as e:
            print(f"DBus signal connection note: {e}")

    @pyqtSlot(str)
    def on_spectacle_recording_taken(self, file_path: str):
        """Triggered automatically by Spectacle when recording finishes (via tray, button or shortcut)."""
        if self.recording:
            self.finalize_saved_file(file_path)

    @pyqtSlot(str)
    def on_spectacle_recording_failed(self, message: str):
        """Triggered if Spectacle reports a capture error."""
        if self.recording:
            self.timer.stop()
            self.recording = False
            self.stop_audio()
            self.recording_finished()
            self.update_button_style(recording=False)
            self.setWindowIcon(get_app_icon())
            self.showNormal()
            self.lbl_timer.setText("⚠️ Recording Failed")
            self.lbl_timer.setStyleSheet("color: #ef4444;")
            self.lbl_subtext.setText(message or "Capture failed")

    def init_ui(self):
        self.setWindowTitle("Screen Recorder")
        self.setMinimumSize(540, 600)
        self.resize(560, 820)
        self.setWindowIcon(get_app_icon())

        self.setStyleSheet("""
            QLabel { border: none; background: transparent; }
            QPushButton { padding: 7px; background: #1e293b; border: 1px solid #334155; border-radius: 7px; }
            QPushButton:hover { background: #334155; }
            QWidget {
                background-color: #0b1120;
                color: #f1f5f9;
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            }
            QFrame.card {
                background-color: #131c31;
                border: 1px solid #1e293b;
                border-radius: 12px;
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

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 16, 22, 16)
        layout.setSpacing(10)

        # Header
        header = QHBoxLayout()
        header.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(get_app_icon().pixmap(28, 28))
        header.addWidget(icon_lbl)

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

        # 1. Capture Area Card
        area_card = QFrame()
        area_card.setProperty("class", "card")
        area_card.setObjectName("area_card")
        area_card.setStyleSheet("QFrame#area_card { background-color:#131c31; border:1px solid #1e293b; border-radius:12px; }")
        area_layout = QVBoxLayout(area_card)
        area_layout.setContentsMargins(14, 10, 14, 10)
        area_layout.setSpacing(6)

        area_title = QLabel("1. Capture Area")
        area_title.setFont(QFont("Inter", 11, QFont.Bold))
        area_title.setStyleSheet("color: #94a3b8;")
        area_layout.addWidget(area_title)

        self.area_group = QButtonGroup(self)
        self.radio_screen = QRadioButton("🖥️  Entire Screen")
        self.radio_region = QRadioButton("✂️  Selected Area (Rectangle)")
        self.radio_window = QRadioButton("🪟  Active Window")

        self.radio_screen.setChecked(True)
        self.area_group.addButton(self.radio_screen)
        self.area_group.addButton(self.radio_region)
        self.area_group.addButton(self.radio_window)

        area_layout.addWidget(self.radio_screen)
        area_layout.addWidget(self.radio_region)
        area_layout.addWidget(self.radio_window)
        layout.addWidget(area_card)

        # 2. Audio Option Card
        audio_card = QFrame()
        audio_card.setProperty("class", "card")
        audio_card.setObjectName("audio_card")
        audio_card.setStyleSheet("QFrame#audio_card { background-color:#131c31; border:1px solid #1e293b; border-radius:12px; }")
        audio_layout = QVBoxLayout(audio_card)
        audio_layout.setContentsMargins(14, 10, 14, 10)
        audio_layout.setSpacing(6)

        audio_title = QLabel("2. Audio Option")
        audio_title.setFont(QFont("Inter", 11, QFont.Bold))
        audio_title.setStyleSheet("color: #94a3b8;")
        audio_layout.addWidget(audio_title)

        mic_name = get_default_mic_name()
        self.audio_group = QButtonGroup(self)
        self.radio_mic = QRadioButton(f"🎙️  Microphone ({mic_name})")
        self.radio_system = QRadioButton("🔊  System Sound (Desktop Audio)")
        self.radio_mute = QRadioButton("🔇  No Audio (Muted)")

        self.radio_mic.setChecked(True)
        self.audio_group.addButton(self.radio_mic)
        self.audio_group.addButton(self.radio_system)
        self.audio_group.addButton(self.radio_mute)

        self.radio_mic.toggled.connect(self.on_audio_mode_changed)
        self.radio_system.toggled.connect(self.on_audio_mode_changed)
        self.radio_mute.toggled.connect(self.on_audio_mode_changed)

        audio_layout.addWidget(self.radio_mic)
        self.mic_combo = QComboBox()
        self.mic_combo.setMinimumHeight(28)
        self.mic_combo.setStyleSheet(
            "QComboBox { background:#0f172a; color:#e2e8f0; border:1px solid #334155; "
            "border-radius:6px; padding:2px 8px; font-size:11px; }"
        )
        self.mic_combo.currentIndexChanged.connect(self.on_mic_device_changed)
        audio_layout.addWidget(self.mic_combo)
        audio_layout.addWidget(self.radio_system)
        audio_layout.addWidget(self.radio_mute)
        self.refresh_mic_devices()

        # Audio Test Row
        test_row = QHBoxLayout()
        test_row.setSpacing(10)

        self.btn_test_audio = QPushButton("🎙️ Test Microphone")
        self.btn_test_audio.setCursor(Qt.PointingHandCursor)
        self.btn_test_audio.setFixedHeight(28)
        self.btn_test_audio.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #38bdf8;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #334155;
            }
            QPushButton:disabled {
                color: #64748b;
                border-color: #1e293b;
                background-color: #0f172a;
            }
        """)
        self.btn_test_audio.clicked.connect(self.test_audio)
        test_row.addWidget(self.btn_test_audio)

        self.btn_fix_mic = QPushButton("🔧 Fix Mic")
        self.btn_fix_mic.setCursor(Qt.PointingHandCursor)
        self.btn_fix_mic.setFixedHeight(28)
        self.btn_fix_mic.setToolTip(
            "Unmute, raise gain, set this mic as the system default for calls and all apps"
        )
        self.btn_fix_mic.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #fbbf24;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #334155; }
        """)
        self.btn_fix_mic.clicked.connect(self.fix_microphone)
        test_row.addWidget(self.btn_fix_mic)

        self.lbl_audio_test_status = QLabel("")
        self.lbl_audio_test_status.setStyleSheet("font-size: 11px; color: #94a3b8;")
        test_row.addWidget(self.lbl_audio_test_status)
        test_row.addStretch()

        audio_layout.addLayout(test_row)
        self.chk_listen = QCheckBox("Listen to input • show live loudness")
        self.chk_listen.toggled.connect(self.refresh_meter)
        audio_layout.addWidget(self.chk_listen)
        self.meter = AudioMeter(self)
        self.meter.changed.connect(self.show_audio_level)
        audio_layout.addWidget(self.meter)
        has_ffmpeg = shutil.which("ffmpeg") is not None
        if not has_ffmpeg:
            self.lbl_level = QLabel(f"Detected: {mic_name} • ⚠️ Run 'sudo apt install ffmpeg' to merge audio")
            self.lbl_level.setStyleSheet("color:#f59e0b; font-size:11px")
        else:
            self.lbl_level = QLabel(f"Detected: {mic_name} • enable listening or record")
            self.lbl_level.setStyleSheet("color:#94a3b8; font-size:11px")
        audio_layout.addWidget(self.lbl_level)
        layout.addWidget(audio_card)

        # 3. Video Format Card (MP4 vs WebM)
        format_card = QFrame()
        format_card.setProperty("class", "card")
        format_card.setObjectName("format_card")
        format_card.setStyleSheet("QFrame#format_card { background-color:#131c31; border:1px solid #1e293b; border-radius:12px; }")
        format_layout = QVBoxLayout(format_card)
        format_layout.setContentsMargins(14, 10, 14, 10)
        format_layout.setSpacing(6)

        format_title = QLabel("3. Video Format")
        format_title.setFont(QFont("Inter", 11, QFont.Bold))
        format_title.setStyleSheet("color: #94a3b8;")
        format_layout.addWidget(format_title)

        self.format_group = QButtonGroup(self)
        self.radio_mp4 = QRadioButton("🎬  MP4 (H.264 & AAC — Universal & Recommended)")
        self.radio_webm = QRadioButton("🌐  WebM (VP9 & Opus — Open Web Format)")

        self.radio_mp4.setChecked(True)
        self.format_group.addButton(self.radio_mp4)
        self.format_group.addButton(self.radio_webm)

        format_layout.addWidget(self.radio_mp4)
        format_layout.addWidget(self.radio_webm)
        layout.addWidget(format_card)

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
            padding: 6px;
        """)
        status_layout = QVBoxLayout(self.status_box)
        status_layout.setContentsMargins(12, 6, 12, 6)

        self.lbl_timer = QLabel("Ready to record")
        self.lbl_timer.setAlignment(Qt.AlignCenter)
        self.lbl_timer.setFont(QFont("Inter", 13, QFont.Bold))
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
        self.btn_record.setFixedHeight(44)
        self.update_button_style(recording=False)
        self.btn_record.clicked.connect(self.toggle_recording)
        layout.addWidget(self.btn_record)

        # Saved Video Actions
        self.actions_layout = QHBoxLayout()
        self.actions_layout.setSpacing(10)

        self.btn_play = QPushButton("▶️ Play Video")
        self.btn_play.setFixedHeight(34)
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
        self.btn_folder.setFixedHeight(34)
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
        self.btn_edit = QPushButton("✂  Edit recording / Open video…")
        self.btn_edit.setMinimumHeight(34)
        self.btn_edit.clicked.connect(self.edit_video)
        layout.addWidget(self.btn_edit)

        # Footer Shortcuts Info
        shortcuts_info = QLabel("Shortcuts:  Win+Shift+R (Area)  •  Win+Alt+R (Screen)")
        shortcuts_info.setAlignment(Qt.AlignCenter)
        shortcuts_info.setStyleSheet("color: #475569; font-size: 11px;")
        layout.addWidget(shortcuts_info)

    def refresh_mic_devices(self):
        """Populate the mic dropdown from PipeWire and restore the saved preference."""
        if not hasattr(self, "mic_combo"):
            return
        current = self.mic_combo.currentData()
        self.mic_combo.blockSignals(True)
        self.mic_combo.clear()
        sources = []
        preferred = None
        if _mic:
            try:
                sources = _mic.list_input_sources()
                preferred = (_mic.find_preferred_source(sources) or {}).get("name")
                if not preferred:
                    preferred = _mic.get_default_source()
            except Exception:
                sources = []
        if not sources:
            # Minimal fallback via pactl short list
            try:
                out = subprocess.check_output(["pactl", "list", "short", "sources"], text=True, timeout=3)
                for line in out.splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 2 and not parts[1].endswith(".monitor"):
                        sources.append({"name": parts[1], "description": parts[1], "is_usb": "usb" in parts[1]})
            except Exception:
                pass
        select = preferred or current
        for src in sources:
            label = _mic.format_source_choice(src) if _mic else (src.get("description") or src["name"])
            self.mic_combo.addItem(label, src["name"])
            if select and src["name"] == select:
                self.mic_combo.setCurrentIndex(self.mic_combo.count() - 1)
        if self.mic_combo.count() == 0:
            self.mic_combo.addItem("No microphone detected", "")
        self.mic_combo.blockSignals(False)
        mic_name = self.mic_combo.currentText() or get_default_mic_name()
        self.radio_mic.setText(f"🎙️  Microphone ({mic_name})")

    def on_mic_device_changed(self, *_args):
        name = self.mic_combo.currentData()
        label = self.mic_combo.currentText() or "Microphone"
        self.radio_mic.setText(f"🎙️  Microphone ({label})")
        if name and _mic:
            try:
                _mic.prefer_source(name, make_system_default=True)
            except Exception:
                pass
        self.refresh_meter()

    def fix_microphone(self):
        """Heal mute/gain and lock this mic as the system default for every app."""
        self.refresh_mic_devices()
        name = get_selected_mic_source(self)
        if not name:
            self.update_audio_test_status("⚠️ No microphone available", "#ef4444")
            return
        if _mic:
            try:
                _mic.prefer_source(name, make_system_default=True)
                heal = _mic.ensure_source_ready(name)
                self.update_audio_test_status(
                    f"✅ Default mic set for all apps · unmute={heal.get('unmuted')} volume={heal.get('volume')}",
                    "#4ade80",
                )
            except Exception as exc:
                self.update_audio_test_status(f"⚠️ Fix failed: {exc}", "#ef4444")
                return
        else:
            try:
                subprocess.run(["pactl", "set-default-source", name], check=False, timeout=3)
                subprocess.run(["pactl", "set-source-mute", name, "0"], check=False, timeout=3)
                subprocess.run(["pactl", "set-source-volume", name, "100%"], check=False, timeout=3)
                self.update_audio_test_status("✅ Mic unmuted and set as system default", "#4ade80")
            except Exception as exc:
                self.update_audio_test_status(f"⚠️ Fix failed: {exc}", "#ef4444")
        self.radio_mic.setChecked(True)
        self.chk_listen.setChecked(True)
        self.refresh_meter()

    def on_audio_mode_changed(self):
        mic_name = self.mic_combo.currentText() if hasattr(self, "mic_combo") else get_default_mic_name()
        has_ffmpeg = shutil.which("ffmpeg") is not None
        if hasattr(self, "mic_combo"):
            self.mic_combo.setEnabled(self.radio_mic.isChecked())
        if hasattr(self, "btn_fix_mic"):
            self.btn_fix_mic.setEnabled(self.radio_mic.isChecked())
        if self.radio_mic.isChecked():
            self.radio_mic.setText(f"🎙️  Microphone ({mic_name})")
            self.btn_test_audio.setText("🎙️ Test Microphone")
            self.btn_test_audio.setEnabled(True)
            self.btn_test_audio.setToolTip("Record 3 seconds and play it back; saves working mic as system default")
            if not self.chk_listen.isChecked():
                if not has_ffmpeg:
                    self.lbl_level.setText(f"Detected: {mic_name} • ⚠️ Run 'sudo apt install ffmpeg' to merge audio")
                    self.lbl_level.setStyleSheet("color:#f59e0b; font-size:11px")
                else:
                    self.lbl_level.setText(f"Detected: {mic_name} • enable listening or record")
                    self.lbl_level.setStyleSheet("color:#94a3b8; font-size:11px")
        elif self.radio_system.isChecked():
            self.btn_test_audio.setText("🔊 Test Sound Chime")
            self.btn_test_audio.setEnabled(True)
            self.btn_test_audio.setToolTip("Play a test chime to verify system audio playback")
            if not self.chk_listen.isChecked():
                self.lbl_level.setText("System audio ready • enable listening or record")
                self.lbl_level.setStyleSheet("color:#94a3b8; font-size:11px")
        else:
            self.btn_test_audio.setText("🔇 Audio Muted")
            self.btn_test_audio.setEnabled(False)
            self.btn_test_audio.setToolTip("Audio is disabled")
            self.lbl_level.setText("Audio recording disabled (muted)")
            self.lbl_level.setStyleSheet("color:#94a3b8; font-size:11px")
        self.lbl_audio_test_status.setText("")
        self.refresh_meter()

    def setup_recording_indicator(self):
        self.indicator = QWidget(self, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.indicator.setWindowTitle("DevOS • Recording")
        row = QHBoxLayout(self.indicator)
        self.indicator_text = QLabel("● REC 00:00")
        row.addWidget(self.indicator_text)
        self.indicator_level = QLabel("Input off")
        row.addWidget(self.indicator_level)
        stop = QPushButton("Stop & save")
        stop.clicked.connect(self.stop_recording)
        row.addWidget(stop)
        show = QPushButton("Recorder")
        show.clicked.connect(self.showNormal)
        row.addWidget(show)
        self._tray_level = -1
        self.tray = QSystemTrayIcon(get_app_icon(), self)
        self.tray.activated.connect(lambda *_: self.showNormal())

    def refresh_meter(self, *_args):
        if not hasattr(self, "meter"):
            return
        mode = self.get_selected_audio_mode()
        if mode != "mute" and (self.recording or self.chk_listen.isChecked()):
            if mode == "system":
                device = get_default_monitor_sink()
                if not device:
                    self.meter.stop()
                    self.lbl_level.setText("System audio source unavailable")
                    return
            else:
                device = get_selected_mic_source(self)
            self.meter.start(device)
        else:
            self.meter.stop()
            if not self.recording and not self.chk_listen.isChecked():
                mic_name = get_default_mic_name()
                has_ffmpeg = shutil.which("ffmpeg") is not None
                if mode == "mic":
                    if not has_ffmpeg:
                        self.lbl_level.setText(f"Detected: {mic_name} • ⚠️ Run 'sudo apt install ffmpeg' to merge audio")
                        self.lbl_level.setStyleSheet("color:#f59e0b; font-size:11px")
                    else:
                        self.lbl_level.setText(f"Detected: {mic_name} • enable listening or record")
                        self.lbl_level.setStyleSheet("color:#94a3b8; font-size:11px")
                elif mode == "system":
                    self.lbl_level.setText("System audio ready • enable listening or record")
                    self.lbl_level.setStyleSheet("color:#94a3b8; font-size:11px")
                else:
                    self.lbl_level.setText("Audio recording disabled (muted)")
                    self.lbl_level.setStyleSheet("color:#94a3b8; font-size:11px")

    def show_audio_level(self, fraction, text):
        if hasattr(self, "lbl_level"):
            self.lbl_level.setText(text)
        if hasattr(self, "indicator_level"):
            self.indicator_level.setText("▮" * round(fraction * 10) + "  " + text)
            self.tray.setToolTip("DevOS Screen Recorder • " + text)
            level = round(fraction * 5)
            if self.recording and level != self._tray_level:
                self._tray_level = level
                pixmap = QPixmap(32, 32)
                pixmap.fill(Qt.transparent)
                painter = QPainter(pixmap)
                for i in range(5):
                    painter.fillRect(2+i*6, 29-(i+1)*4, 4, (i+1)*4,
                                     QColor(("#ef4444" if level == 5 else "#34d399") if i < level else "#64748b"))
                painter.setBrush(QColor("#ef4444"))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(1, 1, 8, 8)
                painter.end()
                self.tray.setIcon(QIcon(pixmap))

    def edit_video(self):
        if self.recording:
            return
        path = self.last_saved_file
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open video to edit", SCREENCASTS_DIR,
                                                 "Video (*.mp4 *.webm *.mkv *.mov);;All files (*)")
        if path:
            try:
                editor = VideoEditor(path, self)
                editor.exec_()
            except Exception as exc:
                QMessageBox.warning(self, "Cannot open video", str(exc))

    def stop_audio(self):
        if self.audio_proc:
            try:
                self.audio_proc.send_signal(signal.SIGINT)
                self.audio_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.audio_proc.kill()
                self.audio_proc.wait()
            self.audio_proc = None

    def recording_finished(self):
        self.indicator.hide()
        self.tray.hide()
        self.btn_edit.setEnabled(True)
        for button in self.area_group.buttons() + self.audio_group.buttons() + self.format_group.buttons():
            button.setEnabled(True)
        self.refresh_meter()

    def closeEvent(self, event):
        if self.recording:
            self.showMinimized()
            event.ignore()
            return
        if self.finalize_thread and self.finalize_thread.isRunning():
            event.ignore()
            return
        if self.test_thread and self.test_thread.isRunning():
            event.ignore()
            return
        self.meter.stop()
        self.indicator.close()
        self.tray.hide()
        event.accept()

    def test_audio(self):
        if self.radio_mic.isChecked():
            self.btn_test_audio.setEnabled(False)
            # Stop the live meter so the test capture owns the device cleanly
            if hasattr(self, "meter"):
                self.meter.stop()
            device = get_selected_mic_source(self)
            self.test_thread = MicTestThread(device=device)
            self.test_thread.status_signal.connect(self.update_audio_test_status)

            def _after():
                self.btn_test_audio.setEnabled(True)
                self.chk_listen.setChecked(True)
                self.refresh_meter()

            self.test_thread.finished_signal.connect(_after)
            self.test_thread.start()
        elif self.radio_system.isChecked():
            self.btn_test_audio.setEnabled(False)
            self.test_thread = ChimeTestThread()
            self.test_thread.status_signal.connect(self.update_audio_test_status)
            self.test_thread.finished_signal.connect(lambda: self.btn_test_audio.setEnabled(True))
            self.test_thread.start()

    def update_audio_test_status(self, text: str, color: str):
        self.lbl_audio_test_status.setText(text)
        self.lbl_audio_test_status.setStyleSheet(f"font-size: 11px; color: {color};")

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

    def get_selected_mode(self) -> str:
        if self.radio_region.isChecked():
            return "region"
        elif self.radio_window.isChecked():
            return "window"
        return "screen"

    def get_selected_audio_mode(self) -> str:
        if self.radio_mic.isChecked():
            return "mic"
        elif self.radio_system.isChecked():
            return "system"
        return "mute"

    def get_selected_format(self) -> str:
        if self.radio_webm.isChecked():
            return "webm"
        return "mp4"

    def toggle_recording(self):
        if not self.recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        mode = self.get_selected_mode()
        audio_mode = self.get_selected_audio_mode()
        self.initial_files = set(glob.glob(os.path.join(SCREENCASTS_DIR, "*")))

        # Start audio recording in background if enabled
        self.temp_audio_file = None
        if audio_mode in ("mic", "system"):
            fd, self.temp_audio_file = tempfile.mkstemp(prefix="devos-audio-", suffix=".wav")
            os.close(fd)
            if audio_mode == "mic":
                mic = get_selected_mic_source(self)
                if _mic and mic:
                    try:
                        _mic.prefer_source(mic, make_system_default=True)
                        _mic.ensure_source_ready(mic)
                    except Exception:
                        pass
                if shutil.which("parecord"):
                    cmd = ["parecord", "--channels=1", "--rate=48000", "--file-format=wav"]
                    if mic:
                        cmd.append("--device=" + mic)
                    cmd.append(self.temp_audio_file)
                elif shutil.which("pw-record"):
                    cmd = ["pw-record", "--channels=1", "--rate=48000"]
                    if mic:
                        cmd.extend(["--target", mic])
                    cmd.append(self.temp_audio_file)
                else:
                    os.unlink(self.temp_audio_file)
                    self.temp_audio_file = None
                    self.lbl_subtext.setText("No audio recorder available (install pulseaudio-utils).")
                    return
            else:
                cmd = ["parecord", "--channels=1", "--rate=48000", "--file-format=wav"]
                monitor = get_default_monitor_sink()
                if not monitor:
                    os.unlink(self.temp_audio_file)
                    self.temp_audio_file = None
                    self.lbl_subtext.setText("System audio source unavailable. Choose a working audio source.")
                    return
                cmd.extend(["-d", monitor, "--channels=2"])
                cmd.append(self.temp_audio_file)
            try:
                self.audio_proc = subprocess.Popen(cmd)
            except OSError as exc:
                os.unlink(self.temp_audio_file)
                self.temp_audio_file = None
                self.lbl_subtext.setText("Audio recording could not start: " + str(exc))
                return

        # Start video capture via Spectacle DBus entry point
        dbus_method = "RecordScreen"
        if mode == "region":
            dbus_method = "RecordRegion"
        elif mode == "window":
            dbus_method = "RecordWindow"

        self.capture_request.start("busctl", ["--user", "call", "org.kde.Spectacle", "/",
                                              "org.kde.Spectacle", dbus_method, "i", "0"])

        self.recording = True
        self.seconds_elapsed = 0
        self.update_button_style(recording=True)
        self.setWindowIcon(get_recording_icon())
        self.btn_play.hide()
        self.btn_folder.hide()
        self.btn_edit.setEnabled(False)
        for button in self.area_group.buttons() + self.audio_group.buttons() + self.format_group.buttons():
            button.setEnabled(False)
        self.refresh_meter()
        self.indicator.show()
        self.tray.setIcon(get_recording_icon())
        self.tray.show()
        self.timer.start()
        self.update_timer()

        if self.chk_minimize.isChecked():
            QTimer.singleShot(400, self.showMinimized)

    def stop_recording(self):
        """User clicked Stop & Save: trigger finish via global shortcut so Spectacle cleanly saves."""
        self.timer.stop()
        self.lbl_timer.setText("Finalizing video...")
        self.lbl_timer.setStyleSheet("color: #38bdf8;")
        self.lbl_subtext.setText("Saving file to ~/Videos/Screencasts...")

        # Stop audio recording process
        self.stop_audio()

        # Invoke Spectacle's shortcut action which stops & finalizes the recording
        mode = self.get_selected_mode()
        shortcut = "RecordScreen"
        if mode == "region":
            shortcut = "RecordRegion"
        elif mode == "window":
            shortcut = "RecordWindow"

        subprocess.run(
            [
                "busctl",
                "--user",
                "call",
                "org.kde.kglobalaccel",
                "/component/org_kde_spectacle_desktop",
                "org.kde.kglobalaccel.Component",
                "invokeShortcut",
                "s",
                shortcut,
            ],
            capture_output=True,
        )

        # Fallback check in case DBus signal is delayed or not received
        QTimer.singleShot(1800, self.check_saved_file_fallback)

    def check_saved_file_fallback(self):
        """Fallback poller if DBus RecordingTaken signal didn't arrive."""
        if not self.recording:
            return
        current_files = set(glob.glob(os.path.join(SCREENCASTS_DIR, "*")))
        new_files = current_files - self.initial_files
        latest = None
        if new_files:
            latest = max(new_files, key=os.path.getmtime)

        if latest and os.path.isfile(latest):
            self.finalize_saved_file(latest)
        else:
            self.recording = False
            self.stop_audio()
            self.recording_finished()
            self.update_button_style(recording=False)
            self.setWindowIcon(get_app_icon())
            self.lbl_timer.setText("Ready to record")
            self.lbl_timer.setStyleSheet("color: #94a3b8;")
            self.lbl_subtext.setText("No new recording was found. Check Spectacle for capture errors.")

    def finalize_saved_file(self, raw_file_path: str):
        """Finalize video: transcode/mux to MP4 (or WebM), display preview, and notify user."""
        self.timer.stop()
        self.recording = False
        self.recording_finished()
        self.update_button_style(recording=False)
        self.setWindowIcon(get_app_icon())

        self.stop_audio()

        self.btn_record.setEnabled(False)
        self.btn_edit.setEnabled(False)
        self.lbl_timer.setText("Saving recording…")
        self.lbl_subtext.setText("Encoding in the background • keep this window open")
        self.finalize_thread = FinalizeThread(raw_file_path, self.temp_audio_file, self.get_selected_format(), self)
        self.finalize_thread.result.connect(self.finish_saved_file)
        self.finalize_thread.finished.connect(lambda: self.btn_record.setEnabled(True))
        self.finalize_thread.finished.connect(lambda: self.btn_edit.setEnabled(True))
        self.finalize_thread.start()

    def finish_saved_file(self, final_path, error):
        raw_source = getattr(self.finalize_thread, "source", None)
        if not error and self.temp_audio_file and os.path.isfile(self.temp_audio_file):
            try:
                os.unlink(self.temp_audio_file)
            except Exception:
                pass
            self.temp_audio_file = None
        if error:
            self.last_saved_file = final_path
            self.showNormal()
            self.lbl_timer.setText("Video kept • audio merge failed")
            if not shutil.which("ffmpeg"):
                self.lbl_subtext.setText("Install ffmpeg with 'sudo apt install ffmpeg' to merge audio into video.")
            else:
                self.lbl_subtext.setText("Your source video and audio are preserved. " + error[:180])
            self.lbl_subtext.setWordWrap(True)
            self.btn_play.show()
            self.btn_folder.show()
            return

        if final_path and os.path.isfile(final_path):
            # Clean up raw intermediate video file created by Spectacle
            if raw_source and os.path.isfile(raw_source) and os.path.abspath(raw_source) != os.path.abspath(final_path):
                try:
                    os.unlink(raw_source)
                except Exception:
                    pass

            # Clean up '-saved' suffix to keep final recording filename clean
            target_ext = f".{self.get_selected_format()}"
            if f"-saved{target_ext}" in final_path:
                clean_path = final_path.replace(f"-saved{target_ext}", target_ext)
                if not os.path.exists(clean_path):
                    try:
                        os.rename(final_path, clean_path)
                        final_path = clean_path
                    except Exception:
                        pass

        self.last_saved_file = final_path
        self.showNormal()
        self.raise_()
        self.activateWindow()

        if final_path and os.path.isfile(final_path):
            basename = os.path.basename(final_path)
            size_kb = os.path.getsize(final_path) // 1024
            ext = os.path.splitext(final_path)[1].upper().replace(".", "")

            self.lbl_timer.setText(f"✅ Recording Saved ({ext})!")
            self.lbl_timer.setStyleSheet("color: #4ade80;")
            self.lbl_subtext.setText(f"{basename} ({size_kb} KB)")

            self.btn_play.show()
            self.btn_folder.show()

            # Desktop notification
            subprocess.Popen([
                "notify-send",
                "-i", "devos-recorder",
                "Screen Recording Saved",
                f"Saved to {basename}\nReady to play or share",
            ])
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
        self.indicator_text.setText(f"● REC {time_str}")
        if self.audio_proc and self.audio_proc.poll() is not None:
            self.lbl_subtext.setText("Audio input stopped • video is still recording. Check your input device.")
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

    # Keep confirmation and input dialogs consistent across DevOS apps.
    import sys as _dialog_sys
    from pathlib import Path as _DialogPath
    _dialog_sys.path.insert(0, str(_DialogPath(__file__).resolve().parent.parent))
    from devos_dialogs import install as _install_dialog_style
    from app_identity import prepare as prepare_identity
    prepare_identity("devos-screen-recorder")
    app = QApplication(sys.argv)
    _install_dialog_style(app)
    app.setApplicationName("devos-screen-recorder")
    app.setApplicationDisplayName("Screen Recorder")
    if hasattr(app, "setDesktopFileName"):
        app.setDesktopFileName("devos-screen-recorder")
        from app_identity import apply as apply_identity
        apply_identity(app, "devos-screen-recorder")
    app.setWindowIcon(get_app_icon())

    window = DevOSRecorder()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
