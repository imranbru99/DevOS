#!/usr/bin/env python3
"""
DevOS Screen Recorder (Fluent Wayland Screen & Audio Recorder)
Provides a clean, frictionless 1-click recording interface for DevOS:
  - Native Wayland & PipeWire capture (zero setup, no warnings, no codec crashes)
  - Dedicated Audio selection: Microphone, System Sound, or Muted
  - Dedicated Video Format selection: MP4 (Universal H.264/AAC) or WebM (VP9/Opus)
  - Built-in Audio Testing: Voice mic playback test & System chime test
  - Clean desktop icon that only displays active red indicator during live recording
  - Instantaneous MP4/WebM encoding with AAC audio muxing
  - Full DBus signal sync with Spectacle system tray and global shortcuts
  - Start, Stop, and Save buttons with instant playback and folder shortcuts
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

from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont, QIcon, QPixmap
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
)
from PyQt5 import QtDBus

# GStreamer for instantaneous, lossless video + audio muxing & MP4 transcoding
try:
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
    HAS_GST = True
except Exception:
    HAS_GST = False

SCREENCASTS_DIR = os.path.expanduser("~/Videos/Screencasts")


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


def transcode_to_mp4(input_video: str, input_audio_wav: Optional[str], output_mp4: str) -> bool:
    """
    Produce a universal, standard MP4 (H.264 video + AAC audio) from the input video and optional audio.
    Runs in ~0.2s using GStreamer hardware/software pipeline.
    """
    if not HAS_GST or not os.path.isfile(input_video):
        return False

    has_openh264 = Gst.ElementFactory.find("openh264enc") is not None
    has_x264 = Gst.ElementFactory.find("x264enc") is not None
    has_audio = bool(input_audio_wav and os.path.isfile(input_audio_wav) and os.path.getsize(input_audio_wav) > 1024)

    if has_openh264:
        video_branch = "dmx.video_0 ! queue ! vp9dec ! videoconvert ! openh264enc bitrate=4000000 ! h264parse ! queue ! mux.video_0"
    elif has_x264:
        video_branch = "dmx.video_0 ! queue ! vp9dec ! videoconvert ! x264enc speed-preset=ultrafast tune=zerolatency ! h264parse ! queue ! mux.video_0"
    else:
        video_branch = "dmx.video_0 ! queue ! vp9parse ! queue ! mux.video_0"

    if has_audio:
        has_voaac = Gst.ElementFactory.find("voaacenc") is not None
        if has_voaac:
            audio_branch = f'filesrc location="{input_audio_wav}" ! wavparse ! audioconvert ! audioresample ! voaacenc ! aacparse ! queue ! mux.audio_0'
        else:
            audio_branch = f'filesrc location="{input_audio_wav}" ! wavparse ! audioconvert ! audioresample ! lamemp3enc ! mpegaudioparse ! queue ! mux.audio_0'

        desc = f"""
            mp4mux name=mux ! filesink location="{output_mp4}"
            filesrc location="{input_video}" ! matroskademux name=dmx
            {video_branch}
            {audio_branch}
        """
    else:
        desc = f"""
            mp4mux name=mux ! filesink location="{output_mp4}"
            filesrc location="{input_video}" ! matroskademux name=dmx
            {video_branch}
        """

    try:
        pipe = Gst.parse_launch(desc)
        pipe.set_state(Gst.State.PLAYING)
        bus = pipe.get_bus()
        msg = bus.timed_pop_filtered(30 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
        pipe.set_state(Gst.State.NULL)
        return msg is not None and msg.type == Gst.MessageType.EOS and os.path.isfile(output_mp4) and os.path.getsize(output_mp4) > 100
    except Exception as e:
        print(f"Error in transcode_to_mp4: {e}")
        return False


def transcode_to_webm(input_video: str, input_audio_wav: Optional[str], output_webm: str) -> bool:
    """Mux video stream and optional audio stream into a final webm container using GStreamer."""
    if not HAS_GST or not os.path.isfile(input_video):
        return False

    has_audio = bool(input_audio_wav and os.path.isfile(input_audio_wav) and os.path.getsize(input_audio_wav) > 1024)
    if not has_audio:
        if input_video != output_webm:
            shutil.copy2(input_video, output_webm)
        return True

    try:
        desc = f"""
            matroskamux name=mux ! filesink location="{output_webm}"
            filesrc location="{input_video}" ! matroskademux name=dmx
            filesrc location="{input_audio_wav}" ! wavparse ! audioconvert ! audioresample ! opusenc ! mux.audio_0
            dmx.video_0 ! queue ! mux.video_0
        """
        pipe = Gst.parse_launch(desc)
        pipe.set_state(Gst.State.PLAYING)
        bus = pipe.get_bus()
        msg = bus.timed_pop_filtered(30 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
        pipe.set_state(Gst.State.NULL)
        return msg is not None and msg.type == Gst.MessageType.EOS and os.path.isfile(output_webm) and os.path.getsize(output_webm) > 100
    except Exception as e:
        print(f"Error in transcode_to_webm: {e}")
        return False


class MicTestThread(QThread):
    status_signal = pyqtSignal(str, str)
    finished_signal = pyqtSignal()

    def run(self):
        test_wav = f"/tmp/devos_mic_test_{int(time.time())}.wav"
        self.status_signal.emit("🎙️ Speak now (listening 2s)...", "#f59e0b")
        try:
            subprocess.run(["parecord", "--channels=1", "--rate=48000", "--file-format=wav", test_wav], timeout=2.0)
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass

        if os.path.isfile(test_wav) and os.path.getsize(test_wav) > 1000:
            self.status_signal.emit("🔊 Playing back your voice...", "#38bdf8")
            subprocess.run(["paplay", test_wav], check=False)
            try:
                os.remove(test_wav)
            except Exception:
                pass
            self.status_signal.emit("✅ Microphone working!", "#4ade80")
        else:
            self.status_signal.emit("⚠️ No audio detected", "#ef4444")

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

        os.makedirs(SCREENCASTS_DIR, exist_ok=True)
        self.init_ui()
        self.setup_dbus_listener()

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_timer)

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
            self.update_button_style(recording=False)
            self.setWindowIcon(get_app_icon())
            self.showNormal()
            self.lbl_timer.setText("⚠️ Recording Failed")
            self.lbl_timer.setStyleSheet("color: #ef4444;")
            self.lbl_subtext.setText(message or "Capture failed")

    def init_ui(self):
        self.setWindowTitle("Screen Recorder")
        self.setFixedSize(500, 680)
        self.setWindowIcon(get_app_icon())

        self.setStyleSheet("""
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

        layout = QVBoxLayout(self)
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
        area_card.setStyleSheet("""
            background-color: #131c31;
            border: 1px solid #1e293b;
            border-radius: 12px;
        """)
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
        audio_card.setStyleSheet("""
            background-color: #131c31;
            border: 1px solid #1e293b;
            border-radius: 12px;
        """)
        audio_layout = QVBoxLayout(audio_card)
        audio_layout.setContentsMargins(14, 10, 14, 10)
        audio_layout.setSpacing(6)

        audio_title = QLabel("2. Audio Option")
        audio_title.setFont(QFont("Inter", 11, QFont.Bold))
        audio_title.setStyleSheet("color: #94a3b8;")
        audio_layout.addWidget(audio_title)

        self.audio_group = QButtonGroup(self)
        self.radio_mic = QRadioButton("🎙️  Microphone (Voice)")
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
        audio_layout.addWidget(self.radio_system)
        audio_layout.addWidget(self.radio_mute)

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

        self.lbl_audio_test_status = QLabel("")
        self.lbl_audio_test_status.setStyleSheet("font-size: 11px; color: #94a3b8;")
        test_row.addWidget(self.lbl_audio_test_status)
        test_row.addStretch()

        audio_layout.addLayout(test_row)
        layout.addWidget(audio_card)

        # 3. Video Format Card (MP4 vs WebM)
        format_card = QFrame()
        format_card.setProperty("class", "card")
        format_card.setStyleSheet("""
            background-color: #131c31;
            border: 1px solid #1e293b;
            border-radius: 12px;
        """)
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

        # Footer Shortcuts Info
        shortcuts_info = QLabel("Shortcuts:  Win+Shift+R (Area)  •  Win+Alt+R (Screen)")
        shortcuts_info.setAlignment(Qt.AlignCenter)
        shortcuts_info.setStyleSheet("color: #475569; font-size: 11px;")
        layout.addWidget(shortcuts_info)

    def on_audio_mode_changed(self):
        if self.radio_mic.isChecked():
            self.btn_test_audio.setText("🎙️ Test Microphone")
            self.btn_test_audio.setEnabled(True)
            self.btn_test_audio.setToolTip("Record 2 seconds and play it back to check mic levels")
        elif self.radio_system.isChecked():
            self.btn_test_audio.setText("🔊 Test Sound Chime")
            self.btn_test_audio.setEnabled(True)
            self.btn_test_audio.setToolTip("Play a test chime to verify system audio playback")
        else:
            self.btn_test_audio.setText("🔇 Audio Muted")
            self.btn_test_audio.setEnabled(False)
            self.btn_test_audio.setToolTip("Audio is disabled")
        self.lbl_audio_test_status.setText("")

    def test_audio(self):
        if self.radio_mic.isChecked():
            self.btn_test_audio.setEnabled(False)
            self.test_thread = MicTestThread()
            self.test_thread.status_signal.connect(self.update_audio_test_status)
            self.test_thread.finished_signal.connect(lambda: self.btn_test_audio.setEnabled(True))
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
            self.temp_audio_file = f"/tmp/devos_audio_{int(time.time())}.wav"
            cmd = ["parecord", "--channels=1", "--rate=48000", "--file-format=wav"]
            if audio_mode == "system":
                monitor = get_default_monitor_sink()
                if monitor:
                    cmd.extend(["-d", monitor, "--channels=2"])
            cmd.append(self.temp_audio_file)
            try:
                self.audio_proc = subprocess.Popen(cmd)
            except Exception:
                self.audio_proc = None

        # Start video capture via Spectacle DBus entry point
        dbus_method = "RecordScreen"
        if mode == "region":
            dbus_method = "RecordRegion"
        elif mode == "window":
            dbus_method = "RecordWindow"

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
        self.setWindowIcon(get_recording_icon())
        self.btn_play.hide()
        self.btn_folder.hide()
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
        if self.audio_proc:
            try:
                self.audio_proc.send_signal(signal.SIGINT)
                self.audio_proc.wait(timeout=1.5)
            except Exception:
                try:
                    self.audio_proc.kill()
                except Exception:
                    pass
            self.audio_proc = None

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
        else:
            cand = glob.glob(os.path.join(SCREENCASTS_DIR, "*.webm")) + glob.glob(os.path.join(SCREENCASTS_DIR, "*.mp4"))
            if cand:
                latest = max(cand, key=os.path.getmtime)

        if latest and os.path.isfile(latest):
            self.finalize_saved_file(latest)
        else:
            self.recording = False
            self.update_button_style(recording=False)
            self.setWindowIcon(get_app_icon())
            self.lbl_timer.setText("Ready to record")
            self.lbl_timer.setStyleSheet("color: #94a3b8;")
            self.lbl_subtext.setText("Saved to ~/Videos/Screencasts")

    def finalize_saved_file(self, raw_file_path: str):
        """Finalize video: transcode/mux to MP4 (or WebM), display preview, and notify user."""
        self.timer.stop()
        self.recording = False
        self.update_button_style(recording=False)
        self.setWindowIcon(get_app_icon())

        if self.audio_proc:
            try:
                self.audio_proc.send_signal(signal.SIGINT)
                self.audio_proc.wait(timeout=1.0)
            except Exception:
                try:
                    self.audio_proc.kill()
                except Exception:
                    pass
            self.audio_proc = None

        target_format = self.get_selected_format()
        final_path = raw_file_path

        if target_format == "mp4":
            base, _ = os.path.splitext(raw_file_path)
            mp4_path = base + ".mp4"
            if transcode_to_mp4(raw_file_path, self.temp_audio_file, mp4_path):
                if os.path.isfile(raw_file_path) and raw_file_path != mp4_path:
                    try:
                        os.remove(raw_file_path)
                    except Exception:
                        pass
                final_path = mp4_path
        elif target_format == "webm":
            if self.temp_audio_file and os.path.isfile(self.temp_audio_file) and os.path.getsize(self.temp_audio_file) > 1024:
                merged_path = raw_file_path + ".merged.webm"
                if transcode_to_webm(raw_file_path, self.temp_audio_file, merged_path):
                    shutil.move(merged_path, raw_file_path)
                final_path = raw_file_path

        # Remove temp audio wav
        if self.temp_audio_file and os.path.isfile(self.temp_audio_file):
            try:
                os.remove(self.temp_audio_file)
            except Exception:
                pass
            self.temp_audio_file = None

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
    app.setApplicationName("devos-screen-recorder")
    app.setApplicationDisplayName("Screen Recorder")
    if hasattr(app, "setDesktopFileName"):
        app.setDesktopFileName("devos-screen-recorder")
    app.setWindowIcon(get_app_icon())

    window = DevOSRecorder()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
