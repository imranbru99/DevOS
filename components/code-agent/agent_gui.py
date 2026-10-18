#!/usr/bin/env python3
"""
DevOS AI Code Agent window: chat with a coding agent that runs on the local DevOS
AI model, watch its plan, and accept or reject every file change and command.

The agent (code_agent.CodeAgent) runs in a worker thread. When it needs an
approval it asks the window through a signal and waits; the Accept / Reject
and Run / Deny buttons answer it.
"""

import html
import os
import re
import shutil
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import capability  # noqa: E402
import code_agent as core  # noqa: E402

from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: E402

MODELS_GUI = os.path.join(os.path.dirname(HERE), "ai-core", "models_gui.py")

BG = "#0b0f1a"
CARD = "#0f172a"
LINE = "#1e293b"
TEXT = "#e2e8f0"
MUTED = "#94a3b8"
ACCENT = "#38bdf8"
VIOLET = "#a78bfa"
GOOD = "#34d399"
BAD = "#f87171"

STYLE = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-family: 'Inter', 'Noto Sans', sans-serif; font-size: 14px; }}
QLabel {{ background: transparent; }}
QLabel#title {{ font-size: 19px; font-weight: 700; color: #f8fafc; }}
QLabel#muted, QLabel#path {{ color: {MUTED}; }}
QLabel#cardTitle {{ font-size: 12px; font-weight: 700; color: {MUTED}; letter-spacing: 1px; }}
QLabel#badge {{ background: #052e2b; color: #5eead4; border: 1px solid #115e59; border-radius: 11px;
               padding: 3px 12px; font-size: 12px; font-weight: 600; }}
QLabel#chip {{ background: #1e1b4b; color: #c4b5fd; border: 1px solid #3730a3; border-radius: 9px;
              padding: 2px 10px; font-size: 12px; }}
QFrame#topbar {{ background: #0d1424; border-bottom: 1px solid {LINE}; }}
QFrame#card {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 14px; }}
QFrame#card[attention="true"] {{ border: 1px solid {ACCENT}; }}
QFrame#gate {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 18px; }}
QPushButton {{ background: #1e293b; border: 1px solid #334155; border-radius: 9px; padding: 7px 14px;
              color: {TEXT}; }}
QPushButton:hover {{ background: #273449; }}
QPushButton:disabled {{ color: #475569; background: #111827; border-color: #1f2937; }}
QPushButton#primary {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #7c3aed);
                      border: 1px solid #38bdf8; color: white; font-weight: 600; padding: 8px 18px; }}
QPushButton#primary:disabled {{ background: #1e293b; border-color: #334155; color: #64748b; }}
QPushButton#accept {{ background: #064e3b; border-color: #10b981; color: #d1fae5; font-weight: 600; }}
QPushButton#reject {{ background: #450a0a; border-color: #ef4444; color: #fee2e2; }}
QPushButton#accept:disabled, QPushButton#reject:disabled {{ background: #111827; border-color: #1f2937;
                                                           color: #475569; }}
QTextBrowser, QPlainTextEdit, QListWidget {{ background: #0a0f1c; border: 1px solid {LINE}; border-radius: 10px;
                                            padding: 6px; selection-background-color: #1d4ed8; }}
QPlainTextEdit#composer {{ background: #0a1222; border: 1px solid #334155; border-radius: 12px; padding: 8px;
                          font-size: 14px; }}
QPlainTextEdit#composer:focus {{ border: 1px solid {ACCENT}; }}
QPlainTextEdit#terminal {{ font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace; font-size: 12px;
                          color: #cbd5e1; background: #05080f; }}
QListWidget::item {{ padding: 5px 4px; border-radius: 6px; }}
QListWidget::item:selected {{ background: #172554; }}
QCheckBox {{ background: transparent; color: {MUTED}; spacing: 7px; }}
QCheckBox::indicator {{ width: 30px; height: 16px; border-radius: 8px; background: #334155; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; }}
QSplitter::handle {{ background: {BG}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #334155; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QStatusBar, QLabel#status {{ color: {MUTED}; font-size: 12px; }}
"""

STEP_ICON = {"running": "○", "done": "✓", "denied": "✕", "failed": "!", "plan": "•"}
STEP_COLOR = {"running": ACCENT, "done": GOOD, "denied": BAD, "failed": "#fbbf24", "plan": MUTED}


def card(title: str):
    frame = QtWidgets.QFrame()
    frame.setObjectName("card")
    layout = QtWidgets.QVBoxLayout(frame)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(8)
    header = QtWidgets.QHBoxLayout()
    label = QtWidgets.QLabel(title.upper())
    label.setObjectName("cardTitle")
    header.addWidget(label)
    header.addStretch(1)
    layout.addLayout(header)
    return frame, layout, header


def diff_html(diff: str) -> str:
    rows = []
    for line in diff.splitlines():
        text = html.escape(line) or "&nbsp;"
        if line.startswith("+++") or line.startswith("---"):
            style = f"color:{MUTED};"
        elif line.startswith("+"):
            style = "background-color:#06301f; color:#a7f3d0;"
        elif line.startswith("-"):
            style = "background-color:#3a0d14; color:#fecaca;"
        elif line.startswith("@@"):
            style = f"color:{VIOLET};"
        else:
            style = "color:#cbd5e1;"
        rows.append(f'<tr><td style="{style} padding:0 6px; white-space:pre;">{text}</td></tr>')
    return ("<table width='100%' cellspacing='0' cellpadding='0' style=\"font-family:'JetBrains Mono',"
            "'DejaVu Sans Mono',monospace; font-size:12px;\">" + "".join(rows) + "</table>")


_TOOL_BLOCK = re.compile(r"```[ \t]*tool[ \t]*([^\n]*)\n.*?(?:\n```|\Z)|<tool_call>.*?(?:</tool_call>|\Z)", re.S)
_CODE_BLOCK = re.compile(r"```[^\n]*\n(.*?)(?:\n```|\Z)", re.S)


def message_html(text: str) -> str:
    """Model text for the chat: tool blocks become small chips, code blocks <pre>."""
    pieces = []
    pos = 0
    for match in _TOOL_BLOCK.finditer(text):
        pieces.append(("text", text[pos:match.start()]))
        call = core.parse_tool_call(match.group(0))
        label = call.name.replace("_", " ") if call else "tool"
        target = ""
        if call:
            target = str(call.args.get("path") or call.args.get("pattern") or call.args.get("command") or "")
            if call.name == "apply_patch":
                target = ", ".join(re.findall(r"^\+\+\+ (?:b/)?(\S+)", str(call.args.get("patch", "")), re.M))
        pieces.append(("tool", f"{label}  {target}".strip()))
        pos = match.end()
    pieces.append(("text", text[pos:]))
    out = []
    for kind, value in pieces:
        if kind == "tool":
            out.append(f'<p><span style="background-color:#1e1b4b; color:#c4b5fd;">&nbsp;▸ '
                       f'{html.escape(value[:90])}&nbsp;</span></p>')
            continue
        last = 0
        for code in _CODE_BLOCK.finditer(value):
            out.append(_prose(value[last:code.start()]))
            out.append('<pre style="background-color:#05080f; color:#e2e8f0; font-family:\'JetBrains Mono\','
                       f'monospace; font-size:12px;">{html.escape(code.group(1))}</pre>')
            last = code.end()
        out.append(_prose(value[last:]))
    return "".join(out)


def _prose(text: str) -> str:
    text = text.strip("\n")
    if not text.strip():
        return ""
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`\n]+)`", r'<code style="color:#7dd3fc;">\1</code>', escaped)
    escaped = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", escaped)
    return "<p>" + escaped.replace("\n", "<br>") + "</p>"


class AgentWorker(QtCore.QThread):
    event = QtCore.pyqtSignal(str, object)
    approval = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, folder, task, policy, llm=None):
        super().__init__()
        self.folder = folder
        self.task = task
        self.policy = policy
        self.llm = llm or core.LocalLLM()
        self._answer = False
        self._answered = threading.Event()
        self.agent = None

    def ask(self, action) -> bool:
        self._answered.clear()
        self.approval.emit(action)
        while not self._answered.wait(0.2):
            if self.agent and self.agent.cancelled:
                return False
        return self._answer

    def answer(self, ok: bool) -> None:
        self._answer = ok
        self._answered.set()

    def cancel(self) -> None:
        if self.agent:
            self.agent.cancel()
        self.answer(False)

    def run(self):
        try:
            workspace = core.Workspace(self.folder)
            self.agent = core.CodeAgent(workspace, self.llm, self.ask, self.policy,
                                        on_event=lambda kind, payload=None: self.event.emit(kind, payload))
            self.agent.run(self.task)
        except core.AgentError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # keep the window alive, show what happened
            self.failed.emit(f"The agent stopped: {exc}")


class GatePanel(QtWidgets.QWidget):
    """Shown instead of the agent when this PC's AI is too small for coding."""

    def __init__(self, reason: str, recheck):
        super().__init__()
        outer = QtWidgets.QVBoxLayout(self)
        outer.addStretch(1)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        box = QtWidgets.QFrame()
        box.setObjectName("gate")
        box.setFixedWidth(560)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)
        title = QtWidgets.QLabel("Coding needs a stronger DevOS AI")
        title.setObjectName("title")
        layout.addWidget(title)
        text = QtWidgets.QLabel(reason)
        text.setObjectName("muted")
        text.setWordWrap(True)
        layout.addWidget(text)
        hint = QtWidgets.QLabel("Everything runs on this PC, so the agent appears once the Coding model or a "
                                "Medium (3B) or bigger model is downloaded.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QtWidgets.QHBoxLayout()
        open_models = QtWidgets.QPushButton("Open DevOS AI Models")
        open_models.setObjectName("primary")
        open_models.clicked.connect(lambda: QtCore.QProcess.startDetached(
            sys.executable or "python3", [MODELS_GUI]))
        again = QtWidgets.QPushButton("Check again")
        again.clicked.connect(recheck)
        buttons.addWidget(open_models)
        buttons.addWidget(again)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        row.addWidget(box)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)


class AgentWindow(QtWidgets.QMainWindow):
    def __init__(self, folder: str = "", capable=None, llm=None):
        super().__init__()
        self.setWindowTitle("DevOS AI Code Agent")
        self.resize(1320, 840)
        self.setStyleSheet(STYLE)
        self.folder = os.path.abspath(folder) if folder else ""
        self.policy = core.ApprovalPolicy(auto_reads=True, auto_edits=False)
        self.llm = llm
        self.worker = None
        self.pending = None
        self.transcript = []  # [role, text]
        self._dirty = False
        self._capable_override = capable
        self._render_timer = QtCore.QTimer(self)
        self._render_timer.setInterval(60)
        self._render_timer.timeout.connect(self._render_if_dirty)
        self._render_timer.start()

        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        self.root_layout = QtWidgets.QVBoxLayout(root)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)
        self.root_layout.addWidget(self._topbar())
        self.stack = QtWidgets.QStackedWidget()
        self.root_layout.addWidget(self.stack, 1)
        self.main = self._main_panel()
        self.stack.addWidget(self.main)
        self.status = QtWidgets.QLabel()
        self.status.setObjectName("status")
        self.status.setContentsMargins(18, 6, 18, 8)
        self.root_layout.addWidget(self.status)
        self.check_capable()
        self.set_folder(self.folder)

    # --------------------------------------------------------------- layout
    def _topbar(self):
        bar = QtWidgets.QFrame()
        bar.setObjectName("topbar")
        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(18, 12, 18, 12)
        row.setSpacing(12)
        mark = QtWidgets.QLabel()
        mark.setFixedSize(30, 30)
        mark.setStyleSheet("border-radius: 9px; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                           "stop:0 #38bdf8, stop:1 #8b5cf6); color: white; font-weight: 800;")
        mark.setAlignment(QtCore.Qt.AlignCenter)
        mark.setText("</>")
        row.addWidget(mark)
        names = QtWidgets.QVBoxLayout()
        names.setSpacing(0)
        title = QtWidgets.QLabel("DevOS AI Code Agent")
        title.setObjectName("title")
        self.path_label = QtWidgets.QLabel("No folder open")
        self.path_label.setObjectName("path")
        names.addWidget(title)
        names.addWidget(self.path_label)
        row.addLayout(names)
        row.addSpacing(8)
        badge = QtWidgets.QLabel(f"●  Local · {core.CODE_MODEL}")
        badge.setObjectName("badge")
        badge.setToolTip("Runs on this PC's DevOS AI. Nothing is sent to the internet.")
        row.addWidget(badge)
        row.addStretch(1)
        self.auto_reads = QtWidgets.QCheckBox("Auto-approve reads")
        self.auto_reads.setChecked(True)
        self.auto_reads.toggled.connect(self._policy_changed)
        self.auto_edits = QtWidgets.QCheckBox("Auto-approve edits")
        self.auto_edits.toggled.connect(self._policy_changed)
        row.addWidget(self.auto_reads)
        row.addWidget(self.auto_edits)
        self.open_btn = QtWidgets.QPushButton("Open folder…")
        self.open_btn.clicked.connect(self.choose_folder)
        row.addWidget(self.open_btn)
        return bar

    def _main_panel(self):
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 6)
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        split.setHandleWidth(12)
        layout.addWidget(split)

        # chat
        chat_card, chat_layout, chat_header = card("Chat")
        self.step_chip = QtWidgets.QLabel("Idle")
        self.step_chip.setObjectName("chip")
        chat_header.addWidget(self.step_chip)
        self.chat = QtWidgets.QTextBrowser()
        self.chat.setOpenExternalLinks(False)
        chat_layout.addWidget(self.chat, 1)
        self.composer = QtWidgets.QPlainTextEdit()
        self.composer.setObjectName("composer")
        self.composer.setPlaceholderText("Describe a change…  e.g. “Add a --verbose flag to cli.py "
                                         "and a test for it”   (Ctrl+Enter to run)")
        self.composer.setFixedHeight(84)
        chat_layout.addWidget(self.composer)
        actions = QtWidgets.QHBoxLayout()
        hint = QtWidgets.QLabel("Reads run on their own · edits and commands wait for you")
        hint.setObjectName("muted")
        hint.setStyleSheet("font-size: 12px;")
        actions.addWidget(hint)
        actions.addStretch(1)
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        self.send_btn = QtWidgets.QPushButton("Run agent")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(self.send)
        actions.addWidget(self.stop_btn)
        actions.addWidget(self.send_btn)
        chat_layout.addLayout(actions)
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Return"), self.composer, activated=self.send)
        split.addWidget(chat_card)

        # right column
        right = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        right.setHandleWidth(12)
        plan_card, plan_layout, _ = card("Plan & steps")
        self.plan = QtWidgets.QListWidget()
        self.plan.setFocusPolicy(QtCore.Qt.NoFocus)
        plan_layout.addWidget(self.plan)
        right.addWidget(plan_card)

        self.diff_card, diff_layout, diff_header = card("Changes")
        self.diff_title = QtWidgets.QLabel("No changes yet")
        self.diff_title.setObjectName("muted")
        diff_header.addWidget(self.diff_title)
        self.diff = QtWidgets.QTextBrowser()
        diff_layout.addWidget(self.diff, 1)
        diff_buttons = QtWidgets.QHBoxLayout()
        diff_buttons.addStretch(1)
        self.reject_btn = QtWidgets.QPushButton("Reject")
        self.reject_btn.setObjectName("reject")
        self.accept_btn = QtWidgets.QPushButton("Accept change")
        self.accept_btn.setObjectName("accept")
        self.reject_btn.clicked.connect(lambda: self.respond(False))
        self.accept_btn.clicked.connect(lambda: self.respond(True))
        diff_buttons.addWidget(self.reject_btn)
        diff_buttons.addWidget(self.accept_btn)
        diff_layout.addLayout(diff_buttons)
        right.addWidget(self.diff_card)

        self.term_card, term_layout, term_header = card("Terminal")
        self.command_label = QtWidgets.QLabel("")
        self.command_label.setStyleSheet("color: #fde68a; font-family: 'JetBrains Mono', monospace;")
        term_header.addWidget(self.command_label)
        self.terminal = QtWidgets.QPlainTextEdit()
        self.terminal.setObjectName("terminal")
        self.terminal.setReadOnly(True)
        term_layout.addWidget(self.terminal, 1)
        term_buttons = QtWidgets.QHBoxLayout()
        term_note = QtWidgets.QLabel("Commands run in the project folder and always ask first")
        term_note.setObjectName("muted")
        term_note.setStyleSheet("font-size: 12px;")
        term_buttons.addWidget(term_note)
        term_buttons.addStretch(1)
        self.deny_btn = QtWidgets.QPushButton("Deny")
        self.deny_btn.setObjectName("reject")
        self.run_btn = QtWidgets.QPushButton("Run command")
        self.run_btn.setObjectName("accept")
        self.deny_btn.clicked.connect(lambda: self.respond(False))
        self.run_btn.clicked.connect(lambda: self.respond(True))
        term_buttons.addWidget(self.deny_btn)
        term_buttons.addWidget(self.run_btn)
        term_layout.addLayout(term_buttons)
        right.addWidget(self.term_card)
        right.setSizes([250, 360, 230])
        split.addWidget(right)
        split.setSizes([700, 600])
        self._set_pending(None)
        return panel

    # ---------------------------------------------------------------- gating
    def check_capable(self):
        ok, reason = self._capable_override if self._capable_override else capability.coding_capable()
        if ok:
            self.stack.setCurrentWidget(self.main)
            self.composer.setEnabled(True)
        else:
            gate = GatePanel(reason, self._recheck)
            self.stack.addWidget(gate)
            self.stack.setCurrentWidget(gate)
        self.capable = ok
        for widget in (self.auto_reads, self.auto_edits, self.open_btn):
            widget.setVisible(ok)
        self._update_status()

    def _recheck(self):
        self._capable_override = None
        current = self.stack.currentWidget()
        self.check_capable()
        if self.capable and current is not self.main:
            self.stack.removeWidget(current)

    # --------------------------------------------------------------- folder
    def choose_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Open project folder",
                                                            self.folder or os.path.expanduser("~"))
        if folder:
            self.set_folder(folder)

    def set_folder(self, folder: str):
        self.folder = folder
        self.path_label.setText(folder or "No folder open — choose one to start")
        self.transcript = []
        if folder:
            notes = ""
            try:
                notes = core.Workspace(folder).read_notes(400)
            except core.ToolError:
                pass
            intro = (f"Ready to work in **{os.path.basename(folder) or folder}**. Tell me what to build or fix; "
                     "I will plan it, read the code, and show every change for you to accept.")
            if notes:
                intro += "\n\nI keep notes about this project in `.devos/agent-notes.md`."
            self.transcript.append(["agent", intro])
        else:
            self.transcript.append(["agent", "Open a project folder to start. I only read and change files "
                                             "inside the folder you choose."])
        self._dirty = True
        self._update_status()

    # ----------------------------------------------------------------- chat
    def _render_if_dirty(self):
        if not self._dirty:
            return
        self._dirty = False
        parts = []
        for role, text in self.transcript:
            if role == "user":
                parts.append('<table width="100%" cellspacing="0" cellpadding="10" style="margin:6px 0;">'
                             '<tr><td width="18%"></td><td style="background-color:#13233f; color:#e0f2fe;">'
                             f'{_prose(text) or "&nbsp;"}</td></tr></table>')
            elif role == "error":
                parts.append(f'<p style="color:{BAD};">{html.escape(text)}</p>')
            elif role == "note":
                parts.append(f'<p style="color:{MUTED}; font-size:12px;">{html.escape(text)}</p>')
            else:
                parts.append('<table width="100%" cellspacing="0" cellpadding="4" style="margin:6px 0;"><tr>'
                             f'<td style="color:{TEXT};"><span style="color:{ACCENT}; font-weight:600;">'
                             f'DevOS AI Code Agent</span>{message_html(text) or "<p>&hellip;</p>"}</td></tr></table>')
        bar = self.chat.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 40
        self.chat.setHtml("".join(parts))
        if at_bottom:
            bar.setValue(bar.maximum())

    def send(self):
        task = self.composer.toPlainText().strip()
        if not task or self.worker or not self.capable:
            return
        if not self.folder:
            self.choose_folder()
            if not self.folder:
                return
        self.composer.clear()
        self.transcript.append(["user", task])
        self.transcript.append(["agent", ""])
        self.plan.clear()
        self._dirty = True
        self.worker = AgentWorker(self.folder, task, self.policy, self.llm)
        self.worker.event.connect(self.on_event)
        self.worker.approval.connect(self.on_approval)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.on_finished)
        self.send_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.step_chip.setText("Thinking…")
        self.worker.start()

    def stop(self):
        if self.worker:
            self.worker.cancel()
            self.step_chip.setText("Stopping…")
        self._set_pending(None)

    def on_event(self, kind, payload):
        if kind == "thinking":
            self.step_chip.setText(f"Step {payload} · thinking")
            last = self.transcript[-1] if self.transcript else None
            if last is None or last[0] != "agent" or last[1]:
                self.transcript.append(["agent", ""])
        elif kind == "token":
            if not self.transcript or self.transcript[-1][0] != "agent":
                self.transcript.append(["agent", ""])
            self.transcript[-1][1] += payload
            self._dirty = True
        elif kind == "plan":
            for step in payload:
                self._add_step(step, "plan")
        elif kind == "step":
            self._add_step(payload["title"], "running")
        elif kind == "step_status":
            self._mark_last_step(payload)
        elif kind == "change":
            self._show_change(payload)
        elif kind == "change_status":
            state = "applied" if payload["applied"] else "rejected"
            self.diff_title.setText(f"{payload['path']} · {state}")
        elif kind == "command":
            self.command_label.setText("$ " + payload.command[:80])
        elif kind == "output":
            self.terminal.appendPlainText(payload["output"].rstrip() or "(no output)")
            suffix = " · timed out" if payload["timed_out"] else ""
            self.terminal.appendPlainText(f"[exit {payload['code']}{suffix}]\n")
        elif kind == "done":
            if self.transcript and self.transcript[-1] == ["agent", ""]:
                self.transcript[-1][1] = payload or "Done."
            self.transcript.append(["note", "Finished. Notes saved to .devos/agent-notes.md."])
            self._dirty = True

    def on_approval(self, action):
        self.pending = action
        if action.kind == "read":
            answer = QtWidgets.QMessageBox.question(self, "Allow reading?", f"{action.title}?")
            self.respond(answer == QtWidgets.QMessageBox.Yes)
            return
        if action.kind == "edit":
            self._show_change(action)
        else:
            self.command_label.setText("$ " + action.command[:80])
            self.terminal.appendPlainText(f"$ {action.command}")
        self._set_pending(action)
        self.step_chip.setText("Waiting for you")
        QtWidgets.QApplication.alert(self)

    def respond(self, ok: bool):
        if self.worker and self.pending is not None:
            self.worker.answer(ok)
        if self.pending is not None and self.pending.kind == "command" and not ok:
            self.terminal.appendPlainText("(denied)\n")
        self.pending = None
        self._set_pending(None)
        if self.worker:
            self.step_chip.setText("Working…")

    def on_failed(self, message):
        self.transcript.append(["error", message])
        self._dirty = True

    def on_finished(self):
        self.worker = None
        self.pending = None
        self._set_pending(None)
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.step_chip.setText("Idle")

    # -------------------------------------------------------------- helpers
    def _show_change(self, action):
        self.diff_title.setText(action.title)
        self.diff.setHtml(diff_html(action.diff))

    def _set_pending(self, action):
        edit = bool(action and action.kind == "edit")
        command = bool(action and action.kind == "command")
        self.accept_btn.setEnabled(edit)
        self.reject_btn.setEnabled(edit)
        self.run_btn.setEnabled(command)
        self.deny_btn.setEnabled(command)
        for frame, on in ((self.diff_card, edit), (self.term_card, command)):
            frame.setProperty("attention", "true" if on else "false")
            frame.style().unpolish(frame)
            frame.style().polish(frame)

    def _add_step(self, title, state):
        item = QtWidgets.QListWidgetItem(f"{STEP_ICON[state]}  {title[:90]}")
        item.setData(QtCore.Qt.UserRole, title)
        item.setForeground(QtGui.QColor(STEP_COLOR[state] if state != "plan" else TEXT))
        self.plan.addItem(item)
        self.plan.scrollToBottom()

    def _mark_last_step(self, state):
        for row in range(self.plan.count() - 1, -1, -1):
            item = self.plan.item(row)
            if item.text().startswith(STEP_ICON["running"]):
                item.setText(f"{STEP_ICON.get(state, '?')}  {item.data(QtCore.Qt.UserRole)[:90]}")
                item.setForeground(QtGui.QColor(STEP_COLOR.get(state, MUTED)))
                return

    def _policy_changed(self):
        self.policy.auto_reads = self.auto_reads.isChecked()
        self.policy.auto_edits = self.auto_edits.isChecked()
        self._update_status()

    def _update_status(self):
        if not getattr(self, "capable", True):
            self.status.setText("DevOS AI Code Agent is waiting for a coding-capable DevOS AI model.")
            return
        rg = "ripgrep search" if shutil.which("rg") else "built-in search"
        self.status.setText(
            f"Local only · {'reads automatic' if self.policy.auto_reads else 'reads ask'} · "
            f"{'edits automatic' if self.policy.auto_edits else 'edits ask'} · commands always ask · {rg}")

    def closeEvent(self, event):
        if self.worker:
            self.worker.cancel()
            self.worker.wait(3000)
        super().closeEvent(event)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([sys.argv[0]])
    app.setApplicationName("DevOS AI Code Agent")
    app.setDesktopFileName("devos-ai-code-agent")
    folder = next((a for a in argv if not a.startswith("-")), "")
    if folder and not os.path.isdir(folder):
        folder = os.path.dirname(os.path.abspath(folder)) if os.path.exists(folder) else ""
    window = AgentWindow(folder)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
