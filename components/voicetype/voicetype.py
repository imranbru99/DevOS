#!/usr/bin/env python3
"""
DevOS Voice Typing - dictate into any app, like Win+H on Windows.

    voicetype.py            Toggle (the Meta+Alt+H shortcut). The first press
                            shows a small mic pill at the bottom of the screen
                            and starts listening; every pause in speech is
                            turned into text and typed into the app that has
                            the keyboard focus. Pressing the shortcut again
                            (or the x on the pill) finishes.
    voicetype.py --stop     Finish a running session (same as a second press).

Everything runs on this PC: recording and speech-to-text reuse the DevOS AI
voice engine (components/assistant/voice.py, offline whisper model), and the
optional "Clean up with AI" step uses the local DevOS AI model.

Typing: plain ASCII text is typed with `xdotool type`; text with Bangla or
other non-ASCII characters is pasted (clipboard + Ctrl+V, Ctrl+Shift+V in
terminals) because xdotool type can mangle complex scripts. The previous
clipboard text is put back afterwards.

Spoken punctuation: "comma", "full stop", "question mark", "new line",
"new paragraph", ... and in Bangla "দাঁড়ি", "কমা", "নতুন লাইন", ...

The pill never takes the keyboard focus, so typing goes to the app the user
was working in. PyQt5 is imported only when the pill is shown, so the text
logic below is testable without a display.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from typing import Callable, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
COMPONENTS = os.path.dirname(HERE)
ASSISTANT_DIR = os.path.join(COMPONENTS, "assistant")
for _p in (HERE, ASSISTANT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import voice  # noqa: E402  (the DevOS AI recorder + offline speech-to-text)

APP_NAME = "Voice Typing"
HOTKEY = "Meta+Alt+H"
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".config", "devos", "voicetype.json")
LOCK_NAME = "devos-voicetype.lock"
STOP_FLAG = "devos-voicetype-stop"

LANG_CHOICES = ("auto", "en", "bn")
LANG_LABELS = {"auto": "Auto", "en": "English", "bn": "বাংলা"}

# Dictation pauses are longer than voice commands: people think between sentences.
DICTATION_SILENCE_S = 1.6
DICTATION_MAX_S = 45
DICTATION_NO_SPEECH_S = 10

AI_CLEANUP_LABEL = "Clean up with AI"
AI_CLEANUP_TIP = ("DevOS AI fixes punctuation and grammar before the text is typed. "
                  "It runs on this PC; nothing is sent anywhere.")

NO_XDOTOOL_TEXT = "Voice typing needs the xdotool package to type into other apps."
NOTHING_HEARD = "I didn't hear anything. Check the microphone and try again."

DEFAULT_CONFIG = {"language": "auto", "ai_cleanup": False}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def load_config(path: str = None) -> dict:
    path = path or CONFIG_PATH
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            if data.get("language") in LANG_CHOICES:
                cfg["language"] = data["language"]
            cfg["ai_cleanup"] = bool(data.get("ai_cleanup", False))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(path: str = None, **updates) -> dict:
    path = path or CONFIG_PATH
    cfg = load_config(path)
    cfg.update({k: v for k, v in updates.items() if k in DEFAULT_CONFIG})
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=1, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass
    return cfg


def next_language(lang: str) -> str:
    i = LANG_CHOICES.index(lang) if lang in LANG_CHOICES else 0
    return LANG_CHOICES[(i + 1) % len(LANG_CHOICES)]


# ---------------------------------------------------------------------------
# Spoken punctuation
# ---------------------------------------------------------------------------

# kind: "end"   attaches to the word before it ("hello comma" -> "hello,")
#       "open"  attaches to the word after it ("open bracket note" -> "(note")
#       "break" line breaks (spaces around them are dropped)
# A trailing "$" in the phrase means: only at the end of a sentence, so
# "a period of time" stays as it is but "that's all period" becomes "that's all."
_EN_COMMANDS = [
    ("new paragraph", "\n\n", "break"),
    ("new line|next line|newline", "\n", "break"),
    ("full stop", ".", "end"),
    ("period$", ".", "end"),
    ("question mark", "?", "end"),
    ("exclamation mark|exclamation point", "!", "end"),
    ("semicolon|semi colon", ";", "end"),
    ("colon", ":", "end"),
    ("comma", ",", "end"),
    ("ellipsis|dot dot dot", "...", "end"),
    ("open bracket|open parenthesis|open paren", "(", "open"),
    ("close bracket|close parenthesis|close paren", ")", "end"),
    ("open quote|begin quote", "\"", "open"),
    ("close quote|end quote|unquote", "\"", "end"),
    ("hyphen", "-", "join"),
]
_BN_COMMANDS = [
    ("নতুন অনুচ্ছেদ|নতুন প্যারা|নতুন প্যারাগ্রাফ", "\n\n", "break"),
    ("নতুন লাইন|পরের লাইন", "\n", "break"),
    ("দাঁড়ি|দাড়ি|পূর্ণচ্ছেদ", "।", "end"),
    ("প্রশ্নবোধক চিহ্ন|প্রশ্ন চিহ্ন|প্রশ্নচিহ্ন", "?", "end"),
    ("বিস্ময়সূচক চিহ্ন|বিস্ময় চিহ্ন|আশ্চর্যবোধক চিহ্ন", "!", "end"),
    ("সেমিকোলন", ";", "end"),
    ("কোলন", ":", "end"),
    ("কমা", ",", "end"),
]

_WORD = r"\wঀ-৿"
_PUNCT = ",.;:!?।"
_SENT = ""            # private-use sentinels, one per command


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def _compile_commands():
    table = []
    for phrase, symbol, kind in _EN_COMMANDS + _BN_COMMANDS:
        end_only = phrase.endswith("$")
        alts = [_nfc(a) for a in phrase.rstrip("$").split("|")]
        alts.sort(key=len, reverse=True)
        body = "|".join(r"\s+".join(re.escape(w) for w in a.split()) for a in alts)
        before = r"(?:[ \t]*[" + re.escape(_PUNCT) + r"])*[ \t]*" if kind in ("end", "join") else r"[ \t]*"
        after = r"(?![" + _WORD + r"])[ \t]*[" + re.escape(_PUNCT) + r"]*"
        if end_only:
            after = r"(?=[ \t]*(?:[" + re.escape(_PUNCT) + r"]|$|\n))" + r"[ \t]*[" + re.escape(_PUNCT) + r"]*"
        rx = re.compile(before + r"(?<![" + _WORD + r"])(?:" + body + r")" + after, re.I)
        table.append((rx, symbol, kind))
    return table


_COMMANDS = _compile_commands()


def apply_voice_punctuation(text: str, capitalize: bool = True) -> str:
    """Turn spoken punctuation words into marks and tidy the spacing.

    >>> apply_voice_punctuation("hello comma how are you question mark")
    'Hello, how are you?'
    """
    t = _nfc(text)
    t = " ".join(t.replace("\r", " ").split(" ")) if t else ""
    marks = []
    for rx, symbol, kind in _COMMANDS:
        def repl(_m, symbol=symbol, kind=kind):
            marks.append((symbol, kind))
            return chr(ord(_SENT) + len(marks) - 1)
        t = rx.sub(repl, t)
    for i, (symbol, kind) in enumerate(marks):
        ch = re.escape(chr(ord(_SENT) + i))
        if kind == "end":
            t = re.sub(r"[ \t]*" + ch + r"[ \t]*", lambda _m, s=symbol: s + " ", t)
        elif kind == "open":
            t = re.sub(r"[ \t]*" + ch + r"[ \t]*", lambda _m, s=symbol: " " + s, t)
        elif kind == "join":
            t = re.sub(r"[ \t]*" + ch + r"[ \t]*", lambda _m, s=symbol: s, t)
        else:
            t = re.sub(r"[ \t]*" + ch + r"[ \t]*", lambda _m, s=symbol: s, t)
    return tidy_spacing(t, capitalize)


def tidy_spacing(t: str, capitalize: bool = True) -> str:
    t = re.sub(r"[ \t]+([,.;:!?।)])", r"\1", t)              # no space before a mark
    t = re.sub(r"([,;:!?।])\1+", r"\1", t)                   # "hello,," -> "hello,"
    t = re.sub(r"(?<!\.)\.\.(?!\.)", ".", t)                 # ".." -> "." but keep "..."
    t = re.sub(r",([.?!।])", r"\1", t)                       # ", ." -> "."
    t = re.sub(r"([,.;:!?।])(?=[^\s\d,.;:!?।)\"'])", r"\1 ", t)  # space after a mark (not 3.5)
    t = re.sub(r"(\d)([.,]) (\d)", r"\1\2\3", t)              # keep 3.5 and 1,000
    t = re.sub(r"\( +", "(", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"[ \t]*\n[ \t]*", "\n", t)
    t = t.strip(" \t")
    if capitalize:
        t = capitalize_sentences(t)
    return t


def capitalize_sentences(t: str, first: bool = True) -> str:
    """Capital letter at the start and after . ? ! and line breaks (Latin letters only)."""
    def up(m):
        return m.group(1) + m.group(2).upper()
    t = re.sub(r"([.?!]\s+|\n\s*)([a-z])", up, t)
    if first:
        t = re.sub(r"^(\W*)([a-z])", up, t)
    return t


def join_segment(previous_tail: str, text: str) -> str:
    """Text to type after earlier dictated text: a space between sentences, none after a line break."""
    if not text:
        return ""
    if previous_tail and not previous_tail[-1].isspace() and text[0] not in _PUNCT + ")\n":
        return " " + text
    return text


# ---------------------------------------------------------------------------
# Typing into the focused app
# ---------------------------------------------------------------------------

TERMINAL_CLASSES = ("konsole", "yakuake", "xterm", "uxterm", "gnome-terminal", "terminator", "alacritty", "kitty",
                    "tilix", "xfce4-terminal", "qterminal", "lxterminal", "urxvt", "st-256color", "wezterm",
                    "terminology", "cool-retro-term", "foot")


def is_plain_ascii(text: str) -> bool:
    return all(32 <= ord(c) < 127 or c in "\n\t" for c in text)


def choose_strategy(text: str) -> str:
    """'type' for plain ASCII (xdotool type is reliable there), 'paste' for Bangla / Unicode."""
    return "type" if is_plain_ascii(text) else "paste"


def is_terminal(wm_class: str) -> bool:
    c = (wm_class or "").strip().lower()
    return any(c == t or c.startswith(t) for t in TERMINAL_CLASSES)


def paste_keys(wm_class: str) -> str:
    return "ctrl+shift+v" if is_terminal(wm_class) else "ctrl+v"


def copy_keys(wm_class: str) -> str:
    return "ctrl+shift+c" if is_terminal(wm_class) else "ctrl+c"


def type_command(text: str, delay_ms: int = 8) -> List[str]:
    return ["xdotool", "type", "--clearmodifiers", "--delay", str(delay_ms), "--", text]


def _run(argv: List[str], timeout: float = 5.0, input_text: Optional[str] = None) -> Tuple[int, str]:
    # xclip -i forks a child that keeps serving the selection: it must not hold our stdout pipe open
    out = subprocess.DEVNULL if input_text is not None else subprocess.PIPE
    try:
        p = subprocess.run(argv, input=input_text.encode("utf-8") if input_text is not None else None,
                           stdout=out, stderr=subprocess.DEVNULL, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return p.returncode, (p.stdout or b"").decode("utf-8", "replace")


class TypingError(Exception):
    pass


class Typer:
    """Puts text into the app that has the keyboard focus (X11: xdotool + xclip).

    run(argv, timeout=..., input_text=None) -> (rc, stdout) is injectable for tests.
    """

    def __init__(self, run: Callable = _run, which: Callable = shutil.which, sleep: Callable = time.sleep):
        self.run = run
        self.which = which
        self.sleep = sleep

    # -- clipboard -------------------------------------------------------------
    def get_clipboard(self, selection: str = "clipboard") -> Optional[str]:
        if not self.which("xclip"):
            return None
        rc, out = self.run(["xclip", "-o", "-selection", selection], timeout=1.5)
        return out if rc == 0 else None

    def set_clipboard(self, text: str, selection: str = "clipboard") -> bool:
        if not self.which("xclip"):
            return False
        # xclip forks and keeps serving the text after this returns
        rc, _ = self.run(["xclip", "-i", "-selection", selection], timeout=2.0, input_text=text)
        return rc == 0

    # -- window info -------------------------------------------------------------
    def active_window(self) -> str:
        for argv in (["xdotool", "getactivewindow"], ["xdotool", "getwindowfocus"]):
            rc, out = self.run(argv, timeout=1.5)
            if rc == 0 and out.strip():
                return out.strip()
        return ""

    def window_class(self, wid: str = "") -> str:
        wid = wid or self.active_window()
        if not wid:
            return ""
        rc, out = self.run(["xdotool", "getwindowclassname", wid], timeout=1.5)
        return out.strip() if rc == 0 else ""

    def activate(self, wid: str) -> bool:
        if not wid:
            return False
        rc, _ = self.run(["xdotool", "windowactivate", "--sync", wid], timeout=3.0)
        if rc != 0:     # no EWMH window manager: plain X focus
            rc, _ = self.run(["xdotool", "windowfocus", "--sync", wid], timeout=3.0)
        return rc == 0

    def key(self, *keys: str) -> bool:
        rc, _ = self.run(["xdotool", "key", "--clearmodifiers"] + list(keys), timeout=3.0)
        return rc == 0

    # -- typing ------------------------------------------------------------------
    def paste(self, text: str, restore: bool = True) -> None:
        if not self.which("xclip"):
            raise TypingError("Pasting needs the xclip package.")
        old = self.get_clipboard() if restore else None
        if not self.set_clipboard(text):
            raise TypingError("Couldn't put the text on the clipboard.")
        self.sleep(0.06)
        if not self.key(paste_keys(self.window_class())):
            raise TypingError("Couldn't paste into the app.")
        if restore and old is not None and old != text:
            self.sleep(0.4)             # let the app read the clipboard first
            self.set_clipboard(old)

    def _type_lines(self, text: str) -> bool:
        """xdotool type does not press Enter for a line break in every app: type line by line, Return between."""
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if i and not self.key("Return"):
                return False
            if line:
                rc, _ = self.run(type_command(line), timeout=max(5.0, len(line) * 0.05))
                if rc != 0:
                    return False
        return True

    def type_text(self, text: str, strategy: Optional[str] = None) -> str:
        """Type `text`; returns the strategy that worked ('type' or 'paste')."""
        if not text:
            return ""
        if not self.which("xdotool"):
            raise TypingError(NO_XDOTOOL_TEXT)
        strategy = strategy or choose_strategy(text)
        if strategy == "type" and self._type_lines(text):
            return "type"
        self.paste(text)
        return "paste"


# ---------------------------------------------------------------------------
# Clean up with AI (optional, off by default)
# ---------------------------------------------------------------------------

CLEANUP_INSTRUCTION = ("Fix the punctuation, capital letters and small grammar mistakes in this dictated text. "
                       "Keep the same words, language and meaning. Reply with the fixed text only.")


def cleanup_messages(text: str) -> List[dict]:
    return [{"role": "system", "content": "You fix dictated text. Reply with the fixed text only."},
            {"role": "user", "content": f"{CLEANUP_INSTRUCTION}\n\nText:\n{text}"}]


def accept_cleanup(original: str, fixed: str) -> str:
    """The model's version when it is plausibly the same text, else the original."""
    f = (fixed or "").strip()
    o = (original or "").strip()
    if not f or not o:
        return original
    ratio = len(f) / max(1, len(o))
    if ratio < 0.6 or ratio > 1.6:
        return original
    if voice.guess_language(o) == "bn" and voice.guess_language(f) != "bn":
        return original                 # it translated instead of fixing
    if f.count("\n") != o.count("\n"):
        f = f.replace("\n", " ") if "\n" not in o else f
        if f.count("\n") != o.count("\n"):
            return original
    return f


def _aiactions():
    d = os.path.join(COMPONENTS, "aiactions")
    if d not in sys.path:
        sys.path.insert(0, d)
    import aiactions
    return aiactions


def ai_cleanup(text: str, ask: Optional[Callable] = None) -> str:
    if not text.strip():
        return text
    if ask is None:
        ask = _aiactions().ask
    try:
        fixed = ask(cleanup_messages(text), max_tokens=min(1024, 64 + len(text)))
    except Exception:
        return text
    return accept_cleanup(text, fixed)


# ---------------------------------------------------------------------------
# Dictation: record -> text (headless; also used by DevOS Notes)
# ---------------------------------------------------------------------------


class Dictation:
    """One recording turned into tidy text. record() blocks: run it in a worker thread."""

    def __init__(self, language: str = "auto", on_level: Callable[[float], None] = lambda v: None,
                 recorder: Optional[object] = None, transcribe: Optional[Callable[[bytes, str], str]] = None):
        self.language = language if language in LANG_CHOICES else "auto"
        self.recorder = recorder or voice.Recorder(
            on_level=on_level, vad=voice.VAD(silence_s=DICTATION_SILENCE_S, max_s=DICTATION_MAX_S,
                                             no_speech_s=DICTATION_NO_SPEECH_S))
        self._transcribe = transcribe or self._whisper
        self.last_language = ""

    @staticmethod
    def _whisper(pcm: bytes, language: str) -> str:
        if language == "auto":
            text = voice.Transcriber.transcribe(pcm)
        else:
            text = voice.Transcriber.transcribe_as(pcm, language)
        return text

    def stop(self):
        self.recorder.stop()

    def record(self) -> Tuple[bytes, str]:
        return self.recorder.record()

    def heard_speech(self) -> bool:
        """False when the recording was stopped before anyone spoke (whisper invents words for silence)."""
        vad = getattr(self.recorder, "vad", None)
        return bool(getattr(vad, "heard_speech", True))

    def text_from(self, pcm: bytes) -> str:
        raw = self._transcribe(pcm, self.language) or ""
        self.last_language = voice.guess_language(raw)
        return apply_voice_punctuation(raw)

    def once(self) -> Tuple[str, str]:
        """(text, problem): record until a pause, then transcribe."""
        pcm, problem = self.record()
        if problem or not pcm:
            return "", problem or NOTHING_HEARD
        text = self.text_from(pcm)
        return text, ("" if text else NOTHING_HEARD)


def voice_problem() -> str:
    """'' when voice typing can work, else a short sentence for the pill."""
    ok, why = voice.VOICE_CHECK.status()
    return "" if ok else why


# ---------------------------------------------------------------------------
# Session (the worker loop behind the pill)
# ---------------------------------------------------------------------------


class Session:
    """Dictates segment after segment until stopped. emit(kind, payload) reports progress:

    listening, writing, cleaning, typed(text), error(message), done(count of words typed)
    """

    def __init__(self, emit: Callable[[str, object], None], typer: Optional[Typer] = None,
                 config: Callable[[], dict] = load_config, dictation_factory: Optional[Callable] = None,
                 cleanup: Callable[[str], str] = ai_cleanup, on_level: Callable[[float], None] = lambda v: None):
        self.emit = emit
        self.typer = typer or Typer()
        self.config = config
        self.factory = dictation_factory or (lambda lang: Dictation(lang, on_level=on_level))
        self.cleanup = cleanup
        self.stop_requested = False
        self.cancelled = False
        self.current: Optional[Dictation] = None
        self.words = 0

    def request_stop(self):
        self.stop_requested = True
        if self.current is not None:
            self.current.stop()

    def cancel(self):
        self.cancelled = True
        self.request_stop()

    def run(self) -> int:
        tail = ""
        try:
            while not self.cancelled:
                cfg = self.config()
                self.emit("listening", cfg.get("language", "auto"))
                self.current = self.factory(cfg.get("language", "auto"))
                if self.stop_requested:
                    break
                pcm, problem = self.current.record()
                if self.cancelled:
                    break
                if not problem and pcm and not self.current.heard_speech():
                    break
                if problem or not pcm:
                    if not self.words and not self.stop_requested:
                        self.emit("error", problem or NOTHING_HEARD)
                        return 0
                    break
                self.emit("writing", "")
                text = self.current.text_from(pcm)
                if self.cancelled:
                    break
                if text and self.config().get("ai_cleanup"):
                    self.emit("cleaning", "")
                    text = self.cleanup(text)
                if text:
                    out = join_segment(tail, text)
                    self.typer.type_text(out)
                    tail = out
                    self.words += len(text.split())
                    self.emit("typed", text)
                if self.stop_requested:
                    break
        except TypingError as exc:
            self.emit("error", str(exc))
            return self.words
        except Exception as exc:        # never leave a frozen pill on screen
            self.emit("error", f"Voice typing stopped: {exc}")
            return self.words
        self.emit("done", self.words)
        return self.words


# ---------------------------------------------------------------------------
# GUI: the mic pill (PyQt5, imported lazily)
# ---------------------------------------------------------------------------

PILL_W = 540
PILL_H = 66
BOTTOM_GAP = 72


def _load_gui():
    from PyQt5 import QtCore, QtGui, QtWidgets
    from PyQt5.QtCore import Qt
    import assistant as ui          # palette + painted icons of DevOS AI
    import overlay                  # Bars / Badge of the voice-command overlay

    class Chip(QtWidgets.QPushButton):
        def __init__(self, text, tip=""):
            super().__init__(text)
            self.setCursor(Qt.PointingHandCursor)
            self.setFocusPolicy(Qt.NoFocus)
            self.setFixedHeight(28)
            self.setToolTip(tip)
            self.setCheckable(True)
            self.setStyleSheet(
                "QPushButton { background: rgba(255,255,255,0.06); color: %s; border: 1px solid rgba(255,255,255,0.10);"
                " border-radius: 14px; padding: 0 11px; font-size: 12px; font-weight: 600; }"
                "QPushButton:hover { border-color: rgba(255,255,255,0.28); }"
                "QPushButton:checked { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(34,211,238,0.28),"
                " stop:1 rgba(99,102,241,0.30)); color: #f1f5f9; border-color: rgba(56,189,248,0.70); }"
                % ui.MUTED)

    class CloseDot(QtWidgets.QPushButton):
        def __init__(self):
            super().__init__()
            self.setCursor(Qt.PointingHandCursor)
            self.setFocusPolicy(Qt.NoFocus)
            self.setFixedSize(28, 28)
            self.setToolTip("Stop voice typing")

        def paintEvent(self, _e):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QtGui.QColor(255, 255, 255, 34 if self.underMouse() else 16))
            p.drawEllipse(QtCore.QRectF(1, 1, 26, 26))
            ui.draw_icon(p, "close", QtCore.QRectF(8, 8, 12, 12), ui.qcolor(ui.TEXT_STRONG), 1.8)
            p.end()

    class MicPill(QtWidgets.QWidget):
        """Floating, always-on-top, never focused."""
        language_changed = QtCore.pyqtSignal(str)
        ai_toggled = QtCore.pyqtSignal(bool)
        close_clicked = QtCore.pyqtSignal()
        finished = QtCore.pyqtSignal()

        def __init__(self, language="auto", ai_on=False):
            super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
                             Qt.WindowDoesNotAcceptFocus | Qt.X11BypassWindowManagerHint)
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setAttribute(Qt.WA_ShowWithoutActivating)
            self.setFocusPolicy(Qt.NoFocus)
            self.setWindowTitle("DevOS Voice Typing")
            self.state = "idle"
            self.language = language
            lay = QtWidgets.QHBoxLayout(self)
            lay.setContentsMargins(14, 10, 12, 10)
            lay.setSpacing(12)
            self.badge = overlay.Badge()
            lay.addWidget(self.badge, 0, Qt.AlignVCenter)
            col = QtWidgets.QVBoxLayout()
            col.setSpacing(1)
            self.title = QtWidgets.QLabel("VOICE TYPING")
            self.title.setStyleSheet(f"color: {ui.MUTED}; font-size: 11px; font-weight: 700; letter-spacing: 0.8px;")
            self.text = QtWidgets.QLabel()
            self.text.setTextFormat(Qt.PlainText)
            self.text.setStyleSheet(f"color: {ui.TEXT_STRONG}; font-size: 14px;")
            self.text.setMinimumWidth(150)
            col.addWidget(self.title)
            col.addWidget(self.text)
            lay.addLayout(col, 1)
            self.bars = overlay.Bars(9)
            lay.addWidget(self.bars, 0, Qt.AlignVCenter)
            self.lang_chip = Chip(LANG_LABELS.get(language, "Auto"), "Spoken language (click to change)")
            self.lang_chip.setCheckable(False)
            self.lang_chip.clicked.connect(self._cycle_language)
            lay.addWidget(self.lang_chip, 0, Qt.AlignVCenter)
            self.ai_chip = Chip("✦ AI", AI_CLEANUP_TIP)
            self.ai_chip.setChecked(bool(ai_on))
            self.ai_chip.toggled.connect(self._ai_toggled)
            lay.addWidget(self.ai_chip, 0, Qt.AlignVCenter)
            self.close_btn = CloseDot()
            self.close_btn.clicked.connect(self.close_clicked.emit)
            lay.addWidget(self.close_btn, 0, Qt.AlignVCenter)
            self.hide_timer = QtCore.QTimer(self)
            self.hide_timer.setSingleShot(True)
            self.hide_timer.timeout.connect(self.fade_out)
            self._fade = None
            self.setFixedSize(PILL_W, PILL_H)

        def set_text(self, text, from_left=False):
            """One line; long dictation shows its end (what was just said)."""
            fm = self.text.fontMetrics()
            width = max(120, self.text.width() or 210)
            mode = QtCore.Qt.ElideLeft if from_left else QtCore.Qt.ElideRight
            self.text.setText(fm.elidedText(" ".join(str(text).split()), mode, width))
            self.text.setToolTip(str(text) if fm.horizontalAdvance(str(text)) > width else "")

        def _cycle_language(self):
            self.language = next_language(self.language)
            self.lang_chip.setText(LANG_LABELS[self.language])
            self.language_changed.emit(self.language)

        def _ai_toggled(self, on):
            self.ai_chip.setToolTip(("On: " if on else "Off: ") + AI_CLEANUP_TIP)
            self.ai_toggled.emit(bool(on))

        def place(self):
            scr = QtWidgets.QApplication.screenAt(QtGui.QCursor.pos()) or QtWidgets.QApplication.primaryScreen()
            if scr is None:
                return
            g = scr.availableGeometry()
            self.move(g.x() + (g.width() - self.width()) // 2, g.y() + g.height() - self.height() - BOTTOM_GAP)

        def paintEvent(self, _e):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            r = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
            rad = r.height() / 2
            p.setPen(Qt.NoPen)
            p.setBrush(QtGui.QColor(11, 15, 26, 240))
            p.drawRoundedRect(r, rad, rad)
            live = self.state in ("listening", "writing", "cleaning")
            edge = ui.accent_gradient(r.left(), 0, r.right(), 0, 150 if live else 50)
            p.setPen(QtGui.QPen(QtGui.QBrush(edge), 1.3))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, rad, rad)
            p.end()

        def show_now(self):
            if self._fade is not None:
                self._fade.stop()
                self._fade = None
            self.setWindowOpacity(1.0)
            self.place()
            if not self.isVisible():
                self.show()
            self.raise_()
            self.update()

        def fade_out(self):
            a = QtCore.QPropertyAnimation(self, b"windowOpacity", self)
            a.setDuration(220)
            a.setStartValue(self.windowOpacity())
            a.setEndValue(0.0)
            a.finished.connect(self._done)
            a.start()
            self._fade = a

        def _done(self):
            self.hide()
            self.finished.emit()

        def set_level(self, v):
            self.bars.set_level(v)

        def handle_event(self, kind, payload):
            self.hide_timer.stop()
            if kind == "listening":
                self.state = "listening"
                self.badge.set_kind("mic")
                self.title.setText("LISTENING · " + HOTKEY.replace("Meta", "Win").upper() + " ENDS")
                self.set_text("Speak now…")
                self.bars.show()
                self.bars.start()
            elif kind in ("writing", "cleaning"):
                self.state = kind
                self.badge.set_kind("spin")
                self.bars.stop()
                self.bars.hide()
                self.title.setText("VOICE TYPING · AI CLEAN-UP" if kind == "cleaning" else "VOICE TYPING")
                self.set_text("DevOS AI is tidying it up…" if kind == "cleaning" else "Writing it down…")
            elif kind == "typed":
                self.set_text("“" + " ".join(str(payload).split()) + "”", from_left=True)
            elif kind == "error":
                self.state = "error"
                self.bars.stop()
                self.bars.hide()
                self.badge.set_kind("warn")
                self.title.setText("VOICE TYPING")
                self.text.setWordWrap(True)
                self.text.setText(str(payload))
                self.setFixedHeight(max(PILL_H, self.sizeHint().height()))
                self.hide_timer.start(3500)
            elif kind == "done":
                self.state = "done"
                self.bars.stop()
                self.bars.hide()
                self.badge.set_kind("ok")
                n = int(payload or 0)
                self.title.setText("VOICE TYPING")
                self.set_text(f"Typed {n} word{'s' if n != 1 else ''}" if n else "Stopped")
                self.hide_timer.start(1100)
            self.show_now()

    return QtCore, QtGui, QtWidgets, MicPill


def make_app(argv):
    import listen
    return listen.make_app(argv)


def run_toggle(argv=None) -> int:
    """First press: start dictating. A press while dictating: finish."""
    import listen
    lock = listen.take_lock(LOCK_NAME)
    stop_flag = os.path.join(listen.runtime_dir(), STOP_FLAG)
    if lock is None:
        open(stop_flag, "w").close()
        return 0
    try:
        os.remove(stop_flag)
    except OSError:
        pass
    QtCore, QtGui, QtWidgets, MicPill = _load_gui()
    import overlay
    app = make_app(argv or sys.argv)
    app.setApplicationName("DevOS Voice Typing")
    cfg = load_config()
    pill = MicPill(cfg["language"], cfg["ai_cleanup"])
    bridge = overlay.Bridge()
    bridge.level.connect(pill.set_level)
    bridge.event.connect(pill.handle_event)
    pill.finished.connect(app.quit)
    pill.language_changed.connect(lambda lang: save_config(language=lang))
    pill.ai_toggled.connect(lambda on: save_config(ai_cleanup=on))

    problem = voice_problem()
    if not problem and not shutil.which("xdotool"):
        problem = NO_XDOTOOL_TEXT
    if problem:
        pill.handle_event("error", problem)
        rc = app.exec_()
        lock.close()
        return rc

    session = Session(bridge.event.emit, on_level=bridge.level.emit)
    pill.close_clicked.connect(session.request_stop)     # what was said so far is still typed

    poll = QtCore.QTimer()
    poll.setInterval(100)

    def check_stop():
        if os.path.exists(stop_flag):
            try:
                os.remove(stop_flag)
            except OSError:
                pass
            session.request_stop()
    poll.timeout.connect(check_stop)
    poll.start()
    pill.handle_event("listening", cfg["language"])
    threading.Thread(target=session.run, daemon=True).start()
    rc = app.exec_()
    lock.close()
    return rc


def request_stop() -> int:
    import listen
    open(os.path.join(listen.runtime_dir(), STOP_FLAG), "w").close()
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    p = argparse.ArgumentParser(description="DevOS Voice Typing: dictate into any app")
    p.add_argument("--stop", action="store_true", help="finish a running voice typing session")
    p.add_argument("--toggle", action="store_true", help="start, or finish when already running (default)")
    ns = p.parse_args(argv[1:])
    if ns.stop:
        return request_stop()
    return run_toggle(argv)


if __name__ == "__main__":
    sys.exit(main())
