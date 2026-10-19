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
# Theme & Premium Palette (Deep Obsidian & Cyber Cyan)
# ==============================================================================
BG = "#080c14"
CARD = "#0d1526"
CARD_HOVER = "#111c33"
LINE = "#1a263e"
LINE_ACTIVE = "#38bdf8"
TEXT = "#f1f5f9"
MUTED = "#94a3b8"
SUBTLE = "#64748b"
ACCENT = "#38bdf8"
ACCENT_HOVER = "#0ea5e9"
VIOLET = "#818cf8"
GOOD = "#10b981"
GOOD_BG = "#064e3b"
BAD = "#ef4444"
BAD_BG = "#450a0a"
AMBER = "#f59e0b"
AMBER_BG = "#451a03"

STYLE = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: 'Inter', 'Segoe UI', 'Noto Sans', sans-serif;
    font-size: 13.5px;
}}
QLabel {{ background: transparent; }}
QLabel#title {{
    font-size: 17px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: 0.3px;
}}
QLabel#subtitle {{
    font-size: 11.5px;
    color: {MUTED};
}}
QLabel#muted, QLabel#path {{ color: {MUTED}; }}
QLabel#cardTitle {{
    font-size: 11.5px;
    font-weight: 700;
    color: #7dd3fc;
    letter-spacing: 0.8px;
}}
QPushButton#badge {{
    background: #042f2e;
    color: #2dd4bf;
    border: 1px solid #0f766e;
    border-radius: 12px;
    padding: 3px 12px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#badge[state="online"] {{
    background: #042f2e;
    color: #2dd4bf;
    border: 1px solid #0f766e;
}}
QPushButton#badge[state="starting"] {{
    background: #451a03;
    color: #fde047;
    border: 1px solid #b45309;
}}
QPushButton#badge[state="offline"] {{
    background: #4c0519;
    color: #fb7185;
    border: 1px solid #e11d48;
}}
QPushButton#badge:hover {{
    border-color: #38bdf8;
}}
QLabel#chip {{
    background: #1e1b4b;
    color: #c4b5fd;
    border: 1px solid #4338ca;
    border-radius: 9px;
    padding: 3px 11px;
    font-size: 12px;
    font-weight: 600;
}}
QLabel#topicLabel {{
    color: #38bdf8;
    font-size: 12.5px;
    font-weight: 600;
}}
QFrame#topbar {{
    background: #09101f;
    border-bottom: 1px solid {LINE};
}}
QFrame#card {{
    background: {CARD};
    border: 1px solid {LINE};
    border-radius: 12px;
}}
QFrame#card[attention="true"] {{
    border: 1px solid {ACCENT};
    background: #0f1a30;
}}
QFrame#thinkingCard {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0d1a33, stop:1 #111e3b);
    border: 1px solid #2563eb;
    border-radius: 10px;
}}
QFrame#gate {{
    background: {CARD};
    border: 1px solid {LINE};
    border-radius: 18px;
}}
QPushButton {{
    background: #17243c;
    border: 1px solid #253654;
    border-radius: 8px;
    padding: 7px 14px;
    color: {TEXT};
    font-weight: 500;
}}
QPushButton:hover {{
    background: #203152;
    border-color: #38bdf8;
}}
QPushButton:disabled {{
    color: #475569;
    background: #0d1627;
    border-color: #1e293b;
}}
QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #6366f1);
    border: 1px solid #38bdf8;
    color: #ffffff;
    font-weight: 600;
    padding: 8px 18px;
    border-radius: 8px;
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0369a1, stop:1 #4f46e5);
    border-color: #7dd3fc;
}}
QPushButton#primary:disabled {{
    background: #1e293b;
    border-color: #334155;
    color: #64748b;
}}
QPushButton#stopBtn {{
    background: #450a0a;
    border: 1px solid #991b1b;
    color: #fecaca;
    font-weight: 600;
    border-radius: 8px;
}}
QPushButton#stopBtn:hover {{
    background: #7f1d1d;
    border-color: #ef4444;
}}
QPushButton#accept {{
    background: #064e3b;
    border: 1px solid #059669;
    color: #d1fae5;
    font-weight: 600;
    border-radius: 8px;
}}
QPushButton#accept:hover {{
    background: #047857;
    border-color: #10b981;
}}
QPushButton#reject {{
    background: #450a0a;
    border: 1px solid #b91c1c;
    color: #fee2e2;
    border-radius: 8px;
}}
QPushButton#reject:hover {{
    background: #7f1d1d;
    border-color: #ef4444;
}}
QPushButton#quickPill {{
    background: #111c30;
    border: 1px solid #1e2e4a;
    color: #94a3b8;
    border-radius: 12px;
    padding: 3px 10px;
    font-size: 11.5px;
}}
QPushButton#quickPill:hover {{
    background: #1a2a47;
    color: #38bdf8;
    border-color: #38bdf8;
}}
QTextBrowser, QPlainTextEdit, QListWidget {{
    background: #070e1c;
    border: 1px solid {LINE};
    border-radius: 9px;
    padding: 8px;
    selection-background-color: #1d4ed8;
}}
QPlainTextEdit#composer {{
    background: #0a1324;
    border: 1px solid #223452;
    border-radius: 10px;
    padding: 9px;
    font-size: 13.5px;
}}
QPlainTextEdit#composer:focus {{
    border: 1px solid {ACCENT};
    background: #0c172d;
}}
QFrame#attachmentBar {{
    background: #0b1528;
    border: 1px dashed #1e3a6a;
    border-radius: 8px;
    padding: 3px 6px;
}}
QFrame#attachmentChip {{
    background: #101e38;
    border: 1px solid #1e3c70;
    border-radius: 6px;
}}
QPushButton#removeAttachBtn {{
    background: transparent;
    border: none;
    color: #ef4444;
    font-size: 11px;
    font-weight: bold;
    padding: 0 4px;
}}
QPushButton#removeAttachBtn:hover {{
    color: #fca5a5;
    background: #450a0a;
    border-radius: 3px;
}}
QPushButton#attachBtn {{
    background: #111c30;
    border: 1px solid #1e2e4a;
    color: #94a3b8;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 12px;
}}
QPushButton#attachBtn:hover {{
    background: #1a2a47;
    color: #38bdf8;
    border-color: #38bdf8;
}}
QPlainTextEdit#terminal {{
    font-family: 'JetBrains Mono', 'Fira Code', 'DejaVu Sans Mono', monospace;
    font-size: 12px;
    color: #cbd5e1;
    background: #040812;
}}
QListWidget {{
    background: #070e1c;
    border: 1px solid {LINE};
    border-radius: 9px;
}}
QListWidget::item {{
    padding: 7px 6px;
    border-radius: 7px;
    margin-bottom: 2px;
}}
QListWidget::item:selected {{
    background: #132442;
    color: #ffffff;
}}
QCheckBox {{
    background: transparent;
    color: {MUTED};
    spacing: 7px;
    font-size: 12.5px;
}}
QCheckBox::indicator {{
    width: 28px;
    height: 15px;
    border-radius: 7px;
    background: #23334d;
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
}}
QProgressBar {{
    border: 1px solid #1e293b;
    border-radius: 4px;
    text-align: center;
    background: #0a1222;
    color: #7dd3fc;
    font-size: 11px;
    font-weight: 600;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #38bdf8);
    border-radius: 3px;
}}
QSplitter::handle {{ background: {BG}; }}
QScrollBar:vertical {{
    background: transparent;
    width: 9px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #253654;
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: #38bdf8;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QStatusBar, QLabel#status {{
    color: {MUTED};
    font-size: 12px;
}}
"""

STEP_ICON = {"running": "⚡", "done": "✓", "denied": "✕", "failed": "!", "plan": "○"}
STEP_COLOR = {"running": ACCENT, "done": GOOD, "denied": BAD, "failed": "#fbbf24", "plan": MUTED}


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
        return ("<div style=\"color:#94a3b8; font-family:'JetBrains Mono','Fira Code',monospace; "
                "font-size:12px; padding:14px; font-style:italic;\">(New empty file or no content changes)</div>")
    rows = []
    lines = diff.splitlines()
    for i, line in enumerate(lines):
        text = html.escape(line) or "&nbsp;"
        if line.startswith("+++") or line.startswith("---"):
            style = f"color:{MUTED}; font-weight: 600;"
        elif line.startswith("+"):
            style = "background-color:#063520; color:#a7f3d0;"
        elif line.startswith("-"):
            style = "background-color:#3d0d17; color:#fecaca;"
        elif line.startswith("@@"):
            style = f"color:{VIOLET}; font-weight: 600;"
        else:
            style = "color:#cbd5e1;"
        rows.append(f'<tr><td width="36" style="color:#475569; padding:0 6px; text-align:right; user-select:none;">{i+1}</td>'
                    f'<td style="{style} padding:0 8px; white-space:pre;">{text}</td></tr>')
    return ("<table width='100%' cellspacing='0' cellpadding='0' style=\"font-family:'JetBrains Mono',"
            "'Fira Code',monospace; font-size:12px; line-height: 1.4;\">" + "".join(rows) + "</table>")


_TOOL_BLOCK = re.compile(r"```[ \t]*tool[ \t]*([^\n]*)\n(.*?)(?:\n```|\Z)|<tool_call>(.*?)(?:</tool_call>|\Z)", re.S)
_CODE_BLOCK = re.compile(r"```([^\n]*)\n(.*?)(?:\n```|\Z)", re.S)
_THINK_BLOCK = re.compile(r"<think>(.*?)(?:</think>|\Z)", re.S)


def message_html(text: str, is_generating: bool = False) -> str:
    """Format AI text into rich markdown, live code previews, and reasoning cards."""
    if not text:
        return ""

    out = []
    
    # 1. Format reasoning <think> tags if present
    think_match = _THINK_BLOCK.search(text)
    if think_match:
        think_content = think_match.group(1).strip()
        if think_content:
            out.append(f'''
            <div style="background:#091224; border:1px solid #1e3a6a; border-left:3px solid #818cf8; border-radius:8px; padding:8px 12px; margin:6px 0;">
              <div style="color:#a5b4fc; font-weight:700; font-size:11px; letter-spacing:0.5px; margin-bottom:4px;">
                🧠 NEURAL REASONING & THOUGHT PROCESS
              </div>
              <div style="color:#cbd5e1; font-size:12px; line-height:1.4;">{html.escape(think_content)}</div>
            </div>
            ''')
        text = _THINK_BLOCK.sub("", text)

    pieces = []
    pos = 0
    for match in _TOOL_BLOCK.finditer(text):
        pieces.append(("text", text[pos:match.start()]))
        raw_call = match.group(0)
        call = core.parse_tool_call(raw_call)
        
        tool_name = call.name if call else "tool"
        target = ""
        content = ""
        if call:
            target = str(call.args.get("path") or call.args.get("pattern") or call.args.get("command") or "")
            if call.name == "apply_patch":
                target = ", ".join(re.findall(r"^\+\+\+ (?:b/)?(\S+)", str(call.args.get("patch", "")), re.M)) or target
                content = str(call.args.get("patch", ""))
            elif call.name == "write_file":
                content = str(call.args.get("content", ""))
            elif call.name == "run_command":
                content = str(call.args.get("command", ""))
        else:
            # Check if streaming tool call
            first_line = raw_call.splitlines()[0] if raw_call else ""
            tool_name = first_line.replace("```tool", "").strip() or "tool"
            m_path = re.search(r"(?:path|file|target)[:\s]*([^\n]+)", raw_call, re.I)
            if m_path:
                target = m_path.group(1).strip()
            # Extract content after ---
            if "---" in raw_call:
                content = raw_call.split("---", 1)[1]

        pieces.append(("tool", (tool_name, target, content)))
        pos = match.end()
    pieces.append(("text", text[pos:]))

    for kind, value in pieces:
        if kind == "tool":
            tool_name, target, content = value
            tool_title = f"{tool_name.replace('_', ' ').upper()}"
            if target:
                tool_title += f" · {html.escape(target)}"
            
            if content.strip():
                lines = content.strip().splitlines()
                preview = "\n".join(lines[:30])
                more = f"\n... ({len(lines) - 30} more lines)" if len(lines) > 30 else ""
                live_badge = ' &nbsp;<span style="color:#38bdf8; font-size:11px;">(Generating...)</span>' if is_generating else ''
                out.append(f'''
                <div style="background:#071224; border:1px solid #1e3a6a; border-radius:9px; margin:8px 0; overflow:hidden;">
                  <div style="background:#0e1e3b; padding:6px 12px; color:#38bdf8; font-size:12px; font-weight:700; border-bottom:1px solid #1e3a6a;">
                    ⚡ {tool_title}{live_badge}
                  </div>
                  <pre style="background:#040914; color:#e2e8f0; font-family:'JetBrains Mono','Fira Code',monospace; font-size:12px; padding:10px; margin:0; white-space:pre-wrap; line-height:1.4;">{html.escape(preview + more)}</pre>
                </div>
                ''')
            else:
                out.append(f'''
                <div style="background:#09152b; border:1px solid #1e2c45; border-radius:7px; padding:5px 12px; margin:6px 0; display:inline-block;">
                  <span style="color:#7dd3fc; font-weight:600; font-size:12px;">⚡ {tool_title}</span>
                </div>
                ''')
            continue

        last = 0
        for code in _CODE_BLOCK.finditer(value):
            out.append(_prose(value[last:code.start()]))
            lang = (code.group(1) or "code").strip()
            out.append(f'''
            <div style="background:#050c18; border:1px solid #1a273e; border-radius:8px; margin:6px 0; overflow:hidden;">
              <div style="background:#091426; padding:4px 10px; color:#64748b; font-size:11px; font-family:sans-serif; border-bottom:1px solid #152238;">
                {html.escape(lang)}
              </div>
              <pre style="color:#e2e8f0; font-family:'JetBrains Mono','Fira Code',monospace; font-size:12px; padding:10px; margin:0; white-space:pre-wrap; line-height:1.4;">{html.escape(code.group(2))}</pre>
            </div>
            ''')
            last = code.end()
        out.append(_prose(value[last:]))
    return "".join(out)


def _prose(text: str) -> str:
    text = text.strip("\n")
    if not text.strip():
        return ""
    img_matches = list(re.finditer(r'\[Attached image: ([^\]]+)\]', text))
    clean_text = re.sub(r'\[Attached image: [^\]]+\]', '', text).strip()
    escaped = html.escape(clean_text)
    escaped = re.sub(r"`([^`\n]+)`", r'<code style="background:#111e33; color:#7dd3fc; padding:2px 5px; border-radius:4px; font-family:\'JetBrains Mono\',monospace; font-size:12px;">\1</code>', escaped)
    escaped = re.sub(r"\*\*([^*\n]+)\*\*", r"<b style='color:#ffffff;'>\1</b>", escaped)
    rendered = "<p style='margin:4px 0; line-height: 1.5;'>" + escaped.replace("\n", "<br>") + "</p>" if clean_text else ""

    if img_matches:
        img_html = ""
        for m in img_matches:
            ipath = m.group(1).strip()
            iname = os.path.basename(ipath)
            img_html += f'''
            <div style="margin: 6px 0; background: #081120; border: 1px solid #1a2c4e; border-radius: 8px; padding: 6px; display: inline-block;">
                <img src="{html.escape(ipath)}" width="240" style="border-radius: 6px;"><br>
                <span style="font-size: 11px; color: #94a3b8; font-family: monospace;">📷 {html.escape(iname)}</span>
            </div><br>
            '''
        rendered = img_html + rendered

    return rendered


# ==============================================================================
# Agent Composer (Enter to send, Shift+Enter newline, Drag/Drop & Paste Images)
# ==============================================================================
class AgentComposer(QtWidgets.QPlainTextEdit):
    submit_requested = QtCore.pyqtSignal()
    image_attached = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            if event.modifiers() & QtCore.Qt.ShiftModifier:
                super().keyPressEvent(event)
                return
            else:
                event.accept()
                self.submit_requested.emit()
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
        self.transcript = []  # [role, text]
        self.attached_images = []
        self.setAcceptDrops(True)
        self.current_topic = ""
        self.active_status_text = "Idle"
        self.start_time = 0
        self._dirty = False
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
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(8)

        # Brand Emblem & Title
        mark = QtWidgets.QLabel()
        mark.setFixedSize(30, 30)
        app_icon = get_app_icon()
        if not app_icon.isNull():
            mark.setPixmap(app_icon.pixmap(28, 28))
            mark.setStyleSheet("background: transparent;")
        else:
            mark.setStyleSheet("border-radius: 8px; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
                               "stop:0 #0ea5e9, stop:1 #6366f1); color: white; font-weight: 800; font-size: 13px;")
            mark.setText("⚡")
        mark.setAlignment(QtCore.Qt.AlignCenter)
        row.addWidget(mark)

        names = QtWidgets.QVBoxLayout()
        names.setSpacing(0)
        title = CompactLabel("DevOS AI Code Agent")
        title.setObjectName("title")
        title.setMinimumWidth(30)
        self.path_label = CompactLabel("No folder open")
        self.path_label.setObjectName("path")
        self.path_label.setStyleSheet("color: #38bdf8; font-weight: 500;")
        self.path_label.setMinimumWidth(30)
        names.addWidget(title)
        names.addWidget(self.path_label)
        row.addLayout(names)
        row.addSpacing(6)

        # Model Beacon Pill (Interactive Status)
        self.ai_badge = QtWidgets.QPushButton("●  devos-ai-code")
        self.ai_badge.setObjectName("badge")
        self.ai_badge.setMinimumWidth(30)
        self.ai_badge.setToolTip("DevOS AI Core is running on 127.0.0.1:11434.\nZero cloud latency, 100% private and offline.")
        self.ai_badge.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.ai_badge.clicked.connect(self._on_badge_clicked)
        row.addWidget(self.ai_badge)

        row.addStretch(1)

        # Policy Toggles
        self.auto_reads = QtWidgets.QCheckBox("Reads")
        self.auto_reads.setToolTip("Auto-approve reads: Automatically inspect project files without confirmation")
        self.auto_reads.setChecked(True)
        self.auto_reads.setMinimumWidth(20)
        self.auto_reads.toggled.connect(self._policy_changed)

        self.auto_edits = QtWidgets.QCheckBox("Edits")
        self.auto_edits.setToolTip("Auto-approve edits: Automatically apply file edits without confirmation")
        self.auto_edits.setMinimumWidth(20)
        self.auto_edits.toggled.connect(self._policy_changed)

        self.auto_commands = QtWidgets.QCheckBox("Commands")
        self.auto_commands.setToolTip("Auto-run commands: Automatically run terminal commands without confirmation")
        self.auto_commands.setMinimumWidth(20)
        self.auto_commands.toggled.connect(self._policy_changed)

        row.addWidget(self.auto_reads)
        row.addWidget(self.auto_edits)
        row.addWidget(self.auto_commands)

        # Quick Project Buttons
        folder_box = QtWidgets.QHBoxLayout()
        folder_box.setSpacing(2)
        self.open_btn = QtWidgets.QPushButton("📁 Open…")
        self.open_btn.setToolTip("Open project folder…")
        self.open_btn.setMinimumWidth(30)
        self.open_btn.clicked.connect(self.choose_folder)
        self.open_btn.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.open_btn.customContextMenuRequested.connect(lambda pos: self._show_recent_menu(self.open_btn.mapToGlobal(pos)))
        folder_box.addWidget(self.open_btn)

        self.recent_btn = QtWidgets.QPushButton("▾")
        self.recent_btn.setFixedWidth(24)
        self.recent_btn.setToolTip("Switch to recent project…")
        self.recent_btn.clicked.connect(lambda: self._show_recent_menu(self.recent_btn.mapToGlobal(self.recent_btn.rect().bottomLeft())))
        folder_box.addWidget(self.recent_btn)
        row.addLayout(folder_box)

        self.new_btn = QtWidgets.QPushButton("🧹 New")
        self.new_btn.setToolTip("Reset the chat canvas for a new objective")
        self.new_btn.setMinimumWidth(30)
        self.new_btn.clicked.connect(self.new_task)
        row.addWidget(self.new_btn)

        return bar

    def _show_recent_menu(self, global_pos: QtCore.QPoint):
        cfg = get_persisted_config()
        recents = [r for r in cfg.get("recent_folders", []) if os.path.isdir(r)]
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background: #0d1526; color: #f1f5f9; border: 1px solid {LINE}; border-radius: 8px; padding: 6px; }}
            QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
            QMenu::item:selected {{ background: #1e293b; color: {ACCENT}; }}
            QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 6px; }}
        """)
        choose_act = menu.addAction("📁 Browse folder…")
        choose_act.triggered.connect(self.choose_folder)
        if recents:
            menu.addSeparator()
            label_act = menu.addAction("Recent Projects:")
            label_act.setEnabled(False)
            for rpath in recents:
                rname = os.path.basename(rpath) or rpath
                prefix = "✓ " if rpath == self.folder else "   "
                act = menu.addAction(f"{prefix}📦 {rname}  ({rpath})")
                act.triggered.connect(lambda _, p=rpath: self.set_folder(p))
        menu.exec_(global_pos)


    # ----------------------------------------------------------------- main panel
    def _main_panel(self):
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 6)
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        split.setHandleWidth(8)
        split.setChildrenCollapsible(False)
        layout.addWidget(split)

        # Left Column: Conversation & Execution Canvas
        chat_card, chat_layout, chat_header = card("Conversation & Agent Execution")
        chat_card.setMinimumWidth(240)
        
        self.step_chip = QtWidgets.QLabel("● Idle")
        self.step_chip.setObjectName("chip")
        chat_header.addWidget(self.step_chip)

        self.chat = QtWidgets.QTextBrowser()
        self.chat.setOpenExternalLinks(False)
        chat_layout.addWidget(self.chat, 1)

        # Active Thinking & Execution Banner (Above Composer)
        self.thinking_banner = QtWidgets.QFrame()
        self.thinking_banner.setObjectName("thinkingCard")
        tb_layout = QtWidgets.QVBoxLayout(self.thinking_banner)
        tb_layout.setContentsMargins(10, 8, 10, 8)
        tb_layout.setSpacing(4)

        tb_top = QtWidgets.QHBoxLayout()
        self.tb_icon = QtWidgets.QLabel("🧠")
        self.tb_icon.setStyleSheet("font-size: 15px;")
        tb_top.addWidget(self.tb_icon)

        self.tb_status = CompactLabel("Analyzing task & project files...")
        self.tb_status.setStyleSheet("color: #f1f5f9; font-weight: 600; font-size: 12.5px;")
        self.tb_status.setMinimumWidth(20)
        tb_top.addWidget(self.tb_status, 1)

        self.tb_timer = QtWidgets.QLabel("00:00s")
        self.tb_timer.setStyleSheet("background: #1e1b4b; color: #a78bfa; border: 1px solid #4338ca; border-radius: 6px; padding: 2px 8px; font-weight: 700; font-size: 11px;")
        tb_top.addWidget(self.tb_timer)
        tb_layout.addLayout(tb_top)

        self.tb_topic = CompactLabel("")
        self.tb_topic.setObjectName("topicLabel")
        self.tb_topic.setMinimumWidth(20)
        tb_layout.addWidget(self.tb_topic)

        self.tb_progress = QtWidgets.QProgressBar()
        self.tb_progress.setFixedHeight(4)
        self.tb_progress.setTextVisible(False)
        self.tb_progress.setRange(0, 0)  # Shimmer / pulsating mode
        tb_layout.addWidget(self.tb_progress)

        self.thinking_banner.setVisible(False)
        chat_layout.addWidget(self.thinking_banner)

        # Composer & Quick Prompts
        quick_row = QtWidgets.QHBoxLayout()
        quick_row.setSpacing(6)
        quick_lbl = QtWidgets.QLabel("Quick:")
        quick_lbl.setStyleSheet("color: #64748b; font-size: 11.5px; font-weight: 600;")
        quick_row.addWidget(quick_lbl)
        
        for label, prompt, tip in [
            ("⚡ Plan", "Analyze the repository and create an architectural plan in docs/PHASE_1.md for the next phase.", "Plan Architecture — Analyze repository and create architectural plan"),
            ("🚀 Run App", "quick_run_app", "Run App — Automatically detect and launch the application dev server"),
            ("🌐 Preview", "quick_open_preview", "Live Preview — Open landing page or localhost web server in browser"),
            ("🧪 Tests", "Inspect tests and run the test suite to verify code integrity and reporting status.", "Run Tests — Inspect and run test suite"),
            ("🔍 Scan", "List key directories and read core entrypoints to understand project architecture.", "Scan Structure — List key directories and inspect core entrypoints"),
            ("📝 Patch", "Implement the next requested feature cleanly with minimal, high-cohesion changes.", "Implement & Patch — Implement next feature cleanly with minimal changes")
        ]:
            pill = QtWidgets.QPushButton(label)
            pill.setObjectName("quickPill")
            pill.setToolTip(tip)
            pill.setMinimumWidth(20)
            if prompt == "quick_run_app":
                pill.clicked.connect(self.quick_run_app)
            elif prompt == "quick_open_preview":
                pill.clicked.connect(self.quick_open_preview)
            else:
                pill.clicked.connect(lambda _, p=prompt: self.insert_prompt(p))
            quick_row.addWidget(pill)
        quick_row.addStretch(1)
        chat_layout.addLayout(quick_row)

        # Attachment Bar
        self.attachment_bar = QtWidgets.QFrame()
        self.attachment_bar.setObjectName("attachmentBar")
        self.attachment_layout = QtWidgets.QHBoxLayout(self.attachment_bar)
        self.attachment_layout.setContentsMargins(6, 4, 6, 4)
        self.attachment_layout.setSpacing(6)
        self.attachment_bar.setVisible(False)
        chat_layout.addWidget(self.attachment_bar)

        self.composer = AgentComposer()
        self.composer.setObjectName("composer")
        self.composer.setPlaceholderText("Describe your development objective… (Enter to run, Shift+Enter for newline, paste/drop images)")
        self.composer.setFixedHeight(86)
        self.composer.submit_requested.connect(self.send)
        self.composer.image_attached.connect(self.add_attachment)
        chat_layout.addWidget(self.composer)

        actions = QtWidgets.QHBoxLayout()
        self.attach_btn = QtWidgets.QPushButton("📷 Attach")
        self.attach_btn.setObjectName("attachBtn")
        self.attach_btn.setToolTip("Attach screenshot or image file (or paste Ctrl+V / drag-and-drop)")
        self.attach_btn.clicked.connect(self.choose_attachment)
        actions.addWidget(self.attach_btn)

        self.hint = CompactLabel("Enter to send · Shift+Enter newline · Paste/drop images")
        self.hint.setObjectName("muted")
        self.hint.setStyleSheet("font-size: 11.5px;")
        self.hint.setMinimumWidth(20)
        actions.addWidget(self.hint)
        actions.addStretch(1)

        self.stop_btn = QtWidgets.QPushButton("✕ Stop")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(self.stop)
        actions.addWidget(self.stop_btn)

        self.send_btn = QtWidgets.QPushButton("⚡ Run agent")
        self.send_btn.setObjectName("primary")
        self.send_btn.setMinimumWidth(30)
        self.send_btn.clicked.connect(self.send)
        actions.addWidget(self.send_btn)

        chat_layout.addLayout(actions)
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Return"), self.composer, activated=self.send)
        QtWidgets.QShortcut(QtGui.QKeySequence.Paste, self, activated=self._handle_paste)
        split.addWidget(chat_card)

        # Right Column: Plan & Steps, Changes, Terminal
        right = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        right.setHandleWidth(8)
        right.setMinimumWidth(220)
        right.setChildrenCollapsible(False)

        # 1. Plan & Steps Card
        plan_card, plan_layout, plan_header = card("Roadmap & Planned Steps")
        plan_card.setMinimumWidth(80)
        self.plan_progress = QtWidgets.QProgressBar()
        self.plan_progress.setFixedHeight(14)
        self.plan_progress.setFixedWidth(50)
        self.plan_progress.setValue(0)
        plan_header.addWidget(self.plan_progress)

        self.plan = QtWidgets.QListWidget()
        self.plan.setFocusPolicy(QtCore.Qt.NoFocus)
        plan_layout.addWidget(self.plan)
        right.addWidget(plan_card)

        # 2. Changes / Diffs Card
        self.diff_card, diff_layout, diff_header = card("Code Changes & Unified Diff")
        self.diff_card.setMinimumWidth(80)
        self.diff_title = CompactLabel("No pending changes")
        self.diff_title.setObjectName("muted")
        self.diff_title.setMinimumWidth(20)
        diff_header.addWidget(self.diff_title)

        self.diff = QtWidgets.QTextBrowser()
        diff_layout.addWidget(self.diff, 1)

        self.diff_btn_box = QtWidgets.QWidget()
        diff_buttons = QtWidgets.QHBoxLayout(self.diff_btn_box)
        diff_buttons.setContentsMargins(0, 4, 0, 0)
        diff_buttons.addStretch(1)
        self.reject_btn = QtWidgets.QPushButton("✕ Reject")
        self.reject_btn.setObjectName("reject")
        self.reject_btn.setMinimumWidth(30)
        self.accept_btn = QtWidgets.QPushButton("✓ Accept")
        self.accept_btn.setObjectName("accept")
        self.accept_btn.setMinimumWidth(30)
        self.reject_btn.clicked.connect(lambda: self.respond(False))
        self.accept_btn.clicked.connect(lambda: self.respond(True))
        diff_buttons.addWidget(self.reject_btn)
        diff_buttons.addWidget(self.accept_btn)
        diff_layout.addWidget(self.diff_btn_box)
        self.diff_btn_box.setVisible(False)
        right.addWidget(self.diff_card)

        # 3. Terminal Card
        self.term_card, term_layout, term_header = card("Terminal Execution")
        self.term_card.setMinimumWidth(80)
        self.command_label = CompactLabel("")
        self.command_label.setStyleSheet("color: #fde68a; font-family: 'JetBrains Mono', monospace; font-size: 11.5px;")
        self.command_label.setMinimumWidth(20)
        term_header.addWidget(self.command_label)

        self.terminal = QtWidgets.QPlainTextEdit()
        self.terminal.setObjectName("terminal")
        self.terminal.setReadOnly(True)
        term_layout.addWidget(self.terminal, 1)

        self.term_btn_box = QtWidgets.QWidget()
        term_buttons = QtWidgets.QHBoxLayout(self.term_btn_box)
        term_buttons.setContentsMargins(0, 4, 0, 0)
        term_note = CompactLabel("Executed inside project root")
        term_note.setObjectName("muted")
        term_note.setStyleSheet("font-size: 11.5px;")
        term_note.setMinimumWidth(20)
        term_buttons.addWidget(term_note)
        term_buttons.addStretch(1)

        self.deny_btn = QtWidgets.QPushButton("✕ Deny")
        self.deny_btn.setObjectName("reject")
        self.deny_btn.setMinimumWidth(30)
        self.run_btn = QtWidgets.QPushButton("⚡ Run")
        self.run_btn.setObjectName("accept")
        self.run_btn.setMinimumWidth(30)
        self.deny_btn.clicked.connect(lambda: self.respond(False))
        self.run_btn.clicked.connect(lambda: self.respond(True))
        term_buttons.addWidget(self.deny_btn)
        term_buttons.addWidget(self.run_btn)
        term_layout.addWidget(self.term_btn_box)
        self.term_btn_box.setVisible(False)
        right.addWidget(self.term_card)

        plan_h = max(110, int(self.height() * 0.22))
        diff_h = max(150, int(self.height() * 0.42))
        term_h = max(110, int(self.height() * 0.26))
        right.setSizes([plan_h, diff_h, term_h])
        split.addWidget(right)
        
        left_w = max(300, int(self.width() * 0.52))
        right_w = max(240, int(self.width() * 0.48))
        split.setSizes([left_w, right_w])

        self._set_pending(None)
        return panel

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
        self.path_label.setText(f"📁 {short_name}" if self.folder else "No folder open — choose one to start")
        self.path_label.setToolTip(self.folder or "")
        self.transcript = []
        if self.folder:
            intro = (f"Ready to work in **{short_name}**. Tell me what to build or fix;\n"
                     "I will plan it, read the codebase, write changes, and execute verification tests.")
            self.transcript.append(["agent", intro])
        else:
            self.transcript.append(["agent", "Open a project folder to start. I work autonomously inside your chosen workspace."])
        self._dirty = True
        self._update_status()


    def new_task(self):
        if self.worker:
            self.stop()
        self.transcript = []
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

        lbl = QtWidgets.QLabel(f"📷 Attached ({len(self.attached_images)}):")
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
        self.tb_timer.setText(f"{mins:02d}:{secs:02d}s")
        # Every 20 seconds of active work, reset system idle timer so screen does not sleep while user watches
        if elapsed > 0 and elapsed % 20 == 0:
            try:
                subprocess.run(["qdbus", "org.freedesktop.ScreenSaver", "/ScreenSaver", "SimulateUserActivity"],
                               check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            except Exception:
                pass

    # ---------------------------------------------------------------- chat rendering
    def _render_if_dirty(self):
        if not self._dirty:
            return
        self._dirty = False
        parts = []
        is_working = bool(self.worker)
        
        for i, (role, text) in enumerate(self.transcript):
            if role == "user":
                parts.append(f'''
                <table width="100%" cellspacing="0" cellpadding="0" style="margin: 10px 0;">
                  <tr>
                    <td width="15%"></td>
                    <td style="background-color: #122244; border: 1px solid #1e386a; border-radius: 12px; padding: 12px 16px; color: #f8fafc;">
                      <div style="color: #38bdf8; font-weight: 700; font-size: 12px; letter-spacing: 0.5px; margin-bottom: 4px;">
                        👤 YOU
                      </div>
                      <div style="font-size: 13.5px; line-height: 1.5;">{_prose(text)}</div>
                    </td>
                  </tr>
                </table>
                ''')
            elif role == "error":
                parts.append(f'''
                <div style="background-color: #450a0a; border: 1px solid #991b1b; border-radius: 8px; padding: 10px 14px; margin: 8px 0; color: #fecaca;">
                  <b style="color: #ef4444;">✕ Error:</b> {html.escape(text)}
                </div>
                ''')
            elif role == "note":
                parts.append(f'''
                <div style="background-color: #0c182c; border: 1px solid #1a2942; border-radius: 8px; padding: 8px 12px; margin: 6px 0; color: #94a3b8; font-size: 12px;">
                  ℹ️ {html.escape(text)}
                </div>
                ''')
            else:
                is_last_agent = (i == len(self.transcript) - 1)
                
                # If text is empty and agent is actively working, show rich thinking card
                if not text.strip() and is_working and is_last_agent:
                    body_html = f'''
                    <div style="background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0d1a33, stop:1 #111e3b); border: 1px solid #2563eb; border-radius: 10px; padding: 12px 16px; margin: 4px 0;">
                      <table width="100%">
                        <tr>
                          <td width="28"><span style="font-size: 18px;">🧠</span></td>
                          <td>
                            <div style="color: #38bdf8; font-weight: 700; font-size: 13px;">NEURAL REASONING & TASK PLANNING</div>
                            <div style="color: #cbd5e1; font-size: 12.5px; margin-top: 3px;">{html.escape(self.active_status_text)}</div>
                          </td>
                          <td align="right" width="80">
                            <span style="background: #1e1b4b; color: #c4b5fd; border: 1px solid #4338ca; border-radius: 6px; padding: 3px 8px; font-size: 11px; font-weight: 700;">THINKING</span>
                          </td>
                        </tr>
                      </table>
                    </div>
                    '''
                else:
                    body_html = message_html(text, is_generating=(is_working and is_last_agent))
                    if not body_html:
                        body_html = "<p style='color: #64748b; font-style: italic;'>Generating thoughts…</p>"

                parts.append(f'''
                <table width="100%" cellspacing="0" cellpadding="0" style="margin: 10px 0;">
                  <tr>
                    <td style="background-color: #0c1424; border: 1px solid #192742; border-radius: 12px; padding: 12px 16px; color: #f1f5f9;">
                      <div style="color: #38bdf8; font-weight: 700; font-size: 12.5px; letter-spacing: 0.5px; margin-bottom: 6px;">
                        ⚡ DevOS AI Code Agent
                      </div>
                      <div>{body_html}</div>
                    </td>
                    <td width="6%"></td>
                  </tr>
                </table>
                ''')

        bar = self.chat.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 40
        self.chat.setHtml("".join(parts))
        if at_bottom:
            bar.setValue(bar.maximum())

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
                    self.ai_badge.setText("⚠  Offline · Click to Setup ▾")
                    self.ai_badge.setProperty("state", "offline")
                    self.ai_badge.setToolTip("DevOS AI Core is offline.\nClick to start local engine or switch to Gemini/Groq.")
            else:
                has_key = bool(engine.get("api_key"))
                status_icon = "⚡" if has_key else "⚠"
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
    def send(self):
        raw_task = self.composer.toPlainText().strip()
        if (not raw_task and not self.attached_images) or self.worker or not self.capable:
            return
        if not self.folder:
            self.choose_folder()
            if not self.folder:
                return

        attached = list(self.attached_images)
        self.attached_images.clear()
        self._update_attachment_bar()
        self.composer.clear()

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
        self.plan.clear()
        self.plan_progress.setValue(0)
        self._dirty = True

        self.start_time = time.time()
        self._elapsed_timer.start()

        # Update thinking banner
        self.current_topic = core.extract_task_topic(agent_task)
        self.active_status_text = "Analyzing project context & task requirements..."
        self.tb_status.setText(self.active_status_text)
        self.tb_topic.setText(f"🎯 Target: {self.current_topic}")
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
        self.step_chip.setText("🧠 Thinking…")
        self.step_chip.setStyleSheet("background: #1e1b4b; color: #c4b5fd; border: 1px solid #4338ca;")
        self._inhibit_sleep()
        self.worker.start()

    def stop(self):
        self._uninhibit_sleep()
        if self.worker:
            self.worker.cancel()
            self.step_chip.setText("Stopping…")
            self.tb_status.setText("Aborting active operation...")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setVisible(False)
        self.send_btn.setEnabled(True)
        self._set_pending(None)


    # ---------------------------------------------------------------- event loop
    def on_event(self, kind, payload):
        if kind == "task_init":
            self.current_topic = payload.get("topic", "")
            self.tb_topic.setText(f"🎯 Target: {self.current_topic}")
            initial_plan = payload.get("plan", [])
            if initial_plan:
                for step in initial_plan:
                    self._add_step(step, "plan")
        elif kind == "thinking_status":
            self.active_status_text = payload.get("status", "")
            self.tb_status.setText(self.active_status_text)
            step_num = payload.get("step", 1)
            self.step_chip.setText(f"🧠 Step {step_num} · Thinking")
            self._dirty = True
        elif kind == "thinking":
            self.step_chip.setText(f"🧠 Step {payload} · Working")
            self.step_chip.setStyleSheet("background: #1e1b4b; color: #a78bfa; border: 1px solid #6366f1;")
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
        elif kind == "step":
            self._add_step(payload["title"], "running")
            self.step_chip.setText(f"⚡ {payload['title'][:32]}")
            self._update_plan_progress()
        elif kind == "step_status":
            self._mark_last_step(payload)
            self._update_plan_progress()
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
                self.transcript[-1][1] = payload or "Task completed successfully."
            self.transcript.append(["note", "Mission accomplished. Notes recorded to .devos/agent-notes.md."])
            self.thinking_banner.setVisible(False)
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
        self.step_chip.setText("⏳ Waiting for you")
        self.step_chip.setStyleSheet("background: #451a03; color: #fde047; border: 1px solid #d97706;")
        QtWidgets.QApplication.alert(self)

    def respond(self, ok: bool):
        if self.worker and self.pending is not None:
            self.worker.answer(ok)
        if self.pending is not None and self.pending.kind == "command" and not ok:
            self.terminal.appendPlainText("(denied)\n")
        self.pending = None
        self._set_pending(None)
        if self.worker:
            self.step_chip.setText("⚡ Working…")
            self.step_chip.setStyleSheet("background: #022c22; color: #5eead4; border: 1px solid #0f766e;")

    def on_failed(self, message):
        self.transcript.append(["error", message])
        self.thinking_banner.setVisible(False)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setVisible(False)
        self.send_btn.setEnabled(True)
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
        self.step_chip.setText("● Idle")
        self.step_chip.setStyleSheet("background: #1e1b4b; color: #c4b5fd; border: 1px solid #4338ca;")
        self._update_plan_progress()


    # ---------------------------------------------------------------- helpers
    def _show_change(self, action):
        self.diff_title.setText(f"📄 {action.title}")
        self.diff.setHtml(diff_html(action.diff))

    def _set_pending(self, action):
        edit = bool(action and action.kind == "edit")
        command = bool(action and action.kind == "command")
        self.diff_btn_box.setVisible(edit)
        self.accept_btn.setEnabled(edit)
        self.reject_btn.setEnabled(edit)
        self.term_btn_box.setVisible(command)
        self.run_btn.setEnabled(command)
        self.deny_btn.setEnabled(command)
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
            return
        done_count = sum(1 for row in range(total) if STEP_ICON["done"] in self.plan.item(row).text())
        pct = int((done_count / total) * 100)
        self.plan_progress.setValue(pct)
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
            f"⚡ Local Neural Engine · {'Auto-reads: ON' if self.policy.auto_reads else 'Auto-reads: OFF'} · "
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
