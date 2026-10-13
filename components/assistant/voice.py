#!/usr/bin/env python3
"""
DevOS AI - offline voice commands.

  Recorder     16 kHz mono 16-bit from the microphone (arecord, or parecord
               on PipeWire), level callback for the on-screen meter, stops on
               request or after SILENCE_STOP_S of silence (simple RMS VAD).
  Transcriber  speech-to-text on this PC with the speech engine package
               (pywhispercpp) and the multilingual base model that ships
               with DevOS in /usr/share/devos/ai/voice/. English and Bangla.

Nothing is downloaded and nothing is sent over the network.
"""

import array
import io
import math
import os
import re
import shutil
import subprocess
import threading
import wave
from typing import Callable, List, Optional, Tuple

RATE = 16000
FRAME_MS = 100
FRAME_BYTES = RATE * 2 * FRAME_MS // 1000      # 16-bit mono
SILENCE_STOP_S = 1.2
MAX_SECONDS = 20
NO_SPEECH_TIMEOUT_S = 6

MODEL_PATH = os.environ.get("DEVOS_VOICE_MODEL", "/usr/share/devos/ai/voice/ggml-base-q5_1.bin")
LANGUAGES = ("bn", "en")        # what voice commands may be in; anything else is retried as English

VOICE_MISSING = "Voice commands aren't set up on this PC yet."


# ---------------------------------------------------------------------------
# VAD
# ---------------------------------------------------------------------------


def rms(samples) -> float:
    """Root mean square of int16 samples (sequence of ints or bytes)."""
    if isinstance(samples, (bytes, bytearray)):
        a = array.array("h")
        a.frombytes(bytes(samples[: len(samples) // 2 * 2]))
        samples = a
    n = len(samples)
    if n == 0:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / n)


def level_0_1(r: float) -> float:
    """Map RMS to a 0..1 meter value on a log scale (speech ~0.5-0.9)."""
    if r <= 1:
        return 0.0
    db = 20 * math.log10(r / 32768.0)      # -90 .. 0 dBFS
    return max(0.0, min(1.0, (db + 60) / 50))


class VAD:
    """Energy VAD with an adaptive noise floor.

    feed(frame) -> True when recording should stop: speech was heard and then
    `silence_s` of silence followed, or nothing was said for `no_speech_s`,
    or `max_s` was reached.
    """

    def __init__(self, frame_ms: int = FRAME_MS, silence_s: float = SILENCE_STOP_S,
                 max_s: float = MAX_SECONDS, no_speech_s: float = NO_SPEECH_TIMEOUT_S,
                 min_threshold: float = 350.0):
        self.frame_s = frame_ms / 1000.0
        self.silence_s = silence_s
        self.max_s = max_s
        self.no_speech_s = no_speech_s
        self.min_threshold = min_threshold
        self.noise = None
        self.elapsed = 0.0
        self.silent_for = 0.0
        self.heard_speech = False
        self.stop_reason = ""

    @property
    def threshold(self) -> float:
        base = (self.noise or 0.0) * 3.0
        return max(self.min_threshold, base)

    def feed(self, frame) -> bool:
        r = rms(frame)
        self.elapsed += self.frame_s
        speech = r >= self.threshold
        if not speech:
            # noise floor follows quiet frames only
            self.noise = r if self.noise is None else (0.9 * self.noise + 0.1 * r)
            self.silent_for += self.frame_s
        else:
            self.heard_speech = True
            self.silent_for = 0.0
        if self.heard_speech and self.silent_for >= self.silence_s:
            self.stop_reason = "silence"
            return True
        if not self.heard_speech and self.elapsed >= self.no_speech_s:
            self.stop_reason = "no-speech"
            return True
        if self.elapsed >= self.max_s:
            self.stop_reason = "max"
            return True
        return False


def frames(pcm: bytes, frame_bytes: int = FRAME_BYTES) -> List[bytes]:
    return [pcm[i:i + frame_bytes] for i in range(0, len(pcm), frame_bytes)]


def synth_tone(seconds: float, amplitude: int, freq: float = 220.0, rate: int = RATE) -> bytes:
    a = array.array("h", (int(amplitude * math.sin(2 * math.pi * freq * i / rate)) for i in range(int(seconds * rate))))
    return a.tobytes()


def pcm_to_wav(pcm: bytes, rate: int = RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


def record_command(which: Callable = shutil.which) -> Optional[List[str]]:
    if which("parecord"):
        return ["parecord", "--raw", "--format=s16le", f"--rate={RATE}", "--channels=1", "--latency-msec=50"]
    if which("arecord"):
        return ["arecord", "-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw"]
    return None


class Recorder:
    """Blocking recorder; run record() in a worker thread, call stop() from the UI."""

    def __init__(self, on_level: Callable[[float], None] = lambda v: None, which: Callable = shutil.which,
                 vad: Optional[VAD] = None):
        self.on_level = on_level
        self.which = which
        self.vad = vad or VAD()
        self._stop = threading.Event()
        self._proc = None

    def stop(self):
        self._stop.set()

    def record(self) -> Tuple[bytes, str]:
        """(pcm, problem)."""
        argv = record_command(self.which)
        if not argv:
            return b"", "No microphone recorder is available on this PC."
        try:
            self._proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError:
            return b"", "I couldn't open the microphone."
        pcm = bytearray()
        try:
            while not self._stop.is_set():
                block = self._proc.stdout.read(FRAME_BYTES)
                if not block:
                    break
                pcm.extend(block)
                self.on_level(level_0_1(rms(block)))
                if self.vad.feed(block):
                    break
        finally:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self.on_level(0.0)
        if not pcm:
            err = b""
            try:
                err = self._proc.stderr.read() or b""
            except Exception:
                pass
            return b"", "No microphone was found." if err else "Nothing was recorded."
        if self.vad.stop_reason == "no-speech":
            return bytes(pcm), "I didn't hear anything. Check that the microphone is on and try again."
        return bytes(pcm), ""


# ---------------------------------------------------------------------------
# Speech to text
# ---------------------------------------------------------------------------


def engine_available() -> bool:
    try:
        import pywhispercpp.model  # noqa: F401
        return True
    except Exception:
        return False


def model_installed(path: str = None) -> bool:
    path = path or MODEL_PATH
    try:
        return os.path.getsize(path) > 1024 * 1024
    except OSError:
        return False


def voice_ready(path: str = None) -> bool:
    """True when voice commands can work: the engine package and the model file are both on this PC."""
    return engine_available() and model_installed(path)


VOICE_UNAVAILABLE_TEXT = "Voice isn't available on this PC: the voice pack or a microphone is missing."
NO_MIC_TEXT = "No microphone found. Plug one in to use voice."
MIC_CHECK_TTL_S = 30.0


def parse_pactl_sources(text: str) -> bool:
    """`pactl list short sources` -> True when a real capture source exists (not just output monitors)."""
    for line in (text or "").splitlines():
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) < 2:
            continue
        if not parts[1].endswith(".monitor"):
            return True
    return False


def parse_arecord_cards(text: str) -> bool:
    """`arecord -l` -> True when at least one capture card is listed."""
    return any(line.startswith("card ") for line in (text or "").splitlines())


def _capture(cmd: List[str], timeout: float = 2.0) -> Optional[str]:
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout,
                           text=True, errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def has_microphone(which: Callable = shutil.which, run: Callable = _capture) -> bool:
    """True when a capture device is found. The sound server is asked first, then the sound cards.
    Without either tool nothing could record anyway, so that counts as no microphone."""
    if which("pactl"):
        out = run(["pactl", "list", "short", "sources"])
        if out is not None:
            return parse_pactl_sources(out)
    if which("arecord"):
        out = run(["arecord", "-l"])
        if out is not None:
            return parse_arecord_cards(out)
        return True             # the card list could not be read: don't block voice on that
    return record_command(which) is not None


class VoiceCheck:
    """voice_ready() plus a microphone check, cached for MIC_CHECK_TTL_S so it can run on every focus."""

    def __init__(self, ready: Callable[[], bool] = None, mic: Callable[[], bool] = None,
                 clock: Callable[[], float] = None, ttl: float = MIC_CHECK_TTL_S):
        import time as _time
        self.ready = ready or voice_ready
        self.mic = mic or has_microphone
        self.clock = clock or _time.monotonic
        self.ttl = ttl
        self._at = None
        self._value = (False, "")

    def status(self, force: bool = False) -> Tuple[bool, str]:
        """(usable, reason): reason is a short user-facing sentence when not usable."""
        now = self.clock()
        if force or self._at is None or now - self._at >= self.ttl:
            if not self.ready():
                self._value = (False, VOICE_UNAVAILABLE_TEXT)
            elif not self.mic():
                self._value = (False, NO_MIC_TEXT)
            else:
                self._value = (True, "")
            self._at = now
        return self._value

    def usable(self, force: bool = False) -> bool:
        return self.status(force)[0]


VOICE_CHECK = VoiceCheck()


def pcm_to_float(pcm: bytes):
    """int16 PCM -> float32 samples in -1..1 (a numpy array; numpy comes with the speech engine)."""
    import numpy as np
    return np.frombuffer(bytes(pcm[: len(pcm) // 2 * 2]), dtype=np.int16).astype(np.float32) / 32768.0


_NOISE = re.compile(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*")       # [BLANK_AUDIO], (music), *cough*
_BENGALI = re.compile(r"[ঀ-৿]")
_OTHER_SCRIPT = re.compile(r"[^\x00-ɏঀ-৿ -⁯\s]")


def clean_segments(segments) -> str:
    text = " ".join((getattr(s, "text", s) or "").strip() for s in segments or [])
    text = _NOISE.sub(" ", text)
    return " ".join(text.split()).strip()


def guess_language(text: str) -> str:
    if _BENGALI.search(text):
        return "bn"
    if _OTHER_SCRIPT.search(text):
        return "other"
    return "en"


class Transcriber:
    """The speech model is loaded once (in the worker thread that first needs it) and kept."""

    _model = None
    _lock = threading.Lock()
    last_language = ""
    n_threads = 0           # 0: as many as useful; the hands-free listener sets a smaller budget

    @classmethod
    def load(cls, path: str = None):
        if cls._model is None:
            from pywhispercpp.model import Model
            threads = cls.n_threads or max(2, min(8, os.cpu_count() or 2))
            cls._model = Model(path or MODEL_PATH, n_threads=threads, redirect_whispercpp_logs_to=None)
        return cls._model

    @classmethod
    def transcribe_as(cls, pcm: bytes, language: str = "en", path: str = None) -> str:
        """Transcribe in a known language (no detection pass: cheaper, used for the wake phrase)."""
        audio = pcm_to_float(pcm)
        with cls._lock:
            model = cls.load(path)
            text = clean_segments(model.transcribe(audio, language=language))
            cls.last_language = language
        return text

    @classmethod
    def detect(cls, model, audio) -> str:
        """Spoken language code, or "" when the engine can't tell us."""
        fn = getattr(model, "auto_detect_language", None)
        if fn is None:
            return ""
        try:
            (lang, _prob), _all = fn(audio)
            return str(lang or "")
        except Exception:
            return ""

    @classmethod
    def transcribe(cls, pcm: bytes, path: str = None) -> str:
        audio = pcm_to_float(pcm)
        with cls._lock:
            model = cls.load(path)
            lang = cls.detect(model, audio)
            if lang in LANGUAGES:
                text = clean_segments(model.transcribe(audio, language=lang))
            elif lang:
                lang = "en"
                text = clean_segments(model.transcribe(audio, language="en"))
            else:
                text = clean_segments(model.transcribe(audio, language="auto"))
                lang = guess_language(text)
                if lang not in LANGUAGES:
                    lang = "en"
                    text = clean_segments(model.transcribe(audio, language="en"))
            cls.last_language = lang
        return text


# Words the small speech model often splits or mishears in commands.
_FIXES = [
    (r"\b(?:can|con|kon) ?fig(?:uration)?\b", "config"),
    (r"\bwhy ?fi\b|\bwi fi\b", "wifi"),
    (r"\bblue ?tooth\b", "bluetooth"),
    (r"\byou ?tube\b", "youtube"),
    (r"\bscreen ?shot\b", "screenshot"),
    (r"\bnote ?pad\b", "notepad"),
    (r"\bgoogle (?:it|that) for\b", "google"),
    (r"\b(?:crome|krome|chrom)\b", "chrome"),
    (r"\bram\b|\bram's\b", "ram"),
]


def fix_transcript(text: str) -> str:
    t = " ".join((text or "").split())
    for pattern, rep in _FIXES:
        t = re.sub(pattern, rep, t, flags=re.I)
    # the speech model ends every sentence with a full stop; it is not part of a dictated note
    t = re.sub(r"(?<!\.)\.$", "", t)
    return t


# ---------------------------------------------------------------------------
# Hands-free: speech segments and the wake phrase
# ---------------------------------------------------------------------------

SEG_FRAME_MS = 30
SEG_FRAME_BYTES = RATE * 2 * SEG_FRAME_MS // 1000      # 960 bytes
SEG_MIN_S = 0.4
SEG_MAX_S = 6.0
SEG_END_SILENCE_S = 0.6
SEG_PREROLL_S = 0.3


class SegmentDetector:
    """Cheap energy VAD on 30 ms frames for always-on listening.

    feed(frame) returns a finished speech segment (bytes, with a little audio
    before the speech) once SEG_END_SILENCE_S of quiet follows it, or None.
    Segments shorter than min_s are dropped (clicks, coughs); a segment is
    cut at max_s so a TV or a long conversation never piles up audio.
    """

    def __init__(self, frame_ms: int = SEG_FRAME_MS, min_s: float = SEG_MIN_S, max_s: float = SEG_MAX_S,
                 end_silence_s: float = SEG_END_SILENCE_S, preroll_s: float = SEG_PREROLL_S,
                 min_threshold: float = 400.0):
        self.frame_s = frame_ms / 1000.0
        self.min_s, self.max_s = min_s, max_s
        self.end_silence_s = end_silence_s
        self.min_threshold = min_threshold
        self.noise = None
        self.pre: List[bytes] = []
        self.pre_n = max(1, int(round(preroll_s / self.frame_s)))
        self.buf: List[bytes] = []
        self.speech_s = 0.0
        self.silent_s = 0.0
        self.active = False
        self.dropped_long = 0

    @property
    def threshold(self) -> float:
        return max(self.min_threshold, (self.noise or 0.0) * 3.0)

    def reset(self):
        self.buf, self.pre = [], []
        self.speech_s = self.silent_s = 0.0
        self.active = False

    def feed(self, frame: bytes) -> Optional[bytes]:
        r = rms(frame)
        loud = r >= self.threshold
        if not self.active:
            if loud:
                self.active = True
                self.buf = list(self.pre) + [frame]
                self.speech_s = self.frame_s
                self.silent_s = 0.0
                self.pre = []
            else:
                self.noise = r if self.noise is None else (0.95 * self.noise + 0.05 * r)
                self.pre.append(frame)
                if len(self.pre) > self.pre_n:
                    self.pre.pop(0)
            return None
        self.buf.append(frame)
        if loud:
            self.speech_s += self.frame_s + self.silent_s
            self.silent_s = 0.0
        else:
            self.silent_s += self.frame_s
        total = len(self.buf) * self.frame_s
        if self.silent_s >= self.end_silence_s or total >= self.max_s:
            seg = b"".join(self.buf)
            long_cut = total >= self.max_s and self.silent_s < self.end_silence_s
            ok = self.speech_s >= self.min_s
            self.reset()
            if long_cut:
                self.dropped_long += 1
            return seg if ok else None
        return None


# "Hey DevOS" and what the small speech model tends to hear instead.
WAKE_GREETINGS = ("hey", "hi", "hay", "hei", "heh", "ok", "okay", "hello", "a", "eh", "yo", "hej", "high")
WAKE_FORMS = ("devos", "devoss", "devo", "devose", "devoes", "devus", "devas", "deevos", "debos", "divos", "thevos",
              "davos", "devops", "devo's", "devohs", "devvos", "deavos", "devils", "devious", "devouts", "devos's",
              "theviews", "deathos")
WAKE_NOT = ("devon", "devil", "seven", "devin", "devine", "eleven", "heaven", "kevin", "davis")


def _wake_tokens(text: str) -> List[Tuple[str, int, int]]:
    return [(m.group(0).lower().replace("'", "").replace("’", ""), m.start(), m.end())
            for m in re.finditer(r"[A-Za-z][A-Za-z'’]*", text or "")]


def _is_devos(compact: str) -> bool:
    if not compact or compact in WAKE_NOT:
        return False
    if compact in WAKE_FORMS:
        return True
    if len(compact) < 4 or not compact.startswith(("d", "th", "b")):
        return False
    # one edit away from "devos" counts (devoz, devos, defos ...)
    a, b = compact, "devos"
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
        prev = cur
    return prev[-1] <= 1


def match_wake(text: str) -> Tuple[bool, str]:
    """(heard the wake phrase, the command said after it - original text, may be '')."""
    toks = _wake_tokens(text)
    if not toks:
        return False, ""
    i = 0
    greeted = False
    while i < len(toks) and i < 2 and toks[i][0] in WAKE_GREETINGS:
        greeted = True
        i += 1
    # the name may be split by the speech model: "dev os", "de vos", "the vos", "dev o s"
    for n in (3, 2, 1):           # the longest reading wins: "devo s" before "devo"
        if i + n > len(toks):
            continue
        compact = "".join(t[0] for t in toks[i:i + n])
        if _is_devos(compact):
            # without a greeting only the exact name counts ("devops pipeline" is not a wake phrase)
            if not greeted and compact not in ("devos", "devoss"):
                return False, ""
            rest = text[toks[i + n - 1][2]:]
            rest = re.sub(r"^[\s,.!?:;'’\-]+", "", rest).strip()
            return True, rest
    return False, ""
