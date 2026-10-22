#!/usr/bin/env python3
"""
DevOS AI Code Agent: Next-Generation Autonomous Pair Programmer and Multi-Agent Development Engine.
Runs locally on DevOS AI (127.0.0.1:11434). Zero cloud latency, 100% private and offline.
Features real-time neural reasoning visualization, live code generation streaming,
instant roadmap planning, and VS Code-grade interactive diff reviews.
"""

import html
import json
import os
import re
import shutil
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import capability  # noqa: E402
import code_agent as core  # noqa: E402
try:
    import providers  # noqa: E402
except ImportError:
    from . import providers  # noqa: E402

from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: E402

ASSISTANT_DIR = os.path.join(os.path.dirname(HERE), "assistant")
if os.path.exists(ASSISTANT_DIR) and ASSISTANT_DIR not in sys.path:
    sys.path.insert(0, ASSISTANT_DIR)

try:
    import vision  # noqa: E402
except Exception:
    vision = None

MODELS_GUI = os.path.join(os.path.dirname(HERE), "ai-core", "models_gui.py")
CONFIG_DIR = os.path.expanduser("~/.config/devos")
CONFIG_PATH = os.path.join(CONFIG_DIR, "code-agent.json")


def get_app_icon() -> QtGui.QIcon:
    """Return high-resolution multi-size icon for DevOS AI Code Agent."""
    icon = QtGui.QIcon()
    for s in [16, 22, 24, 32, 48, 64, 128, 256, 512]:
        p = os.path.expanduser(f"~/.local/share/icons/hicolor/{s}x{s}/apps/devos-ai-code-agent.png")
        if os.path.exists(p):
            icon.addFile(p, QtCore.QSize(s, s))
        p_chroot = os.path.join(HERE, f"../../build/includes.chroot/usr/share/icons/hicolor/{s}x{s}/apps/devos-ai-code-agent.png")
        if os.path.exists(p_chroot):
            icon.addFile(p_chroot, QtCore.QSize(s, s))

    candidates = [
        os.path.join(HERE, "assets", "devos-ai-code-agent.png"),
        os.path.expanduser("~/.local/share/pixmaps/devos-ai-code-agent.png"),
        "/usr/share/pixmaps/devos-ai-code-agent.png",
    ]
    for path in candidates:
        if os.path.exists(path):
            icon.addFile(path)
            break
    return icon



def get_persisted_config() -> dict:
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_persisted_config(data: dict) -> None:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def get_last_opened_folder() -> str:
    cfg = get_persisted_config()
    last = cfg.get("last_folder", "")
    if last and os.path.isdir(last):
        return os.path.abspath(last)
    return ""


def record_opened_folder(folder: str) -> None:
    if not folder or not os.path.isdir(folder):
        return
    folder = os.path.abspath(folder)
    cfg = get_persisted_config()
    cfg["last_folder"] = folder
    recents = [r for r in cfg.get("recent_folders", []) if r != folder and os.path.isdir(r)]
    recents.insert(0, folder)
    cfg["recent_folders"] = recents[:10]
    save_persisted_config(cfg)


# ==============================================================================
# Theme: neutral graphite surfaces, one blue-violet accent (Cursor / Codex / Antigravity feel)
# ==============================================================================
BG = "#0b0b0e"
SURFACE = "#101013"
CARD = "#111114"
RAISED = "#17171c"
CARD_HOVER = "#1d1d23"
LINE = "#222228"
LINE_STRONG = "#2e2e36"
LINE_ACTIVE = "#6c7dff"
TEXT = "#ececf1"
MUTED = "#9b9ba7"
SUBTLE = "#686874"
ACCENT = "#7385ff"
ACCENT_HOVER = "#8a98ff"
ACCENT_SOFT = "#1b1d3a"
VIOLET = "#a78bfa"
GOOD = "#3fb97f"
GOOD_BG = "#0f2a1e"
BAD = "#f0616d"
BAD_BG = "#2a1216"
AMBER = "#e5b454"
AMBER_BG = "#2a2110"
MONO = "'JetBrains Mono', 'Fira Code', 'DejaVu Sans Mono', monospace"

STYLE = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: 'Inter', 'SF Pro Text', 'Segoe UI', 'Noto Sans', sans-serif;
    font-size: 13px;
}}
QLabel {{ background: transparent; }}
QLabel#title {{ font-size: 14px; font-weight: 650; color: {TEXT}; letter-spacing: 0.2px; }}
QLabel#subtitle {{ font-size: 11.5px; color: {MUTED}; }}
QLabel#muted, QLabel#path {{ color: {MUTED}; }}
QLabel#cardTitle {{ font-size: 11px; font-weight: 600; color: {MUTED}; letter-spacing: 0.9px; }}
QLabel#topicLabel {{ color: {MUTED}; font-size: 12px; }}
QLabel#chip {{
    background: {RAISED}; color: {MUTED};
    border: 1px solid {LINE}; border-radius: 10px;
    padding: 2px 10px; font-size: 11.5px; font-weight: 500;
}}
QLabel#chip[state="working"] {{ background: {ACCENT_SOFT}; color: {ACCENT_HOVER}; border: 1px solid #2c3170; }}
QLabel#chip[state="idle"] {{ background: {RAISED}; color: {MUTED}; border: 1px solid {LINE}; }}
QLabel#speed {{ color: {SUBTLE}; font-size: 11.5px; }}
QLabel#timer {{ color: {MUTED}; font-size: 11.5px; font-family: {MONO}; }}

QPushButton#badge {{
    background: {RAISED}; color: {TEXT};
    border: 1px solid {LINE}; border-radius: 13px;
    padding: 4px 12px; font-size: 12px; font-weight: 500;
}}
QPushButton#badge[state="online"] {{ color: {TEXT}; }}
QPushButton#badge[state="starting"] {{ color: {AMBER}; border: 1px solid #4a3a16; }}
QPushButton#badge[state="offline"], QPushButton#badge[state="warning"] {{ color: {BAD}; border: 1px solid #4a1d23; }}
QPushButton#badge:hover {{ background: {CARD_HOVER}; border-color: {LINE_STRONG}; }}

QFrame#topbar {{ background: {BG}; border-bottom: 1px solid {LINE}; }}
QFrame#card {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px; }}
QFrame#card[attention="true"] {{ border: 1px solid #3a4090; background: #101121; }}
QFrame#chatPane {{ background: {BG}; border: none; }}
QFrame#thinkingCard {{ background: transparent; border: none; }}
QFrame#gate {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 18px; }}
QFrame#composerBox {{
    background: {SURFACE}; border: 1px solid {LINE_STRONG}; border-radius: 16px;
}}
QFrame#composerBox[focused="true"] {{ border: 1px solid #4a56c9; background: #121218; }}
QFrame#queueBar, QFrame#goBar {{ background: {ACCENT_SOFT}; border: 1px solid #2c3170; border-radius: 10px; }}

QPushButton {{
    background: {RAISED}; border: 1px solid {LINE}; border-radius: 8px;
    padding: 6px 12px; color: {TEXT}; font-weight: 500;
}}
QPushButton:hover {{ background: {CARD_HOVER}; border-color: {LINE_STRONG}; }}
QPushButton:pressed {{ background: {LINE}; }}
QPushButton:disabled {{ color: #4a4a55; background: {SURFACE}; border-color: {LINE}; }}
QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: {MUTED}; }}
QPushButton#ghost:hover {{ background: {RAISED}; color: {TEXT}; border-color: {LINE}; }}
QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6f83ff, stop:1 #8a6bff);
    border: 1px solid #8a96ff; color: #ffffff; font-weight: 600;
    padding: 7px 18px; border-radius: 10px;
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8092ff, stop:1 #9a7cff);
    border-color: #b3bbff;
}}
QPushButton#primary:disabled {{ background: {RAISED}; border-color: {LINE}; color: #55555f; }}
QPushButton#stopBtn {{ background: {BAD_BG}; border: 1px solid #5a232b; color: #ffb4bb; font-weight: 600; border-radius: 10px; padding: 7px 16px; }}
QPushButton#stopBtn:hover {{ background: #3a171c; border-color: {BAD}; }}
QPushButton#accept {{ background: {GOOD_BG}; border: 1px solid #1f5a40; color: #b8f0d4; font-weight: 600; border-radius: 8px; }}
QPushButton#accept:hover {{ background: #143a29; border-color: {GOOD}; }}
QPushButton#reject {{ background: {BAD_BG}; border: 1px solid #5a232b; color: #ffc9ce; border-radius: 8px; }}
QPushButton#reject:hover {{ background: #3a171c; border-color: {BAD}; }}
QPushButton#quickPill {{
    background: transparent; border: 1px solid {LINE}; color: {MUTED};
    border-radius: 12px; padding: 3px 11px; font-size: 11.5px; font-weight: 500;
}}
QPushButton#quickPill:hover {{ background: {RAISED}; color: {TEXT}; border-color: {LINE_STRONG}; }}
QPushButton#attachBtn, QPushButton#rerunBtn {{
    background: transparent; border: 1px solid transparent; color: {MUTED};
    border-radius: 8px; padding: 5px 10px; font-size: 12px;
}}
QPushButton#attachBtn:hover, QPushButton#rerunBtn:hover {{ background: {RAISED}; color: {TEXT}; }}
QPushButton#rerunBtn:disabled {{ color: #4a4a55; }}
QPushButton#removeAttachBtn {{ background: transparent; border: none; color: {BAD}; font-size: 11px; font-weight: bold; padding: 0 4px; }}
QPushButton#removeAttachBtn:hover {{ color: #ffb4bb; background: {BAD_BG}; border-radius: 3px; }}
QPushButton#jumpBtn {{
    background: {RAISED}; color: {TEXT}; border: 1px solid {LINE_STRONG};
    border-radius: 13px; padding: 4px 14px; font-size: 11.5px; font-weight: 600;
}}
QPushButton#jumpBtn:hover {{ background: {CARD_HOVER}; border-color: {ACCENT}; color: {ACCENT_HOVER}; }}

QTextBrowser, QPlainTextEdit, QListWidget {{
    background: {BG}; border: none; border-radius: 10px; padding: 8px;
    selection-background-color: #34408f;
}}
QTextBrowser#chat {{ background: {BG}; padding: 4px 8px 4px 4px; }}
QTextBrowser#diff, QPlainTextEdit#terminal {{ background: #08080a; border: 1px solid {LINE}; }}
QPlainTextEdit#composer {{ background: transparent; border: none; padding: 6px 8px; font-size: 13.5px; }}
QPlainTextEdit#terminal {{ font-family: {MONO}; font-size: 12px; color: #cfcfd8; }}
QFrame#attachmentBar {{ background: {SURFACE}; border: 1px dashed {LINE_STRONG}; border-radius: 10px; padding: 3px 6px; }}
QFrame#attachmentChip {{ background: {RAISED}; border: 1px solid {LINE_STRONG}; border-radius: 6px; }}

QListWidget {{ background: {SURFACE}; border: none; }}
QListWidget::item {{ padding: 7px 6px; border-radius: 7px; margin-bottom: 1px; }}
QListWidget::item:selected {{ background: {RAISED}; color: #ffffff; }}
QCheckBox {{ background: transparent; color: {MUTED}; spacing: 7px; font-size: 12px; }}
QCheckBox:hover {{ color: {TEXT}; }}
QCheckBox::indicator {{ width: 26px; height: 15px; border-radius: 7px; background: #2a2a31; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; }}
QProgressBar {{ border: none; border-radius: 2px; text-align: center; background: {RAISED}; color: {MUTED}; font-size: 10.5px; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6f83ff, stop:1 #a78bfa); border-radius: 2px; }}
QSplitter::handle {{ background: {BG}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2c2c34; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #44444f; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2c2c34; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QTabWidget::pane {{ border: 1px solid {LINE}; background: {SURFACE}; border-radius: 12px; top: -1px; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {MUTED}; border: none;
    border-bottom: 2px solid transparent; padding: 8px 14px; margin-right: 2px;
    font-weight: 500; font-size: 12.5px;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover:!selected {{ color: {TEXT}; }}
QStatusBar, QLabel#status {{ color: {SUBTLE}; font-size: 11.5px; }}
QToolTip {{ background: {RAISED}; color: {TEXT}; border: 1px solid {LINE_STRONG}; padding: 5px 8px; border-radius: 6px; }}
QMenu {{ background: {RAISED}; color: {TEXT}; border: 1px solid {LINE_STRONG}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {CARD_HOVER}; color: {ACCENT_HOVER}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 6px; }}
"""

STEP_ICON = {"running": "◉", "done": "✓", "denied": "✕", "failed": "!", "plan": "○"}
STEP_COLOR = {"running": ACCENT, "done": GOOD, "denied": BAD, "failed": AMBER, "plan": MUTED}


class CompactLabel(QtWidgets.QLabel):
    """A QLabel that does not force parent layouts to expand to its full text width."""
    def minimumSizeHint(self) -> QtCore.QSize:
        h = super().minimumSizeHint().height()
        return QtCore.QSize(20, h)


def card(title: str, subtitle: str = ""):
    frame = QtWidgets.QFrame()
    frame.setObjectName("card")
    frame.setMinimumWidth(80)
    layout = QtWidgets.QVBoxLayout(frame)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(8)
    header = QtWidgets.QHBoxLayout()
    header_titles = QtWidgets.QVBoxLayout()
    header_titles.setSpacing(1)
    label = CompactLabel(title.upper())
    label.setObjectName("cardTitle")
    label.setMinimumWidth(20)
    header_titles.addWidget(label)
    if subtitle:
        sub = CompactLabel(subtitle)
        sub.setObjectName("subtitle")
        sub.setMinimumWidth(20)
        header_titles.addWidget(sub)
    header.addLayout(header_titles)
    header.addStretch(1)
    layout.addLayout(header)
    return frame, layout, header


def diff_html(diff: str) -> str:
    if not diff or not diff.strip():
        return (f"<div style=\"color:{MUTED}; font-family:{MONO}; font-size:12px; padding:14px;\">"
                "No content changes.</div>")
    rows = []
    old_no = new_no = 0
    for line in diff.splitlines():
        text = html.escape(line.rstrip("\n")) or "&nbsp;"
        gutter_old = gutter_new = ""
        if line.startswith("+++") or line.startswith("---"):
            bg, fg = BG, SUBTLE
        elif line.startswith("@@"):
            bg, fg = "#14152b", VIOLET
            m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", line)
            if m:
                old_no, new_no = int(m.group(1)), int(m.group(2))
        elif line.startswith("+"):
            bg, fg = "#0e2418", "#9be9c0"
            gutter_new, new_no = str(new_no), new_no + 1
        elif line.startswith("-"):
            bg, fg = "#2a1217", "#ffb4bb"
            gutter_old, old_no = str(old_no), old_no + 1
        else:
            bg, fg = BG, "#c9c9d3"
            if old_no or new_no:
                gutter_old, gutter_new = str(old_no), str(new_no)
                old_no, new_no = old_no + 1, new_no + 1
        rows.append(
            f'<tr><td width="34" align="right" bgcolor="{bg}" style="color:#5a5a66; padding:0 6px;">{gutter_old}</td>'
            f'<td width="34" align="right" bgcolor="{bg}" style="color:#5a5a66; padding:0 6px;">{gutter_new}</td>'
            f'<td bgcolor="{bg}" style="color:{fg}; padding:0 10px; white-space:pre;">{text}</td></tr>')
    return (f"<table width='100%' cellspacing='0' cellpadding='0' style=\"font-family:{MONO}; font-size:12px;\">"
            + "".join(rows) + "</table>")


_TOOL_BLOCK = re.compile(r"```[ \t]*tool[ \t]*([^\n]*)\n(.*?)(?:\n```|\Z)|<tool_call>(.*?)(?:</tool_call>|\Z)", re.S)
_CODE_BLOCK = re.compile(r"```([^\n]*)\n(.*?)(?:\n```|\Z)", re.S)
_THINK_BLOCK = re.compile(r"<think>(.*?)(?:</think>|\Z)", re.S)

TOOL_VERBS = {  # tool -> (while running, when done)
    "write_file": ("Writing", "Wrote"), "apply_patch": ("Editing", "Edited"),
    "read_file": ("Reading", "Read"), "list_files": ("Listing", "Listed"),
    "search": ("Searching", "Searched"), "run_command": ("Running", "Ran"),
}


def _gap(px: int = 8) -> str:
    return f'<table width="100%" cellspacing="0" cellpadding="0"><tr><td height="{px}"></td></tr></table>'


def _tool_row(name: str, target: str, content: str, running: bool) -> str:
    verb = TOOL_VERBS.get(name, ("Running", "Ran"))[0 if running else 1]
    dot = f'<span style="color:{ACCENT};">◉</span>' if running else f'<span style="color:{GOOD};">●</span>'
    stats = ""
    lines = content.strip("\n").splitlines() if content.strip() else []
    if name == "write_file" and lines:
        stats = f' &nbsp;<span style="color:{GOOD};">+{len(lines)}</span>'
    elif name == "apply_patch" and lines:
        add = sum(1 for ln in lines if ln.startswith("+") and not ln.startswith("+++"))
        rem = sum(1 for ln in lines if ln.startswith("-") and not ln.startswith("---"))
        stats = f' &nbsp;<span style="color:{GOOD};">+{add}</span> <span style="color:{BAD};">−{rem}</span>'
    if name == "run_command":
        first = (content or target).strip().splitlines()
        shown = html.escape(first[0][:110] if first else "")
    else:
        shown = html.escape(target)
    ellipsis = "…" if running else ""
    row = (f'<p style="margin:3px 0;">{dot}&nbsp;&nbsp;<span style="color:{MUTED};">{verb}{ellipsis}</span> '
           f'<span style="font-family:{MONO}; font-size:12px; color:{TEXT};">{shown}</span>{stats}</p>')
    if name in ("write_file", "apply_patch") and lines:
        limit = 14 if running else 8
        preview = html.escape("\n".join(lines[:limit]))
        more = (f'<br><span style="color:{SUBTLE};">… {len(lines) - limit} more lines · open the Changes tab for the full diff</span>'
                if len(lines) > limit else "")
        row += (f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
                f'<td bgcolor="#09090c" style="background-color:#09090c; border:1px solid {LINE}; padding:8px 12px;">'
                f'<pre style="margin:0; font-family:{MONO}; font-size:12px; color:#c9c9d3; white-space:pre-wrap;">{preview}</pre>{more}'
                f'</td></tr></table>')
    return row


def _code_block(lang: str, code: str) -> str:
    label = html.escape(lang or "code")
    return (f'<table width="100%" cellspacing="0" cellpadding="0"><tr><td bgcolor="#09090c" '
            f'style="background-color:#09090c; border:1px solid {LINE}; padding:8px 12px;">'
            f'<span style="color:{SUBTLE}; font-size:11px;">{label}</span>'
            f'<pre style="margin:4px 0 0 0; font-family:{MONO}; font-size:12px; color:#d4d4dc; white-space:pre-wrap;">{html.escape(code)}</pre>'
            f'</td></tr></table>' + _gap(6))


def message_html(text: str, is_generating: bool = False) -> str:
    """Format agent text: prose, code blocks, reasoning, and compact tool-call rows."""
    if not text:
        return ""
    out = []

    think_match = _THINK_BLOCK.search(text)
    if think_match:
        think = think_match.group(1).strip()
        if think:
            out.append(f'<table width="100%" cellspacing="0" cellpadding="0"><tr><td style="border-left:2px solid #34343e; '
                       f'padding:2px 12px; color:{MUTED}; font-size:12px;"><i>{html.escape(think)}</i></td></tr></table>' + _gap(6))
        text = _THINK_BLOCK.sub("", text)

    pieces = []
    pos = 0
    for match in _TOOL_BLOCK.finditer(text):
        pieces.append(("text", text[pos:match.start()]))
        raw_call = match.group(0)
        call = core.parse_tool_call(raw_call)
        tool_name = call.name if call else "tool"
        target = content = ""
        if call:
            target = str(call.args.get("path") or call.args.get("pattern") or call.args.get("command") or "")
            if call.name == "apply_patch":
                target = ", ".join(re.findall(r"^\+\+\+ (?:b/)?(\S+)", str(call.args.get("patch", "")), re.M)) or target
                content = str(call.args.get("patch", ""))
            elif call.name == "write_file":
                content = str(call.args.get("content", ""))
            elif call.name == "run_command":
                content = str(call.args.get("command", ""))
        else:  # still streaming in: the block is not complete enough to parse
            first_line = raw_call.splitlines()[0] if raw_call else ""
            tool_name = core.normalize_tool_name(first_line.replace("```tool", "").strip()) or "tool"
            m_path = re.search(r"(?:path|file|target)[:\s]*([^\n]+)", raw_call, re.I)
            if m_path:
                target = m_path.group(1).strip()
            if "---" in raw_call:
                content = raw_call.split("---", 1)[1]
        closed = raw_call.rstrip().endswith("```") and raw_call.count("```") >= 2 or raw_call.rstrip().endswith("</tool_call>")
        pieces.append(("tool", (tool_name, target, content, not closed)))
        pos = match.end()
    pieces.append(("text", text[pos:]))

    for kind, value in pieces:
        if kind == "tool":
            tool_name, target, content, streaming = value
            out.append(_tool_row(tool_name, target, content, is_generating and streaming))
            continue
        last = 0
        for code in _CODE_BLOCK.finditer(value):
            out.append(_prose(value[last:code.start()]))
            out.append(_code_block((code.group(1) or "").strip(), code.group(2)))
            last = code.end()
        out.append(_prose(value[last:]))
    return "".join(out)


def _inline(escaped: str) -> str:
    """`code` and **bold** in already-escaped text. Code spans are set aside first, so a '*' inside one
    never pairs up with a bold marker."""
    spans: List[str] = []

    def stash(m):
        spans.append(m.group(1))
        return f"\x00{len(spans) - 1}\x00"

    text = re.sub(r"`([^`\n]+)`", stash, escaped)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"<b style='color:#ffffff;'>\1</b>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: (
        f'<span style="background-color:{RAISED}; color:#c4cbff; font-family:{MONO}; font-size:12px;">&nbsp;'
        f'{spans[int(m.group(1))]}&nbsp;</span>'), text)


def _prose(text: str) -> str:
    text = text.strip("\n")
    if not text.strip():
        return ""
    img_matches = list(re.finditer(r'\[Attached image: ([^\]]+)\]', text))
    clean_text = re.sub(r'\[Attached image: [^\]]+\]', '', text).strip()
    rendered = ""
    if clean_text:
        paras = []
        for line in clean_text.splitlines():
            esc = html.escape(line.rstrip())
            heading = re.match(r"^\s{0,3}#{1,4}\s+(.*)$", esc)
            bullet = re.match(r"^(\s*)(?:([-*•])|(\d+[.)]))\s+(.*)$", esc)
            if not esc.strip():
                paras.append("<div style='font-size:6px;'>&nbsp;</div>")
            elif heading:
                paras.append(f"<div style='font-size:14.5px; font-weight:600; color:#ffffff; margin-top:4px;'>{_inline(heading.group(1))}</div>")
            elif bullet:
                marker = bullet.group(3) or "•"
                left = 6 + (18 if len(bullet.group(1)) >= 2 else 0)
                paras.append(f"<div style='margin-left:{left}px;'><span style='color:{SUBTLE};'>{marker}</span>&nbsp; "
                             f"{_inline(bullet.group(4))}</div>")
            else:
                paras.append(f"<div>{_inline(esc)}</div>")
        rendered = f"<div style='line-height:150%; color:#e4e4ea;'>{''.join(paras)}</div>"
    if img_matches:
        img_html = ""
        for m in img_matches:
            ipath = m.group(1).strip()
            img_html += (f'<table cellspacing="0" cellpadding="0"><tr><td bgcolor="{SURFACE}" style="border:1px solid {LINE}; padding:6px;">'
                         f'<img src="{html.escape(ipath)}" width="240"><br>'
                         f'<span style="font-size:11px; color:{MUTED};">{html.escape(os.path.basename(ipath))}</span></td></tr></table>' + _gap(4))
        rendered = img_html + rendered
    return rendered


# ==============================================================================
# Agent Composer (Enter to send, Shift+Enter newline, Drag/Drop & Paste Images)
# ==============================================================================
class AgentComposer(QtWidgets.QPlainTextEdit):
    submit_requested = QtCore.pyqtSignal()
    image_attached = QtCore.pyqtSignal(str)
    focus_changed = QtCore.pyqtSignal(bool)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.focus_changed.emit(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.focus_changed.emit(False)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.history = []
        self.history_index = -1
        self._temp_edit = ""

    def add_history(self, text: str):
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
        self.history_index = len(self.history)
        self._temp_edit = ""

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            if event.modifiers() & QtCore.Qt.ShiftModifier:
                super().keyPressEvent(event)
                return
            else:
                event.accept()
                self.submit_requested.emit()
                return
        elif event.key() == QtCore.Qt.Key_Up:
            cursor = self.textCursor()
            if cursor.blockNumber() == 0 or not self.toPlainText().strip():
                if self.history:
                    if self.history_index == len(self.history):
                        self._temp_edit = self.toPlainText()
                    if self.history_index > 0:
                        self.history_index -= 1
                        self.setPlainText(self.history[self.history_index])
                        c = self.textCursor()
                        c.movePosition(QtGui.QTextCursor.End)
                        self.setTextCursor(c)
                        event.accept()
                        return
        elif event.key() == QtCore.Qt.Key_Down:
            cursor = self.textCursor()
            if cursor.blockNumber() == self.document().blockCount() - 1 or not self.toPlainText().strip():
                if self.history and self.history_index < len(self.history):
                    self.history_index += 1
                    if self.history_index < len(self.history):
                        self.setPlainText(self.history[self.history_index])
                    else:
                        self.setPlainText(self._temp_edit)
                    c = self.textCursor()
                    c.movePosition(QtGui.QTextCursor.End)
                    self.setTextCursor(c)
                    event.accept()
                    return
        super().keyPressEvent(event)

    def canInsertFromMimeData(self, source: QtCore.QMimeData) -> bool:
        if source.hasImage() or (source.hasUrls() and any(self._is_image_url(u) for u in source.urls())):
            return True
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: QtCore.QMimeData):
        if source.hasImage():
            image = source.imageData()
            if isinstance(image, QtGui.QImage) and not image.isNull():
                saved_path = self._save_qimage(image)
                if saved_path:
                    self.image_attached.emit(saved_path)
                    return
            elif isinstance(image, QtGui.QPixmap) and not image.isNull():
                saved_path = self._save_qimage(image.toImage())
                if saved_path:
                    self.image_attached.emit(saved_path)
                    return

        if source.hasUrls():
            img_urls = [u for u in source.urls() if self._is_image_url(u)]
            if img_urls:
                for u in img_urls:
                    local = u.toLocalFile()
                    if local and os.path.exists(local):
                        self.image_attached.emit(local)
                return

        super().insertFromMimeData(source)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent):
        mime = event.mimeData()
        if mime.hasImage() or (mime.hasUrls() and any(self._is_image_url(u) for u in mime.urls())):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent):
        mime = event.mimeData()
        if mime.hasImage() or (mime.hasUrls() and any(self._is_image_url(u) for u in mime.urls())):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent):
        mime = event.mimeData()
        if mime.hasImage() or (mime.hasUrls() and any(self._is_image_url(u) for u in mime.urls())):
            self.insertFromMimeData(mime)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    @staticmethod
    def _is_image_url(url: QtCore.QUrl) -> bool:
        if not url.isLocalFile():
            return False
        fn = url.toLocalFile().lower()
        return fn.endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".svg"))

    @staticmethod
    def _save_qimage(qimg: QtGui.QImage) -> str:
        cache_dir = os.path.expanduser("~/.local/share/devos/ai/agent-images")
        os.makedirs(cache_dir, exist_ok=True)
        ts = int(time.time() * 1000)
        out_path = os.path.join(cache_dir, f"clipboard_{ts}.png")
        if qimg.save(out_path, "PNG"):
            return out_path
        return ""


# ==============================================================================
# Worker Thread
# ==============================================================================
class AgentWorker(QtCore.QThread):
    event = QtCore.pyqtSignal(str, object)
    approval = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, folder, task, policy, llm=None, history=None):
        super().__init__()
        self.folder = folder
        self.task = task
        self.policy = policy
        self.llm = llm or core.LocalLLM()
        self.history = history or []
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
        if hasattr(self.llm, "close"):
            try:
                self.llm.close()
            except Exception:
                pass
        self.answer(False)

    def run(self):
        try:
            workspace = core.Workspace(self.folder)
            self.agent = core.CodeAgent(workspace, self.llm, self.ask, self.policy,
                                        on_event=lambda kind, payload=None: self.event.emit(kind, payload),
                                        max_steps=40, history=self.history)
            self.agent.run(self.task)
        except core.AgentError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"The agent stopped: {exc}")


# ==============================================================================
# Engine & Acceleration Settings Dialog
# ==============================================================================
class EngineSettingsDialog(QtWidgets.QDialog):
    """Cursor/Antigravity-grade AI Engine & Speed Switcher."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DevOS AI Engine & Acceleration Settings")
        self.resize(540, 520)
        self.setStyleSheet("""
            QDialog { background-color: #0b0f19; color: #f8fafc; font-family: 'Inter', sans-serif; }
            QLabel { color: #f8fafc; font-size: 13px; }
            QComboBox, QLineEdit {
                background: #141c2c; border: 1px solid #233148; border-radius: 6px;
                padding: 8px 12px; color: #f8fafc; font-size: 13px;
            }
            QComboBox:focus, QLineEdit:focus { border: 1px solid #38bdf8; }
            QPushButton {
                border-radius: 6px; padding: 8px 16px; font-weight: 600; font-size: 13px;
            }
        """)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        # Header
        head_box = QtWidgets.QHBoxLayout()
        icon = QtWidgets.QLabel("⚡")
        icon.setStyleSheet("font-size: 26px;")
        head_box.addWidget(icon)
        
        titles = QtWidgets.QVBoxLayout()
        t1 = QtWidgets.QLabel("AI Acceleration & Engine Settings")
        t1.setStyleSheet("font-size: 17px; font-weight: 800; color: #38bdf8;")
        t2 = QtWidgets.QLabel("Run at Cursor/Antigravity speeds (150-300+ tok/s) via cloud or 100% offline.")
        t2.setStyleSheet("font-size: 12px; color: #94a3b8;")
        titles.addWidget(t1)
        titles.addWidget(t2)
        head_box.addLayout(titles)
        head_box.addStretch(1)
        layout.addLayout(head_box)

        # Provider Selection Box
        box = QtWidgets.QFrame()
        box.setStyleSheet("background: #111827; border: 1px solid #1f2937; border-radius: 8px; padding: 14px;")
        box_layout = QtWidgets.QVBoxLayout(box)
        box_layout.setSpacing(10)

        p_lbl = QtWidgets.QLabel("<b>Active AI Provider / Accelerator:</b>")
        box_layout.addWidget(p_lbl)

        self.provider_combo = QtWidgets.QComboBox()
        self.providers_order = ["gemini", "groq", "deepseek", "openai", "local"]
        for pid in self.providers_order:
            pinfo = providers.PROVIDERS[pid]
            self.provider_combo.addItem(f"{pinfo['name']} — {pinfo['speed']}", pid)
        box_layout.addWidget(self.provider_combo)

        self.speed_badge = QtWidgets.QLabel("")
        self.speed_badge.setStyleSheet("color: #7dd3fc; font-size: 12px; font-weight: 600;")
        box_layout.addWidget(self.speed_badge)

        # Model Selection
        m_lbl = QtWidgets.QLabel("<b>Model:</b>")
        box_layout.addWidget(m_lbl)
        self.model_combo = QtWidgets.QComboBox()
        self.model_combo.setEditable(True)
        box_layout.addWidget(self.model_combo)

        # API Key
        self.key_lbl = QtWidgets.QLabel("<b>API Key:</b>")
        box_layout.addWidget(self.key_lbl)
        key_row = QtWidgets.QHBoxLayout()
        self.key_edit = QtWidgets.QLineEdit()
        self.key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.key_edit.setPlaceholderText("Enter API key (e.g. AIzaSy... or gsk_...)")
        key_row.addWidget(self.key_edit)

        self.toggle_eye = QtWidgets.QPushButton("👁")
        self.toggle_eye.setFixedWidth(40)
        self.toggle_eye.setStyleSheet("background: #1e293b; color: #cbd5e1;")
        self.toggle_eye.clicked.connect(self._toggle_key_visibility)
        key_row.addWidget(self.toggle_eye)
        box_layout.addLayout(key_row)

        self.key_link = QtWidgets.QLabel("")
        self.key_link.setOpenExternalLinks(True)
        self.key_link.setStyleSheet("font-size: 11.5px; color: #38bdf8;")
        box_layout.addWidget(self.key_link)

        # Endpoint URL (Advanced)
        ep_lbl = QtWidgets.QLabel("<b>Endpoint URL:</b>")
        box_layout.addWidget(ep_lbl)
        self.endpoint_edit = QtWidgets.QLineEdit()
        box_layout.addWidget(self.endpoint_edit)
        
        layout.addWidget(box)

        # Benchmark / Test Button & Result
        bench_row = QtWidgets.QHBoxLayout()
        self.test_btn = QtWidgets.QPushButton("⚡ Benchmark & Test Connection")
        self.test_btn.setStyleSheet("background: #0369a1; color: white;")
        self.test_btn.clicked.connect(self._run_benchmark)
        bench_row.addWidget(self.test_btn)
        bench_row.addStretch(1)
        layout.addLayout(bench_row)

        self.result_lbl = QtWidgets.QLabel("")
        self.result_lbl.setStyleSheet("font-size: 12px; color: #cbd5e1; padding: 4px;")
        layout.addWidget(self.result_lbl)

        layout.addStretch(1)

        # Dialog Buttons
        btn_box = QtWidgets.QHBoxLayout()
        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.setStyleSheet("background: #1e293b; color: #cbd5e1;")
        cancel_btn.clicked.connect(self.reject)
        
        save_btn = QtWidgets.QPushButton("Save & Activate Engine")
        save_btn.setStyleSheet("background: #2563eb; color: white; padding: 8px 20px;")
        save_btn.clicked.connect(self._save_and_apply)

        btn_box.addStretch(1)
        btn_box.addWidget(cancel_btn)
        btn_box.addWidget(save_btn)
        layout.addLayout(btn_box)

        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self._load_current_settings()

    def _toggle_key_visibility(self):
        if self.key_edit.echoMode() == QtWidgets.QLineEdit.Password:
            self.key_edit.setEchoMode(QtWidgets.QLineEdit.Normal)
            self.toggle_eye.setText("🙈")
        else:
            self.key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
            self.toggle_eye.setText("👁")

    def _load_current_settings(self):
        conf = providers.load_config()
        active = conf.get("active_provider") or "local"
        idx = self.provider_combo.findData(active)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        else:
            self.provider_combo.setCurrentIndex(0)
        self._update_fields_for_provider(active, conf)

    def _on_provider_changed(self, idx):
        pid = self.provider_combo.currentData()
        conf = providers.load_config()
        self._update_fields_for_provider(pid, conf)

    def _update_fields_for_provider(self, pid: str, conf: Dict[str, Any]):
        pinfo = providers.PROVIDERS.get(pid, providers.PROVIDERS["local"])
        p_conf = conf.get("providers", {}).get(pid, {})
        
        self.speed_badge.setText(f"{pinfo['tagline']}  ·  {pinfo['speed']}")

        # Populate models
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for m in pinfo["models"]:
            self.model_combo.addItem(m)
        cur_model = p_conf.get("model") or pinfo["default_model"]
        idx = self.model_combo.findText(cur_model)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        else:
            self.model_combo.setEditText(cur_model)
        self.model_combo.blockSignals(False)

        # Endpoint
        self.endpoint_edit.setText(p_conf.get("endpoint") or pinfo["endpoint"])

        # API Key
        cur_key = p_conf.get("api_key") or (os.environ.get(pinfo["env_key"], "") if pinfo.get("env_key") else "")
        self.key_edit.setText(cur_key)

        if pid == "local":
            self.key_lbl.setText("<b>API Key (Not Required for Offline Engine):</b>")
            self.key_edit.setEnabled(False)
            self.key_edit.setPlaceholderText("Offline mode: runs on local CPU/GPU")
            self.key_link.setText("🔒 100% private offline: no API key or internet required.")
        else:
            self.key_lbl.setText(f"<b>{pinfo['name']} API Key:</b>")
            self.key_edit.setEnabled(True)
            self.key_edit.setPlaceholderText("Enter API key (stored encrypted locally)")
            if pinfo.get("key_url"):
                self.key_link.setText(f'<a href="{pinfo["key_url"]}" style="color: #38bdf8;">🔑 Get free {pinfo["name"]} API key →</a>')
            else:
                self.key_link.setText("")

    def _run_benchmark(self):
        pid = self.provider_combo.currentData()
        endpoint = self.endpoint_edit.text().strip()
        model = self.model_combo.currentText().strip()
        key = self.key_edit.text().strip()

        self.test_btn.setEnabled(False)
        self.test_btn.setText("⚡ Benchmarking...")
        self.result_lbl.setText("Sending benchmark query...")
        QtWidgets.QApplication.processEvents()

        def do_test():
            res = providers.test_engine_connection(endpoint, model, key)
            QtCore.QMetaObject.invokeMethod(self, "_on_benchmark_done",
                                            QtCore.Qt.QueuedConnection,
                                            QtCore.Q_ARG(object, res))
        threading.Thread(target=do_test, daemon=True).start()

    @QtCore.pyqtSlot(object)
    def _on_benchmark_done(self, res):
        self.test_btn.setEnabled(True)
        self.test_btn.setText("⚡ Benchmark & Test Connection")
        if res.get("success"):
            self.result_lbl.setStyleSheet("color: #4ade80; font-size: 12px; font-weight: bold;")
            self.result_lbl.setText(f"✅ {res['message']} — Response: \"{res['reply'][:60]}\"")
        else:
            self.result_lbl.setStyleSheet("color: #f87171; font-size: 12px;")
            self.result_lbl.setText(f"❌ Connection failed: {res.get('error', 'Unknown error')}")

    def _save_and_apply(self):
        pid = self.provider_combo.currentData()
        endpoint = self.endpoint_edit.text().strip()
        model = self.model_combo.currentText().strip()
        key = self.key_edit.text().strip()

        conf = providers.load_config()
        conf["active_provider"] = pid
        p_entry = conf.setdefault("providers", {}).setdefault(pid, {})
        p_entry["endpoint"] = endpoint
        p_entry["model"] = model
        p_entry["api_key"] = key
        providers.save_config(conf)
        self.accept()


# ==============================================================================
# Gating Widget
# ==============================================================================
class GatePanel(QtWidgets.QWidget):
    def __init__(self, reason: str, recheck):
        super().__init__()
        outer = QtWidgets.QVBoxLayout(self)
        outer.addStretch(1)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        box = QtWidgets.QFrame()
        box.setObjectName("gate")
        box.setFixedWidth(580)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(34, 30, 34, 30)
        layout.setSpacing(14)
        title = QtWidgets.QLabel("Coding requires a stronger DevOS AI")
        title.setObjectName("title")
        layout.addWidget(title)
        text = QtWidgets.QLabel(reason)
        text.setObjectName("muted")
        text.setWordWrap(True)
        layout.addWidget(text)
        hint = QtWidgets.QLabel("DevOS runs neural AI offline on your local CPU/GPU. The agent activates automatically once the Coding model or a Medium 3B+ model is downloaded.")
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


# ==============================================================================
# Main Agent Window
# ==============================================================================
class AgentWindow(QtWidgets.QMainWindow):
    def __init__(self, folder: str = "", capable=None, llm=None):
        super().__init__()
        self.setWindowTitle("DevOS AI Code Agent")
        self.setWindowIcon(get_app_icon())
        
        # Responsive sizing: fit cleanly within screen work area (e.g. 1024x576, 1366x768)
        screen = QtWidgets.QApplication.primaryScreen()
        geom = screen.availableGeometry() if screen else QtCore.QRect(0, 0, 1024, 576)
        w = min(1360, max(640, geom.width() - 16))
        h = min(840, max(460, geom.height() - 36))
        self.resize(w, h)
        # Position cleanly inside visible screen bounds, never negative X or off to the left
        pos_x = max(geom.x(), geom.x() + max(0, (geom.width() - w) // 2))
        pos_y = max(geom.y(), geom.y() + max(0, (geom.height() - h) // 2))
        self.move(pos_x, pos_y)
        self.setStyleSheet(STYLE)
        
        # Restore last opened folder if none explicitly provided
        if not folder:
            folder = get_last_opened_folder()
        self.folder = os.path.abspath(folder) if (folder and os.path.isdir(folder)) else ""
        self.policy = core.ApprovalPolicy(auto_reads=True, auto_edits=False, auto_commands=False)
        self.llm = llm
        self.worker = None
        self.pending = None
        self.prompt_queue = []  # List of (raw_task, attached_images) for prompt queuing
        self.transcript = []  # [role, text]
        self.attached_images = []
        self.user_prompts = []  # List of (raw_task, attached_images) for rerun
        self.last_task = ""
        self.last_attached = []
        self.setAcceptDrops(True)
        self.current_topic = ""
        self.active_status_text = "Idle"
        self.start_time = 0
        self._dirty = False
        self._auto_scroll_to_bottom = True
        self._last_rendered_html = ""
        self._item_cache = {}
        self._phase_mode = False
        self._rendered_items = []
        self._tail_pos = None
        self._capable_override = capable
        self._inhibit_cookie = None

        # Animation & update timer
        self._render_timer = QtCore.QTimer(self)
        self._render_timer.setInterval(60)
        self._render_timer.timeout.connect(self._render_if_dirty)
        self._render_timer.start()

        # Elapsed timer for thinking & execution
        self._elapsed_timer = QtCore.QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        # AI backend health monitor
        self._ai_health_timer = QtCore.QTimer(self)
        self._ai_health_timer.setInterval(4000)
        self._ai_health_timer.timeout.connect(self._check_ai_status)
        self._ai_health_timer.start()
        QtCore.QTimer.singleShot(250, self._check_ai_status)
        QtCore.QTimer.singleShot(600, self._warmup_ai_if_needed)

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
        
        # Telemetry Status Bar
        self.status = CompactLabel()
        self.status.setObjectName("status")
        self.status.setContentsMargins(14, 4, 14, 6)
        self.root_layout.addWidget(self.status)

        self.check_capable()
        self.set_folder(self.folder)

    # ------------------------------------------------------------------ top bar
    def _topbar(self):
        bar = QtWidgets.QFrame()
        bar.setObjectName("topbar")
        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(16, 8, 14, 8)
        row.setSpacing(10)

        mark = QtWidgets.QLabel()
        mark.setFixedSize(26, 26)
        app_icon = get_app_icon()
        if not app_icon.isNull():
            mark.setPixmap(app_icon.pixmap(24, 24))
            mark.setStyleSheet("background: transparent;")
        else:
            mark.setStyleSheet("border-radius: 7px; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                               "stop:0 #6f83ff, stop:1 #8a6bff); color: white; font-weight: 800; font-size: 12px;")
            mark.setText("D")
        mark.setAlignment(QtCore.Qt.AlignCenter)
        row.addWidget(mark)

        title = CompactLabel("DevOS Code")
        title.setObjectName("title")
        title.setMinimumWidth(30)
        row.addWidget(title)

        divider = QtWidgets.QLabel("/")
        divider.setStyleSheet(f"color: {LINE_STRONG}; font-size: 16px;")
        row.addWidget(divider)

        # Project chip: shows the open folder, click for recent projects
        self.path_label = CompactLabel("No folder open")
        self.path_label.setObjectName("path")
        self.path_label.setStyleSheet(f"color: {TEXT}; font-weight: 500;")
        self.path_label.setMinimumWidth(30)
        row.addWidget(self.path_label)

        self.recent_btn = QtWidgets.QPushButton("⌄")
        self.recent_btn.setObjectName("ghost")
        self.recent_btn.setFixedWidth(26)
        self.recent_btn.setToolTip("Switch to a recent project…")
        self.recent_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.recent_btn.clicked.connect(lambda: self._show_recent_menu(self.recent_btn.mapToGlobal(self.recent_btn.rect().bottomLeft())))
        row.addWidget(self.recent_btn)

        # Model beacon pill (interactive status)
        self.ai_badge = QtWidgets.QPushButton("●  devos-ai-code")
        self.ai_badge.setObjectName("badge")
        self.ai_badge.setMinimumWidth(30)
        self.ai_badge.setToolTip("DevOS AI Core is running on 127.0.0.1:11434.\nZero cloud latency, 100% private and offline.")
        self.ai_badge.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.ai_badge.clicked.connect(self._on_badge_clicked)
        row.addWidget(self.ai_badge)

        row.addStretch(1)

        # Autonomy toggles
        self.auto_reads = QtWidgets.QCheckBox("Reads")
        self.auto_reads.setToolTip("Auto-approve reads: inspect project files without asking")
        self.auto_reads.setChecked(True)
        self.auto_reads.setMinimumWidth(20)
        self.auto_reads.toggled.connect(self._policy_changed)

        self.auto_edits = QtWidgets.QCheckBox("Edits")
        self.auto_edits.setToolTip("Auto-approve edits: apply file changes without asking")
        self.auto_edits.setMinimumWidth(20)
        self.auto_edits.toggled.connect(self._policy_changed)

        self.auto_commands = QtWidgets.QCheckBox("Commands")
        self.auto_commands.setToolTip("Auto-run commands: run terminal commands without asking")
        self.auto_commands.setMinimumWidth(20)
        self.auto_commands.toggled.connect(self._policy_changed)

        for box in (self.auto_reads, self.auto_edits, self.auto_commands):
            row.addWidget(box)
        row.addSpacing(6)

        self.open_btn = QtWidgets.QPushButton("Open folder")
        self.open_btn.setToolTip("Open project folder… (right-click for recent projects)")
        self.open_btn.setMinimumWidth(30)
        self.open_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.open_btn.clicked.connect(self.choose_folder)
        self.open_btn.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.open_btn.customContextMenuRequested.connect(lambda pos: self._show_recent_menu(self.open_btn.mapToGlobal(pos)))
        row.addWidget(self.open_btn)

        self.new_btn = QtWidgets.QPushButton("New chat")
        self.new_btn.setToolTip("Reset the conversation for a new objective")
        self.new_btn.setMinimumWidth(30)
        self.new_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.new_btn.clicked.connect(self.new_task)
        row.addWidget(self.new_btn)

        return bar

    def _show_recent_menu(self, global_pos: QtCore.QPoint):
        cfg = get_persisted_config()
        recents = [r for r in cfg.get("recent_folders", []) if os.path.isdir(r)]
        menu = QtWidgets.QMenu(self)
        choose_act = menu.addAction("Browse folder…")
        choose_act.triggered.connect(self.choose_folder)
        if recents:
            menu.addSeparator()
            label_act = menu.addAction("Recent Projects:")
            label_act.setEnabled(False)
            for rpath in recents:
                rname = os.path.basename(rpath) or rpath
                prefix = "✓ " if rpath == self.folder else "   "
                act = menu.addAction(f"{prefix}{rname}  ({rpath})")
                act.triggered.connect(lambda _, p=rpath: self.set_folder(p))
        menu.exec_(global_pos)


    # ----------------------------------------------------------------- main panel
    def _main_panel(self):
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 6)
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        split.setHandleWidth(12)
        split.setChildrenCollapsible(False)
        layout.addWidget(split)

        # ---- Left: conversation (no card chrome; the stream is the page)
        chat_card = QtWidgets.QFrame()
        chat_card.setObjectName("chatPane")
        chat_card.setMinimumWidth(260)
        chat_layout = QtWidgets.QVBoxLayout(chat_card)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(8)

        status_row = QtWidgets.QHBoxLayout()
        status_row.setContentsMargins(4, 0, 4, 0)
        self.step_chip = QtWidgets.QLabel("Idle")
        self.step_chip.setObjectName("chip")
        self.step_chip.setProperty("state", "idle")
        status_row.addWidget(self.step_chip)
        status_row.addStretch(1)
        self.speed_label = CompactLabel("")
        self.speed_label.setObjectName("speed")
        self.speed_label.setMinimumWidth(20)
        status_row.addWidget(self.speed_label)
        chat_layout.addLayout(status_row)

        chat_container = QtWidgets.QWidget()
        chat_box_layout = QtWidgets.QVBoxLayout(chat_container)
        chat_box_layout.setContentsMargins(0, 0, 0, 0)
        chat_box_layout.setSpacing(2)

        self.chat = QtWidgets.QTextBrowser()
        self.chat.setObjectName("chat")
        self.chat.setOpenExternalLinks(False)
        self.chat.setOpenLinks(False)
        self.chat.anchorClicked.connect(self._on_anchor_clicked)
        self.chat.verticalScrollBar().valueChanged.connect(self._on_chat_scroll)
        chat_box_layout.addWidget(self.chat, 1)

        jump_row = QtWidgets.QHBoxLayout()
        jump_row.setContentsMargins(0, 0, 8, 2)
        jump_row.addStretch(1)
        self.jump_to_latest_btn = QtWidgets.QPushButton("↓  Latest")
        self.jump_to_latest_btn.setObjectName("jumpBtn")
        self.jump_to_latest_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.jump_to_latest_btn.setToolTip("Scroll down to the latest message")
        self.jump_to_latest_btn.setVisible(False)
        self.jump_to_latest_btn.clicked.connect(self.scroll_to_bottom)
        jump_row.addWidget(self.jump_to_latest_btn)
        chat_box_layout.addLayout(jump_row)
        chat_layout.addWidget(chat_container, 1)

        # ---- Live work banner (status, timer, thin progress)
        self.thinking_banner = QtWidgets.QFrame()
        self.thinking_banner.setObjectName("thinkingCard")
        tb_layout = QtWidgets.QVBoxLayout(self.thinking_banner)
        tb_layout.setContentsMargins(6, 0, 6, 0)
        tb_layout.setSpacing(5)

        tb_top = QtWidgets.QHBoxLayout()
        tb_top.setSpacing(8)
        self.tb_icon = QtWidgets.QLabel("●")
        self.tb_icon.setStyleSheet(f"color: {ACCENT}; font-size: 10px;")
        tb_top.addWidget(self.tb_icon)
        self.tb_status = CompactLabel("Analyzing task & project files…")
        self.tb_status.setStyleSheet(f"color: {TEXT}; font-size: 12.5px;")
        self.tb_status.setMinimumWidth(20)
        tb_top.addWidget(self.tb_status, 1)
        self.tb_timer = QtWidgets.QLabel("00:00")
        self.tb_timer.setObjectName("timer")
        tb_top.addWidget(self.tb_timer)
        tb_layout.addLayout(tb_top)

        self.tb_topic = CompactLabel("")
        self.tb_topic.setObjectName("topicLabel")
        self.tb_topic.setMinimumWidth(20)
        tb_layout.addWidget(self.tb_topic)

        self.tb_progress = QtWidgets.QProgressBar()
        self.tb_progress.setFixedHeight(2)
        self.tb_progress.setTextVisible(False)
        self.tb_progress.setRange(0, 0)  # shimmer
        tb_layout.addWidget(self.tb_progress)
        self.thinking_banner.setVisible(False)
        chat_layout.addWidget(self.thinking_banner)

        # ---- Queue bar
        self.queue_bar = QtWidgets.QFrame()
        self.queue_bar.setObjectName("queueBar")
        self.queue_layout = QtWidgets.QHBoxLayout(self.queue_bar)
        self.queue_layout.setContentsMargins(12, 6, 10, 6)
        self.queue_layout.setSpacing(10)
        self.queue_label = QtWidgets.QLabel("")
        self.queue_label.setStyleSheet(f"color: {ACCENT_HOVER}; font-size: 12px; font-weight: 500; background: transparent;")
        self.queue_layout.addWidget(self.queue_label)
        self.queue_layout.addStretch(1)
        self.queue_run_btn = QtWidgets.QPushButton("Interrupt & run now")
        self.queue_run_btn.setStyleSheet(f"QPushButton {{ background: {ACCENT}; color: #fff; border: none; border-radius: 6px; "
                                         f"padding: 3px 10px; font-size: 11.5px; font-weight: 600; }} "
                                         f"QPushButton:hover {{ background: {ACCENT_HOVER}; }}")
        self.queue_run_btn.clicked.connect(self.run_next_queued_now)
        self.queue_layout.addWidget(self.queue_run_btn)
        self.queue_clear_btn = QtWidgets.QPushButton("Clear")
        self.queue_clear_btn.setObjectName("ghost")
        self.queue_clear_btn.clicked.connect(self.clear_queue)
        self.queue_layout.addWidget(self.queue_clear_btn)
        self.queue_bar.setVisible(False)
        chat_layout.addWidget(self.queue_bar)

        # ---- "go" bar: the saved brief is waiting for the user's approval of the next phase
        self.go_bar = QtWidgets.QFrame()
        self.go_bar.setObjectName("goBar")
        go_row = QtWidgets.QHBoxLayout(self.go_bar)
        go_row.setContentsMargins(12, 6, 10, 6)
        go_row.setSpacing(8)
        self.go_label = QtWidgets.QLabel("")
        self.go_label.setStyleSheet(f"color: {TEXT}; font-size: 12.5px; background: transparent;")
        self.go_label.setWordWrap(True)
        go_row.addWidget(self.go_label, 1)
        self.go_btn = QtWidgets.QPushButton("Go")
        self.go_btn.setObjectName("primary")
        self.go_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.go_btn.setToolTip("Build the next phase of your brief, then stop and report")
        self.go_btn.clicked.connect(lambda: self._send_quick("go"))
        go_row.addWidget(self.go_btn)
        self.go_all_btn = QtWidgets.QPushButton("Go all")
        self.go_all_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.go_all_btn.setToolTip("Build every remaining phase without stopping")
        self.go_all_btn.clicked.connect(lambda: self._send_quick("go all"))
        go_row.addWidget(self.go_all_btn)
        self.go_bar.setVisible(False)
        chat_layout.addWidget(self.go_bar)

        # ---- Quick actions
        quick_row = QtWidgets.QHBoxLayout()
        quick_row.setContentsMargins(4, 0, 4, 0)
        quick_row.setSpacing(6)
        for label, prompt, tip in [
            ("Plan", "Analyze the repository and create an architectural plan in docs/PHASE_1.md for the next phase.", "Analyze the repository and write an architectural plan"),
            ("Run app", "quick_run_app", "Detect the app entrypoint and start its dev server"),
            ("Preview", "quick_open_preview", "Open the landing page or localhost server in a browser"),
            ("Tests", "Inspect tests and run the test suite to verify code integrity and reporting status.", "Inspect and run the test suite"),
            ("Scan", "List key directories and read core entrypoints to understand project architecture.", "Map the project structure and entrypoints"),
            ("Patch", "Implement the next requested feature cleanly with minimal, high-cohesion changes.", "Implement the next feature with minimal changes"),
        ]:
            pill = QtWidgets.QPushButton(label)
            pill.setObjectName("quickPill")
            pill.setToolTip(tip)
            pill.setMinimumWidth(20)
            pill.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
            if prompt == "quick_run_app":
                pill.clicked.connect(self.quick_run_app)
            elif prompt == "quick_open_preview":
                pill.clicked.connect(self.quick_open_preview)
            else:
                pill.clicked.connect(lambda _, p=prompt: self.insert_prompt(p))
            quick_row.addWidget(pill)
        quick_row.addStretch(1)
        chat_layout.addLayout(quick_row)

        # ---- Composer: one rounded box holding attachments, input and actions
        self.composer_box = QtWidgets.QFrame()
        self.composer_box.setObjectName("composerBox")
        self.composer_box.setProperty("focused", "false")
        box = QtWidgets.QVBoxLayout(self.composer_box)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(4)

        self.attachment_bar = QtWidgets.QFrame()
        self.attachment_bar.setObjectName("attachmentBar")
        self.attachment_layout = QtWidgets.QHBoxLayout(self.attachment_bar)
        self.attachment_layout.setContentsMargins(6, 4, 6, 4)
        self.attachment_layout.setSpacing(6)
        self.attachment_bar.setVisible(False)
        box.addWidget(self.attachment_bar)

        self.composer = AgentComposer()
        self.composer.setObjectName("composer")
        self.composer.setPlaceholderText("Describe what to build or fix…   Enter to run · Shift+Enter for a new line · paste or drop images")
        self.composer.setFixedHeight(60)
        self.composer.submit_requested.connect(self.send)
        self.composer.image_attached.connect(self.add_attachment)
        self.composer.focus_changed.connect(self._composer_focus)
        self.composer.textChanged.connect(self._grow_composer)
        box.addWidget(self.composer)

        actions = QtWidgets.QHBoxLayout()
        actions.setSpacing(4)
        self.attach_btn = QtWidgets.QPushButton("Attach")
        self.attach_btn.setObjectName("attachBtn")
        self.attach_btn.setToolTip("Attach a screenshot or image (or paste with Ctrl+V / drag and drop)")
        self.attach_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.attach_btn.clicked.connect(self.choose_attachment)
        actions.addWidget(self.attach_btn)

        self.rerun_btn = QtWidgets.QPushButton("Rerun last")
        self.rerun_btn.setObjectName("rerunBtn")
        self.rerun_btn.setToolTip("Rerun the last prompt (or press ↑ in the box)")
        self.rerun_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.rerun_btn.setEnabled(False)
        self.rerun_btn.clicked.connect(self.rerun_last_prompt)
        actions.addWidget(self.rerun_btn)

        self.hint = CompactLabel("")
        self.hint.setObjectName("muted")
        self.hint.setStyleSheet(f"font-size: 11.5px; color: {SUBTLE};")
        self.hint.setMinimumWidth(20)
        actions.addWidget(self.hint, 1)

        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setVisible(False)
        self.stop_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.stop_btn.clicked.connect(self.stop)
        actions.addWidget(self.stop_btn)

        self.send_btn = QtWidgets.QPushButton("Run agent  ↑")
        self.send_btn.setObjectName("primary")
        self.send_btn.setMinimumWidth(30)
        self.send_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.send_btn.clicked.connect(self.send)
        actions.addWidget(self.send_btn)
        box.addLayout(actions)
        chat_layout.addWidget(self.composer_box)

        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Return"), self.composer, activated=self.send)
        QtWidgets.QShortcut(QtGui.QKeySequence.Paste, self, activated=self._handle_paste)
        split.addWidget(chat_card)

        # ---- Right: inspector (Changes / Terminal / Roadmap)
        plan_card, plan_layout, plan_header = card("Roadmap")
        plan_card.setMinimumWidth(80)
        self.plan_progress = QtWidgets.QProgressBar()
        self.plan_progress.setFixedHeight(8)
        self.plan_progress.setFixedWidth(70)
        self.plan_progress.setTextVisible(False)
        self.plan_progress.setValue(0)
        plan_header.addWidget(self.plan_progress)

        self.plan = QtWidgets.QListWidget()
        self.plan.setFocusPolicy(QtCore.Qt.NoFocus)
        plan_layout.addWidget(self.plan)

        self.diff_card, diff_layout, diff_header = card("Diff")
        self.diff_card.setMinimumWidth(80)
        self.diff_title = CompactLabel("No pending changes")
        self.diff_title.setObjectName("muted")
        self.diff_title.setMinimumWidth(20)
        diff_header.addWidget(self.diff_title)

        self.diff = QtWidgets.QTextBrowser()
        self.diff.setObjectName("diff")
        diff_layout.addWidget(self.diff, 1)

        self.diff_btn_box = QtWidgets.QWidget()
        diff_buttons = QtWidgets.QHBoxLayout(self.diff_btn_box)
        diff_buttons.setContentsMargins(0, 4, 0, 0)
        diff_buttons.addStretch(1)
        self.reject_btn = QtWidgets.QPushButton("Reject")
        self.reject_btn.setObjectName("reject")
        self.reject_btn.setMinimumWidth(30)
        self.accept_btn = QtWidgets.QPushButton("Accept")
        self.accept_btn.setObjectName("accept")
        self.accept_btn.setMinimumWidth(30)
        self.reject_btn.clicked.connect(lambda: self.respond(False))
        self.accept_btn.clicked.connect(lambda: self.respond(True))
        diff_buttons.addWidget(self.reject_btn)
        diff_buttons.addWidget(self.accept_btn)
        diff_layout.addWidget(self.diff_btn_box)
        self.diff_btn_box.setVisible(False)

        self.term_card, term_layout, term_header = card("Terminal")
        self.term_card.setMinimumWidth(80)
        self.command_label = CompactLabel("")
        self.command_label.setStyleSheet(f"color: {AMBER}; font-family: {MONO}; font-size: 11.5px;")
        self.command_label.setMinimumWidth(20)
        term_header.addWidget(self.command_label)

        self.terminal = QtWidgets.QPlainTextEdit()
        self.terminal.setObjectName("terminal")
        self.terminal.setReadOnly(True)
        term_layout.addWidget(self.terminal, 1)

        self.term_btn_box = QtWidgets.QWidget()
        term_buttons = QtWidgets.QHBoxLayout(self.term_btn_box)
        term_buttons.setContentsMargins(0, 4, 0, 0)
        term_note = CompactLabel("Runs inside the project folder")
        term_note.setObjectName("muted")
        term_note.setStyleSheet("font-size: 11.5px;")
        term_note.setMinimumWidth(20)
        term_buttons.addWidget(term_note)
        term_buttons.addStretch(1)
        self.deny_btn = QtWidgets.QPushButton("Deny")
        self.deny_btn.setObjectName("reject")
        self.deny_btn.setMinimumWidth(30)
        self.run_btn = QtWidgets.QPushButton("Run")
        self.run_btn.setObjectName("accept")
        self.run_btn.setMinimumWidth(30)
        self.deny_btn.clicked.connect(lambda: self.respond(False))
        self.run_btn.clicked.connect(lambda: self.respond(True))
        term_buttons.addWidget(self.deny_btn)
        term_buttons.addWidget(self.run_btn)
        term_layout.addWidget(self.term_btn_box)
        self.term_btn_box.setVisible(False)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("inspectorTabs")
        self.tabs.setMinimumWidth(260)
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.diff_card, "Changes (0)")
        self.tabs.addTab(self.term_card, "Terminal")
        self.tabs.addTab(plan_card, "Roadmap")
        split.addWidget(self.tabs)

        left_w = max(300, int(self.width() * 0.60))
        right_w = max(240, int(self.width() * 0.40))
        split.setSizes([left_w, right_w])

        self._set_pending(None)
        return panel

    def _update_go_bar(self):
        """Show Go / Go all when a brief is saved in this folder and its next phase awaits approval."""
        state = None
        if self.folder and not self.worker:
            try:
                state = core.brief.BriefState.load(self.folder)
            except Exception:
                state = None
        nxt = state.phase(state.next) if state and state.awaiting else None
        self.go_bar.setVisible(bool(nxt))
        if nxt:
            self.go_label.setText(f"Phase {nxt['n']} of {state.total} is ready: {nxt['title']}")
            self.go_label.setToolTip(f"{state.title}\nNext: Phase {nxt['n']} — {nxt['title']}")

    def _send_quick(self, text: str):
        if self.worker:
            return
        self.composer.setPlainText(text)
        self.send()

    def _composer_focus(self, focused: bool):
        self.composer_box.setProperty("focused", "true" if focused else "false")
        self.composer_box.style().unpolish(self.composer_box)
        self.composer_box.style().polish(self.composer_box)

    def _grow_composer(self):
        """The input grows with what is typed (up to ~8 lines), like Cursor and Codex."""
        doc_h = int(self.composer.document().size().height()) + 14
        self.composer.setFixedHeight(max(60, min(170, doc_h)))

    def _set_chip(self, text: str, state: str = "working"):
        self.step_chip.setText(text)
        self.step_chip.setProperty("state", state)
        self.step_chip.style().unpolish(self.step_chip)
        self.step_chip.style().polish(self.step_chip)

    # ---------------------------------------------------------------- capabilities
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

    # ---------------------------------------------------------------- folder
    def choose_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Open project folder",
                                                            self.folder or os.path.expanduser("~"))
        if folder:
            self.set_folder(folder)

    def set_folder(self, folder: str):
        if folder and os.path.isdir(folder):
            self.folder = os.path.abspath(folder)
            record_opened_folder(self.folder)
        else:
            self.folder = ""
        short_name = os.path.basename(self.folder) or self.folder
        self.path_label.setText(short_name if self.folder else "No folder open")
        self.path_label.setToolTip(self.folder or "")
        self.transcript = []
        self._rendered_items = []
        self._dirty = True
        self._update_status()
        if hasattr(self, "go_bar"):
            self._update_go_bar()


    def new_task(self):
        if self.worker:
            self.stop()
        self.transcript = []
        self._phase_mode = False
        self.attached_images.clear()
        self._update_attachment_bar()
        self.composer.clear()
        self.plan.clear()
        self.plan_progress.setValue(0)
        self.diff.clear()
        self.diff_title.setText("No pending changes")
        self.terminal.clear()
        self.command_label.setText("")
        self.thinking_banner.setVisible(False)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setVisible(False)
        self.send_btn.setEnabled(True)
        self._set_pending(None)
        self.set_folder(self.folder)

    def choose_attachment(self):
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "Attach Image / Screenshot",
            os.path.expanduser("~"),
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.svg);;All Files (*)"
        )
        for f in files:
            if f and os.path.exists(f):
                self.add_attachment(f)

    def add_attachment(self, path: str):
        if path and path not in self.attached_images:
            self.attached_images.append(path)
            self._update_attachment_bar()

    def remove_attachment(self, path: str):
        if path in self.attached_images:
            self.attached_images.remove(path)
            self._update_attachment_bar()

    def _update_attachment_bar(self):
        while self.attachment_layout.count():
            item = self.attachment_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not self.attached_images:
            self.attachment_bar.setVisible(False)
            return

        lbl = QtWidgets.QLabel(f"Attached ({len(self.attached_images)})")
        lbl.setStyleSheet("color: #38bdf8; font-weight: 600; font-size: 11.5px;")
        self.attachment_layout.addWidget(lbl)

        for path in self.attached_images:
            chip = QtWidgets.QFrame()
            chip.setObjectName("attachmentChip")
            chip_layout = QtWidgets.QHBoxLayout(chip)
            chip_layout.setContentsMargins(6, 2, 4, 2)
            chip_layout.setSpacing(6)

            thumb = QtWidgets.QLabel()
            pix = QtGui.QPixmap(path)
            if not pix.isNull():
                thumb.setPixmap(pix.scaled(20, 20, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
            chip_layout.addWidget(thumb)

            name_lbl = QtWidgets.QLabel(os.path.basename(path))
            name_lbl.setStyleSheet("color: #e2e8f0; font-size: 11.5px;")
            name_lbl.setToolTip(path)
            chip_layout.addWidget(name_lbl)

            del_btn = QtWidgets.QPushButton("✕")
            del_btn.setObjectName("removeAttachBtn")
            del_btn.setFixedSize(18, 18)
            del_btn.setToolTip("Remove attachment")
            del_btn.clicked.connect(lambda _, p=path: self.remove_attachment(p))
            chip_layout.addWidget(del_btn)

            self.attachment_layout.addWidget(chip)

        self.attachment_layout.addStretch(1)
        self.attachment_bar.setVisible(True)

    def _handle_paste(self):
        cb = QtWidgets.QApplication.clipboard()
        mime = cb.mimeData()
        if mime and (mime.hasImage() or (mime.hasUrls() and any(AgentComposer._is_image_url(u) for u in mime.urls()))):
            self.composer.insertFromMimeData(mime)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent):
        mime = event.mimeData()
        if mime.hasImage() or (mime.hasUrls() and any(AgentComposer._is_image_url(u) for u in mime.urls())):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent):
        mime = event.mimeData()
        if mime.hasImage() or (mime.hasUrls() and any(AgentComposer._is_image_url(u) for u in mime.urls())):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent):
        mime = event.mimeData()
        if mime.hasImage() or (mime.hasUrls() and any(AgentComposer._is_image_url(u) for u in mime.urls())):
            self.composer.insertFromMimeData(mime)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


    def insert_prompt(self, prompt: str):
        self.composer.setPlainText(prompt)
        self.composer.setFocus()

    def _inhibit_sleep(self):
        """Inhibit display sleep and screen locking while the agent is actively working."""
        if self._inhibit_cookie is not None:
            return
        try:
            res = subprocess.run(
                ["qdbus", "org.freedesktop.ScreenSaver", "/ScreenSaver", "Inhibit",
                 "DevOS AI Code Agent", "Autonomous coding task in progress"],
                capture_output=True, text=True, timeout=2
            )
            val = res.stdout.strip()
            if res.returncode == 0 and val.isdigit():
                self._inhibit_cookie = int(val)
        except Exception:
            pass

    def _uninhibit_sleep(self):
        """Release screen sleep inhibit lock when agent is idle or stopped."""
        if self._inhibit_cookie is not None:
            try:
                subprocess.run(
                    ["qdbus", "org.freedesktop.ScreenSaver", "/ScreenSaver", "UnInhibit",
                     str(self._inhibit_cookie)],
                    check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2
                )
            except Exception:
                pass
            self._inhibit_cookie = None

    # ---------------------------------------------------------------- timer
    def _tick_elapsed(self):
        if not self.worker:
            self._elapsed_timer.stop()
            return
        elapsed = int(time.time() - self.start_time)
        mins, secs = divmod(elapsed, 60)
        self.tb_timer.setText(f"{mins:02d}:{secs:02d}")
        # Every 20 seconds of active work, reset system idle timer so screen does not sleep while user watches
        if elapsed > 0 and elapsed % 20 == 0:
            try:
                subprocess.run(["qdbus", "org.freedesktop.ScreenSaver", "/ScreenSaver", "SimulateUserActivity"],
                               check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            except Exception:
                pass

    # ---------------------------------------------------------------- chat rendering & scrolling
    def _on_chat_scroll(self, val):
        bar = self.chat.verticalScrollBar()
        distance_from_bottom = bar.maximum() - val
        if distance_from_bottom > 120:
            self._auto_scroll_to_bottom = False
            if hasattr(self, "jump_to_latest_btn"):
                self.jump_to_latest_btn.setVisible(True)
        else:
            self._auto_scroll_to_bottom = True
            if hasattr(self, "jump_to_latest_btn"):
                self.jump_to_latest_btn.setVisible(False)

    def scroll_to_bottom(self):
        self._auto_scroll_to_bottom = True
        if hasattr(self, "jump_to_latest_btn"):
            self.jump_to_latest_btn.setVisible(False)
        self.chat.moveCursor(QtGui.QTextCursor.End)
        bar = self.chat.verticalScrollBar()
        bar.setValue(bar.maximum())
        QtCore.QTimer.singleShot(0, lambda: self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum()))
        QtCore.QTimer.singleShot(25, lambda: self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum()))
        QtCore.QTimer.singleShot(75, lambda: self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum()))

    SUGGESTIONS = [
        ("Understand this project", "Scan the project: list key folders, read the main entrypoints, and explain the architecture and how to run it."),
        ("Build the landing page", "Build a modern, responsive landing page for this application with hero, feature cards and navigation, and connect its route."),
        ("Fix what is broken", "Run the app and tests, find what fails, and fix the root causes with minimal changes."),
        ("Plan the next phase", "Analyze the repository and write an architectural plan in docs/PHASE_1.md, then start phase 1."),
    ]

    def _hero_html(self) -> str:
        name = html.escape(os.path.basename(self.folder) or self.folder) if self.folder else ""
        sub = (f"Working in <span style='color:{TEXT};'>{name}</span> &nbsp;·&nbsp; runs fully offline on this PC"
               if self.folder else "Open a project folder to begin &nbsp;·&nbsp; runs fully offline on this PC")
        rows = ""
        if self.folder:
            for i, (title, _prompt) in enumerate(self.SUGGESTIONS):
                rows += (f'<tr><td bgcolor="{SURFACE}" style="background-color:{SURFACE}; border:1px solid {LINE}; padding:11px 16px;">'
                         f'<a href="action:suggest:{i}" style="color:{TEXT}; text-decoration:none; font-size:13px;">{html.escape(title)}'
                         f'</a> <span style="color:{SUBTLE};">&nbsp;→</span></td></tr><tr><td height="6"></td></tr>')
        else:
            rows = (f'<tr><td align="center"><a href="action:open" style="color:{ACCENT_HOVER}; text-decoration:none;">'
                    f'Open folder…</a></td></tr>')
        return (f'<table width="100%" cellspacing="0" cellpadding="0"><tr><td height="40"></td></tr>'
                f'<tr><td align="center" style="color:{ACCENT}; font-size:26px;">◆</td></tr>'
                f'<tr><td align="center" style="color:#ffffff; font-size:22px; font-weight:600; padding:8px 0 4px 0;">What should we build?</td></tr>'
                f'<tr><td align="center" style="color:{MUTED}; font-size:12.5px; padding-bottom:22px;">{sub}</td></tr></table>'
                f'<table width="78%" align="center" cellspacing="0" cellpadding="0">{rows}</table>')

    def _item_html(self, role: str, text: str, p_idx: int, live: bool, working: bool) -> str:
        if role == "user":
            shown = text
            if len(shown) > 900:
                shown = shown[:700].rstrip() + f"\n… (+{len(text) - 700:,} more characters; the full brief was sent to the agent)"
            return (f'<table width="100%" cellspacing="0" cellpadding="0"><tr><td bgcolor="{RAISED}" '
                    f'style="background-color:{RAISED}; border:1px solid {LINE_STRONG}; padding:10px 14px;">'
                    f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
                    f'<td style="color:{SUBTLE}; font-size:11px; font-weight:600; letter-spacing:1px;">YOU</td>'
                    f'<td align="right"><a href="action:rerun:{p_idx}" style="color:{MUTED}; text-decoration:none; font-size:11px;">Rerun</a>'
                    f'&nbsp;&nbsp;<a href="action:edit:{p_idx}" style="color:{MUTED}; text-decoration:none; font-size:11px;">Edit</a></td></tr></table>'
                    f'{_prose(shown)}</td></tr></table>' + _gap(14))
        if role == "error":
            return (f'<table width="100%" cellspacing="0" cellpadding="0"><tr><td bgcolor="{BAD_BG}" '
                    f'style="background-color:{BAD_BG}; border:1px solid #5a232b; padding:10px 14px; color:#ffc9ce;">'
                    f'<b style="color:{BAD};">Something went wrong</b><br>{html.escape(text)}<br>'
                    f'<a href="action:retry" style="color:#ffffff; font-weight:600; text-decoration:none;">Retry &nbsp;↻</a>'
                    f'</td></tr></table>' + _gap(10))
        if role == "note":
            if text.startswith("Phase "):
                return (_gap(6) + f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
                        f'<td width="22" style="color:{ACCENT}; font-size:12px;">◆</td>'
                        f'<td style="color:#ffffff; font-weight:600; font-size:13px; border-top:1px solid {LINE}; padding-top:8px;">'
                        f'{html.escape(text)}</td></tr></table>' + _gap(6))
            return (f'<table width="100%" cellspacing="0" cellpadding="0"><tr><td align="center" '
                    f'style="color:{SUBTLE}; font-size:11.5px; padding:4px 0;">{html.escape(text)}</td></tr></table>' + _gap(6))
        if not text.strip() and live and working:
            body = (f'<span style="color:{ACCENT};">●</span> '
                    f'<span style="color:{MUTED};">{html.escape(self.active_status_text)}</span>')
        else:
            body = message_html(text, is_generating=(live and working))
            if not body:
                body = f"<span style='color:{SUBTLE};'>No response.</span>"
        retry = ""
        if not working and ("did not produce an answer" in text or "error" in text.lower()):
            retry = (f'<br><a href="action:retry" style="color:{ACCENT_HOVER}; text-decoration:none; font-weight:600;">'
                     f'Retry prompt &nbsp;↻</a>')
        return (f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
                f'<td width="22" valign="top" style="color:{ACCENT}; padding-top:2px;">◆</td>'
                f'<td>{body}{retry}</td></tr></table>' + _gap(14))

    def _render_if_dirty(self):
        """Render the transcript. While the agent streams only the last message changes, so
        only that tail is replaced; re-parsing the whole chat 16 times a second made long
        sessions lag."""
        if not self._dirty:
            return
        self._dirty = False
        working = bool(self.worker)
        items = []
        user_idx = 0
        last = len(self.transcript) - 1
        for i, (role, text) in enumerate(self.transcript):
            p_idx = user_idx
            if role == "user":
                user_idx += 1
            live = (i == last)
            key = (role, text, p_idx, live and working, self.active_status_text if (live and working and not text.strip()) else "")
            html_item = self._item_cache.get(key)
            if html_item is None:
                if len(self._item_cache) > 300:
                    self._item_cache.clear()
                html_item = self._item_cache[key] = self._item_html(role, text, p_idx, live, working)
            items.append(html_item)
        if not items:
            items = [self._hero_html()]

        prev = self._rendered_items
        if prev and len(prev) == len(items) and prev[-1] == items[-1] and prev[:-1] == items[:-1]:
            return
        bar = self.chat.verticalScrollBar()
        was_at_bottom = self._auto_scroll_to_bottom or (bar.value() >= bar.maximum() - 70)
        old_val = bar.value()

        doc = self.chat.document()
        if prev and len(prev) == len(items) and prev[:-1] == items[:-1] and self._tail_pos is not None:
            cursor = QtGui.QTextCursor(doc)
            cursor.setPosition(self._tail_pos)
            cursor.movePosition(QtGui.QTextCursor.End, QtGui.QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
            cursor.insertHtml(items[-1])
        else:
            self.chat.setHtml("".join(items[:-1]))
            self._tail_pos = max(0, doc.characterCount() - 1)
            cursor = QtGui.QTextCursor(doc)
            cursor.movePosition(QtGui.QTextCursor.End)
            cursor.insertHtml(items[-1])
        self._rendered_items = items

        if was_at_bottom:
            self.scroll_to_bottom()
        else:
            bar.setValue(old_val)

    def _warmup_ai_if_needed(self):
        if not core.check_ai_health():
            threading.Thread(target=core.ensure_ai_service, daemon=True).start()

    def _check_ai_status(self):
        engine = providers.get_active_engine()
        if hasattr(self, "ai_badge"):
            if engine["is_local"]:
                healthy = core.check_ai_health()
                if healthy:
                    self.ai_badge.setText("●  devos-ai-code (Local) ▾")
                    self.ai_badge.setProperty("state", "online")
                    self.ai_badge.setToolTip("DevOS AI Core (Local Offline Engine) is active on 127.0.0.1:11434.\nClick to change model or speed acceleration settings.")
                else:
                    self.ai_badge.setText("▲  Offline · click to set up ▾")
                    self.ai_badge.setProperty("state", "offline")
                    self.ai_badge.setToolTip("DevOS AI Core is offline.\nClick to start local engine or switch to Gemini/Groq.")
            else:
                has_key = bool(engine.get("api_key"))
                status_icon = "●" if has_key else "▲"
                self.ai_badge.setText(f"{status_icon}  {engine['badge']} ▾")
                self.ai_badge.setProperty("state", "cloud" if has_key else "warning")
                self.ai_badge.setToolTip(f"Active Provider: {engine['name']}\nModel: {engine['model']}\nSpeed: {engine['speed']}\nClick to configure AI engines and API keys.")
            self.ai_badge.style().unpolish(self.ai_badge)
            self.ai_badge.style().polish(self.ai_badge)

    def _on_badge_clicked(self):
        dlg = EngineSettingsDialog(self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.llm = core.LocalLLM()
            self._check_ai_status()
            eng = providers.get_active_engine()
            self.statusBar().showMessage(f"AI Engine switched to: {eng['name']} ({eng['model']}) — {eng['speed']}", 6000)

    def _manual_start_ai(self):
        core.ensure_ai_service(timeout_seconds=15.0)
        QtCore.QMetaObject.invokeMethod(self, "_check_ai_status", QtCore.Qt.QueuedConnection)

    def quick_run_app(self):
        """Quick action: automatically detects app entrypoint and runs dev server."""
        if not self.folder:
            self.choose_folder()
            if not self.folder:
                return
        try:
            run_info = core.Workspace(self.folder).detect_run_info()
            cmd = run_info.get("command")
            if cmd:
                self.composer.setPlainText(f"Run the application dev server using `{cmd}` and verify operational status.")
                self.send()
            else:
                self.composer.setPlainText("Identify the project entrypoint, launch the dev server, and check the landing page.")
                self.send()
        except Exception as e:
            self.composer.setPlainText(f"Run the application and verify landing page status. ({e})")
            self.send()

    def quick_open_preview(self):
        """Quick action: opens the live landing page in the web browser."""
        url = "http://localhost:3000"
        if self.folder:
            try:
                run_info = core.Workspace(self.folder).detect_run_info()
                if run_info.get("url"):
                    url = run_info["url"]
            except Exception:
                pass
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))
        self.statusBar().showMessage(f"Opened live preview at {url}", 4000)

    # ---------------------------------------------------------------- send & stop
    def _update_queue_ui(self):
        if not self.prompt_queue:
            self.queue_bar.setVisible(False)
            return
        count = len(self.prompt_queue)
        first_text, _ = self.prompt_queue[0]
        preview = (first_text[:50] + "…") if len(first_text) > 50 else (first_text or "[Image Prompt]")
        self.queue_label.setText(f"⏳ Queued Prompt ({count}): \"{preview}\"")
        self.queue_bar.setVisible(True)

    def clear_queue(self):
        self.prompt_queue.clear()
        self._update_queue_ui()
        self.statusBar().showMessage("Cleared prompt queue.", 3000)

    def run_next_queued_now(self):
        if not self.prompt_queue:
            return
        next_task, next_attached = self.prompt_queue.pop(0)
        self._update_queue_ui()
        if self.worker:
            self.stop()
            # Launch as soon as worker thread halts
            def wait_and_launch():
                if self.worker and self.worker.isRunning():
                    QtCore.QTimer.singleShot(60, wait_and_launch)
                else:
                    self._execute_prompt(next_task, next_attached)
            QtCore.QTimer.singleShot(100, wait_and_launch)
        else:
            self._execute_prompt(next_task, next_attached)

    def send(self):
        raw_task = self.composer.toPlainText().strip()
        if not raw_task and not self.attached_images:
            return
        if not self.capable:
            return

        if raw_task:
            self.composer.add_history(raw_task)

        attached = list(self.attached_images)
        self.attached_images.clear()
        self._update_attachment_bar()
        self.composer.clear()

        # If a task is actively running, queue this new prompt cleanly!
        if self.worker:
            self.prompt_queue.append((raw_task, attached))
            self._update_queue_ui()
            self.statusBar().showMessage(
                f"Prompt queued ({len(self.prompt_queue)} in queue). Runs next, or click 'Interrupt & Run Now'.",
                4000
            )
            return

        self._execute_prompt(raw_task, attached)

    def rerun_last_prompt(self):
        if not self.last_task and not self.user_prompts:
            return
        task = self.last_task if self.last_task else self.user_prompts[-1][0]
        att = list(self.last_attached if self.last_task else self.user_prompts[-1][1])
        if self.worker:
            self.composer.setPlainText(task)
            self.composer.setFocus()
            self.statusBar().showMessage("Copied previous prompt to composer.", 3000)
            return
        curr = self.composer.toPlainText().strip()
        if not curr:
            self._execute_prompt(task, att)
        else:
            self.composer.setPlainText(task)
            self.composer.setFocus()

    def _on_anchor_clicked(self, url: QtCore.QUrl):
        href = url.toString()
        if href in ("action:retry", "action:rerun"):
            self.rerun_last_prompt()
            return
        if href == "action:open":
            self.choose_folder()
            return
        if href.startswith("action:suggest:"):
            try:
                self.insert_prompt(self.SUGGESTIONS[int(href.split(":")[-1])][1])
            except (ValueError, IndexError):
                pass
            return
        if href.startswith("action:rerun:"):
            try:
                idx = int(href.split(":")[-1])
                if 0 <= idx < len(self.user_prompts):
                    task, att = self.user_prompts[idx]
                    self._execute_prompt(task, list(att))
            except Exception:
                pass
            return
        if href.startswith("action:edit:"):
            try:
                idx = int(href.split(":")[-1])
                if 0 <= idx < len(self.user_prompts):
                    task, _ = self.user_prompts[idx]
                    self.composer.setPlainText(task)
                    self.composer.setFocus()
                    c = self.composer.textCursor()
                    c.movePosition(QtGui.QTextCursor.End)
                    self.composer.setTextCursor(c)
            except Exception:
                pass
            return
        QtGui.QDesktopServices.openUrl(url)

    def _execute_prompt(self, raw_task, attached):
        if not self.folder:
            self.choose_folder()
            if not self.folder:
                return

        self.last_task = raw_task
        self.last_attached = list(attached)
        self.user_prompts.append((raw_task, list(attached)))
        if hasattr(self, "rerun_btn"):
            self.rerun_btn.setEnabled(True)
            self.rerun_btn.setText("Rerun last")
            self.rerun_btn.setStyleSheet("")

        task_text = raw_task if raw_task else "Please inspect the attached screenshot / image and address any issues, errors, or requests shown in it."

        display_text = task_text
        worker_task_parts = [task_text]

        if attached:
            for p in attached:
                display_text += f"\n[Attached image: {p}]"

                ocr_text = ""
                try:
                    if vision and vision.ocr_available():
                        extracted, _ = vision.ocr(p)
                        if extracted and extracted.strip():
                            ocr_text = extracted.strip()
                except Exception:
                    pass

                part = f"[Attached image: {p}]"
                if ocr_text:
                    part += f"\n[Extracted text/code from {os.path.basename(p)} via OCR]:\n```\n{ocr_text}\n```"
                worker_task_parts.append(part)

        agent_task = "\n\n".join(worker_task_parts)

        self.transcript.append(["user", display_text])
        self.transcript.append(["agent", ""])
        self._phase_mode = False
        self.plan.clear()
        self.plan_progress.setValue(0)
        self._auto_scroll_to_bottom = True
        self._dirty = True
        self.scroll_to_bottom()

        self.start_time = time.time()
        self._elapsed_timer.start()

        # Update thinking banner
        self.current_topic = core.extract_task_topic(agent_task)
        self.active_status_text = "Analyzing project context & task requirements..."
        self.tb_status.setText(self.active_status_text)
        self.tb_topic.setText(self.current_topic)
        self.thinking_banner.setVisible(True)
        # Collect previous conversation turns for multi-turn context
        history_turns = []
        for role, text in self.transcript[:-2]:
            if text and text.strip():
                history_turns.append({
                    "role": "user" if role == "user" else "assistant",
                    "content": text.strip()[:2000]
                })

        self.worker = AgentWorker(self.folder, agent_task, self.policy, self.llm, history=history_turns)
        self.worker.event.connect(self.on_event)
        self.worker.approval.connect(self.on_approval)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.on_finished)

        self.send_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.stop_btn.setVisible(True)
        self.go_bar.setVisible(False)
        self._set_chip("Thinking…")
        self._inhibit_sleep()
        self.worker.start()

    def stop(self):
        self._uninhibit_sleep()
        if self.worker:
            self.worker.cancel()
            self._set_chip("Stopping…", "idle")
            self.tb_status.setText("Aborting active operation...")
            QtCore.QTimer.singleShot(1200, self._force_cleanup_worker)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setVisible(False)
        self.send_btn.setEnabled(True)
        self._set_pending(None)

    def _force_cleanup_worker(self):
        if self.worker and self.worker.isRunning():
            try:
                self.worker.terminate()
                self.worker.wait(150)
            except Exception:
                pass
            self.on_finished()


    # ---------------------------------------------------------------- event loop
    def on_event(self, kind, payload):
        if kind == "task_init":
            self.current_topic = payload.get("topic", "")
            self.tb_topic.setText(self.current_topic)
            initial_plan = payload.get("plan", [])
            if initial_plan:
                for step in initial_plan:
                    self._add_step(step, "plan")
        elif kind == "thinking_status":
            self.active_status_text = payload.get("status", "")
            self.tb_status.setText(self.active_status_text)
            step_num = payload.get("step", 1)
            self._set_chip(f"Step {step_num} · thinking")
            self._dirty = True
        elif kind == "thinking":
            self._set_chip(f"Step {payload} · working")
            last = self.transcript[-1] if self.transcript else None
            if last is None or last[0] != "agent" or last[1]:
                self.transcript.append(["agent", ""])
        elif kind == "token":
            if not self.transcript or self.transcript[-1][0] != "agent":
                self.transcript.append(["agent", ""])
            self.transcript[-1][1] += payload
            self._dirty = True
        elif kind == "plan":
            self.plan.clear()
            for step in payload:
                self._add_step(step, "plan")
            self._update_plan_progress()
        elif kind == "phase":
            self._phase_mode = True
            self._set_chip(f"Phase {payload['index']} of {payload['total']}")
            if self.transcript and self.transcript[-1] == ["agent", ""]:
                self.transcript.pop()            # the empty placeholder: the phase header goes first
            self.transcript.append(["note", f"Phase {payload['index']} of {payload['total']}: {payload['title']}"])
            self.transcript.append(["agent", ""])
            self._set_phase_row(payload["index"], "running")
            self._dirty = True
        elif kind == "report":
            if self.transcript and self.transcript[-1] == ["agent", ""]:
                self.transcript[-1][1] = payload
            else:
                self.transcript.append(["agent", payload])
            self._dirty = True
        elif kind == "speed":
            self.speed_label.setText(f"{payload['tokens_per_sec']} tok/s · last reply {payload['seconds']}s")
        elif kind == "step":
            self._set_chip(payload['title'][:34])
            if not self._phase_mode:
                self._add_step(payload["title"], "running")
                self._update_plan_progress()
        elif kind == "step_status":
            if not self._phase_mode:
                self._mark_last_step(payload)
                self._update_plan_progress()
        elif kind == "phase_done":
            self._set_phase_row(payload["index"], "done" if payload.get("ok") else "failed")
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
            self._dirty = True
            if self.transcript and self.transcript[-1] == ["agent", ""]:
                self.transcript[-1][1] = payload or "Task completed successfully."
            agent = getattr(self.worker, "agent", None)
            changed = getattr(agent, "changed", None) or []
            count = len(set(changed))
            if count:
                self.transcript.append(["note", f"Done · {count} file{'s' if count != 1 else ''} changed"])
            else:
                self.transcript.append(["note", "Execution completed."])
            self.thinking_banner.setVisible(False)

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
        self._set_chip("Waiting for you", "idle")
        QtWidgets.QApplication.alert(self)

    def respond(self, ok: bool):
        if self.worker and self.pending is not None:
            self.worker.answer(ok)
        if self.pending is not None and self.pending.kind == "command" and not ok:
            self.terminal.appendPlainText("(denied)\n")
        self.pending = None
        self._set_pending(None)
        if self.worker:
            self._set_chip("Working…")

    def on_failed(self, message):
        self.transcript.append(["error", message])
        self.thinking_banner.setVisible(False)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setVisible(False)
        self.send_btn.setEnabled(True)
        if hasattr(self, "rerun_btn"):
            self.rerun_btn.setEnabled(True)
            self.rerun_btn.setText("Retry failed prompt")
        self._dirty = True

    def on_finished(self):
        self._uninhibit_sleep()
        self.worker = None
        self.pending = None
        self._set_pending(None)
        self._elapsed_timer.stop()
        self.thinking_banner.setVisible(False)
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setVisible(False)
        self._set_chip("Idle", "idle")
        self.speed_label.setText("")
        self._update_go_bar()
        self._update_plan_progress()

        # Check if last response was an error/failure
        if self.transcript and any(err in self.transcript[-1][1].lower() for err in ("did not produce an answer", "failed", "error")):
            if hasattr(self, "rerun_btn"):
                self.rerun_btn.setEnabled(True)
                self.rerun_btn.setText("Retry failed prompt")

        # If there are queued prompts, execute the next one in queue
        if self.prompt_queue:
            next_task, next_attached = self.prompt_queue.pop(0)
            self._update_queue_ui()
            QtCore.QTimer.singleShot(120, lambda: self._execute_prompt(next_task, next_attached))


    # ---------------------------------------------------------------- helpers
    def _show_change(self, action):
        self.diff_title.setText(action.title)
        self.diff.setHtml(diff_html(action.diff))
        if hasattr(self, "tabs"):
            self.tabs.setCurrentWidget(self.diff_card)
            self.tabs.setTabText(0, "Changes · Pending")

    def _set_pending(self, action):
        edit = bool(action and action.kind == "edit")
        command = bool(action and action.kind == "command")
        self.diff_btn_box.setVisible(edit)
        self.accept_btn.setEnabled(edit)
        self.reject_btn.setEnabled(edit)
        self.term_btn_box.setVisible(command)
        self.run_btn.setEnabled(command)
        self.deny_btn.setEnabled(command)
        if edit and hasattr(self, "tabs"):
            self.tabs.setCurrentWidget(self.diff_card)
        elif command and hasattr(self, "tabs"):
            self.tabs.setCurrentWidget(self.term_card)
        for frame, on in ((self.diff_card, edit), (self.term_card, command)):
            frame.setProperty("attention", "true" if on else "false")
            frame.style().unpolish(frame)
            frame.style().polish(frame)

    def _add_step(self, title, state):
        idx = self.plan.count() + 1
        item = QtWidgets.QListWidgetItem(f"{idx:02d}. {STEP_ICON[state]}  {title[:85]}")
        item.setData(QtCore.Qt.UserRole, title)
        item.setForeground(QtGui.QColor(STEP_COLOR[state] if state != "plan" else TEXT))
        self.plan.addItem(item)
        self.plan.scrollToBottom()

    def _set_phase_row(self, number: int, state: str):
        """Roadmap row of a brief phase: the row whose title starts 'Phase <number>', else the number-th row."""
        row = next((r for r in range(self.plan.count())
                    if (self.plan.item(r).data(QtCore.Qt.UserRole) or "").startswith(f"Phase {number} ")), None)
        if row is None and 0 < number <= self.plan.count():
            row = number - 1
        if row is None:
            return
        item = self.plan.item(row)
        title = item.data(QtCore.Qt.UserRole) or ""
        item.setText(f"{row + 1:02d}. {STEP_ICON.get(state, '?')}  {title[:85]}")
        item.setForeground(QtGui.QColor(STEP_COLOR.get(state, MUTED)))
        self._update_plan_progress()

    def _mark_last_step(self, state):
        for row in range(self.plan.count() - 1, -1, -1):
            item = self.plan.item(row)
            if STEP_ICON["running"] in item.text():
                title = item.data(QtCore.Qt.UserRole)
                idx = row + 1
                item.setText(f"{idx:02d}. {STEP_ICON.get(state, '?')}  {title[:85]}")
                item.setForeground(QtGui.QColor(STEP_COLOR.get(state, MUTED)))
                return

    def _update_plan_progress(self):
        total = self.plan.count()
        if total == 0:
            self.plan_progress.setValue(0)
            if hasattr(self, "tabs"):
                self.tabs.setTabText(2, "Roadmap")
            return
        done_count = sum(1 for row in range(total) if STEP_ICON["done"] in self.plan.item(row).text())
        pct = int((done_count / total) * 100)
        self.plan_progress.setValue(pct)
        if hasattr(self, "tabs"):
            self.tabs.setTabText(2, f"Roadmap · {pct}%")
        self.plan_progress.setToolTip(f"{done_count}/{total} steps completed ({pct}%)")

    def _policy_changed(self):
        self.policy.auto_reads = self.auto_reads.isChecked()
        self.policy.auto_edits = self.auto_edits.isChecked()
        self.policy.auto_commands = getattr(self, 'auto_commands', None) and self.auto_commands.isChecked()
        self._update_status()

    def _update_status(self):
        if not getattr(self, "capable", True):
            self.status.setText("DevOS AI Code Agent is waiting for a coding-capable DevOS AI model.")
            return
        rg = "Ripgrep Accelerated" if shutil.which("rg") else "Built-in Search"
        cmd_str = "Auto-commands: ON" if getattr(self.policy, "auto_commands", False) else "Commands: Ask First"
        self.status.setText(
            f"Local Neural Engine · {'Auto-reads: ON' if self.policy.auto_reads else 'Auto-reads: OFF'} · "
            f"{'Auto-edits: ON' if self.policy.auto_edits else 'Auto-edits: OFF'} · {cmd_str} · {rg} · 100% Private Offline")
        if hasattr(self, "hint"):
            auto_c = getattr(self.policy, "auto_commands", False)
            auto_e = getattr(self.policy, "auto_edits", False)
            if auto_e and auto_c:
                self.hint.setText("Autonomous mode · Reads, edits & terminal commands run automatically")
            elif auto_c:
                self.hint.setText("Reads & terminal commands automatic · Edits ask for approval")
            elif auto_e:
                self.hint.setText("Reads & edits automatic · Terminal commands ask for approval")
            else:
                self.hint.setText("Reads automatic · Edits & terminal commands ask for approval")

    def closeEvent(self, event):
        self._uninhibit_sleep()
        if self.worker:
            self.worker.cancel()
            self.worker.wait(3000)
        super().closeEvent(event)


# ==============================================================================
# Entry Point
# ==============================================================================
def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["devos-ai-code-agent"] + sys.argv[1:])
    app.setApplicationName("devos-ai-code-agent")
    app.setApplicationDisplayName("DevOS AI Code Agent")
    app.setDesktopFileName("devos-ai-code-agent")
    app.setWindowIcon(get_app_icon())
    folder = next((a for a in argv if not a.startswith("-")), "")
    if folder and not os.path.isdir(folder):
        folder = os.path.dirname(os.path.abspath(folder)) if os.path.exists(folder) else ""
    if not folder:
        folder = get_last_opened_folder()
    window = AgentWindow(folder)
    window.show()
    return app.exec_()




if __name__ == "__main__":
    sys.exit(main())
