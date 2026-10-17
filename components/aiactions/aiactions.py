#!/usr/bin/env python3
"""
DevOS AI actions - do something with the selected text, in any app.

    aiactions.py                     The Meta+Alt+A shortcut: reads the
                                     selected text, shows a popup near the
                                     mouse with Rewrite / Fix grammar /
                                     Shorter / More formal / Translate /
                                     Summarize / Explain / Reply / a custom
                                     prompt, streams the answer from the local
                                     model and can Replace the selection,
                                     Copy it, or Insert it below.
    aiactions.py --file PATH [--action summarize]
                                     The Dolphin "Summarize with DevOS AI"
                                     entry: same popup for a text file.
    aiactions.py --text "..."        Start with this text instead of the selection.

The selection is the X11 PRIMARY selection (whatever is highlighted); when
that is empty, Ctrl+C (Ctrl+Shift+C in terminals) is sent to the focused app
and the clipboard is read. Everything runs on this PC with the DevOS AI model
(OpenAI-compatible API on 127.0.0.1:11434); nothing leaves the computer.

Prompts are short and literal on purpose: the built-in model is small.
Everything above the GUI line imports without PyQt5 (tests run headless).
"""

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
COMPONENTS = os.path.dirname(HERE)
for _p in (HERE, os.path.join(COMPONENTS, "assistant"), os.path.join(COMPONENTS, "voicetype")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import voicetype  # noqa: E402  (xdotool / xclip helpers: Typer)

APP_NAME = "DevOS AI Actions"
HOTKEY = "Meta+Alt+A"
MAX_INPUT_CHARS = 6000          # the small model's context is limited; longer text is cut
CONTINUE_TAIL_CHARS = 1500

SYSTEM_PROMPT = ("You are DevOS AI, a writing helper on the user's PC. Do exactly what the instruction says "
                 "with the text. Reply with the result only: no introduction, no notes, no quotes.")


@dataclass(frozen=True)
class Action:
    key: str
    label: str
    instruction: str
    replaces: bool = True           # the result can stand in for the selection
    max_tokens: int = 0             # 0: from the text length
    glyph: str = "✦"


ACTIONS: List[Action] = [
    Action("rewrite", "Rewrite", "Rewrite this text so it is clear and reads well. Keep the meaning and the language.",
           glyph="✎"),
    Action("fix", "Fix grammar", "Fix the spelling, grammar and punctuation of this text. Keep the wording and the "
           "language. Change nothing else.", glyph="✓"),
    Action("shorter", "Shorter", "Make this text shorter. Keep the key points and the language.", glyph="↧"),
    Action("formal", "More formal", "Rewrite this text in a polite, formal and professional tone. Keep the meaning "
           "and the language.", glyph="◆"),
    Action("to_bn", "To Bangla", "Translate this text into Bangla (Bengali script).", glyph="অ"),
    Action("to_en", "To English", "Translate this text into English.", glyph="A"),
    Action("summarize", "Summarize", "Summarize this text in 3 to 5 short bullet points, in the same language as "
           "the text.", replaces=False, max_tokens=320, glyph="≡"),
    Action("explain", "Explain", "Explain this text in simple words for a beginner. Use 2 to 5 short sentences.",
           replaces=False, max_tokens=320, glyph="?"),
    Action("reply", "Reply", "Write a short, friendly reply to this message, in the same language as the message.",
           replaces=False, max_tokens=320, glyph="↩"),
    # Used by DevOS Notes (not shown in the popup grid)
    Action("todo", "Make to-do list", "Turn this text into a to-do list. One task per line, each line starting "
           "with \"- [ ] \". Keep the language of the text.", replaces=False, max_tokens=400, glyph="☐"),
    Action("continue", "Continue writing", "Continue this text with 2 to 4 more sentences in the same language "
           "and style. Reply with only the new sentences.", replaces=False, max_tokens=220, glyph="→"),
]
ACTION_BY_KEY: Dict[str, Action] = {a.key: a for a in ACTIONS}
POPUP_ACTIONS = ("rewrite", "fix", "shorter", "formal", "to_bn", "to_en", "summarize", "explain", "reply")
CUSTOM = "custom"


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def clip_text(text: str, limit: int = MAX_INPUT_CHARS, tail: bool = False) -> str:
    t = (text or "").replace("\r\n", "\n").strip()
    if len(t) <= limit:
        return t
    if tail:
        cut = t[-limit:]
        sp = cut.find(" ")
        return cut[sp + 1:] if 0 <= sp < 40 else cut
    cut = t[:limit]
    sp = cut.rfind(" ")
    return cut[:sp] if sp > limit - 40 else cut


def build_messages(action: str, text: str, custom: str = "") -> List[Dict[str, str]]:
    """Chat messages for the local model. action is a key of ACTION_BY_KEY or 'custom'."""
    if action == CUSTOM:
        instruction = " ".join((custom or "").split()).rstrip(".") + "."
        if instruction == ".":
            raise ValueError("empty custom prompt")
    else:
        instruction = ACTION_BY_KEY[action].instruction
    body = clip_text(text, CONTINUE_TAIL_CHARS if action == "continue" else MAX_INPUT_CHARS,
                     tail=(action == "continue"))
    if not body:
        user = instruction
    else:
        user = f"{instruction}\n\nText:\n\"\"\"\n{body}\n\"\"\""
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def max_tokens_for(action: str, text: str) -> int:
    a = ACTION_BY_KEY.get(action)
    if a is not None and a.max_tokens:
        return a.max_tokens
    # rewrites/translations are about as long as the input (Bangla needs more tokens per word)
    n = len(clip_text(text))
    factor = 1.0 if action == "to_bn" else 0.5
    return int(max(160, min(1024, 64 + n * factor)))


_PREAMBLE = re.compile(
    r"^\s*(?:sure[,!.]?\s*)?(?:here(?:'s| is| are)\b[^\n:]{0,80}:|(?:rewritten|corrected|fixed|formal|shorter|"
    r"translated|improved) (?:text|version)\s*:|translation\s*:|summary\s*:|reply\s*:|answer\s*:)\s*", re.I)


def clean_output(text: str) -> str:
    """The model's answer without chatty wrapping (Here is..., code fences, surrounding quotes)."""
    t = (text or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\n(.*?)\n?```$", r"\1", t, flags=re.S).strip()
    t = _PREAMBLE.sub("", t, count=1).strip()
    t = t.strip()
    if t.startswith('"""') and t.endswith('"""') and len(t) > 6:
        t = t[3:-3].strip()
    for q1, q2 in (('"', '"'), ("“", "”"), ("'", "'")):
        if len(t) > 2 and t.startswith(q1) and t.endswith(q2) and t.count(q1) + (t.count(q2) if q1 != q2 else 0) == 2:
            t = t[1:-1].strip()
    return t


# ---------------------------------------------------------------------------
# The local model
# ---------------------------------------------------------------------------


def ask(messages: List[Dict[str, str]], on_delta: Optional[Callable[[str], None]] = None, cancel=None,
        max_tokens: int = 384) -> str:
    """Answer from the on-device model (streamed through on_delta when given). Raises engine.ModelUnavailable."""
    import engine
    model = engine.LocalModel(engine.AI_URL, timeout=240.0)
    try:
        text = model.chat(messages, on_delta=on_delta, cancel=cancel, max_tokens=max_tokens)
    except engine.ModelUnavailable as exc:
        if str(exc) == engine.MODEL_OFFLINE:
            engine.start_ai_service()
        raise
    return clean_output(text)


def run_action(action: str, text: str, custom: str = "", on_delta=None, cancel=None, ask_fn: Callable = None) -> str:
    fn = ask_fn or ask
    return fn(build_messages(action, text, custom), on_delta=on_delta, cancel=cancel,
              max_tokens=max_tokens_for(action, text))


# ---------------------------------------------------------------------------
# Reading the selection, putting the answer back
# ---------------------------------------------------------------------------


def read_selection(typer: Optional[voicetype.Typer] = None, sleep: Callable = time.sleep,
                   copy_wait: float = 0.18) -> Tuple[str, str]:
    """(text, source). source: 'primary' (highlighted text), 'copy' (Ctrl+C fallback) or '' (nothing)."""
    typer = typer or voicetype.Typer()
    primary = typer.get_clipboard("primary")
    if primary and primary.strip():
        return primary, "primary"
    before = typer.get_clipboard("clipboard")
    if not typer.which("xdotool"):
        return "", ""
    typer.key(voicetype.copy_keys(typer.window_class()))
    sleep(copy_wait)
    after = typer.get_clipboard("clipboard")
    if after and after.strip() and after != before:
        return after, "copy"
    return "", ""


INSERT_BELOW_KEYS = ("Right", "End", "Return")


def apply_result(mode: str, text: str, window: str, typer: Optional[voicetype.Typer] = None) -> str:
    """mode: replace | insert | copy. Returns '' or a problem sentence."""
    typer = typer or voicetype.Typer()
    if not text:
        return "Nothing to use yet."
    if mode == "copy":
        return "" if typer.set_clipboard(text) else "Couldn't copy (xclip is missing)."
    if not typer.which("xdotool"):
        return voicetype.NO_XDOTOOL_TEXT
    if window:
        typer.activate(window)
    try:
        if mode == "insert":
            typer.key(*INSERT_BELOW_KEYS)
        typer.paste(text)
    except voicetype.TypingError as exc:
        return str(exc)
    return ""


def read_text_file(path: str, limit: int = MAX_INPUT_CHARS * 2) -> str:
    with open(path, "rb") as fh:
        data = fh.read(limit)
    for enc in ("utf-8", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def word_count(text: str) -> int:
    return len((text or "").split())


# ---------------------------------------------------------------------------
# GUI (PyQt5, imported lazily)
# ---------------------------------------------------------------------------

POPUP_W = 460


def _load_gui():
    import threading
    from PyQt5 import QtCore, QtGui, QtWidgets
    from PyQt5.QtCore import Qt
    import assistant as ui

    STYLE = f"""
    QWidget#card {{ background: transparent; }}
    QLabel {{ color: {ui.TEXT}; background: transparent; }}
    QLabel#title {{ color: #f8fafc; font-size: 15px; font-weight: 700; }}
    QLabel#badge {{ color: #04121a; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #38bdf8, stop:1 #818cf8);
                   border-radius: 8px; padding: 1px 7px; font-size: 10px; font-weight: 800; letter-spacing: 0.6px; }}
    QLabel#muted {{ color: {ui.MUTED}; font-size: 12px; }}
    QLabel#section {{ color: {ui.FAINT}; font-size: 10px; font-weight: 800; letter-spacing: 1px; }}
    QPlainTextEdit, QTextEdit {{ background: #0f172a; color: {ui.TEXT}; border: 1px solid #1e293b; border-radius: 10px;
                     padding: 6px 8px; font-size: 13px; selection-background-color: #0369a1; }}
    QPlainTextEdit:focus, QLineEdit:focus {{ border-color: #38bdf8; }}
    QLineEdit {{ background: #0f172a; color: {ui.TEXT}; border: 1px solid #1e293b; border-radius: 17px;
                 padding: 0 14px; font-size: 13px; min-height: 34px; }}
    QPushButton#chip {{ background: #111a2e; color: {ui.TEXT}; border: 1px solid #1e293b; border-radius: 10px;
                        padding: 0 8px; min-height: 34px; font-size: 12.5px; font-weight: 600; text-align: left; }}
    QPushButton#chip:hover {{ background: #15213a; border-color: #38bdf8; color: #f8fafc; }}
    QPushButton#chip:disabled {{ color: {ui.FAINT}; }}
    QPushButton#primary {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #38bdf8, stop:1 #818cf8);
                           color: #04121a; border: none; border-radius: 16px; padding: 0 16px; min-height: 32px;
                           font-weight: 700; }}
    QPushButton#primary:disabled {{ background: #1e293b; color: {ui.FAINT}; }}
    QPushButton#ghost {{ background: rgba(255,255,255,0.05); color: {ui.TEXT}; border: 1px solid #1e293b;
                         border-radius: 16px; padding: 0 14px; min-height: 32px; font-weight: 600; }}
    QPushButton#ghost:hover {{ border-color: #38bdf8; }}
    QPushButton#ghost:disabled {{ color: {ui.FAINT}; }}
    QPushButton#icon {{ background: transparent; border: none; color: {ui.MUTED}; font-size: 15px; min-width: 28px;
                        min-height: 28px; border-radius: 14px; }}
    QPushButton#icon:hover {{ background: rgba(255,255,255,0.08); color: #f8fafc; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; }}
    QScrollBar::handle:vertical {{ background: #334155; border-radius: 4px; min-height: 24px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """

    class Bridge(QtCore.QObject):
        delta = QtCore.pyqtSignal(int, str)
        done = QtCore.pyqtSignal(int, str, str)        # run id, text, error

    class Popup(QtWidgets.QWidget):
        def __init__(self, text="", source="", window="", file_path="", typer=None):
            super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setWindowTitle(APP_NAME)
            self.setStyleSheet(STYLE)
            self.window_id = window
            self.file_path = file_path
            self.typer = typer or voicetype.Typer()
            self.bridge = Bridge()
            self.bridge.delta.connect(self._on_delta)
            self.bridge.done.connect(self._on_done)
            self.run_id = 0
            self.cancel = None
            self.answer = ""
            self.current = ""
            self._drag = None

            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(18, 18, 18, 18)        # room for the shadow
            card = QtWidgets.QWidget()
            card.setObjectName("card")
            outer.addWidget(card)
            shadow = QtWidgets.QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(36)
            shadow.setOffset(0, 10)
            shadow.setColor(QtGui.QColor(0, 0, 0, 170))
            card.setGraphicsEffect(shadow)
            self.card = card
            lay = QtWidgets.QVBoxLayout(card)
            lay.setContentsMargins(16, 14, 16, 16)
            lay.setSpacing(10)

            head = QtWidgets.QHBoxLayout()
            head.setSpacing(9)
            logo = QtWidgets.QLabel()
            logo.setPixmap(ui.logo_pixmap(26))
            head.addWidget(logo)
            title = QtWidgets.QLabel("DevOS AI")
            title.setObjectName("title")
            head.addWidget(title)
            badge = QtWidgets.QLabel("AI · ON THIS PC")
            badge.setObjectName("badge")
            head.addWidget(badge)
            head.addStretch(1)
            close = QtWidgets.QPushButton("✕")
            close.setObjectName("icon")
            close.setCursor(Qt.PointingHandCursor)
            close.setToolTip("Close (Esc)")
            close.clicked.connect(self.close)
            head.addWidget(close)
            lay.addLayout(head)

            self.src_label = QtWidgets.QLabel()
            self.src_label.setObjectName("section")
            lay.addWidget(self.src_label)
            self.src = QtWidgets.QPlainTextEdit()
            self.src.setPlaceholderText("Select text in any app first, or type / paste it here…")
            self.src.setPlainText(text)
            self.src.setFixedHeight(74)
            self.src.textChanged.connect(self._src_changed)
            lay.addWidget(self.src)

            self.grid_box = QtWidgets.QWidget()
            grid = QtWidgets.QGridLayout(self.grid_box)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(8)
            self.chips = []
            for i, key in enumerate(POPUP_ACTIONS):
                a = ACTION_BY_KEY[key]
                b = QtWidgets.QPushButton(f"  {a.glyph}   {a.label}")
                b.setObjectName("chip")
                b.setCursor(Qt.PointingHandCursor)
                b.setToolTip(f"{a.label} ({i + 1})")
                b.clicked.connect(lambda _c=False, k=key: self.start(k))
                grid.addWidget(b, i // 3, i % 3)
                self.chips.append(b)
            lay.addWidget(self.grid_box)

            self.prompt = QtWidgets.QLineEdit()
            self.prompt.setPlaceholderText("Ask AI to…  e.g. make it friendlier, add emojis  (Enter)")
            self.prompt.returnPressed.connect(self._custom)
            lay.addWidget(self.prompt)

            self.result_box = QtWidgets.QWidget()
            rl = QtWidgets.QVBoxLayout(self.result_box)
            rl.setContentsMargins(0, 2, 0, 0)
            rl.setSpacing(8)
            rh = QtWidgets.QHBoxLayout()
            self.result_label = QtWidgets.QLabel("RESULT")
            self.result_label.setObjectName("section")
            rh.addWidget(self.result_label)
            rh.addStretch(1)
            self.status = QtWidgets.QLabel("")
            self.status.setObjectName("muted")
            rh.addWidget(self.status)
            rl.addLayout(rh)
            self.result = QtWidgets.QPlainTextEdit()
            self.result.setReadOnly(False)
            self.result.setMinimumHeight(130)
            self.result.setStyleSheet("QPlainTextEdit { background: #0b1324; border: 1px solid #1d3b5c; "
                                      "font-size: 13.5px; }")
            rl.addWidget(self.result, 1)
            btns = QtWidgets.QHBoxLayout()
            btns.setSpacing(8)
            self.back_btn = QtWidgets.QPushButton("← Actions")
            self.back_btn.setObjectName("ghost")
            self.back_btn.clicked.connect(self.back)
            btns.addWidget(self.back_btn)
            self.stop_btn = QtWidgets.QPushButton("Stop")
            self.stop_btn.setObjectName("ghost")
            self.stop_btn.clicked.connect(self.stop)
            btns.addWidget(self.stop_btn)
            btns.addStretch(1)
            self.copy_btn = QtWidgets.QPushButton("Copy")
            self.copy_btn.setObjectName("ghost")
            self.copy_btn.clicked.connect(lambda: self.use("copy"))
            btns.addWidget(self.copy_btn)
            self.insert_btn = QtWidgets.QPushButton("Insert below")
            self.insert_btn.setObjectName("ghost")
            self.insert_btn.clicked.connect(lambda: self.use("insert"))
            btns.addWidget(self.insert_btn)
            self.replace_btn = QtWidgets.QPushButton("Replace")
            self.replace_btn.setObjectName("primary")
            self.replace_btn.setToolTip("Replace the selected text (Ctrl+Enter)")
            self.replace_btn.clicked.connect(lambda: self.use("replace"))
            btns.addWidget(self.replace_btn)
            for b in (self.back_btn, self.stop_btn, self.copy_btn, self.insert_btn, self.replace_btn):
                b.setCursor(Qt.PointingHandCursor)
            if file_path:
                self.insert_btn.hide()
                self.replace_btn.hide()
            rl.addLayout(btns)
            lay.addWidget(self.result_box)
            self.result_box.hide()

            foot = QtWidgets.QLabel("Runs on this PC with the DevOS AI model · nothing is sent online")
            foot.setObjectName("muted")
            foot.setStyleSheet(f"color: {ui.FAINT}; font-size: 11px;")
            lay.addWidget(foot)
            self.foot = foot

            QtWidgets.QShortcut(QtGui.QKeySequence("Escape"), self, self.close)
            QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Return"), self, lambda: self.use("replace"))
            for i, key in enumerate(POPUP_ACTIONS):
                sc = QtWidgets.QShortcut(QtGui.QKeySequence(f"Alt+{i + 1}"), self)
                sc.activated.connect(lambda k=key: self.start(k))
            self.setFixedWidth(POPUP_W + 36)
            self._src_changed()
            self.source = source
            self._label_source()

        # -- painting / moving ----------------------------------------------------
        def paintEvent(self, _e):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            r = QtCore.QRectF(self.card.geometry()).adjusted(0.5, 0.5, -0.5, -0.5)
            p.setPen(Qt.NoPen)
            p.setBrush(QtGui.QColor("#0b0f1a"))
            p.drawRoundedRect(r, 16, 16)
            g = QtGui.QLinearGradient(r.topLeft(), r.topRight())
            g.setColorAt(0, QtGui.QColor(56, 189, 248, 150))
            g.setColorAt(1, QtGui.QColor(129, 140, 248, 120))
            p.setPen(QtGui.QPen(QtGui.QBrush(g), 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 16, 16)
            p.end()

        def mousePressEvent(self, e):
            if e.button() == Qt.LeftButton:
                self._drag = e.globalPos() - self.frameGeometry().topLeft()

        def mouseMoveEvent(self, e):
            if self._drag is not None and e.buttons() & Qt.LeftButton:
                self.move(e.globalPos() - self._drag)

        def mouseReleaseEvent(self, _e):
            self._drag = None

        def place_near(self, pos):
            self.adjustSize()
            scr = QtWidgets.QApplication.screenAt(pos) or QtWidgets.QApplication.primaryScreen()
            g = scr.availableGeometry() if scr else QtCore.QRect(0, 0, 1920, 1080)
            x = min(max(g.left() + 4, pos.x() - 30), g.right() - self.width() - 4)
            y = pos.y() + 14
            if y + self.height() > g.bottom() - 4:
                y = max(g.top() + 4, pos.y() - self.height() - 14)
            self.move(x, y)

        # -- state -------------------------------------------------------------
        def _label_source(self):
            n = word_count(self.src.toPlainText())
            where = {"primary": "SELECTED TEXT", "copy": "SELECTED TEXT", "file": "FILE"}.get(self.source, "TEXT")
            if self.file_path:
                where = "FILE · " + os.path.basename(self.file_path).upper()
            self.src_label.setText(f"{where} · {n} WORD{'S' if n != 1 else ''}" if n else "NO TEXT SELECTED")

        def _src_changed(self):
            has = bool(self.src.toPlainText().strip())
            for b in self.chips:
                b.setEnabled(has)
            if hasattr(self, "source"):
                self._label_source()

        def _custom(self):
            if self.prompt.text().strip():
                self.start(CUSTOM)

        def start(self, key):
            text = self.src.toPlainText()
            if not text.strip() and key != CUSTOM:
                return
            import engine
            if self.cancel is not None:
                self.cancel.stop()
            self.run_id += 1
            rid = self.run_id
            self.current = key
            self.answer = ""
            self.cancel = engine.StreamHandle()
            label = ACTION_BY_KEY[key].label if key != CUSTOM else self.prompt.text().strip()
            self.result_label.setText(("AI · " + label).upper()[:48])
            self.result.setPlainText("")
            self.result.setPlaceholderText("DevOS AI is writing…")
            self.status.setText("Writing…")
            replaces = key == CUSTOM or ACTION_BY_KEY[key].replaces
            self.replace_btn.setText("Replace" if replaces else "Replace anyway")
            self.replace_btn.setObjectName("primary" if replaces else "ghost")
            self.replace_btn.style().unpolish(self.replace_btn)
            self.replace_btn.style().polish(self.replace_btn)
            for b in (self.copy_btn, self.insert_btn, self.replace_btn):
                b.setEnabled(False)
            self.stop_btn.show()
            self.grid_box.hide()
            self.src.setFixedHeight(54)
            self.result_box.show()
            self.adjustSize()
            custom = self.prompt.text()
            cancel = self.cancel

            def job():
                try:
                    out = run_action(key, text, custom, on_delta=lambda d: self.bridge.delta.emit(rid, d),
                                     cancel=cancel)
                    self.bridge.done.emit(rid, out, "")
                except Exception as exc:
                    self.bridge.done.emit(rid, "", str(exc) or "DevOS AI didn't answer.")
            threading.Thread(target=job, daemon=True).start()

        def _on_delta(self, rid, piece):
            if rid != self.run_id:
                return
            self.answer += piece
            self.result.setPlainText(self.answer.lstrip())
            self.result.moveCursor(QtGui.QTextCursor.End)

        def _on_done(self, rid, text, error):
            if rid != self.run_id:
                return
            self.stop_btn.hide()
            if error and not self.answer:
                self.status.setText("")
                self.result.setPlainText("")
                self.result.setPlaceholderText(error)
                return
            final = text or clean_output(self.answer)
            self.result.setPlainText(final)
            self.status.setText(f"{word_count(final)} words")
            for b in (self.copy_btn, self.insert_btn, self.replace_btn):
                b.setEnabled(bool(final))

        def stop(self):
            if self.cancel is not None:
                self.cancel.stop()
            self.status.setText("Stopped")

        def back(self):
            self.stop()
            self.run_id += 1
            self.result_box.hide()
            self.grid_box.show()
            self.src.setFixedHeight(74)
            self.adjustSize()

        def use(self, mode):
            text = self.result.toPlainText().strip()
            if not text or (mode != "copy" and self.file_path):
                return
            if mode == "copy":
                problem = apply_result("copy", text, "", self.typer)
                if not problem:
                    QtWidgets.QApplication.clipboard().setText(text)
                self.status.setText(problem or "Copied ✓")
                return
            self.hide()
            QtWidgets.QApplication.processEvents()
            problem = apply_result(mode, text, self.window_id, self.typer)
            if problem:
                self.show()
                self.status.setText(problem)
                return
            QtCore.QTimer.singleShot(150, self.close)

        def closeEvent(self, e):
            if self.cancel is not None:
                self.cancel.stop()
            super().closeEvent(e)

    return QtCore, QtGui, QtWidgets, Popup


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    p = argparse.ArgumentParser(description="DevOS AI actions on the selected text")
    p.add_argument("--file", help="work on this text file (Dolphin service menu)")
    p.add_argument("--action", choices=list(ACTION_BY_KEY), help="start this action at once")
    p.add_argument("--text", help="start with this text instead of the selection")
    ns = p.parse_args(argv[1:])

    typer = voicetype.Typer()
    window = ""
    source = ""
    if ns.file:
        try:
            text = clip_text(read_text_file(ns.file))
        except OSError as exc:
            text = ""
            print(f"Can't read {ns.file}: {exc}", file=sys.stderr)
        source = "file"
    elif ns.text is not None:
        text, source = ns.text, "text"
    else:
        window = typer.active_window()
        text, source = read_selection(typer)

    QtCore, QtGui, QtWidgets, Popup = _load_gui()
    import listen
    app = listen.make_app(argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(True)
    pop = Popup(text, source, window, ns.file or "", typer)
    if ns.file:
        scr = QtWidgets.QApplication.primaryScreen()
        pop.adjustSize()
        if scr:
            g = scr.availableGeometry()
            pop.move(g.x() + (g.width() - pop.width()) // 2, g.y() + (g.height() - pop.height()) // 3)
    else:
        pop.place_near(QtGui.QCursor.pos())
    pop.show()
    pop.raise_()
    pop.activateWindow()
    if ns.action:
        pop.start(ns.action)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
