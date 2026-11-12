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
import sys
import threading
import time
import wave
from typing import Callable, Dict, List, Optional, Tuple

RATE = 16000
FRAME_MS = 100
FRAME_BYTES = RATE * 2 * FRAME_MS // 1000      # 16-bit mono
SILENCE_STOP_S = 0.85          # end the utterance soon after the user pauses
MAX_SECONDS = 20
NO_SPEECH_TIMEOUT_S = 5
CALL_SILENCE_STOP_S = 0.55     # pause → auto-send (no manual Send)
CALL_NO_SPEECH_S = 10.0        # wait for the person to start talking
CALL_SPEECH_HOLD_S = 0.12      # brief noise blips ignored; real words kept
CALL_NOISE_MULT = 3.8          # speech above ambient
CALL_MIN_THRESHOLD = 420.0     # laptop mics are often quiet — don't set this too high

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

    feed(frame) -> True when recording should stop. Background noise alone must
    not count as speech — a short sustained hold above threshold is required.
    """

    def __init__(self, frame_ms: int = FRAME_MS, silence_s: float = SILENCE_STOP_S,
                 max_s: float = MAX_SECONDS, no_speech_s: float = NO_SPEECH_TIMEOUT_S,
                 min_threshold: float = 350.0, noise_mult: float = 3.0,
                 speech_hold_s: float = 0.12):
        self.frame_s = frame_ms / 1000.0
        self.silence_s = silence_s
        self.max_s = max_s
        self.no_speech_s = no_speech_s
        self.min_threshold = min_threshold
        self.noise_mult = noise_mult
        self.speech_hold_s = speech_hold_s
        self.noise = None
        self.elapsed = 0.0
        self.silent_for = 0.0
        self.speech_for = 0.0
        self.heard_speech = False
        self.stop_reason = ""

    @property
    def threshold(self) -> float:
        base = (self.noise or 0.0) * self.noise_mult
        return max(self.min_threshold, base)

    def is_speech_frame(self, frame) -> bool:
        return rms(frame) >= self.threshold

    def feed(self, frame) -> bool:
        r = rms(frame)
        self.elapsed += self.frame_s
        speech = r >= self.threshold
        if not speech:
            self.noise = r if self.noise is None else (0.92 * self.noise + 0.08 * r)
            self.silent_for += self.frame_s
            self.speech_for = 0.0
        else:
            self.speech_for += self.frame_s
            self.silent_for = 0.0
            if self.speech_for >= self.speech_hold_s:
                self.heard_speech = True
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


def _preferred_capture_source() -> Optional[str]:
    """Best PipeWire/Pulse capture source name, if the sound server is up."""
    try:
        components = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if components not in sys.path:
            sys.path.insert(0, components)
        from audio.mic_defaults import get_default_source, find_preferred_source
        name = get_default_source()
        if name and not name.endswith(".monitor"):
            return name
        preferred = find_preferred_source()
        if preferred and preferred.get("name"):
            return str(preferred["name"])
    except Exception:
        pass
    if shutil.which("pactl"):
        try:
            out = subprocess.check_output(
                ["pactl", "get-default-source"], text=True, stderr=subprocess.DEVNULL, timeout=2,
            ).strip()
            if out and not out.endswith(".monitor"):
                return out
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def alsa_capture_device(text: str) -> Optional[str]:
    cards = re.findall(r"^card\s+(\d+):[^\n]*?device\s+(\d+):([^\n]*)",
                       text, re.MULTILINE | re.IGNORECASE)
    if not cards:
        return None
    usb_cards = set(re.findall(r"^card\s+(\d+):[^\n]*\busb\b", text, re.MULTILINE | re.IGNORECASE))
    card, device, _ = next((entry for entry in cards if entry[0] in usb_cards), cards[0])
    return f"plughw:{card},{device}"


def record_command(which: Callable = shutil.which, device: Optional[str] = None,
                   run: Optional[Callable] = None) -> Optional[List[str]]:
    if which("parecord"):
        source = device or _preferred_capture_source()
        if source and not source.endswith(".monitor"):
            return ["parecord", f"--device={source}", "--raw", "--format=s16le",
                    f"--rate={RATE}", "--channels=1", "--latency-msec=50"]
    if which("arecord"):
        capture = alsa_capture_device((run or _capture)(["arecord", "-l"]) or "")
        args = ["arecord", "-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw"]
        if capture:
            return [*args, "-D", capture]
        if not which("pactl") and not which("parecord"):
            return args
    return None


class Recorder:
    """Blocking recorder; run record() in a worker thread, call stop() from the UI."""

    def __init__(self, on_level: Callable[[float], None] = lambda v: None, which: Callable = shutil.which,
                 vad: Optional[VAD] = None, call_mode: bool = False):
        self.on_level = on_level
        self.which = which
        if vad is not None:
            self.vad = vad
        elif call_mode:
            self.vad = VAD(
                silence_s=CALL_SILENCE_STOP_S,
                no_speech_s=CALL_NO_SPEECH_S,
                min_threshold=CALL_MIN_THRESHOLD,
                noise_mult=CALL_NOISE_MULT,
                speech_hold_s=CALL_SPEECH_HOLD_S,
            )
        else:
            self.vad = VAD()
        self.call_mode = bool(call_mode)
        self._stop = threading.Event()
        self._proc = None
        self._manual_stop = False
        self.speaking = False          # True only after real speech is confirmed

    def stop(self):
        """Stop capture now. Terminates arecord so a blocked read() wakes up."""
        self._manual_stop = True
        self._stop.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def record(self) -> Tuple[bytes, str]:
        """(pcm, problem)."""
        argv = record_command(self.which)
        if not argv:
            return b"", "No microphone input is ready. Open Sound and check Input."
        try:
            self._proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError:
            return b"", "I couldn't open the microphone."
        pcm = bytearray()
        # Keep a short preroll so hang-up mid-wait still has audio if speech started.
        preroll: List[bytes] = []
        preroll_max = 8   # ~0.8 s
        try:
            while not self._stop.is_set():
                block = self._proc.stdout.read(FRAME_BYTES)
                if not block:
                    break
                if self._stop.is_set():
                    break
                was_speaking = self.vad.heard_speech
                stop_now = self.vad.feed(block)
                r = rms(block)
                # Always capture audio in call mode.
                if self.call_mode:
                    if not self.vad.heard_speech:
                        preroll.append(block)
                        if len(preroll) > preroll_max:
                            preroll.pop(0)
                        # Soft meter: show relative energy so the user sees the mic works.
                        thr = max(1.0, self.vad.threshold)
                        self.on_level(max(0.0, min(1.0, (r / thr) * 0.45)))
                    else:
                        if not was_speaking:
                            self.speaking = True
                            pcm = bytearray(b"".join(preroll))
                            preroll = []
                        pcm.extend(block)
                        thr = max(1.0, self.vad.threshold)
                        self.on_level(max(0.0, min(1.0, r / thr)))
                else:
                    pcm.extend(block)
                    self.on_level(level_0_1(r))
                if stop_now:
                    break
        finally:
            try:
                if self._proc.poll() is None:
                    self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self.on_level(0.0)
        # Manual stop before VAD locked on speech: use preroll + whatever we have.
        if self._manual_stop and not pcm and preroll:
            pcm = bytearray(b"".join(preroll))
        if not pcm:
            err = b""
            try:
                err = self._proc.stderr.read() or b""
            except Exception:
                pass
            return b"", "The microphone could not be opened. Check Sound → Input or close other apps using it." if err else "Nothing was recorded."
        # Manual stop: always try to understand whatever was captured.
        if self._manual_stop and len(pcm) >= FRAME_BYTES * 2:
            return bytes(pcm), ""
        if self.vad.stop_reason == "no-speech" and not self.vad.heard_speech:
            return bytes(pcm), "I didn't hear anything. Speak closer to the mic, then pause — or tap ■ when done."
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
    If pactl is up but only lists monitors (USB mic not in PipeWire yet), fall through to arecord.
    Without either tool nothing could record anyway, so that counts as no microphone."""
    if which("pactl"):
        out = run(["pactl", "list", "short", "sources"])
        if out is not None and parse_pactl_sources(out):
            return True
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
# Whisper often invents these on silence / noise when forced to a language.
_HALLUCINATION = re.compile(
    r"(?:thank you(?: for watching)?|thanks for watching|please subscribe|"
    r"i am the one who has been born|"
    r"字幕由|amara\.org|"
    r"^[\s\"'“”]*you[\s\"'“”.]*$|"
    r"^[\s\"'“”]*(?:the end|null|bye)[\s\"'“”.]*$)",
    re.I,
)


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


def _bn_score(text: str) -> int:
    """Higher = more likely real Bangla speech (not English hallucination)."""
    t = (text or "").strip()
    if not t or _HALLUCINATION.search(t):
        return -100
    bn = len(_BENGALI.findall(t))
    latin = len(re.findall(r"[A-Za-z]", t))
    if bn == 0:
        return -5 if latin > 8 else 0
    return bn * 3 - max(0, latin - 2)


def _en_score(text: str) -> int:
    t = (text or "").strip()
    if not t or _HALLUCINATION.search(t):
        return -100
    if _BENGALI.search(t):
        return len(t) // 2
    latin = len(re.findall(r"[A-Za-z]", t))
    return latin if latin >= 2 else -5


def _preferred_stt_language() -> str:
    """User voice setting: 'bn' / 'en' / 'auto'."""
    try:
        import voice_prefs
        pref = voice_prefs.tts_language_pref()
        if pref in ("bn", "en"):
            return pref
    except Exception:
        pass
    return "auto"


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
            if text and _HALLUCINATION.search(text):
                text = ""
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
    def _pick_bn_en(cls, model, audio, prefer: str = "auto") -> Tuple[str, str]:
        """Run bn + en passes and keep the better transcript (Bangla daily speech)."""
        bn_text = clean_segments(model.transcribe(audio, language="bn"))
        en_text = clean_segments(model.transcribe(audio, language="en"))
        if bn_text and _HALLUCINATION.search(bn_text):
            bn_text = ""
        if en_text and _HALLUCINATION.search(en_text):
            en_text = ""
        bn_s, en_s = _bn_score(bn_text), _en_score(en_text)
        if prefer == "bn":
            bn_s += 4
        elif prefer == "en":
            en_s += 4
        if bn_s > en_s and bn_text:
            return bn_text, "bn"
        if en_text:
            return en_text, "en"
        if bn_text:
            return bn_text, "bn"
        return "", prefer if prefer in LANGUAGES else "en"

    @classmethod
    def transcribe(cls, pcm: bytes, path: str = None) -> str:
        audio = pcm_to_float(pcm)
        prefer = _preferred_stt_language()
        sticky = cls.last_language if cls.last_language in LANGUAGES else ""
        with cls._lock:
            model = cls.load(path)

            def _one(language: str) -> str:
                text = clean_segments(model.transcribe(audio, language=language))
                if text and _HALLUCINATION.search(text):
                    return ""
                return text

            # Forced language from Voice settings — single pass first (dual only if empty).
            if prefer in ("bn", "en"):
                text = _one(prefer)
                if text:
                    cls.last_language = prefer
                    return text
                text, lang = cls._pick_bn_en(model, audio, prefer=prefer)
                cls.last_language = lang
                return text

            # Call / follow-up turns: reuse last language (avoids dual bn+en every time).
            if sticky:
                text = _one(sticky)
                if text:
                    cls.last_language = sticky
                    return text

            lang = cls.detect(model, audio)
            # Tiny models often mis-label Bangla as hi/ur/as/en — dual-pass when unsure.
            if lang in ("bn", "hi", "as", "ur", "ne") or lang not in LANGUAGES:
                text, lang = cls._pick_bn_en(model, audio, prefer="auto")
            elif lang == "en":
                # First English pass only; dual-pass if that came up empty.
                text = _one("en")
                if text:
                    lang = "en"
                else:
                    text, lang = cls._pick_bn_en(model, audio, prefer="en")
            else:
                text = clean_segments(model.transcribe(audio, language="auto"))
                if text and _HALLUCINATION.search(text):
                    text = ""
                lang = guess_language(text) if text else "en"
                if lang not in LANGUAGES:
                    text, lang = cls._pick_bn_en(model, audio, prefer="auto")
            cls.last_language = lang if lang in LANGUAGES else "en"
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
SEG_MIN_S = 0.28          # short wake "Mira" must still form a segment
SEG_MAX_S = 6.0
SEG_END_SILENCE_S = 0.45  # hang up the segment sooner so wake feels instant
SEG_PREROLL_S = 0.35


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



def form_transcript(text: str) -> str:
    """Compat alias — prefer fix_transcript."""
    return fix_transcript(text)

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


def match_wake(text: str, wake_name: Optional[str] = None) -> Tuple[bool, str]:
    """(heard the wake phrase, the command said after it).

    Default wake name is **Mira** (configurable in DevOS AI settings / installer).
    Legacy “Hey DevOS” still works.
    """
    try:
        import voice_prefs
        return voice_prefs.match_wake_name(text, wake_name or voice_prefs.wake_name())
    except Exception:
        pass
    # Fallback: legacy DevOS matching if prefs unavailable
    toks = _wake_tokens(text)
    if not toks:
        return False, ""
    i = 0
    greeted = False
    while i < len(toks) and i < 2 and toks[i][0] in WAKE_GREETINGS:
        greeted = True
        i += 1
    for n in (3, 2, 1):
        if i + n > len(toks):
            continue
        compact = "".join(t[0] for t in toks[i:i + n])
        if _is_devos(compact):
            if not greeted and compact not in ("devos", "devoss"):
                return False, ""
            rest = text[toks[i + n - 1][2]:]
            rest = re.sub(r"^[\s,.!?:;'’\-]+", "", rest).strip()
            return True, rest
    return False, ""


# ---------------------------------------------------------------------------
# Spoken replies (voice in → speak the answer; typed action commands stay quiet)
# ---------------------------------------------------------------------------

_TTS_VENV = os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share"),
    "devos", "tts-venv",
)
_TTS_CACHE = os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"),
    "devos", "assistant-tts",
)
# Gender-aware voices live in voice_prefs; keep a tiny fallback map here.
_EDGE_VOICES = {"bn": "bn-BD-NabanitaNeural", "en": "en-US-JennyNeural"}


def _edge_voice_for(language: str) -> str:
    try:
        import voice_prefs
        return voice_prefs.edge_voice_id(language)
    except Exception:
        return _EDGE_VOICES.get(language, _EDGE_VOICES["en"])

# Tool actions that just do something on screen — no chat bubble when typed,
# and no spoken reply (the open window / search is the feedback).
SILENT_ACTIONS = frozenset((
    "web_search", "open_url", "open_app", "open_folder", "open_settings", "open_tool",
    "open_path", "close_app", "media", "volume", "brightness", "lock", "screenshot",
    "type_text", "open_app_and_type", "social_post", "write_note", "create_folder",
    "uninstall", "compose_email", "power", "reminder",
))


def reply_language(text: str) -> str:
    """bn if the answer is mostly Bangla script, else en."""
    s = text or ""
    bn = sum(1 for ch in s if "\u0980" <= ch <= "\u09FF")
    latin = sum(1 for ch in s if ("A" <= ch <= "Z") or ("a" <= ch <= "z"))
    return "bn" if bn >= max(8, latin // 2) else "en"


def plain_for_speech(md: str, limit: int = 480) -> str:
    """Strip markdown so TTS does not read stars and links aloud."""
    text = md or ""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*`#_>~]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0]
    return text


# Spoken replies: prefer full sentences end-to-end. Starting after one word caused
# stop–start gaps and dropped middle sentences when prefetch was abandoned.
_TTS_RATE = "+0%"              # natural human pace (do not speed up)
_GAP_BRIDGE_S = 0.35           # short handoff while next sentence finishes synth
_FIRST_CHUNK_MIN = 48          # first spoken unit ≈ a short clause, not one word
_FIRST_WORDS = 10              # wait for a natural phrase before the first cut
_CHUNK_SOFT_MIN = 40
_PLAY_PROCS: List["subprocess.Popen"] = []
_PLAY_LOCK = threading.Lock()
_WARM_STARTED = False
_FFPLAY_FAST = [
    "ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet",
    "-fflags", "nobuffer", "-flags", "low_delay",
    "-probesize", "32", "-analyzeduration", "0",
]
# Short greetings with end punctuation may start immediately ("Hi!", "Sure.").
_OPENER_RE = re.compile(
    r"^(Sure|Okay|OK|Yes|Yeah|Yep|Hi|Hello|Hey|Alright|Of course|Absolutely|"
    r"Right|Got it|No problem|Thanks|Thank you|Please|Well|"
    r"হ্যাঁ|জি|আচ্ছা|ঠিক আছে|হ্যালো|নমস্কার|জি\s*আচ্ছা)"
    r"([.!।؟])(?:\s+|$)",
    re.IGNORECASE | re.UNICODE,
)


def ensure_tts_venv() -> bool:
    """Create ~/.local/share/devos/tts-venv with edge-tts when missing (once).

    Without this, voice-call replies fall back to espeak (or stay silent if
    ffplay/espeak are unavailable). Chat call mode needs this for neural TTS.
    """
    py = os.path.join(_TTS_VENV, "bin", "python")
    if os.path.isfile(py):
        return True
    if not shutil.which("python3"):
        return False
    try:
        subprocess.run(
            ["python3", "-m", "venv", _TTS_VENV],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, check=True,
        )
        pip = os.path.join(_TTS_VENV, "bin", "pip")
        subprocess.run(
            [pip, "install", "-q", "edge-tts>=6.1.0"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300, check=True,
        )
        return os.path.isfile(py)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def warm_tts(language: str = "en") -> None:
    """Start the edge-tts worker early (app open / mic ready) so the first reply is snappy."""
    global _WARM_STARTED
    _WARM_STARTED = True

    def _warm():
        ensure_tts_venv()
        _EdgePool.warm(language if language in ("en", "bn") else "en")

    threading.Thread(target=_warm, daemon=True, name="devos-tts-warm").start()


def _stop_speech():
    """Stop only DevOS TTS players we started — avoid racing our own next phrase."""
    with _PLAY_LOCK:
        procs = list(_PLAY_PROCS)
        _PLAY_PROCS.clear()
    for proc in procs:
        try:
            proc.terminate()
        except OSError:
            pass
    for proc in procs:
        try:
            proc.wait(timeout=1.5)
        except Exception:
            try:
                proc.kill()
            except OSError:
                pass
    # Leftover players from older builds / crashed trackers
    if shutil.which("pkill"):
        subprocess.run(
            ["pkill", "-f", "ffplay.*devos-assistant-tts"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for name in ("espeak-ng", "espeak", "spd-say"):
            subprocess.run(["pkill", "-x", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class _EdgePool:
    """One long-lived edge-tts Python so each phrase skips cold import + TLS."""

    _lock = threading.Lock()
    _proc: Optional[subprocess.Popen] = None
    _writer_lock = threading.Lock()

    _WORKER = r"""
import asyncio, sys, edge_tts
async def one(text, voice, out, rate):
    await edge_tts.Communicate(text, voice, rate=rate).save(out)
def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.rstrip("\n")
        if not line:
            continue
        try:
            out, voice, rate, text = line.split("\t", 3)
        except ValueError:
            sys.stdout.write("ERR\n"); sys.stdout.flush(); continue
        try:
            asyncio.run(one(text, voice, out, rate))
            ok = "OK" if __import__("os").path.isfile(out) else "ERR"
        except Exception:
            ok = "ERR"
        sys.stdout.write(ok + "\n"); sys.stdout.flush()
if __name__ == "__main__":
    main()
"""

    @classmethod
    def _python(cls) -> Optional[str]:
        py = os.path.join(_TTS_VENV, "bin", "python")
        return py if os.path.isfile(py) else None

    @classmethod
    def ensure(cls) -> bool:
        with cls._lock:
            if cls._proc is not None and cls._proc.poll() is None:
                return True
            need_venv = not cls._python()
        if need_venv:
            ensure_tts_venv()
        with cls._lock:
            if cls._proc is not None and cls._proc.poll() is None:
                return True
            py = cls._python()
            if not py:
                return False
            try:
                cls._proc = subprocess.Popen(
                    [py, "-c", cls._WORKER],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                )
                return True
            except OSError:
                cls._proc = None
                return False

    @classmethod
    def warm(cls, language: str = "en"):
        """Fire a tiny synthesis so the first real phrase is warm."""
        if not cls.ensure():
            return
        os.makedirs(_TTS_CACHE, exist_ok=True)
        out = os.path.join(_TTS_CACHE, "devos-assistant-tts-warm.mp3")
        cls.synthesize(".", language, out, timeout=20)

    @classmethod
    def synthesize(cls, text: str, language: str, out: str, rate: str = _TTS_RATE,
                   timeout: float = 45) -> bool:
        if not text or not text.strip():
            return False
        if not cls.ensure() or cls._proc is None or cls._proc.stdin is None or cls._proc.stdout is None:
            return False
        voice_name = _edge_voice_for(language)
        # Tabs separate fields; strip tabs/newlines from spoken text.
        safe = (text or "").replace("\t", " ").replace("\n", " ").strip()
        payload = "%s\t%s\t%s\t%s\n" % (out, voice_name, rate, safe)
        with cls._writer_lock:
            try:
                if cls._proc.poll() is not None:
                    cls._proc = None
                    if not cls.ensure() or cls._proc is None:
                        return False
                cls._proc.stdin.write(payload)
                cls._proc.stdin.flush()
                # Read OK/ERR
                deadline = __import__("time").time() + timeout
                while __import__("time").time() < deadline:
                    line = cls._proc.stdout.readline()
                    if not line:
                        break
                    if line.strip() == "OK":
                        return os.path.isfile(out) and os.path.getsize(out) > 0
                    if line.strip() == "ERR":
                        return False
            except (OSError, BrokenPipeError, ValueError):
                try:
                    if cls._proc is not None:
                        cls._proc.kill()
                except Exception:
                    pass
                cls._proc = None
                return False
        return False

    @classmethod
    def shutdown(cls):
        with cls._lock:
            if cls._proc is not None:
                try:
                    if cls._proc.stdin:
                        cls._proc.stdin.close()
                    cls._proc.kill()
                except Exception:
                    pass
                cls._proc = None


def _speak_edge(text: str, language: str, out: Optional[str] = None, rate: str = _TTS_RATE) -> bool:
    if not shutil.which("ffplay"):
        return False
    os.makedirs(_TTS_CACHE, exist_ok=True)
    out = out or os.path.join(_TTS_CACHE, "devos-assistant-tts.mp3")
    if not _EdgePool.synthesize(text, language, out, rate=rate):
        return False
    return _play_file(out)


def speak_reply(text: str, language: Optional[str] = None, stop_first: bool = True) -> None:
    """Speak an assistant answer fully (blocking). Prefetches the next sentence."""
    plain = plain_for_speech(text)
    if not plain:
        return
    if language in ("en", "bn"):
        lang = language
    else:
        try:
            import voice_prefs
            lang = voice_prefs.resolve_reply_language(None, plain)
        except Exception:
            lang = reply_language(plain)
    if stop_first:
        _stop_speech()
    # Build sentence list, then play with one-ahead synthesis to hide .!? gaps.
    chunks: List[str] = []
    cursor = 0
    first = True
    while cursor < len(plain):
        chunk, advance = _next_speak_cut(plain[cursor:], force=False, first=first)
        if not chunk or advance <= 0:
            tail = plain[cursor:].strip()
            if tail:
                chunks.append(tail)
            break
        chunks.append(chunk)
        cursor += advance
        first = False
    if not chunks:
        return
    next_path: Optional[str] = None
    for i, chunk in enumerate(chunks):
        path = next_path
        next_path = None
        # Prefetch following sentence while this one plays (hides .!? gaps).
        th = None
        box: Dict[str, object] = {}
        out = ""
        if i + 1 < len(chunks):
            nxt = chunks[i + 1]
            out = os.path.join(
                _TTS_CACHE,
                "devos-assistant-tts-sr-%d.mp3" % (int(time.time() * 1000) % 100000000 + i),
            )

            def _pre(n=nxt, o=out):
                box["item"] = n
                box["ok"] = _synthesize_to_file(n, lang, o)
                if box["ok"]:
                    box["path"] = o

            th = threading.Thread(target=_pre, daemon=True)
            th.start()
        if path and _play_file(path):
            pass
        else:
            _speak_chunk(chunk, lang, edge_wait_s=12.0 if i == 0 else 20.0)
        if th is not None:
            _wait_prefetch(box, th, _GAP_BRIDGE_S)
            next_path = box.get("path")  # type: ignore
            if not next_path and box.get("ok"):
                next_path = out


def _next_speak_cut(pending: str, force: bool = False, first: bool = False) -> Tuple[str, int]:
    """Return (ready_chunk, advance) — advance is how many chars of pending were consumed.

    Prefer full sentences so DevOS AI speaks end-to-end. Never cut after a single
    word while more text is still arriving (that caused stop–start speech).
    """
    pending = pending or ""
    if not pending.strip():
        return "", 0

    # Sentence / line end — speak a complete sentence as soon as it lands.
    m = re.search(r"[.!?।؟](?:\s+|$)|[\n]", pending)
    if m and m.end() >= 3:
        cut = m.end()
        if cut > 220:
            for sep in (", ", "; ", " — ", " এবং "):
                idx = pending.find(sep, 80, 200)
                if idx >= 80:
                    cut = idx + len(sep)
                    break
            else:
                idx = pending.rfind(" ", 100, 200)
                if idx >= 100:
                    cut = idx + 1
        chunk = pending[:cut].strip()
        return (chunk, cut) if chunk else ("", 0)

    # First audio: short punctuated greeting only, or a full short clause —
    # never the first word alone.
    if first:
        opener = _OPENER_RE.match(pending)
        if opener and opener.end() >= 2:
            cut = opener.end()
            while cut < len(pending) and pending[cut].isspace():
                cut += 1
            chunk = pending[:cut].strip()
            if chunk:
                return chunk, cut
        words = pending.split()
        if len(words) >= _FIRST_WORDS and len(pending.strip()) >= _FIRST_CHUNK_MIN:
            take = words[:_FIRST_WORDS]
            pattern = r"\s+".join(re.escape(w) for w in take)
            mm = re.search(pattern, pending)
            if mm:
                cut = mm.end()
                if cut < len(pending) and pending[cut:cut + 1] in ",;":
                    cut += 1
                while cut < len(pending) and pending[cut].isspace():
                    cut += 1
                chunk = pending[:cut].strip()
                if chunk:
                    return chunk, cut
        # Whole short reply already on screen (no more text coming yet / force).
        stripped = pending.strip()
        if force and 2 <= len(stripped) <= 80:
            return stripped, len(pending)
        if 2 <= len(stripped) <= 40 and re.match(
            r"^[\w\u0980-\u09FF][\w\u0980-\u09FF'’\- ]*[.!?।؟]$", stripped
        ):
            return stripped, len(pending)

    # Mid-sentence comma breaks only for long clauses (fewer cuts ⇒ fewer gaps).
    if len(pending) >= 140:
        for sep in (", ", "; ", " — ", " এবং "):
            idx = pending.find(sep, 80, 180)
            if idx >= 80:
                cut = idx + len(sep)
                chunk = pending[:cut].strip()
                return (chunk, cut) if chunk else ("", 0)

    if force and len(pending.strip()) >= 4:
        return pending.strip(), len(pending)
    return "", 0


def _synthesize_to_file(text: str, language: str, out: str, rate: str = _TTS_RATE) -> bool:
    """Write neural TTS audio to out via the warm edge-tts worker."""
    os.makedirs(_TTS_CACHE, exist_ok=True)
    return _EdgePool.synthesize(text, language, out, rate=rate)


def _track_proc(proc: "subprocess.Popen") -> "subprocess.Popen":
    with _PLAY_LOCK:
        _PLAY_PROCS.append(proc)
    return proc


def _untrack_proc(proc: "subprocess.Popen") -> None:
    with _PLAY_LOCK:
        try:
            _PLAY_PROCS.remove(proc)
        except ValueError:
            pass


def _play_file(path: str) -> bool:
    """Play an mp3 to the end. Does not kill the next queued phrase."""
    if not path or not os.path.isfile(path) or os.path.getsize(path) < 32:
        return False
    if not shutil.which("ffplay"):
        return False
    try:
        proc = _track_proc(subprocess.Popen(
            _FFPLAY_FAST + [path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ))
        try:
            proc.wait(timeout=180)
            return proc.returncode == 0 or proc.returncode is None
        except subprocess.TimeoutExpired:
            proc.kill()
            return False
        finally:
            _untrack_proc(proc)
    except OSError:
        return False


def _wait_prefetch(box: Dict[str, object], thread: threading.Thread,
                   max_wait_s: float = _GAP_BRIDGE_S) -> None:
    """After a phrase ends, wait briefly for the next file — avoid long silence gaps."""
    deadline = time.time() + max(0.05, max_wait_s)
    while time.time() < deadline:
        if "path" in box or box.get("item") not in (None, "__pending__") or "ok" in box:
            break
        thread.join(timeout=0.02)
    item = box.get("item", "__pending__")
    # Next sentence known but mp3 still cooking — give synth a short bridge window.
    if item not in (None, "__none__", "__pending__") and "path" not in box:
        extra = time.time() + min(0.9, max_wait_s + 0.5)
        while time.time() < extra and "path" not in box and box.get("ok") is not False:
            thread.join(timeout=0.02)
    elif "ok" in box and box.get("ok") and "path" not in box:
        # speak_reply sets ok/path without always setting item first
        extra = time.time() + min(0.9, max_wait_s + 0.5)
        while time.time() < extra and "path" not in box:
            thread.join(timeout=0.02)
    thread.join(timeout=0.01)


def _speak_espeak(text: str, language: str) -> bool:
    bin_name = "espeak-ng" if shutil.which("espeak-ng") else ("espeak" if shutil.which("espeak") else None)
    if not bin_name:
        return False
    voice = "bn" if language == "bn" else "en"
    # Natural pace a ~10-year-old can follow (not rushed).
    speed = "145" if language == "bn" else "155"
    try:
        proc = _track_proc(subprocess.Popen(
            [bin_name, "-v", voice, "-s", speed, "-g", "4", text],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ))
        try:
            proc.wait(timeout=120)
            return True
        except subprocess.TimeoutExpired:
            proc.kill()
            return False
        finally:
            _untrack_proc(proc)
    except OSError:
        return False


_STREAM_EDGE = r"""
import asyncio, sys, edge_tts
async def main():
    text, voice, rate = sys.argv[1], sys.argv[2], sys.argv[3]
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            sys.stdout.buffer.write(chunk["data"])
            sys.stdout.buffer.flush()
asyncio.run(main())
"""


def _speak_stream_edge(text: str, language: str) -> bool:
    """Pipe neural audio to ffplay as it arrives — sound starts before the file is finished."""
    plain = (text or "").strip()
    if not plain or not shutil.which("ffplay"):
        return False
    py = _EdgePool._python()
    if not py:
        return False
    voice_name = _edge_voice_for(language)
    try:
        edge = subprocess.Popen(
            [py, "-c", _STREAM_EDGE, plain, voice_name, _TTS_RATE],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if edge.stdout is None:
            edge.kill()
            return False
        ff = _track_proc(subprocess.Popen(
            _FFPLAY_FAST + ["-f", "mp3", "-i", "pipe:0"],
            stdin=edge.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ))
        edge.stdout.close()
        try:
            rc = ff.wait(timeout=180)
        except subprocess.TimeoutExpired:
            ff.kill()
            edge.kill()
            return False
        finally:
            _untrack_proc(ff)
        try:
            edge.wait(timeout=8)
        except subprocess.TimeoutExpired:
            edge.kill()
        return rc == 0
    except OSError:
        return False


def _speak_chunk(text: str, language: str, out: Optional[str] = None,
                 edge_wait_s: float = 45.0) -> bool:
    """Speak one phrase ASAP so voice tracks live typing — never skip text."""
    plain = (text or "").strip()
    if not plain:
        return True
    os.makedirs(_TTS_CACHE, exist_ok=True)
    path = out or os.path.join(_TTS_CACHE, "devos-assistant-tts-%d.mp3" % (int(time.time() * 1000) % 100000000))

    # Warm edge-tts worker first (already imported + TLS). Spawning a fresh
    # Python for live stream was adding 1–3s — voice then started after typing.
    box: Dict[str, object] = {}

    def _edge():
        box["ok"] = _synthesize_to_file(plain, language, path)

    th = threading.Thread(target=_edge, daemon=True)
    th.start()
    # Short clauses: wait a bit for warm-pool mp3; longer sentences get more time.
    # Avoid bouncing to live-stream after one word — that caused stop–start gaps.
    brief = 0.75 if len(plain) < 140 else min(edge_wait_s, 10.0)
    deadline = time.time() + brief
    while time.time() < deadline:
        if box.get("ok"):
            break
        th.join(timeout=0.03)
    if box.get("ok") and _play_file(path):
        return True
    # Live stream overlaps remaining synth — including short first call chunks.
    if _speak_stream_edge(plain, language):
        return True
    if not box.get("ok"):
        th.join(timeout=max(1.0, min(edge_wait_s, 6.0)))
    if box.get("ok") and _play_file(path):
        return True
    return _speak_espeak(plain, language)


class StreamSpeaker:
    """Speak while the answer is still streaming — full sentences, no cut-offs.

    Warm edge-tts worker + sentence-sized chunks. Every queued phrase is spoken
    to the end (neural, or local espeak fallback). finish() flushes the tail.
    """

    def __init__(self):
        self._plain = ""
        self._cursor = 0
        self._lang = "en"
        self._q: Optional["queue.Queue[Optional[str]]"] = None
        self._thread: Optional[threading.Thread] = None
        self._seq = 0
        self._active = False
        self.used = False
        self._first_chunk = True
        self._lock = threading.Lock()

    def start(self, language: Optional[str] = None):
        self.stop(kill_audio=False)
        import queue
        self._plain = ""
        self._cursor = 0
        self._lang = language or "en"
        self._q = queue.Queue()
        self._seq = 0
        self._active = True
        self.used = True
        self._first_chunk = True
        warm_tts(self._lang)
        self._thread = threading.Thread(target=self._worker, daemon=True, name="devos-tts-stream")
        self._thread.start()

    def feed_delta_total(self, full_stream_md: str):
        if not self._active or self._q is None:
            return
        plain = plain_for_speech(full_stream_md, limit=4000)
        if not plain:
            return
        with self._lock:
            if self._lang == "en" and reply_language(plain) == "bn":
                self._lang = "bn"
            self._plain = plain
            if self._cursor > len(self._plain):
                self._cursor = 0
            while True:
                pending = self._plain[self._cursor:]
                chunk, advance = _next_speak_cut(pending, force=False, first=self._first_chunk)
                if not chunk or advance <= 0:
                    break
                self._q.put(chunk)
                self._first_chunk = False
                self._cursor += advance

    def finish(self):
        if not self._active or self._q is None:
            return
        with self._lock:
            leftover = self._plain[self._cursor:].strip()
            if leftover:
                self._q.put(leftover)
                self._cursor = len(self._plain)
        self._q.put(None)
        if self._thread is not None:
            self._thread.join(timeout=240)
        self._active = False
        self._thread = None
        self._q = None

    def stop(self, kill_audio: bool = True):
        self._active = False
        if kill_audio:
            _stop_speech()
        q = self._q
        if q is not None:
            try:
                while True:
                    q.get_nowait()
            except Exception:
                pass
            try:
                q.put_nowait(None)
            except Exception:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None
        self._q = None
        self._plain = ""
        self._cursor = 0

    def _worker(self):
        """Speak every queued sentence in order; prefetch next audio during playback.

        Never abandon an in-flight queue read — that stole middle sentences when the
        first short chunk finished before the next sentence was queued.
        """
        import queue as _queue
        q = self._q
        if q is None:
            return

        def synth_path(text: str) -> Optional[str]:
            path = os.path.join(_TTS_CACHE, "devos-assistant-tts-%d.mp3" % self._seq)
            self._seq += 1
            return path if _synthesize_to_file(text, self._lang, path) else None

        current: Optional[str] = None
        current_path: Optional[str] = None
        first = True
        while self._active:
            if current is None:
                try:
                    current = q.get(timeout=120)
                except _queue.Empty:
                    break
                if current is None:
                    break
                current_path = None

            nxt_box: Dict[str, object] = {}

            def prefetch():
                # Block until the next sentence (or finish sentinel) is queued.
                try:
                    nxt = q.get(timeout=240)
                except _queue.Empty:
                    nxt_box["item"] = "__none__"
                    return
                nxt_box["item"] = nxt
                if nxt is not None:
                    nxt_box["path"] = synth_path(nxt)

            th = threading.Thread(target=prefetch, daemon=True)
            th.start()
            # Prefer prefetched mp3; otherwise synthesize/stream this sentence fully.
            if current_path and _play_file(current_path):
                first = False
            else:
                _speak_chunk(current, self._lang, edge_wait_s=12.0 if first else 20.0)
                first = False

            # Wait until prefetch has taken the next queue item. Abandoning early
            # let the orphan thread consume sentence N+1 while we skipped to N+2.
            while self._active and "item" not in nxt_box:
                th.join(timeout=0.05)
            if not self._active:
                break
            _wait_prefetch(nxt_box, th, _GAP_BRIDGE_S)

            nxt = nxt_box.get("item", "__none__")
            if nxt == "__none__":
                current = current_path = None
                continue
            if nxt is None:
                break
            current = nxt  # type: ignore
            current_path = nxt_box.get("path")  # type: ignore
            # Missing path → next loop uses _speak_chunk (never skip the text).

