"""Live PulseAudio/PipeWire level monitor, active only at the user's request."""
import array
import math
import sys
from PyQt5.QtCore import QProcess, QTimer, pyqtSignal
from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QPainter, QColor


def pcm_peak(data):
    samples = array.array("h")
    samples.frombytes(data[:len(data) // 2 * 2])
    if sys.byteorder != "little":
        samples.byteswap()
    return max((abs(v) / 32768 for v in samples), default=0)


def level_fraction(peak):
    """Logarithmic -60…0 dBFS scale, not a microphone gain control."""
    return max(0., min(1., (20 * math.log10(max(peak, .001)) + 60) / 60))


class AudioMeter(QWidget):
    changed = pyqtSignal(float, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(24)
        self.setAccessibleName("Live audio input level")
        self.peak = 0
        self.running = False
        self.pending = b""
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.read_audio)
        self.process.readyReadStandardError.connect(lambda: self.process.readAllStandardError())
        self.process.errorOccurred.connect(lambda *_: self.failed())
        self.process.finished.connect(lambda *_: self.failed() if self.running else None)
        self.decay = QTimer(self)
        self.decay.setInterval(80)
        self.decay.timeout.connect(self.tick)

    def start(self, device=None):
        self.stop()
        self.running = True
        self.pending = b""
        args = ["--raw", "--format=s16le", "--channels=1", "--rate=16000", "--latency-msec=50"]
        if device:
            args += ["--device", device]
        self.process.start("parec", args)
        self.decay.start()

    def failed(self):
        if self.running:
            self.running = False
            self.decay.stop()
            self.peak = 0
            self.update()
            self.changed.emit(0, "Audio meter unavailable • check input device")

    def stop(self):
        self.running = False
        self.decay.stop()
        if self.process.state() != QProcess.NotRunning:
            self.process.terminate()
            if not self.process.waitForFinished(500):
                self.process.kill()
                self.process.waitForFinished(500)
        self.peak = 0
        self.update()
        self.changed.emit(0, "Microphone off")

    def read_audio(self):
        data = self.pending + bytes(self.process.readAllStandardOutput())
        size = len(data) // 2 * 2
        self.pending = data[size:]
        self.peak = max(self.peak, pcm_peak(data[:size]))

    def tick(self):
        peak = self.peak
        db = 20 * math.log10(max(peak, .00001))
        text = "Clipping • lower input volume" if peak >= .98 else ("No signal" if db < -60 else f"Listening • {db:.0f} dBFS")
        self.changed.emit(level_fraction(peak), text)
        self.setAccessibleDescription(text)
        self.peak *= .72
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        fraction = level_fraction(self.peak) if self.running else 0
        for i in range(28):
            color = "#ef4444" if i > 24 else "#fbbf24" if i > 20 else "#34d399"
            painter.fillRect(int(i * self.width() / 28), 3, max(1, int(self.width() / 28)-3), self.height()-6,
                             QColor(color if i / 28 < fraction else "#243047"))
