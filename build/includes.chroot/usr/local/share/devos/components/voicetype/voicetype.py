#!/usr/bin/env python3
"""
DevOS Voice Typing — speak into whatever text box the mouse was on.

    1. Point/click the text box (WhatsApp, Chrome, mail, Notepad, …)
    2. Press Win+Alt+A (or Win+Alt+H) — mic remembers that mouse spot
    3. Speak → pause → text is clicked+pasted at that same spot
    4. Press the hotkey again to stop (session stays open across pauses)

Works anywhere: last mouse position is the typing target.
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
HOTKEY_ALT = "Meta+Alt+A"   # same mic flow (users expect this for “voice write”)
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".config", "devos", "voicetype.json")
LOCK_NAME = "devos-voicetype.lock"
STOP_FLAG = "devos-voicetype-stop"

LANG_CHOICES = ("auto", "en", "bn")
LANG_LABELS = {"auto": "Auto", "en": "English", "bn": "বাংলা"}

# Short pause → commit into the box quickly so you *see* words appear while talking.
DICTATION_SILENCE_S = 0.55
DICTATION_MAX_S = 45
# How long to wait for the *next* phrase before looping again (session stays open).
DICTATION_NO_SPEECH_S = 60

AI_CLEANUP_LABEL = "Clean up with AI"
AI_CLEANUP_TIP = ("DevOS AI fixes spelling and grammar before each phrase is typed. "
                  "Runs on this PC; nothing is sent anywhere.")

NO_XDOTOOL_TEXT = ("Voice typing needs wtype (Wayland) or xdotool (X11) to type into "
                   "other apps. Open DevOS Notepad, or install: sudo apt install wtype")
NOTHING_HEARD = "I didn't hear anything. Check the microphone and try again."
NO_TARGET_TEXT = "Point the mouse at a text box, then press Win+Alt+A."
NO_MOUSE_TEXT = "Couldn't read the mouse position. Move the pointer onto a text box and try again."
# Sentinel targets when xdotool cannot see windows on Wayland.
TARGET_NOTEPAD = "notepad"
TARGET_FOCUS = "focus"  # click last mouse position, then type/paste
LAST_MOUSE_PATH = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "devos-voicetype-last-mouse.json"
)
START_TS_PATH = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "devos-voicetype-started"
)
LOG_PATH = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "devos-voicetype.log"
)
# Ignore a second Win+Alt+A within this window (Cursor/portal can double-fire).
HOTKEY_DEBOUNCE_S = 1.2


def log(msg: str) -> None:
    line = "%s %s\n" % (time.strftime("%H:%M:%S"), msg)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass

# Off by default: type raw speech fast. User can enable AI polish later.
DEFAULT_CONFIG = {"language": "auto", "ai_cleanup": False}

# Our floating mic must never become the typing target.
_OWN_WM = ("devos-voice-typing", "voicetype.py", "devos-ai-actions")


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


def notepad_socket_path() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    uid = os.getuid() if hasattr(os, "getuid") else 0
    return os.path.join(runtime, "devos-notepad-%d.sock" % uid)


def notepad_available() -> bool:
    return os.path.exists(notepad_socket_path())


def session_is_wayland() -> bool:
    return (os.environ.get("XDG_SESSION_TYPE") or "").lower() == "wayland" or bool(
        os.environ.get("WAYLAND_DISPLAY")
    )


_KWIN_FOCUS_CACHE: Tuple[float, str, str] = (0.0, "", "")


def kwin_focused_app() -> Tuple[str, str]:
    """(caption, resourceClass) of the focused window via KWin (Plasma Wayland)."""
    global _KWIN_FOCUS_CACHE
    now = time.time()
    if now - _KWIN_FOCUS_CACHE[0] < 0.4:
        return _KWIN_FOCUS_CACHE[1], _KWIN_FOCUS_CACHE[2]
    if not shutil.which("qdbus6"):
        return "", ""
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    nonce = "DEVOS%d" % (int(time.time() * 1000) % 1000000000)
    js_path = os.path.join(runtime, "devos-kwin-focus.js")
    # print() lands in the kwin_wayland journal — unique nonce lets us find our line.
    script = (
        "var c = workspace.activeWindow;\n"
        "if (!c && workspace.activeClient) c = workspace.activeClient;\n"
        "var cap = c ? ('' + (c.caption || '')) : '';\n"
        "var cls = c ? ('' + (c.resourceClass || '')) : '';\n"
        "print('%s|' + cap.replace(/\\|/g, ' ') + '|' + cls);\n" % nonce
    )
    try:
        with open(js_path, "w", encoding="utf-8") as fh:
            fh.write(script)
    except OSError:
        return "", ""
    plugin = "devos-focus-%s" % nonce
    try:
        subprocess.run(
            ["qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript", plugin],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
        )
        subprocess.run(
            ["qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.loadScript", js_path, plugin],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2, check=False,
        )
        subprocess.run(
            ["qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.start"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
        )
        time.sleep(0.12)
        log = subprocess.run(
            ["journalctl", "--user", "-n", "40", "--no-pager", "-o", "cat"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=2, text=True,
        )
        subprocess.run(
            ["qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript", plugin],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return "", ""
    for line in reversed((log.stdout or "").splitlines()):
        if nonce + "|" in line:
            parts = line.split("|", 2)
            if len(parts) >= 3:
                cap, cls = parts[1].strip(), parts[2].strip()
                _KWIN_FOCUS_CACHE = (now, cap, cls)
                return cap, cls
            break
    return "", ""


def focused_is_notepad() -> bool:
    cap, cls = kwin_focused_app()
    blob = (cap + " " + cls).lower()
    return "notepad" in blob or "devos-notepad" in blob


def focused_is_own_mic() -> bool:
    cap, cls = kwin_focused_app()
    blob = (cap + " " + cls).lower()
    return any(x in blob for x in ("voice typing", "devos-voice-typing", "voicetype"))


def atspi_available() -> bool:
    try:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi  # noqa: F401
        return True
    except Exception:
        return False


def atspi_click(x: int, y: int) -> bool:
    """Left-click at screen coords via AT-SPI (works on Wayland where xdotool does not)."""
    try:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
        if not Atspi.is_initialized():
            Atspi.init()
        return bool(Atspi.generate_mouse_event(int(x), int(y), "b1c"))
    except Exception as exc:
        log("atspi_click fail: %s" % exc)
        return False


def atspi_type_text(text: str) -> bool:
    """Type unicode text into the focused widget via AT-SPI (Cursor / Electron Wayland)."""
    if not text:
        return True
    try:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
        if not Atspi.is_initialized():
            Atspi.init()
        # STRING synth injects the whole string at the caret.
        ok = bool(Atspi.generate_keyboard_event(0, text, Atspi.KeySynthType.STRING))
        log("atspi_type ok=%s len=%d" % (ok, len(text)))
        return ok
    except Exception as exc:
        log("atspi_type fail: %s" % exc)
        return False


def atspi_paste() -> bool:
    """Ctrl+V via AT-SPI key synth."""
    try:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
        if not Atspi.is_initialized():
            Atspi.init()
        Atspi.generate_keyboard_event(0, "Control_L", Atspi.KeySynthType.PRESS)
        Atspi.generate_keyboard_event(0, "v", Atspi.KeySynthType.PRESSRELEASE)
        Atspi.generate_keyboard_event(0, "Control_L", Atspi.KeySynthType.RELEASE)
        return True
    except Exception as exc:
        log("atspi_paste fail: %s" % exc)
        return False


def dismiss_desktop_notifications(max_age_probe: bool = True) -> None:
    """Close freedesktop/Plasma notification bubbles (expire stuck toasts)."""
    try:
        subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", "org.freedesktop.Notifications",
                "--object-path", "/org/freedesktop/Notifications",
                "--method", "org.freedesktop.Notifications.GetCapabilities",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return
    # Probe for current max id, then close a window of recent ids.
    try:
        out = subprocess.check_output(
            [
                "gdbus", "call", "--session",
                "--dest", "org.freedesktop.Notifications",
                "--object-path", "/org/freedesktop/Notifications",
                "--method", "org.freedesktop.Notifications.Notify",
                "DevOS Voice Typing", "0", "", " ", " ",
                "[]", '{"urgency": <byte 0>, "transient": <true>}', "1",
            ],
            text=True, timeout=3, stderr=subprocess.DEVNULL,
        )
        digits = "".join(ch if ch.isdigit() else " " for ch in out).split()
        max_id = int(digits[0]) if digits else 0
    except (OSError, subprocess.SubprocessError, ValueError):
        max_id = 0
    if max_id <= 0:
        return
    for i in range(max_id, max(0, max_id - 40), -1):
        try:
            subprocess.run(
                [
                    "gdbus", "call", "--session",
                    "--dest", "org.freedesktop.Notifications",
                    "--object-path", "/org/freedesktop/Notifications",
                    "--method", "org.freedesktop.Notifications.CloseNotification",
                    str(i),
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1,
            )
        except (OSError, subprocess.SubprocessError):
            pass


def kwin_activate(caption: str = "", resource_class: str = "") -> bool:
    """Bring a window to the front on Plasma Wayland (needed for Cursor / Electron)."""
    if not shutil.which("qdbus6"):
        return False
    needle = (caption or resource_class or "").strip()
    if not needle:
        return False
    # Escape for JS string
    safe = needle.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")[:120]
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    js_path = os.path.join(runtime, "devos-kwin-activate.js")
    plugin = "devos-act-%d" % (int(time.time() * 1000) % 1000000000)
    script = (
        "var needle = '%s'.toLowerCase();\n"
        "var list = (workspace.windowList ? workspace.windowList() : workspace.clientList());\n"
        "for (var i = 0; i < list.length; i++) {\n"
        "  var c = list[i];\n"
        "  var cap = ((c.caption || '') + '').toLowerCase();\n"
        "  var cls = ((c.resourceClass || '') + '').toLowerCase();\n"
        "  if ((needle && cap.indexOf(needle) !== -1) || (needle && cls.indexOf(needle) !== -1)) {\n"
        "    if (workspace.activeWindow !== undefined) workspace.activeWindow = c;\n"
        "    else workspace.activeClient = c;\n"
        "    break;\n"
        "  }\n"
        "}\n"
    ) % safe
    try:
        with open(js_path, "w", encoding="utf-8") as fh:
            fh.write(script)
        subprocess.run(
            ["qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript", plugin],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
        )
        subprocess.run(
            ["qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.loadScript", js_path, plugin],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
        )
        subprocess.run(
            ["qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.start"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
        )
        time.sleep(0.15)
        subprocess.run(
            ["qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript", plugin],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def insert_into_notepad(text: str, timeout: float = 1.5) -> bool:
    """Wayland-safe: ask running DevOS Notepad to insert at the caret via local socket.

    Requires a real ``inserted`` ack from a Notepad build that handles dictation.
    A bare ``ok`` (older builds / open-file-only) is treated as failure so we can
    fall through to wtype/xdotool instead of silently dropping text.
    """
    if not text:
        return True
    path = notepad_socket_path()
    if not os.path.exists(path):
        return False
    try:
        import socket
        payload = (json.dumps({"insert": text}, ensure_ascii=False) + "\n").encode("utf-8")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(path)
        sock.sendall(payload)
        try:
            ack = sock.recv(32).decode("utf-8", "replace").strip().lower()
        except OSError:
            ack = ""
        sock.close()
        return ack.startswith("inserted")
    except OSError:
        return False


def _which(cmd: str) -> Optional[str]:
    """Find a binary even when Plasma launches us without ~/.local/bin on PATH."""
    found = shutil.which(cmd)
    if found:
        return found
    home = os.path.expanduser("~")
    for folder in (
        os.path.join(HERE, "bin"),                          # vendored next to voicetype.py
        os.path.join(home, ".local", "bin"),
        "/usr/local/bin",
        "/usr/bin",
    ):
        path = os.path.join(folder, cmd)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def kwtype_bin() -> Optional[str]:
    """KDE Wayland keyboard injector (org_kde_kwin_fake_input). Prefer over wtype/AT-SPI."""
    for name in ("kwtypr", "kwtype"):
        path = _which(name)
        if path:
            return path
    return None


def kde_type_text(text: str) -> bool:
    """Type via kwtypr/kwtype — the correct injector for KWin Wayland (not wtype)."""
    if not text:
        return True
    bin_path = kwtype_bin()
    if not bin_path:
        return False
    # kwtypr: fake_input keysyms. unicode-fallback for Bangla etc.
    argv = [bin_path, "--initial-delay", "15", "--unicode-fallback", "--", text]
    # Older kwtype only takes positional text
    if os.path.basename(bin_path) == "kwtype":
        argv = [bin_path, text]
    try:
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=max(8.0, len(text) * 0.05))
        log("kde_type (%s) rc=%s err=%s" % (os.path.basename(bin_path), p.returncode,
                                            (p.stderr or b"")[:200].decode("utf-8", "replace")))
        return p.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        log("kde_type fail: %s" % exc)
        return False


def _run(argv: List[str], timeout: float = 5.0, input_text: Optional[str] = None) -> Tuple[int, str]:
    # xclip -i forks a child that keeps serving the selection: it must not hold our stdout pipe open
    out = subprocess.DEVNULL if input_text is not None else subprocess.PIPE
    try:
        # Resolve argv[0] via ~/.local/bin when PATH is thin (kglobalaccel).
        if argv and not os.path.isabs(argv[0]) and "/" not in argv[0]:
            resolved = _which(argv[0])
            if resolved:
                argv = [resolved] + list(argv[1:])
        p = subprocess.run(argv, input=input_text.encode("utf-8") if input_text is not None else None,
                           stdout=out, stderr=subprocess.DEVNULL, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return p.returncode, (p.stdout or b"").decode("utf-8", "replace")


class TypingError(Exception):
    pass


class Typer:
    """Puts text into the focused app.

    Prefer DevOS Notepad socket (works on Wayland). Else wtype / wl-copy on
    Wayland, else xdotool + xclip on X11.

    run(argv, timeout=..., input_text=None) -> (rc, stdout) is injectable for tests.
    """

    def __init__(self, run: Callable = _run, which: Callable = _which, sleep: Callable = time.sleep):
        self.run = run
        self.which = which
        self.sleep = sleep
        # Universal target: last mouse position when Win+Alt+A fired (any app).
        self.click_x: Optional[int] = None
        self.click_y: Optional[int] = None
        self.click_wid: str = ""
        self.click_caption: str = ""
        self.click_class: str = ""

    def can_type_without_window_id(self) -> bool:
        """True when we can dictate without an xdotool window id (Wayland-safe)."""
        return (
            self.click_x is not None
            or notepad_available()
            or bool(self.which("wtype"))
            or not session_is_wayland()
        )

    def mouse_info(self) -> Tuple[Optional[int], Optional[int], str]:
        """(x, y, window_id) for the pointer — window_id may be empty on pure Wayland."""
        if self.which("xdotool"):
            rc, out = self.run(["xdotool", "getmouselocation", "--shell"], timeout=1.5)
            if rc == 0:
                vals = {}
                for line in out.splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        try:
                            vals[k.strip()] = int(v.strip())
                        except ValueError:
                            vals[k.strip()] = v.strip()
                x, y = vals.get("X"), vals.get("Y")
                wid = str(vals.get("WINDOW") or "")
                if isinstance(x, int) and isinstance(y, int):
                    return x, y, wid
        try:
            from PyQt5.QtGui import QCursor
            p = QCursor.pos()
            return int(p.x()), int(p.y()), ""
        except Exception:
            return None, None, ""

    def mouse_location(self) -> Tuple[Optional[int], Optional[int]]:
        x, y, _ = self.mouse_info()
        return x, y

    def _save_last_mouse(self) -> None:
        if self.click_x is None or self.click_y is None:
            return
        try:
            with open(LAST_MOUSE_PATH, "w", encoding="utf-8") as fh:
                json.dump({
                    "x": self.click_x, "y": self.click_y, "wid": self.click_wid,
                    "caption": self.click_caption, "cls": self.click_class,
                    "t": time.time(),
                }, fh)
        except OSError:
            pass

    def _load_last_mouse(self) -> bool:
        try:
            with open(LAST_MOUSE_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            x, y = int(data["x"]), int(data["y"])
            # Ignore stale positions older than 10 minutes.
            if time.time() - float(data.get("t") or 0) > 600:
                return False
            self.click_x, self.click_y = x, y
            self.click_wid = str(data.get("wid") or "")
            self.click_caption = str(data.get("caption") or "")
            self.click_class = str(data.get("cls") or "")
            return True
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def capture_click_point(self) -> bool:
        """On hotkey: remember current pointer + focused app as the typing target."""
        x, y, wid = self.mouse_info()
        cap, cls = kwin_focused_app()
        if x is None or y is None:
            ok = self._load_last_mouse()
            if ok and not self.click_caption:
                self.click_caption, self.click_class = cap, cls
            return ok
        self.click_x, self.click_y, self.click_wid = x, y, wid or ""
        self.click_caption, self.click_class = cap, cls
        self._save_last_mouse()
        return True

    def is_wayland_electron_target(self) -> bool:
        blob = (self.click_caption + " " + self.click_class).lower()
        return any(x in blob for x in ("cursor", "code", "vscode", "electron", "slack", "discord", "teams"))

    def click_at(self, x: int, y: int) -> bool:
        """Move pointer and left-click so that spot gets the caret again."""
        ok = False
        if self.which("xdotool"):
            rc1, _ = self.run(["xdotool", "mousemove", "--sync", str(int(x)), str(int(y))], timeout=2.0)
            rc2, _ = self.run(["xdotool", "click", "1"], timeout=2.0)
            ok = rc1 == 0 and rc2 == 0
        if not ok and self.which("ydotool"):
            rc, _ = self.run(
                ["ydotool", "mousemove", "--absolute", "-x", str(int(x)), "-y", str(int(y))],
                timeout=2.0,
            )
            if rc == 0:
                rc, _ = self.run(["ydotool", "click", "0xC0"], timeout=2.0)
                ok = rc == 0
        if ok:
            self.sleep(0.12)
        return ok

    def refocus_click_point(self) -> bool:
        """Restore the text box: KWin-activate, AT-SPI click at last mouse (Wayland-safe)."""
        activated = False
        if self.click_caption or self.click_class:
            activated = kwin_activate(self.click_caption or self.click_class,
                                      self.click_class or self.click_caption)
            if activated:
                self.sleep(0.18)
        clicked = False
        if self.click_x is not None and self.click_y is not None:
            # AT-SPI click works on Wayland; xdotool does not for Cursor.
            if atspi_available():
                clicked = atspi_click(self.click_x, self.click_y)
                log("refocus atspi_click=%s at %s,%s" % (clicked, self.click_x, self.click_y))
            if not clicked:
                clicked = self.click_at(self.click_x, self.click_y)
                log("refocus xdotool_click=%s" % clicked)
            if clicked:
                self.sleep(0.15)
        return activated or clicked

    # -- clipboard -------------------------------------------------------------
    def get_clipboard(self, selection: str = "clipboard") -> Optional[str]:
        if self.which("wl-paste") and session_is_wayland():
            rc, out = self.run(["wl-paste", "--no-newline"], timeout=1.5)
            if rc == 0:
                return out
        if not self.which("xclip"):
            return None
        rc, out = self.run(["xclip", "-o", "-selection", selection], timeout=1.5)
        return out if rc == 0 else None

    def set_clipboard(self, text: str, selection: str = "clipboard") -> bool:
        # Wayland: wl-copy keeps the selection alive like xclip.
        if self.which("wl-copy") and session_is_wayland():
            try:
                p = subprocess.Popen(
                    ["wl-copy", "--"],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
                assert p.stdin is not None
                p.stdin.write(text.encode("utf-8", "replace"))
                p.stdin.close()
                try:
                    p.wait(timeout=0.3)
                except subprocess.TimeoutExpired:
                    pass
                return True
            except OSError:
                pass
        if not self.which("xclip"):
            return False
        # xclip keeps serving the selection — do not wait for it to exit.
        try:
            p = subprocess.Popen(
                ["xclip", "-i", "-selection", selection],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            assert p.stdin is not None
            p.stdin.write(text.encode("utf-8", "replace"))
            p.stdin.close()
            try:
                p.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
            return True
        except OSError:
            return False

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

    def window_name(self, wid: str = "") -> str:
        wid = wid or self.active_window()
        if not wid:
            return ""
        rc, out = self.run(["xdotool", "getwindowname", wid], timeout=1.5)
        return out.strip() if rc == 0 else ""

    def is_own_window(self, wid: str) -> bool:
        if not wid:
            return True
        cls = self.window_class(wid).lower()
        name = self.window_name(wid).lower()
        return any(x in cls or x in name for x in _OWN_WM) or "voice typing" in name

    def capture_target(self) -> str:
        """Window that should receive dictation (the focused app *before* our mic)."""
        wid = self.active_window()
        if wid and not self.is_own_window(wid):
            return wid
        return ""

    def window_geometry(self, wid: str) -> Tuple[int, int, int, int]:
        """(x, y, w, h) for wid, or zeros."""
        if not wid:
            return 0, 0, 0, 0
        rc, out = self.run(["xdotool", "getwindowgeometry", "--shell", wid], timeout=1.5)
        if rc != 0:
            return 0, 0, 0, 0
        vals = {}
        for line in out.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                try:
                    vals[k.strip()] = int(v.strip())
                except ValueError:
                    pass
        return vals.get("X", 0), vals.get("Y", 0), vals.get("WIDTH", 0), vals.get("HEIGHT", 0)

    def focus_editor(self, wid: str) -> bool:
        """Activate window and click into the document area so the caret is ready."""
        if not wid or not self.activate(wid):
            return False
        _x, _y, w, h = self.window_geometry(wid)
        if w < 40 or h < 40:
            return True
        # Click center of the client area (Notepad editor / WhatsApp chat body).
        # Avoid the very bottom chrome (tabs/status) and top menu.
        cx = max(20, w // 2)
        cy = max(40, min(h - 80, int(h * 0.45)))
        self.run(["xdotool", "mousemove", "--window", wid, str(cx), str(cy)], timeout=1.0)
        self.run(["xdotool", "click", "--window", wid, "1"], timeout=1.0)
        self.sleep(0.08)
        return True

    def activate(self, wid: str) -> bool:
        if not wid:
            return False
        rc, _ = self.run(["xdotool", "windowactivate", "--sync", wid], timeout=3.0)
        if rc != 0:     # no EWMH window manager: plain X focus
            rc, _ = self.run(["xdotool", "windowfocus", "--sync", wid], timeout=3.0)
        if rc == 0:
            self.sleep(0.06)
        return rc == 0

    def key(self, *keys: str) -> bool:
        # Wayland: wtype can inject into the currently focused surface.
        if self.which("wtype") and session_is_wayland():
            argv = ["wtype"]
            for k in keys:
                for part in str(k).split("+"):
                    p = part.strip().lower()
                    if not p:
                        continue
                    if p in ("ctrl", "control"):
                        argv.extend(["-M", "ctrl"])
                    elif p in ("shift",):
                        argv.extend(["-M", "shift"])
                    elif p in ("alt", "mod1"):
                        argv.extend(["-M", "alt"])
                    elif p in ("super", "meta", "mod4"):
                        argv.extend(["-M", "logo"])
                    elif p in ("return", "enter"):
                        argv.extend(["-k", "Return"])
                    elif p in ("v",) or len(p) == 1:
                        argv.extend(["-k", p.upper() if len(p) == 1 else p])
                    else:
                        argv.extend(["-k", p])
            rc, _ = self.run(argv, timeout=3.0)
            return rc == 0
        if not self.which("xdotool"):
            return False
        rc, _ = self.run(["xdotool", "key", "--clearmodifiers"] + list(keys), timeout=3.0)
        return rc == 0

    # -- typing ------------------------------------------------------------------
    def paste(self, text: str, restore: bool = True, wid: str = "") -> None:
        if not (self.which("wl-copy") or self.which("xclip")):
            raise TypingError("Pasting needs wl-copy or xclip.")
        old = self.get_clipboard() if restore else None
        if not self.set_clipboard(text):
            raise TypingError("Couldn't put the text on the clipboard.")
        self.sleep(0.08)
        cls = ""
        if wid and wid not in (TARGET_NOTEPAD, TARGET_FOCUS):
            cls = self.window_class(wid)
        elif not wid or wid == TARGET_FOCUS:
            cls = self.window_class()
        keys = paste_keys(cls)
        # Cursor / Electron on Wayland: refocus then retry paste a few times.
        for attempt in range(3):
            if attempt:
                self.refocus_click_point()
                self.sleep(0.12)
            if self.key(keys):
                break
        else:
            # Last try: type ASCII directly if paste keys failed.
            if is_plain_ascii(text) and self._type_lines(text):
                if restore and old is not None and old != text:
                    self.sleep(0.35)
                    self.set_clipboard(old)
                return
            raise TypingError("Couldn't paste into the app. Click the text box, then try again.")
        if restore and old is not None and old != text:
            self.sleep(0.35)
            self.set_clipboard(old)

    def _type_lines(self, text: str) -> bool:
        """Type line by line; Return between. Prefer wtype on Wayland."""
        lines = text.split("\n")
        if self.which("wtype") and session_is_wayland():
            for i, line in enumerate(lines):
                if i and not self.key("Return"):
                    return False
                if line:
                    rc, _ = self.run(["wtype", "--", line], timeout=max(5.0, len(line) * 0.04))
                    if rc != 0:
                        return False
            return True
        if not self.which("xdotool"):
            return False
        for i, line in enumerate(lines):
            if i and not self.key("Return"):
                return False
            if line:
                rc, _ = self.run(type_command(line, delay_ms=4), timeout=max(5.0, len(line) * 0.04))
                if rc != 0:
                    return False
        return True

    def looks_like_notepad(self, wid: str = "") -> bool:
        if wid == TARGET_NOTEPAD:
            return True
        if not wid or wid == TARGET_FOCUS:
            return False
        cls = self.window_class(wid).lower()
        name = self.window_name(wid).lower()
        return "notepad" in cls or "notepad" in name or "devos-notepad" in cls

    def mouse_over_notepad(self) -> bool:
        """True when the saved pointer is over DevOS Notepad."""
        if self.click_wid and self.looks_like_notepad(self.click_wid):
            return True
        # Pure Wayland often has no WINDOW id — use KWin caption as a hint.
        if not self.click_wid and self.click_x is not None:
            return focused_is_notepad()
        return False

    def resolve_target(self) -> str:
        """Always target the last mouse spot; Notepad socket only if pointer is over it."""
        if self.click_x is None:
            self.capture_click_point()
        if notepad_available() and self.mouse_over_notepad():
            return TARGET_NOTEPAD
        # Every other app (WhatsApp, Chrome, mail, …): click last mouse + type.
        if self.click_x is not None and (self.which("wtype") or self.which("xdotool") or self.which("wl-copy")):
            return TARGET_FOCUS
        if self.which("wtype") or not session_is_wayland():
            return TARGET_FOCUS if self.click_x is not None else ""
        if notepad_available():
            return TARGET_NOTEPAD
        return ""

    def prepare_input_focus(self, into: str = "") -> None:
        """Click the saved mouse position so that text box gets the caret."""
        if into == TARGET_NOTEPAD:
            return
        if self.refocus_click_point():
            return
        x, y = self.mouse_location()
        if x is not None and y is not None:
            self.click_x, self.click_y = x, y
            self.click_at(x, y)

    def type_text(self, text: str, strategy: Optional[str] = None, into: str = "") -> str:
        """Type at the last mouse position (any app). Notepad may use its socket."""
        if not text:
            return ""
        # Locked target from hotkey time wins — don't jump to another app mid-session.
        if into == TARGET_NOTEPAD and insert_into_notepad(text):
            return "notepad"
        # Focus the app + click last mouse. Mic is hidden by the UI on "writing".
        self.prepare_input_focus(into)
        self.sleep(0.2)
        log("type_text into=%s len=%d caption=%r" % (into, len(text), self.click_caption))
        # Always park text on the clipboard first (manual Ctrl+V safety net).
        self.set_clipboard(text)
        # Best on KDE Plasma Wayland: KWin fake-input via kwtypr (wtype does NOT work on KWin).
        if session_is_wayland() and kde_type_text(text):
            return "kwtypr"
        # AT-SPI often reports success but Electron/Cursor ignores it — try anyway.
        if atspi_available() and atspi_type_text(text):
            return "atspi"
        if atspi_paste():
            log("type_text clipboard+atspi_paste")
            return "atspi-paste"
        # X11 / wlroots compositors.
        if self.which("wtype"):
            rc, _ = self.run(["wtype", "--", text], timeout=max(5.0, len(text) * 0.04))
            if rc == 0:
                return "wtype"
            log("wtype failed rc=%s (KWin lacks virtual-keyboard — use kwtypr)" % rc)
        if self.which("xdotool") and not session_is_wayland():
            self.paste(text, wid=into if into not in (TARGET_FOCUS, TARGET_NOTEPAD, "") else TARGET_FOCUS)
            return "paste"
        # Last resort: clipboard is loaded — ask user to press Ctrl+V once.
        raise TypingError(
            "Text is on the clipboard — press Ctrl+V. "
            "(Install ~/.local/bin/kwtypr for auto-type on Plasma Wayland.)"
        )


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
# Global mouse-click → stop (evdev; works on Wayland)
# ---------------------------------------------------------------------------

_EV_KEY = 0x01
# Mouse / pointer buttons (left/right/middle + side buttons).
_BTN_CODES = frozenset((0x110, 0x111, 0x112, 0x113, 0x114, 0x115, 0x116, 0x117))


class ClickToStop:
    """Watch physical mouse buttons; call on_click() for real user presses.

    Ignores clicks while ``ignore_until`` is in the future (our own refocus taps).
    """

    def __init__(self, on_click: Callable[[], None]):
        self.on_click = on_click
        self.ignore_until = 0.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def ignore_for(self, seconds: float) -> None:
        self.ignore_until = max(self.ignore_until, time.time() + max(0.0, seconds))

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="voicetype-clickwatch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=1.5)
        self._thread = None

    def _open_devices(self):
        import glob
        fds = []
        for path in sorted(glob.glob("/dev/input/event*")):
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            fds.append(fd)
        return fds

    def _run(self) -> None:
        import select
        import struct as _st
        size = _st.calcsize("llHHi")
        fds = self._open_devices()
        if not fds:
            log("clickwatch: no /dev/input/event* access — mouse-stop disabled")
            return
        log("clickwatch: watching %d input devices" % len(fds))
        # Grace after hotkey so the same physical action that started us is ignored.
        self.ignore_for(0.9)
        try:
            while not self._stop.is_set():
                try:
                    readable, _, _ = select.select(fds, [], [], 0.25)
                except (OSError, ValueError):
                    break
                now = time.time()
                for fd in readable:
                    try:
                        data = os.read(fd, size * 32)
                    except BlockingIOError:
                        continue
                    except OSError:
                        continue
                    for off in range(0, len(data) // size * size, size):
                        _sec, _usec, typ, code, val = _st.unpack_from("llHHi", data, off)
                        if typ != _EV_KEY or val != 1:
                            continue
                        if code not in _BTN_CODES:
                            continue
                        if now < self.ignore_until:
                            log("clickwatch: ignored synthetic/grace click")
                            continue
                        log("clickwatch: user click → stop")
                        try:
                            self.on_click()
                        except Exception as exc:
                            log("clickwatch on_click err: %s" % exc)
                        return
        finally:
            for fd in fds:
                try:
                    os.close(fd)
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# Session (the worker loop behind the pill)
# ---------------------------------------------------------------------------


class Session:
    """Dictates segment after segment into a locked target window until stopped.

    emit: listening | writing | cleaning | typed(text) | error | done(words)
    Stop: Win+Alt+A again, tap mic, or click the mouse anywhere.
    """

    def __init__(self, emit: Callable[[str, object], None], typer: Optional[Typer] = None,
                 config: Callable[[], dict] = load_config, dictation_factory: Optional[Callable] = None,
                 cleanup: Callable[[str], str] = ai_cleanup, on_level: Callable[[float], None] = lambda v: None,
                 target_window: str = ""):
        self.emit = emit
        self.typer = typer or Typer()
        self.config = config
        self.factory = dictation_factory or (lambda lang: Dictation(lang, on_level=on_level))
        self.cleanup = cleanup
        self.target_window = target_window or ""
        self.stop_requested = False
        self.cancelled = False
        self.current: Optional[Dictation] = None
        self.words = 0
        self.click_watch: Optional[ClickToStop] = None

    def request_stop(self):
        self.stop_requested = True
        if self.current is not None:
            self.current.stop()

    def cancel(self):
        self.cancelled = True
        self.request_stop()

    def _arm_click_ignore(self, seconds: float = 0.7) -> None:
        if self.click_watch is not None:
            self.click_watch.ignore_for(seconds)

    def run(self) -> int:
        tail = ""
        target = self.target_window
        self.click_watch = ClickToStop(self.request_stop)
        self.click_watch.start()
        try:
            if not target:
                target = self.typer.resolve_target()
            if not target:
                self.emit("error", NO_TARGET_TEXT)
                return 0
            while not self.cancelled and not self.stop_requested:
                cfg = self.config()
                self.emit("listening", cfg.get("language", "auto"))
                self.current = self.factory(cfg.get("language", "auto"))
                if self.stop_requested or self.cancelled:
                    break
                pcm, problem = self.current.record()
                if self.cancelled or self.stop_requested:
                    break
                # Quiet gap / no speech → keep the session open until stop/click.
                if not self.current.heard_speech() or problem or not pcm:
                    continue
                self.emit("writing", "")
                # Our refocus click must not stop the session.
                self._arm_click_ignore(1.2)
                time.sleep(0.28)
                text = self.current.text_from(pcm)
                if self.cancelled or self.stop_requested:
                    break
                if text and self.config().get("ai_cleanup"):
                    self.emit("cleaning", "")
                    text = self.cleanup(text)
                if text:
                    out = join_segment(tail, text)
                    try:
                        self._arm_click_ignore(1.2)
                        self.typer.type_text(out, into=target)
                        tail = out
                        self.words += len(text.split())
                        self.emit("typed", text)
                    except TypingError as exc:
                        self.emit("warn", str(exc))
                        time.sleep(0.8)
                        self.emit("listening", cfg.get("language", "auto"))
                        continue
        except Exception as exc:        # never leave a frozen pill on screen
            self.emit("error", f"Voice typing stopped: {exc}")
            return self.words
        finally:
            if self.click_watch is not None:
                self.click_watch.stop()
                self.click_watch = None
        self.emit("done", self.words)
        return self.words


# ---------------------------------------------------------------------------
# GUI: the mic pill (PyQt5, imported lazily)
# ---------------------------------------------------------------------------

MIC_SIZE = 64
BOTTOM_GAP = 88          # above WhatsApp/Chrome compose bar
MIC_GREEN = "#25D366"
MIC_GREEN_HOT = "#1ebe57"


def _load_gui():
    import math
    from PyQt5 import QtCore, QtGui, QtWidgets
    from PyQt5.QtCore import Qt

    class MicFab(QtWidgets.QWidget):
        """Compact WhatsApp-style mic — does not cover the text box."""
        close_clicked = QtCore.pyqtSignal()
        finished = QtCore.pyqtSignal()
        # kept for Session bridge compatibility (language / AI chips removed from compact UI)
        language_changed = QtCore.pyqtSignal(str)
        ai_toggled = QtCore.pyqtSignal(bool)

        def __init__(self, language="auto", ai_on=False):
            # Tool + DoesNotAcceptFocus: stay above apps without stealing the caret.
            # (X11BypassWindowManagerHint breaks focus routing on Plasma Wayland.)
            super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
                             Qt.WindowDoesNotAcceptFocus)
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setAttribute(Qt.WA_ShowWithoutActivating)
            self.setFocusPolicy(Qt.NoFocus)
            self.setWindowTitle("DevOS Voice Typing")
            self.setFixedSize(MIC_SIZE + 16, MIC_SIZE + 16)
            self.state = "idle"
            self.language = language
            self._ai_on = bool(ai_on)
            self._level = 0.0
            self._pulse = 0.0
            self._tip = "Win+Alt+A start · click anywhere to stop"
            self._timer = QtCore.QTimer(self)
            self._timer.setInterval(33)
            self._timer.timeout.connect(self._tick)
            self._timer.start()
            self.hide_timer = QtCore.QTimer(self)
            self.hide_timer.setSingleShot(True)
            self.hide_timer.timeout.connect(self.fade_out)
            self._fade = None
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(self._tip)

        def mousePressEvent(self, e):
            if e.button() == Qt.LeftButton:
                self.close_clicked.emit()

        def _tick(self):
            self._pulse = (self._pulse + 0.14) % 6.28
            self.update()

        def set_level(self, v):
            self._level = max(0.0, min(1.0, float(v)))

        def place(self):
            scr = QtWidgets.QApplication.screenAt(QtGui.QCursor.pos()) or QtWidgets.QApplication.primaryScreen()
            if scr is None:
                return
            g = scr.availableGeometry()
            # Bottom-right, clear of the message input
            self.move(g.x() + g.width() - self.width() - 20,
                      g.y() + g.height() - self.height() - BOTTOM_GAP)

        def paintEvent(self, _e):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            cx = cy = self.width() / 2.0
            r = MIC_SIZE / 2.0 - 2
            live = self.state in ("listening", "writing", "cleaning")
            if live:
                ring = 4.0 + 7.0 * self._level + 2.0 * (0.5 + 0.5 * math.sin(self._pulse))
                p.setPen(Qt.NoPen)
                p.setBrush(QtGui.QColor(37, 211, 102, 50))
                p.drawEllipse(QtCore.QPointF(cx, cy), r + ring, r + ring)
            hot = self.underMouse()
            if self.state == "writing" or self.state == "cleaning":
                color = QtGui.QColor("#0ea5e9")  # typing / polish
            elif self.state == "done":
                color = QtGui.QColor("#22c55e")
            elif self.state == "error":
                color = QtGui.QColor("#ef4444")
            else:
                color = QtGui.QColor(MIC_GREEN_HOT if hot else MIC_GREEN)
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QtCore.QPointF(cx, cy), r, r)
            p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            if self.state in ("writing", "cleaning"):
                # small “typing” bars
                for i, h in enumerate((8, 14, 10)):
                    x = cx - 8 + i * 8
                    p.drawLine(QtCore.QPointF(x, cy + h / 2), QtCore.QPointF(x, cy - h / 2))
            else:
                p.drawRoundedRect(QtCore.QRectF(cx - 5.5, cy - 12, 11, 15), 5.5, 5.5)
                p.drawArc(QtCore.QRectF(cx - 10, cy - 5, 20, 17), 200 * 16, 140 * 16)
                p.drawLine(QtCore.QPointF(cx, cy + 10), QtCore.QPointF(cx, cy + 14))
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
            a.setDuration(200)
            a.setStartValue(self.windowOpacity())
            a.setEndValue(0.0)
            a.finished.connect(self._done)
            a.start()
            self._fade = a

        def _done(self):
            self.hide()
            self.finished.emit()

        def handle_event(self, kind, payload):
            self.hide_timer.stop()
            if kind == "listening":
                self.state = "listening"
                self._tip = "Listening… click anywhere (or Win+Alt+A) to stop."
                self.setToolTip(self._tip)
                self.show_now()
            elif kind == "writing":
                # Hide while pasting so Cursor/Electron keeps keyboard focus.
                self.state = "writing"
                self._tip = "Typing into the box…"
                self.setToolTip(self._tip)
                self.hide()
            elif kind == "cleaning":
                self.state = "cleaning"
                self._tip = "Polishing with AI, then typing…"
                self.setToolTip(self._tip)
                self.hide()
            elif kind == "typed":
                self.state = "listening"
                words = " ".join(str(payload).split())
                self._tip = f"Typed: “{words[:80]}{'…' if len(words) > 80 else ''}” · keep speaking"
                self.setToolTip(self._tip)
                self.show_now()
            elif kind == "warn":
                # Recoverable (paste failed) — stay open, keep listening.
                self.state = "listening"
                self._tip = str(payload)
                self.setToolTip(self._tip)
                self.show_now()
            elif kind == "error":
                self.state = "error"
                self._tip = str(payload)
                self.setToolTip(self._tip)
                self.show_now()
                self.hide_timer.start(3200)
            elif kind == "done":
                self.state = "done"
                n = int(payload or 0)
                self._tip = f"Done — typed {n} word{'s' if n != 1 else ''}" if n else "Stopped"
                self.setToolTip(self._tip)
                self.show_now()
                self.hide_timer.start(900)

    # Alias kept so run_toggle / tests keep working
    MicPill = MicFab
    return QtCore, QtGui, QtWidgets, MicPill


def make_app(argv):
    import listen
    return listen.make_app(argv)


def _write_start_ts() -> None:
    try:
        with open(START_TS_PATH, "w", encoding="utf-8") as fh:
            fh.write(str(time.time()))
    except OSError:
        pass


def _started_too_recently() -> bool:
    try:
        with open(START_TS_PATH, "r", encoding="utf-8") as fh:
            started = float(fh.read().strip() or "0")
        return (time.time() - started) < HOTKEY_DEBOUNCE_S
    except (OSError, ValueError):
        return False


def run_toggle(argv=None) -> int:
    """First press: start dictating. A press while dictating: finish."""
    import listen
    lock = listen.take_lock(LOCK_NAME)
    stop_flag = os.path.join(listen.runtime_dir(), STOP_FLAG)
    if lock is None:
        # Cursor's global-shortcut portal can re-fire the same keypress and
        # would stop us instantly — ignore stop requests for a short moment.
        if _started_too_recently():
            return 0
        open(stop_flag, "w").close()
        return 0
    try:
        os.remove(stop_flag)
    except OSError:
        pass
    _write_start_ts()
    QtCore, QtGui, QtWidgets, MicPill = _load_gui()
    import overlay
    # Capture the chat/mail/notepad window *before* our mic appears.
    # On Wayland xdotool often cannot see the window — fall back to Notepad
    # socket or "focus" mode (wtype into whatever is focused).
    typer = Typer()
    # Anywhere: remember mouse position at hotkey fire — that spot is the text box.
    got_mouse = typer.capture_click_point()
    target = typer.resolve_target()

    app = make_app(argv or sys.argv)
    app.setApplicationName("DevOS Voice Typing")
    from app_identity import apply as apply_identity
    apply_identity(app, "devos-voice-typing")
    cfg = load_config()
    pill = MicPill(cfg["language"], cfg["ai_cleanup"])
    bridge = overlay.Bridge()
    bridge.level.connect(pill.set_level)
    bridge.event.connect(pill.handle_event)
    pill.finished.connect(app.quit)
    pill.language_changed.connect(lambda lang: save_config(language=lang))
    pill.ai_toggled.connect(lambda on: save_config(ai_cleanup=on))

    problem = voice_problem()
    if not problem and not got_mouse:
        problem = NO_MOUSE_TEXT
    if not problem and not typer.can_type_without_window_id() and not shutil.which("xdotool"):
        problem = NO_XDOTOOL_TEXT
    if not problem and not target:
        problem = NO_TARGET_TEXT
    if problem:
        pill.handle_event("error", problem)
        rc = app.exec_()
        lock.close()
        return rc

    session = Session(bridge.event.emit, typer=typer, on_level=bridge.level.emit,
                      target_window=target)
    pill.close_clicked.connect(session.request_stop)

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
    # Auto-dismiss desktop notification bubbles every ~2.5s while listening.
    dismiss_desktop_notifications()
    toast_clear = QtCore.QTimer()
    toast_clear.setInterval(2500)
    toast_clear.timeout.connect(dismiss_desktop_notifications)
    toast_clear.start()
    log("session start target=%s mouse=(%s,%s) caption=%r atspi=%s wtype=%s"
        % (target, typer.click_x, typer.click_y, typer.click_caption,
           atspi_available(), bool(typer.which("wtype"))))
    # Click the remembered mouse spot so the text box has the caret, then listen.
    if target != TARGET_NOTEPAD:
        typer.prepare_input_focus(target)
    pill.handle_event("listening", cfg["language"])
    if typer.click_x is not None:
        pill.setToolTip(
            "Listening at mouse (%d, %d). Speak — text goes there. Win+Alt+A to stop."
            % (typer.click_x, typer.click_y)
        )
    threading.Thread(target=session.run, daemon=True).start()
    rc = app.exec_()
    toast_clear.stop()
    dismiss_desktop_notifications()
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
