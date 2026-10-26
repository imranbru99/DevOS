"""Small clip editor for DevOS recordings; always exports a separate MP4."""
import os
import subprocess
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                            QListWidget, QDoubleSpinBox, QComboBox, QFileDialog, QMessageBox)
from media_edit import Clip, probe, export_video


class ExportThread(QThread):
    result = pyqtSignal(str)

    def __init__(self, args, parent):
        super().__init__(parent)
        self.args = args

    def run(self):
        try:
            export_video(*self.args)
            self.result.emit("")
        except Exception as exc:
            self.result.emit(str(exc))


class VideoEditor(QDialog):
    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.source = source
        self.duration, self.has_audio = probe(source)
        self.clips = [Clip(0, self.duration)]
        self.voice = None
        self.worker = None
        self.setWindowTitle("DevOS • Edit recording")
        self.resize(680, 560)
        layout = QVBoxLayout(self)
        title = QLabel("Edit your recording")
        title.setStyleSheet("font-size:24px; font-weight:600; padding:12px")
        layout.addWidget(title)
        name = QLabel(os.path.basename(source))
        name.setWordWrap(True)
        layout.addWidget(name)
        layout.addWidget(QLabel("Clips play in order. Times refer to the original video. Your original is preserved."))
        self.timeline = QListWidget()
        self.timeline.currentRowChanged.connect(self.select_clip)
        layout.addWidget(self.timeline)
        row = QHBoxLayout()
        self.start, self.end = QDoubleSpinBox(), QDoubleSpinBox()
        for label, field in (("Start (seconds)", self.start), ("End (seconds)", self.end)):
            field.setDecimals(3)
            field.setRange(0, self.duration)
            row.addWidget(QLabel(label))
            row.addWidget(field)
        layout.addLayout(row)
        row = QHBoxLayout()
        for label, callback in (("Trim selected", self.trim), ("Copy selection to end", self.copy),
                                ("Cut selection", self.cut), ("Remove clip", self.remove)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.audio = QComboBox()
        for label, mode in (("Keep original audio", "original"), ("Remove all audio", "mute"),
                            ("Replace with voice / audio file", "replace"), ("Mix voice with original audio", "mix")):
            self.audio.addItem(label, mode)
        layout.addWidget(self.audio)
        self.voice_button = QPushButton("Choose voice / audio file…")
        self.voice_button.clicked.connect(self.choose_voice)
        layout.addWidget(self.voice_button)
        row = QHBoxLayout()
        preview = QPushButton("Play original")
        preview.clicked.connect(lambda: subprocess.Popen(["xdg-open", self.source]))
        row.addWidget(preview)
        self.export_button = QPushButton("Export edited MP4…")
        self.export_button.clicked.connect(self.export)
        row.addWidget(self.export_button)
        layout.addLayout(row)
        self.status = QLabel("Ready • edits are applied when you export")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.refresh(0)

    def refresh(self, index=0):
        self.timeline.clear()
        for i, c in enumerate(self.clips):
            self.timeline.addItem(f"{i+1:02d}   {c.start:.3f}s → {c.end:.3f}s    •    {c.duration:.3f}s")
        self.timeline.setCurrentRow(min(index, len(self.clips)-1))

    def select_clip(self, index):
        if 0 <= index < len(self.clips):
            self.start.setValue(self.clips[index].start)
            self.end.setValue(self.clips[index].end)

    def selection(self):
        a, b = self.start.value(), self.end.value()
        if b <= a:
            self.status.setText("End must be after start.")
            return None
        return Clip(a, b)

    def trim(self):
        clip = self.selection()
        index = self.timeline.currentRow()
        if clip and index >= 0:
            self.clips[index] = clip
            self.refresh(index)

    def copy(self):
        clip = self.selection()
        if clip and len(self.clips) < 100:
            self.clips.append(clip)
            self.refresh(len(self.clips)-1)

    def cut(self):
        selection = self.selection()
        index = self.timeline.currentRow()
        if not selection or index < 0:
            return
        c = self.clips[index]
        if selection.start < c.start or selection.end > c.end:
            self.status.setText("Cut times must be within the selected clip.")
            return
        pieces = []
        if selection.start > c.start:
            pieces.append(Clip(c.start, selection.start))
        if selection.end < c.end:
            pieces.append(Clip(selection.end, c.end))
        self.clips[index:index+1] = pieces
        self.refresh(index)

    def remove(self):
        index = self.timeline.currentRow()
        if index >= 0:
            del self.clips[index]
            self.refresh(index)

    def choose_voice(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose voice or music", "", "Audio (*.wav *.mp3 *.m4a *.aac *.ogg *.opus *.flac);;All files (*)")
        if path:
            self.voice = path
            self.voice_button.setText(os.path.basename(path))

    def export(self):
        if not self.clips:
            self.status.setText("Add a clip before exporting.")
            return
        mode = self.audio.currentData()
        if mode in ("replace", "mix") and not self.voice:
            self.status.setText("Choose a voice / audio file first.")
            return
        destination, _ = QFileDialog.getSaveFileName(self, "Export a new video", os.path.splitext(self.source)[0]+"-edited.mp4", "MP4 video (*.mp4)")
        if not destination:
            return
        if not destination.lower().endswith(".mp4"):
            destination += ".mp4"
        self.worker = ExportThread((self.source, list(self.clips), self.duration, self.has_audio, mode, self.voice, destination), self)
        self.export_button.setEnabled(False)
        self.status.setText("Exporting… You can continue using the desktop.")
        self.worker.result.connect(lambda error: self.export_done(error, destination))
        self.worker.finished.connect(lambda: self.export_button.setEnabled(True))
        self.worker.start()

    def export_done(self, error, destination):
        self.status.setText("Export failed: " + error if error else "Saved: " + destination)

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.status.setText("Please wait for the export to finish before closing.")
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            event.ignore()
            self.status.setText("Please wait for the export to finish before closing.")
        else:
            event.accept()
