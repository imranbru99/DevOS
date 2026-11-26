"""Live PulseAudio/PipeWire level monitor, active only at the user's request."""
import array
import math
import shutil
import sys
import time
try:
    from PyQt5.QtCore import QProcess, QTimer, pyqtSignal
    from PyQt5.QtWidgets import QWidget
    from PyQt5.QtGui import QPainter, QColor
    _QT = True
except ImportError:
    _QT = False


def pcm_peak(data):
    samples = array.array("h")
    samples.frombytes(data[:len(data) // 2 * 2])
    if sys.byteorder != "little":
        samples.byteswap()
    return max((abs(v) / 32768 for v in samples), default=0)


def level_fraction(peak):
    """Logarithmic -60…0 dBFS scale, not a microphone gain control."""
    return max(0., min(1., (20 * math.log10(max(peak, .001)) + 60) / 60))


def meter_command(device=None, which=shutil.which):
    """Same raw capture the voice recorder uses.

    parec at 16 kHz opens some USB microphones and then returns silence.
    parecord at 48 kHz is the path that actually delivers samples.
    """
    if which("parecord"):
        cmd = ["parecord", "--raw", "--format=s16le", "--channels=1",
               "--rate=48000", "--latency-msec=50"]
        if device:
            cmd.append("--device=" + device)
        return cmd
    cmd = ["parec", "--raw", "--format=s16le", "--channels=1",
           "--rate=48000", "--latency-msec=50"]
    if device:
        cmd.append("--device=" + device)
    return cmd


def level_status(peak, bytes_seen, waited):
    """Label for the live meter. Silence with no bytes is a dead capture."""
    if bytes_seen <= 0 and waited >= 1.2:
        return "No audio from this microphone • click Fix Mic"
    if peak >= .98:
        return "Clipping • lower input volume"
    db = 20 * math.log10(max(peak, .00001))
    if db < -60:
        return "No signal"
    return f"Listening • {db:.0f} dBFS"


if _QT:
    class AudioMeter(QWidget):
       changed = pyqtSignal(float, str)

       def __init__(self, parent=None):
           super().__init__(parent)
           self.setMinimumHeight(24)
           self.setAccessibleName("Live audio input level")
           self.peak = 0
           self.running = False
           self.pending = b""
           self.bytes_seen = 0
           self.started_at = 0
           self.error_text = ""
           self.process = QProcess(self)
           self.process.readyReadStandardOutput.connect(self.read_audio)
           self.process.readyReadStandardError.connect(self.read_error)
           self.process.errorOccurred.connect(lambda *_: self.failed())
           self.process.finished.connect(lambda *_: self.failed() if self.running else None)
           self.decay = QTimer(self)
           self.decay.setInterval(80)
           self.decay.timeout.connect(self.tick)

       def start(self, device=None):
           self.stop()
           self.running = True
           self.pending = b""
           self.bytes_seen = 0
           self.started_at = time.monotonic()
           self.error_text = ""
           argv = meter_command(device)
           self.process.start(argv[0], argv[1:])
           self.decay.start()

       def read_error(self):
           self.error_text += bytes(self.process.readAllStandardError()).decode("utf-8", "replace")

       def failed(self):
           if self.running:
               self.running = False
               self.decay.stop()
               self.peak = 0
               self.update()
               detail = ""
               for line in reversed(self.error_text.splitlines()):
                   if line.strip():
                       detail = line.strip()
                       break
               text = detail or "Audio meter unavailable • check input device"
               self.changed.emit(0, text)

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
           self.changed.emit(0, "Audio idle")

       def read_audio(self):
           data = self.pending + bytes(self.process.readAllStandardOutput())
           size = len(data) // 2 * 2
           self.pending = data[size:]
           if size:
               self.bytes_seen += size
           self.peak = max(self.peak, pcm_peak(data[:size]))

       def tick(self):
           peak = self.peak
           waited = time.monotonic() - self.started_at if self.started_at else 0
           text = level_status(peak, self.bytes_seen, waited)
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
