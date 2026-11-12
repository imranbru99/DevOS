#!/usr/bin/env python3
"""DevOS AI Multi-Agent Task Pipeline & Rate-Limit Scheduler - Visual GUI.

Visual dashboard for managing, queuing, and monitoring sequential AI tasks
across ChatGPT/Codex, Google Antigravity, and DevOS Local AI.
Features:
- Step 1: Agent selector
- Step 2: Current working project command queuing (optional)
- Step 3: Add another / next project with title-to-slug auto-conversion
- Step 4: Sequential multi-project execution with local folder auto-creation
"""

import datetime
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, QTimer, QCoreApplication
from PyQt5.QtGui import QIcon, QFont, QColor
from PyQt5.QtWidgets import QLineEdit, QTextEdit, QComboBox, QProgressBar

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components" / "ai-agent"))
from task_pipeline import (
    TaskPipeline,
    parse_reset_time,
    discover_agents,
    is_agent_working,
    to_slug,
    split_prompts,
    notify,
    clear_pipeline_notifications,
    copy_to_clipboard,
    get_grouped_projects,
    detect_current_project,
    list_existing_projects,
)
try:
    import pipeline_premium as premium
except Exception:  # pragma: no cover
    premium = None


def get_app_icon():
    """Resolve the highest-fidelity DevOS AI Pipeline application icon."""
    icon = QIcon.fromTheme("devos-ai-pipeline")
    if not icon.isNull():
        return icon

    search_paths = [
        Path.home() / ".local/share/icons/hicolor/scalable/apps/devos-ai-pipeline.svg",
        Path.home() / ".local/share/icons/hicolor/256x256/apps/devos-ai-pipeline.png",
        ROOT / "build/includes.chroot/usr/share/icons/hicolor/scalable/apps/devos-ai-pipeline.svg",
        ROOT / "build/includes.chroot/usr/share/icons/hicolor/256x256/apps/devos-ai-pipeline.png",
        ROOT / "build/includes.chroot/usr/share/icons/hicolor/512x512/apps/devos-ai-pipeline.png",
        Path("/usr/share/icons/hicolor/scalable/apps/devos-ai-pipeline.svg"),
        Path("/usr/share/icons/hicolor/256x256/apps/devos-ai-pipeline.png"),
    ]
    for p in search_paths:
        if p.exists():
            return QIcon(str(p))
    return icon


STYLE = """
QMainWindow, QWidget {
    background-color: #060a17;
    color: #e2e8f0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px;
}
QWidget#centralWidget {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #050814,
        stop:0.35 #070e24,
        stop:0.7 #0a1533,
        stop:1 #060b18);
}
QFrame#card {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(15, 23, 42, 0.95), stop:1 rgba(10, 16, 32, 0.95));
    border: 1px solid rgba(56, 189, 248, 0.22);
    border-radius: 12px;
}
QFrame#banner_strip {
    background-color: #0b152d;
    border: 1px solid #1e355b;
    border-radius: 8px;
}
QFrame#stats_bar {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0a1634, stop:1 #0d1e42);
    border: 1px solid #1e3a6f;
    border-radius: 10px;
}
QFrame#kpi_card {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0e1d3d, stop:1 #0a152d);
    border: 1px solid #1e3a68;
    border-radius: 8px;
}
QLabel#kpi_num {
    font-size: 15px;
    font-weight: 800;
    color: #38bdf8;
    letter-spacing: -0.2px;
}
QLabel#kpi_label {
    font-size: 10px;
    font-weight: 700;
    color: #94a3b8;
    letter-spacing: 0.6px;
}
QFrame#section_current {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #081a33, stop:1 #061124);
    border: 1px solid #0e7490;
    border-radius: 10px;
}
QFrame#section_next {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0c1433, stop:1 #080d22);
    border: 1px solid #4338ca;
    border-radius: 10px;
}
QFrame#project_card {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #101c38, stop:1 #0b1326);
    border: 1px solid #223759;
    border-radius: 10px;
}
QFrame#project_card:hover {
    border-color: #38bdf8;
}
QFrame#step_row {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #070e1c, stop:1 #0a1428);
    border: 1px solid #1c2e4a;
    border-radius: 7px;
}
QFrame#step_row:hover {
    border-color: #38bdf8;
}
QFrame#banner_rate_limit {
    background-color: #2a1b06;
    border: 1px solid #d97706;
    border-radius: 8px;
}
QLabel#title {
    font-size: 21px;
    font-weight: 800;
    color: #f8fafc;
    letter-spacing: -0.3px;
}
QProgressBar {
    background-color: #0b1220;
    border: 1px solid #1e293b;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #10b981);
    border-radius: 3px;
}
QScrollBar:vertical {
    background: #080d1a;
    width: 8px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #253347;
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #3b82f6;
}
QLabel#subtitle {
    color: #94a3b8;
    font-size: 13px;
}
QLabel#tag_label {
    background-color: #1e293b;
    color: #38bdf8;
    font-size: 11px;
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 4px;
    border: 1px solid #334155;
}
QLabel#badge_cyan {
    background-color: #032b43;
    color: #38bdf8;
    font-size: 11px;
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 4px;
    border: 1px solid #0284c7;
}
QLabel#badge_indigo {
    background-color: #1e1b4b;
    color: #a5b4fc;
    font-size: 11px;
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 4px;
    border: 1px solid #4338ca;
}
QLabel#field_label {
    font-weight: 600;
    color: #94a3b8;
    font-size: 12px;
}
QLabel#badge_agent {
    font-weight: 700;
    font-size: 11px;
    padding: 3px 8px;
    border-radius: 4px;
}
QLabel#badge_slug {
    background-color: #032b43;
    color: #38bdf8;
    font-family: monospace;
    font-size: 11px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 4px;
    border: 1px solid #0284c7;
}
QLabel#badge_step {
    background-color: #1e293b;
    color: #94a3b8;
    font-size: 11px;
    font-weight: 700;
    padding: 3px 7px;
    border-radius: 4px;
    border: 1px solid #334155;
}
QLabel#path_info {
    color: #64748b;
    font-size: 11px;
    font-family: monospace;
}
QPushButton {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 7px 15px;
    font-weight: 600;
    color: #f8fafc;
}
QPushButton:hover {
    background-color: #29384d;
    border-color: #475569;
}
QPushButton#primary {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #0369a1);
    border: 1px solid #38bdf8;
    color: #ffffff;
    font-weight: 700;
}
QPushButton#primary:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0369a1, stop:1 #075985);
}
QPushButton#accent_action {
    background-color: #082f49;
    border: 1px solid #0ea5e9;
    color: #38bdf8;
    font-weight: 600;
}
QPushButton#accent_action:hover {
    background-color: #0c4a6e;
    color: #ffffff;
}
QPushButton#accent_warning {
    background-color: #d97706;
    border: 1px solid #fbbf24;
    color: #ffffff;
}
QPushButton#accent_warning:hover {
    background-color: #b45309;
}
QPushButton#danger {
    background-color: #991b1b;
    border: 1px solid #f87171;
    color: #ffffff;
}
QPushButton#small_btn {
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
    border-radius: 5px;
}
QPushButton#danger_small {
    background-color: #3f1010;
    border: 1px solid #7f1d1d;
    color: #fca5a5;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 700;
    border-radius: 4px;
}
QPushButton#danger_small:hover {
    background-color: #7f1d1d;
    color: #ffffff;
    border-color: #ef4444;
}
QComboBox, QLineEdit, QTextEdit {
    background-color: #060a14;
    border: 1px solid #222f44;
    border-radius: 6px;
    padding: 7px 10px;
    color: #f8fafc;
}
QComboBox:focus, QLineEdit:focus, QTextEdit:focus {
    border: 1px solid #0284c7;
    background-color: #080e1c;
}
QProgressBar {
    background-color: #162032;
    border: none;
    border-radius: 3px;
    height: 5px;
    text-align: center;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #38bdf8);
    border-radius: 3px;
}
QScrollArea {
    border: none;
    background-color: transparent;
}
QScrollBar:vertical {
    border: none;
    background: #080d1a;
    width: 8px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #1e293b;
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #334155;
}
QCheckBox {
    color: #38bdf8;
    font-weight: 500;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border-radius: 3px;
    border: 1px solid #334155;
    background-color: #060a14;
}
QCheckBox::indicator:checked {
    background-color: #0284c7;
    border-color: #38bdf8;
}
"""


def queue_error_to_log(method):
    @functools.wraps(method)
    def wrapped(self, *args, **kwargs):
        try:
            try:
                return method(self, *args, **kwargs)
            except TypeError:
                # Slot called from Qt signal passing unwanted arguments (e.g. checked: bool)
                return method(self)
        except (OSError, RuntimeError, ValueError) as exc:
            self.log_box.append("Queue unchanged: " + str(exc))
    return wrapped


class PipelineWorker(QtCore.QThread):
    result = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(str)

    def __init__(self, pipeline, parent, observe_only=False):
        super().__init__(parent)
        self.pipeline = pipeline
        self.observe_only = observe_only

    def run(self):
        try:
            if self.observe_only:
                self.pipeline.observe_tasks()
            else:
                self.pipeline.execute_parallel_tick(limit=4)
            self.result.emit("")
        except Exception as exc:
            self.pipeline.emit_event("Pipeline error: " + str(exc))
            self.result.emit(str(exc))


class FullPromptViewerDialog(QtWidgets.QDialog):
    """Full Prompt Inspector & Editor dialog with live editing, saving, and copy."""
    def __init__(self, step_idx: int, task: dict, on_save=None, parent=None):
        super().__init__(parent)
        self.step_idx = step_idx
        self.task = task
        self.on_save = on_save
        self.setWindowTitle(f"Step {step_idx} Prompt Inspector & Editor — {task.get('project_title', 'Project')}")
        self.resize(800, 560)
        self.setStyleSheet(STYLE)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        hdr = QtWidgets.QHBoxLayout()
        badge = QtWidgets.QLabel(f"Step {step_idx} • {task.get('agent', '').upper()}")
        badge.setObjectName("badge_cyan")
        hdr.addWidget(badge)

        prompt = task.get("prompt", "")
        self.meta_lbl = QtWidgets.QLabel(f"{len(prompt.split()):,} words • {len(prompt):,} characters")
        self.meta_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
        hdr.addWidget(self.meta_lbl)
        hdr.addStretch()

        btn_copy = QtWidgets.QPushButton("📋 Copy Prompt")
        btn_copy.setObjectName("small_btn")
        btn_copy.setStyleSheet("background-color: #0f172a; color: #38bdf8; font-size: 11px; padding: 4px 10px; border: 1px solid #1e293b; border-radius: 4px;")
        btn_copy.clicked.connect(lambda: copy_to_clipboard(self.editor.toPlainText()))
        hdr.addWidget(btn_copy)
        layout.addLayout(hdr)

        self.editor = QtWidgets.QTextEdit()
        self.editor.setPlainText(prompt)
        self.editor.setFont(QtGui.QFont("Monospace", 10))
        self.editor.textChanged.connect(self._update_metrics)
        layout.addWidget(self.editor, stretch=1)

        bottom_bar = QtWidgets.QHBoxLayout()
        tip_lbl = QtWidgets.QLabel("💡 You can edit this prompt directly and click 'Save & Update Step' below.")
        tip_lbl.setStyleSheet("color: #64748b; font-size: 11px;")
        bottom_bar.addWidget(tip_lbl)
        bottom_bar.addStretch()

        btn_close = QtWidgets.QPushButton("Cancel")
        btn_close.clicked.connect(self.reject)
        bottom_bar.addWidget(btn_close)

        btn_save = QtWidgets.QPushButton("💾 Save & Update Step")
        btn_save.setObjectName("primary")
        btn_save.setStyleSheet("background-color: #2563eb; color: white; font-weight: 700; padding: 6px 16px; border-radius: 5px;")
        btn_save.clicked.connect(self._save_prompt)
        bottom_bar.addWidget(btn_save)

        layout.addLayout(bottom_bar)

    def _update_metrics(self):
        txt = self.editor.toPlainText()
        self.meta_lbl.setText(f"{len(txt.split()):,} words • {len(txt):,} characters")

    def _save_prompt(self):
        new_prompt = self.editor.toPlainText().strip()
        if not new_prompt:
            QtWidgets.QMessageBox.warning(self, "Empty Prompt", "Prompt cannot be empty.")
            return
        if self.on_save:
            self.on_save(self.task["id"], new_prompt)
        self.accept()


class StepRow(QtWidgets.QFrame):
    def __init__(self, step_idx: int, task: dict, on_failover=None, on_confirm=None, on_delete=None, on_update=None, parent=None, on_move=None, can_up=False, can_down=False):
        super().__init__(parent)
        self.on_move = on_move
        self.can_up = can_up
        self.can_down = can_down
        self.step_idx = step_idx
        self.task = task
        self.on_failover = on_failover
        self.on_confirm = on_confirm
        self.on_delete = on_delete
        self.on_update = on_update
        self.setObjectName("step_row")
        self.init_ui()

    def view_full_prompt(self, *args, **kwargs):
        dlg = FullPromptViewerDialog(self.step_idx, self.task, on_save=self.on_update, parent=self)
        dlg.exec_()

    def init_ui(self):
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(10)

        # Step badge (Step 1, Step 2, etc.)
        step_lbl = QtWidgets.QLabel(f"Step {self.step_idx}")
        step_lbl.setObjectName("badge_step")
        layout.addWidget(step_lbl)

        # Agent icon / badge
        agent = self.task.get("agent", "antigravity").lower()
        known = discover_agents()
        agent_info = known.get(agent, {
            "name": agent.title(),
            "color": "#475569"
        })
        badge = QtWidgets.QLabel(agent_info["name"])
        badge.setObjectName("badge_agent")
        badge.setStyleSheet(f"background-color: {agent_info['color']}; color: white;")
        layout.addWidget(badge)

        # Center info: prompt & status
        center_box = QtWidgets.QVBoxLayout()
        center_box.setSpacing(3)

        prompt_text = self.task.get("prompt", "").strip()
        words = len(prompt_text.split())

        preview = ' '.join(prompt_text.split()[:5]) + (' …' if words > 5 else '')
        prompt_lbl = QtWidgets.QLabel(preview)
        prompt_lbl.setObjectName('prompt_preview')
        prompt_lbl.setTextFormat(Qt.PlainText)
        prompt_lbl.setWordWrap(True)
        center_box.addWidget(prompt_lbl)
        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(QtWidgets.QLabel(f"{words:,} words"))
        edit = QtWidgets.QPushButton("View / Edit")
        edit.setObjectName('small_btn')
        edit.clicked.connect(self.view_full_prompt)
        controls.addWidget(edit)
        for label, direction, enabled in (("↑", -1, self.can_up), ("↓", 1, self.can_down)):
            button = QtWidgets.QPushButton(label)
            button.setObjectName('small_btn')
            button.setToolTip('Move prompt up' if direction == -1 else 'Move prompt down')
            button.setEnabled(bool(self.on_move) and enabled)
            button.clicked.connect(lambda _, d=direction: self.on_move(self.task['id'], d))
            controls.addWidget(button)
        controls.addStretch()
        center_box.addLayout(controls)

        status = self.task.get("status", "QUEUED")
        status_text = f"○ Queued"
        status_color = "#94a3b8"

        if status == "RUNNING":
            status_text = self.task.get("status_message") or "⚡ Running: Execution in progress..."
            status_color = "#38bdf8"
        elif status == "RATE_LIMITED":
            retry_at = self.task.get("retry_at", "")
            if retry_at:
                try:
                    dt = datetime.datetime.fromisoformat(retry_at)
                    status_text = f"⏳ Rate-Limited: Cooldown active until {dt.strftime('%I:%M %p')}"
                except Exception:
                    status_text = "⏳ Rate-Limited"
            else:
                status_text = "⏳ Rate-Limited"
            status_color = "#fbbf24"
        elif status == "SUBMITTED":
            status_text = "📩 Submitted • verify completion in agent"
            status_color = "#fbbf24"
        elif status == "COMPLETED":
            status_text = "✔ Completed"
            status_color = "#34d399"
        elif status == "FAILED":
            status_text = "✖ Failed: " + (self.task.get("status_message") or self.task.get("output") or "See activity log")[:300]
            status_color = "#f87171"

        status_lbl = QtWidgets.QLabel(status_text)
        status_lbl.setWordWrap(True)
        status_lbl.setTextFormat(Qt.PlainText)
        status_lbl.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {status_color};")
        center_box.addWidget(status_lbl)

        layout.addLayout(center_box, stretch=1)

        # GitHub Repo Link button if repo was created
        github_url = self.task.get("github_url")
        if github_url:
            btn_repo = QtWidgets.QPushButton("Open GitHub")
            btn_repo.setObjectName("small_btn")
            btn_repo.setToolTip(github_url)
            btn_repo.setStyleSheet("background-color: #238636; color: white; font-weight: 600; padding: 4px 10px; border-radius: 5px;")
            btn_repo.clicked.connect(lambda: subprocess.Popen(["xdg-open", github_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            layout.addWidget(btn_repo)

        if status == "SUBMITTED" and self.on_confirm:
            btn_confirm = QtWidgets.QPushButton("Confirm Completed")
            btn_confirm.setObjectName("small_btn")
            btn_confirm.clicked.connect(lambda: self.on_confirm(self.task["id"]))
            layout.addWidget(btn_confirm)

        if status == "FAILED":
            retry = QtWidgets.QPushButton("Retry step")
            retry.clicked.connect(lambda: self.window().retry_task(self.task["id"]))
            layout.addWidget(retry)

        # Failover action button if rate limited
        if status == "RATE_LIMITED" and self.on_failover:
            btn_failover = QtWidgets.QPushButton("Switch to Antigravity")
            btn_failover.setObjectName("accent_warning")
            btn_failover.setStyleSheet("padding: 4px 8px; font-size: 11px;")
            btn_failover.setToolTip("Skip cooldown and run via another agent (local if Antigravity quota is already exhausted)")
            btn_failover.clicked.connect(lambda: self.on_failover(self.task["id"]))
            layout.addWidget(btn_failover)

        # Delete step button (if QUEUED or FAILED)
        if status in ("QUEUED", "FAILED") and self.on_delete:
            btn_del = QtWidgets.QPushButton("X")
            btn_del.setObjectName("danger_small")
            btn_del.setToolTip("Remove this step from pipeline")
            btn_del.clicked.connect(lambda: self.on_delete(self.task["id"]))
            layout.addWidget(btn_del)


class ProjectPipelineCard(QtWidgets.QFrame):
    def __init__(self, project_data: dict, on_failover=None, on_confirm=None, on_delete_task=None, on_delete_project=None, on_update_task=None, parent=None, on_add_prompt=None, on_move_prompt=None):
        super().__init__(parent)
        self.on_add_prompt = on_add_prompt
        self.on_move_prompt = on_move_prompt
        self.project_data = project_data
        self.on_failover = on_failover
        self.on_confirm = on_confirm
        self.on_delete_task = on_delete_task
        self.on_delete_project = on_delete_project
        self.on_update_task = on_update_task
        self.setObjectName("project_card")
        self.init_ui()

    def init_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(6)

        # Project Status calculation
        tasks = self.project_data.get("tasks", [])
        total_tasks = len(tasks)
        completed_tasks = sum(1 for t in tasks if t["status"] == "COMPLETED")
        running_tasks = [t for t in tasks if t["status"] == "RUNNING"]
        rate_limited_tasks = [t for t in tasks if t["status"] == "RATE_LIMITED"]
        failed_tasks = [t for t in tasks if t["status"] == "FAILED"]
        submitted_tasks = [t for t in tasks if t["status"] == "SUBMITTED"]

        if running_tasks:
            curr_idx = tasks.index(running_tasks[0]) + 1
            status_text = f"RUNNING ({curr_idx}/{total_tasks})"
            status_color = "#38bdf8"
            bg_color = "#032b43"
        elif rate_limited_tasks:
            status_text = "RATE LIMITED"
            status_color = "#fbbf24"
            bg_color = "#2a1b06"
        elif failed_tasks:
            status_text = "FAILED"
            status_color = "#f87171"
            bg_color = "#450a0a"
        elif submitted_tasks:
            status_text = "SUBMITTED"
            status_color = "#fbbf24"
            bg_color = "#2a1b06"
        elif completed_tasks == total_tasks and total_tasks > 0:
            status_text = f"ALL {total_tasks} COMPLETED"
            status_color = "#34d399"
            bg_color = "#064e3b"
        else:
            status_text = f"QUEUED ({total_tasks} steps)"
            status_color = "#94a3b8"
            bg_color = "#1e293b"

        # ROW 1: Project Title on Left, Action Buttons on Right (ALWAYS PINNED AND VISIBLE)
        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(8)

        tag_badge = QtWidgets.QLabel("PROJECT")
        tag_badge.setObjectName("tag_label")
        row1.addWidget(tag_badge)

        title_lbl = QtWidgets.QLabel(self.project_data.get("title", "Project"))
        title_lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc;")
        title_lbl.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        row1.addWidget(title_lbl, stretch=1)

        # Right-aligned actions container
        actions_box = QtWidgets.QHBoxLayout()
        actions_box.setSpacing(6)

        status_pill = QtWidgets.QLabel(status_text)
        status_pill.setStyleSheet(
            f"background-color: {bg_color}; color: {status_color}; font-size: 11px; font-weight: 700; "
            f"padding: 3px 8px; border-radius: 5px; border: 1px solid {status_color}44;"
        )
        actions_box.addWidget(status_pill)

        proj_dir = self.project_data.get("dir", "")
        if proj_dir:
            btn_folder = QtWidgets.QPushButton("Folder")
            btn_folder.setObjectName("small_btn")
            btn_folder.setToolTip(f"Open {proj_dir} in file manager")
            btn_folder.clicked.connect(lambda: self.open_local_folder(proj_dir))
            actions_box.addWidget(btn_folder)

            btn_ide = QtWidgets.QPushButton("IDE")
            btn_ide.setObjectName("small_btn")
            btn_ide.setStyleSheet("background-color: #2563eb; color: white; font-weight: 600; padding: 3px 8px; border-radius: 5px;")
            btn_ide.setToolTip(f"Open {proj_dir} in Antigravity IDE")
            btn_ide.clicked.connect(lambda _, d=proj_dir: subprocess.Popen(["/opt/antigravity/antigravity", d], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            actions_box.addWidget(btn_ide)

        gh_url = self.project_data.get("github_url")
        if gh_url:
            btn_gh = QtWidgets.QPushButton("GitHub")
            btn_gh.setObjectName("small_btn")
            btn_gh.setStyleSheet("background-color: #238636; color: white; font-weight: 600; padding: 3px 8px; border-radius: 5px;")
            btn_gh.clicked.connect(lambda: subprocess.Popen(["xdg-open", gh_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            actions_box.addWidget(btn_gh)

        slug = self.project_data.get("slug", "project")
        if not running_tasks and self.on_delete_project:
            btn_del_proj = QtWidgets.QPushButton("✕ Delete")
            btn_del_proj.setStyleSheet(
                "background-color: #581c1c; color: #fca5a5; font-weight: 700; font-size: 11px; "
                "padding: 3px 8px; border-radius: 4px; border: 1px solid #b91c1c;"
            )
            btn_del_proj.setToolTip(f"Delete project '{slug}' and all its tasks from queue")
            btn_del_proj.clicked.connect(lambda _, s=slug: self.on_delete_project(s))
            actions_box.addWidget(btn_del_proj)

        self.btn_toggle = QtWidgets.QPushButton("▲")
        self.btn_toggle.setObjectName("small_btn")
        self.btn_toggle.setFixedWidth(26)
        self.btn_toggle.setToolTip("Expand or collapse project steps")
        self.btn_toggle.clicked.connect(self.toggle_steps)
        actions_box.addWidget(self.btn_toggle)

        row1.addLayout(actions_box)
        main_layout.addLayout(row1)

        # ROW 2: Slug badge and Path (separate row so it never clips buttons)
        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(8)

        slug_badge = QtWidgets.QLabel(f"slug: {slug}")
        slug_badge.setObjectName("badge_slug")
        row2.addWidget(slug_badge)

        path_lbl = QtWidgets.QLabel(f"📁 {proj_dir}")
        path_lbl.setObjectName("path_info")
        path_lbl.setToolTip(proj_dir)
        path_lbl.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        row2.addWidget(path_lbl, stretch=1)

        main_layout.addLayout(row2)

        # Progress bar (if more than 1 task)
        if total_tasks > 1:
            pbar = QtWidgets.QProgressBar()
            pbar.setMaximum(total_tasks)
            pbar.setValue(completed_tasks)
            pbar.setTextVisible(False)
            main_layout.addWidget(pbar)

        # Compact list: every prompt is visible in its execution order.
        self.step_rows = []
        self.current_step_idx = 0
        self.show_all_mode = True
        add_prompt = QtWidgets.QPushButton("+ Add Prompt to This Project")
        add_prompt.setObjectName('add_project_prompt')
        add_prompt.setEnabled(self.on_add_prompt is not None)
        add_prompt.clicked.connect(lambda _: self.on_add_prompt(self.project_data['slug']))
        main_layout.addWidget(add_prompt)

        # Step rows container
        self.steps_container = QtWidgets.QWidget()
        steps_vbox = QtWidgets.QVBoxLayout(self.steps_container)
        steps_vbox.setContentsMargins(0, 4, 0, 0)
        steps_vbox.setSpacing(6)
        for idx, task in enumerate(tasks, start=1):
            row = StepRow(
                step_idx=idx,
                task=task,
                on_failover=self.on_failover,
                on_confirm=self.on_confirm,
                on_delete=self.on_delete_task,
                on_update=self.on_update_task,
                on_move=self.on_move_prompt,
                can_up=idx > 1 and task['status'] == 'QUEUED' and tasks[idx-2]['status'] == 'QUEUED',
                can_down=idx < total_tasks and task['status'] == 'QUEUED' and tasks[idx]['status'] == 'QUEUED',
            )
            self.step_rows.append(row)
            steps_vbox.addWidget(row)

        main_layout.addWidget(self.steps_container)
        self.update_step_visibility()

    def _save_nav_state(self):
        slug = self.project_data.get("slug", "project")
        win = self.window()
        if win and hasattr(win, "card_nav_states"):
            win.card_nav_states[slug] = {
                "step_idx": self.current_step_idx,
                "show_all": self.show_all_mode
            }

    def goto_prev_step(self, *args, **kwargs):
        if not self.step_rows:
            return
        if self.current_step_idx > 0:
            self.current_step_idx -= 1
            self._save_nav_state()
            self.update_step_visibility()

    def goto_next_step(self, *args, **kwargs):
        if not self.step_rows:
            return
        if self.current_step_idx < len(self.step_rows) - 1:
            self.current_step_idx += 1
            self._save_nav_state()
            self.update_step_visibility()

    def toggle_all_steps_view(self, *args, **kwargs):
        self.show_all_mode = not self.show_all_mode
        self._save_nav_state()
        if hasattr(self, "btn_all_steps"):
            self.btn_all_steps.setText("Focused View" if self.show_all_mode else "Show All Steps")
        self.update_step_visibility()

    def update_step_visibility(self):
        total = len(self.step_rows)
        if total <= 1:
            return

        if hasattr(self, "step_nav_lbl"):
            task = self.step_rows[self.current_step_idx].task
            words = len(task.get("prompt", "").split())
            self.step_nav_lbl.setText(f"Step {self.current_step_idx + 1} of {total} ({words:,} words)")

        if hasattr(self, "btn_prev_step"):
            self.btn_prev_step.setEnabled(self.current_step_idx > 0)
        if hasattr(self, "btn_next_step"):
            self.btn_next_step.setEnabled(self.current_step_idx < total - 1)

        target_row = self.step_rows[self.current_step_idx]
        if self.show_all_mode:
            for idx, r in enumerate(self.step_rows):
                r.setVisible(True)
                if idx == self.current_step_idx:
                    r.setStyleSheet("#step_row { border: 2px solid #38bdf8; background-color: #0a1120; }")
                else:
                    r.setStyleSheet("")
        else:
            for idx, r in enumerate(self.step_rows):
                r.setVisible(idx == self.current_step_idx)
                r.setStyleSheet("")

    def toggle_steps(self, *args, **kwargs):
        visible = not self.steps_container.isVisible()
        self.steps_container.setVisible(visible)
        self.btn_toggle.setText("▲" if visible else "▼")

    def open_local_folder(self, folder_path: str):
        try:
            p = Path(folder_path).resolve()
            p.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(["xdg-open", str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


class TaskCard(QtWidgets.QFrame):
    """Backward-compatible TaskCard widget."""
    def __init__(self, task: dict, on_failover=None, parent=None, on_confirm=None):
        super().__init__(parent)
        self.task = task
        self.on_failover = on_failover
        self.on_confirm = on_confirm
        self.setObjectName("card")
        self.init_ui()

    def init_ui(self):
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        agent = self.task.get("agent", "antigravity").lower()
        known = discover_agents()
        agent_info = known.get(agent, {
            "name": agent.title(),
            "color": "#475569"
        })
        badge = QtWidgets.QLabel(agent_info["name"])
        badge.setObjectName("badge_agent")
        badge.setStyleSheet(f"background-color: {agent_info['color']}; color: white;")
        layout.addWidget(badge)

        center_box = QtWidgets.QVBoxLayout()
        center_box.setSpacing(4)

        prompt_lbl = QtWidgets.QLabel(self.task.get("prompt", ""))
        prompt_lbl.setWordWrap(True)
        prompt_lbl.setStyleSheet("font-size: 13px; font-weight: 500; color: #f8fafc;")
        center_box.addWidget(prompt_lbl)

        status = self.task.get("status", "QUEUED")
        status_text = f"Status: {status}"
        status_color = "#94a3b8"

        if status == "RUNNING":
            status_text = "RUNNING: In progress..."
            status_color = "#38bdf8"
        elif status == "RATE_LIMITED":
            retry_at = self.task.get("retry_at", "")
            if retry_at:
                try:
                    dt = datetime.datetime.fromisoformat(retry_at)
                    status_text = f"RATE LIMITED: Cooldown active until {dt.strftime('%I:%M %p')}"
                except Exception:
                    status_text = "RATE LIMITED"
            status_color = "#fbbf24"
        elif status == "SUBMITTED":
            status_text = "Submitted • verify completion in the agent"
            status_color = "#fbbf24"
        elif status == "COMPLETED":
            status_text = "COMPLETED"
            status_color = "#34d399"
        elif status == "FAILED":
            status_text = "FAILED"
            status_color = "#f87171"

        status_lbl = QtWidgets.QLabel(status_text)
        status_lbl.setWordWrap(True)
        status_lbl.setTextFormat(Qt.PlainText)
        status_lbl.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {status_color};")
        center_box.addWidget(status_lbl)

        layout.addLayout(center_box, stretch=1)

        github_url = self.task.get("github_url")
        if github_url:
            btn_repo = QtWidgets.QPushButton("Open GitHub")
            btn_repo.setToolTip(github_url)
            btn_repo.setStyleSheet("background-color: #238636; color: white; font-weight: 600; padding: 6px 12px; border-radius: 6px;")
            btn_repo.clicked.connect(lambda: subprocess.Popen(["xdg-open", github_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            layout.addWidget(btn_repo)

        if status == "SUBMITTED" and self.on_confirm:
            button = QtWidgets.QPushButton("Confirm Completed")
            button.clicked.connect(lambda: self.on_confirm(self.task["id"]))
            layout.addWidget(button)

        if status == "RATE_LIMITED" and self.on_failover:
            btn_failover = QtWidgets.QPushButton("Switch to Antigravity")
            btn_failover.setObjectName("accent_warning")
            btn_failover.setToolTip("Skip cooldown and run via another agent (local if Antigravity quota is already exhausted)")
            btn_failover.clicked.connect(lambda: self.on_failover(self.task["id"]))
            layout.addWidget(btn_failover)


DEFAULT_STEPS_25 = ""  # Personal steps are loaded only from this PC’s config.
MIN_STEP_PACK = 1
MAX_STEP_PACK = 6
MAX_STEP_GROUPS = 20

STEPS_25_TEMPLATE_FILE = Path.home() / ".config/devos/pipeline_steps_25.md"
STEP_PACK_FILE = Path.home() / ".config/devos/pipeline_step_pack.json"


def _write_private_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(content)
    path.chmod(0o600)


def _new_group_id() -> str:
    return f"g{int(time.time() * 1000) % 10_000_000_000}"


def _clean_steps(raw_steps) -> list:
    cleaned = []
    for item in raw_steps or []:
        text = str(item).strip()
        if not text:
            continue
        # One pasted block may contain multiple serial steps separated by ---
        parts = split_prompts(text)
        for part in parts:
            if part and len(cleaned) < MAX_STEP_PACK:
                cleaned.append(part)
        if len(cleaned) >= MAX_STEP_PACK:
            break
    return cleaned[:MAX_STEP_PACK]


def _normalize_group(raw, fallback_name="Default") -> dict:
    if not isinstance(raw, dict):
        return {}
    name = str(raw.get("name") or fallback_name).strip() or fallback_name
    steps = _clean_steps(raw.get("steps") or [])
    if not steps:
        return {}
    gid = str(raw.get("id") or "").strip() or _new_group_id()
    return {"id": gid, "name": name, "steps": steps}


def _load_step_pack_data() -> dict:
    """Load versioned step-group store; migrate flat v1 / markdown."""
    if STEP_PACK_FILE.exists():
        try:
            data = json.loads(STEP_PACK_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        if isinstance(data, dict):
            groups = []
            for raw in data.get("groups") or []:
                group = _normalize_group(raw)
                if group:
                    groups.append(group)
            if groups:
                default_id = str(data.get("default_group_id") or groups[0]["id"])
                if not any(g["id"] == default_id for g in groups):
                    default_id = groups[0]["id"]
                return {"version": 2, "default_group_id": default_id, "groups": groups}
            # v1 flat list
            flat = _clean_steps(data.get("steps") or [])
            if flat:
                gid = _new_group_id()
                return {
                    "version": 2,
                    "default_group_id": gid,
                    "groups": [{"id": gid, "name": "Default", "steps": flat}],
                }

    md = ""
    if STEPS_25_TEMPLATE_FILE.exists():
        try:
            md = STEPS_25_TEMPLATE_FILE.read_text(encoding="utf-8")
        except Exception:
            md = ""
    flat = split_prompts(md)[:MAX_STEP_PACK] if md.strip() else []
    if flat:
        gid = _new_group_id()
        return {
            "version": 2,
            "default_group_id": gid,
            "groups": [{"id": gid, "name": "Default", "steps": flat}],
        }
    return {"version": 2, "default_group_id": "", "groups": []}


def _sync_markdown_mirror(steps):
    cleaned = _clean_steps(steps)
    if not cleaned:
        _write_private_file(STEPS_25_TEMPLATE_FILE, "")
        return
    _write_private_file(STEPS_25_TEMPLATE_FILE, "\n---\n" + "\n---\n".join(cleaned))


def save_step_groups(groups, default_group_id=None) -> dict:
    """Persist named step groups. Each group’s steps queue serially on Auto-add."""
    normalized = []
    for raw in groups or []:
        group = _normalize_group(raw, fallback_name=f"Group {len(normalized) + 1}")
        if group:
            normalized.append(group)
        if len(normalized) >= MAX_STEP_GROUPS:
            break
    if not normalized:
        raise ValueError("Save at least one group with 1–6 steps.")
    default_id = str(default_group_id or "").strip()
    if not any(g["id"] == default_id for g in normalized):
        default_id = normalized[0]["id"]
    payload = {
        "version": 2,
        "default_group_id": default_id,
        "groups": normalized,
    }
    _write_private_file(STEP_PACK_FILE, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    default = next(g for g in normalized if g["id"] == default_id)
    _sync_markdown_mirror(default["steps"])
    return payload


def list_step_groups() -> list:
    return list(_load_step_pack_data().get("groups") or [])


def get_step_group(group_id=None) -> dict:
    """Return one group dict {id,name,steps}. Default group when group_id is None."""
    data = _load_step_pack_data()
    groups = data.get("groups") or []
    if not groups:
        return {}
    if group_id:
        for group in groups:
            if group["id"] == group_id:
                return dict(group)
    default_id = data.get("default_group_id")
    for group in groups:
        if group["id"] == default_id:
            return dict(group)
    return dict(groups[0])


def get_step_pack() -> list:
    """Return default group steps (serial Auto-add list) for this PC only."""
    group = get_step_group()
    return list(group.get("steps") or [])


def save_step_pack(steps) -> list:
    """Persist steps into the default group (compat helper)."""
    cleaned = _clean_steps(steps)
    if not cleaned:
        raise ValueError(f"Save at least {MIN_STEP_PACK} step (up to {MAX_STEP_PACK}).")
    data = _load_step_pack_data()
    groups = list(data.get("groups") or [])
    default_id = data.get("default_group_id") or ""
    updated = False
    for group in groups:
        if group["id"] == default_id:
            group["steps"] = cleaned
            updated = True
            break
    if not updated:
        gid = _new_group_id()
        groups = [{"id": gid, "name": "Default", "steps": cleaned}] + groups
        default_id = gid
    save_step_groups(groups, default_id)
    return cleaned


def get_steps_25_template() -> str:
    """Load this PC’s private step template; no personal prompts ship in source."""
    if STEPS_25_TEMPLATE_FILE.exists():
        try:
            content = STEPS_25_TEMPLATE_FILE.read_text(encoding="utf-8")
            if content.strip():
                return content
        except Exception:
            pass
    steps = get_step_pack()
    if not steps:
        return DEFAULT_STEPS_25
    return "\n---\n" + "\n---\n".join(steps)


def save_steps_25_template(content: str):
    """Save user-customized step template (markdown) and sync default group."""
    text = content if content is not None else ""
    _write_private_file(STEPS_25_TEMPLATE_FILE, text)
    steps = split_prompts(text)
    if steps:
        save_step_pack(steps)


def format_step_pack_for_editor(steps) -> str:
    """Join pack steps with --- for paste into a single text editor."""
    cleaned = _clean_steps(steps)
    if not cleaned:
        return ""
    return "\n---\n" + "\n---\n".join(cleaned)


def choose_step_group(parent=None):
    """Pick a saved group. One group → return it; many → menu; none → None."""
    groups = list_step_groups()
    if not groups:
        return None
    if len(groups) == 1:
        return groups[0]

    selected = {"group": None}
    menu = QtWidgets.QMenu(parent)
    menu.setStyleSheet(
        "QMenu { background-color: #0f172a; color: #e2e8f0; border: 1px solid #334155; }"
        "QMenu::item:selected { background-color: #1e3a5f; }"
    )
    for group in groups:
        count = len(group.get("steps") or [])
        action = menu.addAction(f"{group['name']}  ({count} steps)")
        action.setData(group["id"])

    def _picked(action):
        gid = action.data()
        for group in groups:
            if group["id"] == gid:
                selected["group"] = group
                break

    menu.triggered.connect(_picked)
    # Prefer button-anchored popup when caller is a widget with a geometry.
    if parent is not None and hasattr(parent, "mapToGlobal") and hasattr(parent, "rect"):
        menu.exec_(parent.mapToGlobal(parent.rect().bottomLeft()))
    else:
        menu.exec_(QtGui.QCursor.pos())
    return selected["group"]


class Steps25TemplateDialog(QtWidgets.QDialog):
    """Manage named step groups. Each group’s steps Auto-add serially."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙ Step groups (Auto-add)")
        self.resize(920, 660)
        self.setStyleSheet(STYLE)
        self._groups = []
        self._current_id = ""
        self._loading = False

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        header = QtWidgets.QLabel("⚙ Step groups")
        header.setStyleSheet("font-size: 15px; font-weight: 700; color: #38bdf8;")
        layout.addWidget(header)

        desc = QtWidgets.QLabel(
            "Save reusable groups of 1–6 steps. Paste several prompts in one box separated by --- "
            "and they become serial steps. Click Auto-add → pick a group → every step queues in order."
        )
        desc.setStyleSheet("color: #94a3b8; font-size: 11px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(12)

        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel("Groups"))
        self.group_list = QtWidgets.QListWidget()
        self.group_list.currentRowChanged.connect(self._on_group_selected)
        left.addWidget(self.group_list, stretch=1)

        left_btns = QtWidgets.QHBoxLayout()
        btn_new = QtWidgets.QPushButton("+ New group")
        btn_new.clicked.connect(self._new_group)
        left_btns.addWidget(btn_new)
        btn_del = QtWidgets.QPushButton("Delete")
        btn_del.clicked.connect(self._delete_group)
        left_btns.addWidget(btn_del)
        left.addLayout(left_btns)
        body.addLayout(left, stretch=1)

        right = QtWidgets.QVBoxLayout()
        name_row = QtWidgets.QHBoxLayout()
        name_row.addWidget(QtWidgets.QLabel("Group name"))
        self.name_input = QtWidgets.QLineEdit()
        self.name_input.setPlaceholderText("e.g. Engineering follow-ups")
        self.name_input.textChanged.connect(self._on_name_changed)
        name_row.addWidget(self.name_input, stretch=1)
        right.addLayout(name_row)

        hint = QtWidgets.QLabel(
            "Steps in this group (separate with --- on its own line). "
            "Auto-add inserts them one after another."
        )
        hint.setStyleSheet("color: #64748b; font-size: 11px;")
        hint.setWordWrap(True)
        right.addWidget(hint)

        self.steps_editor = QtWidgets.QPlainTextEdit()
        self.steps_editor.setFont(QtGui.QFont("Monospace", 10))
        self.steps_editor.setPlaceholderText(
            "Step 2 prompt text…\n"
            "---\n"
            "Step 3 prompt text…\n"
            "---\n"
            "Step 4 prompt text…"
        )
        self.steps_editor.textChanged.connect(self._on_steps_changed)
        right.addWidget(self.steps_editor, stretch=1)

        self.step_count_lbl = QtWidgets.QLabel("")
        self.step_count_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
        right.addWidget(self.step_count_lbl)

        self.default_check = QtWidgets.QCheckBox("Default group for one-click Auto-add")
        right.addWidget(self.default_check)

        body.addLayout(right, stretch=3)
        layout.addLayout(body, stretch=1)

        bottom = QtWidgets.QHBoxLayout()
        bottom.addStretch()
        btn_cancel = QtWidgets.QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(btn_cancel)
        btn_save = QtWidgets.QPushButton("💾 Save groups")
        btn_save.setObjectName("primary")
        btn_save.setStyleSheet(
            "background-color: #2563eb; color: white; font-weight: 700; padding: 6px 16px; border-radius: 5px;"
        )
        btn_save.clicked.connect(self._save)
        bottom.addWidget(btn_save)
        layout.addLayout(bottom)

        data = _load_step_pack_data()
        self._groups = [dict(g) for g in (data.get("groups") or [])]
        self._default_id = data.get("default_group_id") or ""
        if not self._groups:
            gid = _new_group_id()
            self._groups = [{"id": gid, "name": "Default", "steps": []}]
            self._default_id = gid
        self._refresh_group_list(select_id=self._default_id or self._groups[0]["id"])

    def _refresh_group_list(self, select_id=None):
        self._loading = True
        self.group_list.clear()
        select_row = 0
        for index, group in enumerate(self._groups):
            count = len(group.get("steps") or [])
            mark = " ★" if group["id"] == self._default_id else ""
            self.group_list.addItem(f"{group.get('name') or 'Untitled'} ({count}){mark}")
            if select_id and group["id"] == select_id:
                select_row = index
        self.group_list.setCurrentRow(select_row)
        self._loading = False
        self._on_group_selected(select_row)

    def _current_group(self):
        row = self.group_list.currentRow()
        if 0 <= row < len(self._groups):
            return self._groups[row]
        return None

    def _flush_editor_into_current(self):
        group = None
        for item in self._groups:
            if item["id"] == self._current_id:
                group = item
                break
        if not group:
            return
        name = self.name_input.text().strip() or group.get("name") or "Untitled"
        group["name"] = name
        group["steps"] = _clean_steps(split_prompts(self.steps_editor.toPlainText()))
        if self.default_check.isChecked():
            self._default_id = group["id"]

    def _on_group_selected(self, row):
        if self._loading:
            return
        if self._current_id:
            self._flush_editor_into_current()
        if not (0 <= row < len(self._groups)):
            return
        group = self._groups[row]
        self._current_id = group["id"]
        self._loading = True
        self.name_input.setText(group.get("name") or "")
        self.steps_editor.setPlainText("\n---\n".join(group.get("steps") or []))
        self.default_check.setChecked(group["id"] == self._default_id)
        self._loading = False
        self._update_step_count()

    def _on_name_changed(self, _text=""):
        if self._loading:
            return
        self._flush_editor_into_current()
        row = self.group_list.currentRow()
        if 0 <= row < len(self._groups):
            group = self._groups[row]
            count = len(group.get("steps") or [])
            mark = " ★" if group["id"] == self._default_id else ""
            self.group_list.item(row).setText(f"{group.get('name') or 'Untitled'} ({count}){mark}")

    def _on_steps_changed(self):
        if self._loading:
            return
        self._flush_editor_into_current()
        self._update_step_count()
        self._on_name_changed()

    def _update_step_count(self):
        steps = _clean_steps(split_prompts(self.steps_editor.toPlainText()))
        self.step_count_lbl.setText(f"{len(steps)} serial step(s) in this group (max {MAX_STEP_PACK})")

    def _new_group(self):
        if len(self._groups) >= MAX_STEP_GROUPS:
            QtWidgets.QMessageBox.information(self, "Limit", f"At most {MAX_STEP_GROUPS} groups.")
            return
        self._flush_editor_into_current()
        gid = _new_group_id()
        self._groups.append({"id": gid, "name": f"Group {len(self._groups) + 1}", "steps": []})
        self._refresh_group_list(select_id=gid)

    def _delete_group(self):
        if len(self._groups) <= 1:
            QtWidgets.QMessageBox.information(self, "Keep one", "Keep at least one group.")
            return
        row = self.group_list.currentRow()
        if not (0 <= row < len(self._groups)):
            return
        removed = self._groups.pop(row)
        if self._default_id == removed["id"]:
            self._default_id = self._groups[0]["id"]
        self._current_id = ""
        self._refresh_group_list(select_id=self._groups[min(row, len(self._groups) - 1)]["id"])

    def _save(self):
        self._flush_editor_into_current()
        if self.default_check.isChecked() and self._current_id:
            self._default_id = self._current_id
        valid = []
        for group in self._groups:
            steps = _clean_steps(group.get("steps") or [])
            if not steps:
                continue
            valid.append({
                "id": group["id"],
                "name": (group.get("name") or "Untitled").strip() or "Untitled",
                "steps": steps,
            })
        if not valid:
            QtWidgets.QMessageBox.warning(
                self,
                "Empty groups",
                "Each saved group needs at least one step. Separate multiple steps with ---.",
            )
            return
        try:
            save_step_groups(valid, self._default_id)
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Cannot save", str(exc))
            return
        QtWidgets.QMessageBox.information(
            self,
            "Groups saved",
            f"Saved {len(valid)} group(s). Auto-add queues every step in the chosen group in order.",
        )
        self.accept()


class BatchProjectDialog(QtWidgets.QDialog):
    """Visual Batch Project Generator: automatically queues up to 20+ projects
    with a custom/templated Step 1 specification prompt, and shared Steps 2-5 boilerplate.
    """
    def __init__(self, pipeline, parent=None, default_agent="multi"):
        super().__init__(parent)
        self.pipeline = pipeline
        self.default_agent = default_agent
        self.setWindowTitle("⚡ Batch Multi-Project Generator (20 Projects)")
        self.setMinimumSize(800, 580)
        self.setStyleSheet(STYLE)
        self.init_ui()

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # Title / Description
        header_lbl = QtWidgets.QLabel("⚡ Batch Project & Multi-Agent Step Generator")
        header_lbl.setStyleSheet("font-size: 16px; font-weight: 800; color: #38bdf8;")
        layout.addWidget(header_lbl)

        desc_lbl = QtWidgets.QLabel(
            "Quickly configure up to 20 separate project folders. Step 1 executes the full application spec, "
            "and Steps 2–5 automatically execute shared engineering tasks (testing, docker, security, docs) across AI agents."
        )
        desc_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
        desc_lbl.setWordWrap(True)
        layout.addWidget(desc_lbl)

        # Split: Left (Projects List) | Right (Step Prompts & Config)
        splitter = QtWidgets.QSplitter(Qt.Horizontal)

        # Left: Project Titles
        left_box = QtWidgets.QWidget()
        ll = QtWidgets.QVBoxLayout(left_box)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)

        proj_header_row = QtWidgets.QHBoxLayout()
        proj_lbl = QtWidgets.QLabel("Project Titles (One per line):")
        proj_lbl.setStyleSheet("font-weight: 700; color: #f1f5f9;")
        proj_header_row.addWidget(proj_lbl)

        btn_sample = QtWidgets.QPushButton("Load 20 Sample Tech Projects")
        btn_sample.setObjectName("small_btn")
        btn_sample.setStyleSheet("background-color: #0f172a; color: #38bdf8; font-size: 11px; padding: 4px 8px; border: 1px solid #1e293b; border-radius: 4px;")
        btn_sample.clicked.connect(self.load_sample_projects)
        proj_header_row.addWidget(btn_sample)
        ll.addLayout(proj_header_row)

        self.projects_text = QtWidgets.QTextEdit()
        self.projects_text.setPlaceholderText(
            "Enter project titles, one per line:\n\n"
            "01-user-auth-service\n"
            "02-billing-stripe-api\n"
            "03-crm-lead-pipeline\n"
            "04-ecommerce-catalog\n"
            "...\n(Up to 20 or more projects)"
        )
        ll.addWidget(self.projects_text)

        splitter.addWidget(left_box)

        # Right: Prompt Configuration
        right_box = QtWidgets.QWidget()
        rl = QtWidgets.QVBoxLayout(right_box)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        step1_lbl = QtWidgets.QLabel("Step 1 Spec Prompt (Unique per project):")
        step1_lbl.setStyleSheet("font-weight: 700; color: #38bdf8;")
        rl.addWidget(step1_lbl)

        self.step1_input = QtWidgets.QTextEdit()
        self.step1_input.setMaximumHeight(85)
        self.step1_input.setPlainText(
            "Build complete, production-ready backend and web interface for {title} with database migrations, API routes, and models."
        )
        rl.addWidget(self.step1_input)

        step25_lbl = QtWidgets.QLabel("Shared follow-up steps 2–6 (applied to ALL projects; separate with ---):")
        step25_lbl.setStyleSheet("font-weight: 700; color: #a78bfa;")
        rl.addWidget(step25_lbl)

        self.step25_text = QtWidgets.QTextEdit()
        pack = get_step_pack()
        self.step25_text.setPlainText(
            "\n---\n".join(pack) if pack else get_steps_25_template().strip()
        )
        rl.addWidget(self.step25_text)

        # Agent & GitHub options
        opt_row = QtWidgets.QHBoxLayout()
        self.agent_combo = QtWidgets.QComboBox()
        self.agent_combo.addItem("✨ Multi-Agent Hybrid (Antigravity + DevOS Code)", "multi")
        self.agent_combo.addItem("Antigravity AI (Primary CLI)", "antigravity")
        self.agent_combo.addItem("DevOS Local AI", "local")
        opt_row.addWidget(self.agent_combo)

        self.cb_github = QtWidgets.QCheckBox("Auto-create GitHub Repo")
        self.cb_github.setChecked(True)
        opt_row.addWidget(self.cb_github)
        rl.addLayout(opt_row)

        splitter.addWidget(right_box)
        layout.addWidget(splitter, stretch=1)

        # Bottom Buttons
        btn_box = QtWidgets.QHBoxLayout()
        btn_cancel = QtWidgets.QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        btn_box.addStretch()

        self.btn_generate = QtWidgets.QPushButton("⚡ Generate Projects into Pipeline")
        self.btn_generate.setObjectName("primary")
        self.btn_generate.setStyleSheet("background-color: #2563eb; color: white; font-weight: 700; padding: 8px 18px; border-radius: 6px;")
        self.btn_generate.clicked.connect(self.generate_projects)
        btn_box.addWidget(self.btn_generate)

        layout.addLayout(btn_box)

    def load_sample_projects(self):
        samples = [
            "01-user-auth-service",
            "02-billing-stripe-api",
            "03-realtime-chat-engine",
            "04-crm-lead-pipeline",
            "05-ecommerce-catalog",
            "06-inventory-tracker",
            "07-invoice-vat-engine",
            "08-prompt-analytics-dashboard",
            "09-support-ticket-helpdesk",
            "10-cloud-media-cdn",
            "11-api-rate-limiter",
            "12-feed-comment-system",
            "13-appointment-booking",
            "14-seo-sitemap-generator",
            "15-web3-payment-processor",
            "16-multitenant-org-manager",
            "17-kanban-sprint-board",
            "18-iot-telemetry-collector",
            "19-newsletter-campaign-dispatcher",
            "20-patient-healthcare-portal",
        ]
        self.projects_text.setPlainText("\n".join(samples))

    def generate_projects(self):
        lines = [l.strip() for l in self.projects_text.toPlainText().splitlines() if l.strip()]
        if not lines:
            QtWidgets.QMessageBox.warning(self, "No Projects", "Please enter at least one project title.")
            return

        step1_template = self.step1_input.toPlainText().strip()
        shared_steps = split_prompts(self.step25_text.toPlainText())

        base_dir = self.pipeline.get_base_dir()
        agent = self.agent_combo.currentData() or "multi"
        create_repo = self.cb_github.isChecked()

        for line in lines:
            title = line.strip()
            slug = to_slug(title)
            proj_dir = str(Path(base_dir) / slug)
            os.makedirs(proj_dir, exist_ok=True)

            # Step 1
            prompt1 = step1_template.replace("{title}", title).replace("{slug}", slug)
            step1_agent = "antigravity" if agent == "multi" else agent
            self.pipeline.add(
                prompt=prompt1,
                agent=step1_agent,
                project=proj_dir,
                project_title=title,
                project_slug=slug,
                create_repo=create_repo,
                repo_name=slug if create_repo else "",
                notify_desktop=False,
            )

            # Steps 2-5
            hybrid_cycle = ["antigravity", "local", "local", "antigravity"]
            for idx, shared_prompt in enumerate(shared_steps):
                step_agent = hybrid_cycle[idx % len(hybrid_cycle)] if agent == "multi" else agent
                self.pipeline.add(
                    prompt=shared_prompt,
                    agent=step_agent,
                    project=proj_dir,
                    project_title=title,
                    project_slug=slug,
                    create_repo=False,
                    notify_desktop=False,
                )

        total_steps = len(lines) * (1 + len(shared_steps))
        notify("Batch Generated", f"Queued {len(lines)} projects ({total_steps} sequential steps)")
        self.accept()


class PromptEditorDialog(QtWidgets.QDialog):
    """Large, dedicated multi-paragraph prompt and specification editor.
    Perfect for 5,000+ word architecture prompts, with live step detection,
    word counting, file loading, and template insertion.
    """
    def __init__(self, initial_text: str = "", project_name: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"📝 Master Specification & Sequential Steps Editor — {project_name or 'Project'}")
        self.resize(860, 600)
        self.setStyleSheet(STYLE)
        self.init_ui(initial_text)

    def init_ui(self, initial_text):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        # Header with actions
        hdr = QtWidgets.QHBoxLayout()
        title_lbl = QtWidgets.QLabel("Master Prompt & Sequential Steps Editor")
        title_lbl.setStyleSheet("font-size: 15px; font-weight: 800; color: #38bdf8;")
        hdr.addWidget(title_lbl)

        hdr.addStretch()

        btn_load = QtWidgets.QPushButton("📄 Load Prompt File (.md / .txt)")
        btn_load.setObjectName("small_btn")
        btn_load.setStyleSheet("background-color: #0f172a; color: #38bdf8; font-size: 11px; padding: 4px 10px; border: 1px solid #1e293b; border-radius: 5px;")
        btn_load.clicked.connect(self.load_from_file)
        hdr.addWidget(btn_load)

        btn_sep = QtWidgets.QPushButton("+ Insert Step Separator (---)")
        btn_sep.setObjectName("small_btn")
        btn_sep.setStyleSheet("background-color: #1e1b4b; color: #a5b4fc; font-size: 11px; padding: 4px 10px; border: 1px solid #312e81; border-radius: 5px;")
        btn_sep.clicked.connect(self.insert_step_separator)
        hdr.addWidget(btn_sep)

        btn_steps25 = QtWidgets.QPushButton("✨ Auto-add group")
        btn_steps25.setObjectName("small_btn")
        btn_steps25.setToolTip("Pick a saved step group; append all its steps serially")
        btn_steps25.setStyleSheet("background-color: #064e3b; color: #6ee7b7; font-size: 11px; padding: 4px 10px; border: 1px solid #047857; border-radius: 5px;")
        btn_steps25.clicked.connect(self.append_steps_25)
        hdr.addWidget(btn_steps25)

        layout.addLayout(hdr)

        # Main Text Editor
        self.editor = QtWidgets.QTextEdit()
        self.editor.setPlaceholderText(
            "Paste or write your full master project specification here (5,000+ words, markdown, code blocks, lists all supported).\n\n"
            "To add sequential commands/steps for this project, separate them with '---' on a new line:\n\n"
            "Step 1: [Master 5,000-word Full Application Specification]\n"
            "---\n"
            "Step 2: Add comprehensive unit tests with Pest/PHPUnit\n"
            "---\n"
            "Step 3: Create Dockerfile and docker-compose.yml"
        )
        self.editor.setFont(QtGui.QFont("Monospace", 10))
        self.editor.setPlainText(initial_text)
        self.editor.textChanged.connect(self.update_metrics)
        layout.addWidget(self.editor, stretch=1)

        # Metrics bar: live words, characters, and steps count
        self.metrics_lbl = QtWidgets.QLabel("")
        self.metrics_lbl.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600;")
        layout.addWidget(self.metrics_lbl)

        # Bottom Buttons
        btn_box = QtWidgets.QHBoxLayout()
        btn_cancel = QtWidgets.QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        btn_box.addStretch()

        btn_apply = QtWidgets.QPushButton("✔ Apply to Project")
        btn_apply.setObjectName("primary")
        btn_apply.setStyleSheet("background-color: #2563eb; color: white; font-weight: 700; padding: 7px 18px; border-radius: 6px;")
        btn_apply.clicked.connect(self.accept)
        btn_box.addWidget(btn_apply)

        layout.addLayout(btn_box)
        self.update_metrics()

    def update_metrics(self):
        text = self.editor.toPlainText().strip()
        words = len(text.split()) if text else 0
        chars = len(text)
        steps = split_prompts(text)
        count = len(steps)
        if not text:
            self.metrics_lbl.setText("Empty • Ready to paste or load spec")
        elif count == 1:
            self.metrics_lbl.setText(f"📝 1 Master Prompt Step ({words:,} words, {chars:,} characters) • Use '---' to add subsequent steps")
        else:
            breakdown = ", ".join(f"Step {i+1}: {len(s.split()):,} words" for i, s in enumerate(steps[:4]))
            if count > 4:
                breakdown += f", +{count - 4} more"
            self.metrics_lbl.setText(f"📝 {count} Sequential Steps Detected ({words:,} total words) — [{breakdown}]")

    def insert_step_separator(self):
        cursor = self.editor.textCursor()
        cursor.insertText("\n\n---\n\n")
        self.editor.setFocus()

    def append_steps_25(self):
        steps = split_prompts(get_steps_25_template())
        if not steps:
            groups = list_step_groups()
            if not groups:
                QtWidgets.QMessageBox.information(
                    self,
                    "No saved steps",
                    "Save a step group with ⚙ on the pipeline window first.",
                )
                return
            group = choose_step_group(self.sender() if isinstance(self.sender(), QtWidgets.QWidget) else self)
            steps = list((group or {}).get("steps") or [])
            if not steps:
                return
        elif len(list_step_groups()) > 1:
            group = choose_step_group(self.sender() if isinstance(self.sender(), QtWidgets.QWidget) else self)
            if group:
                steps = list(group.get("steps") or []) or steps
        current = self.editor.toPlainText().rstrip()
        append_txt = format_step_pack_for_editor(steps)
        self.editor.setPlainText(current + append_txt if current else append_txt.lstrip())

    def load_from_file(self):
        selected, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Specification / Prompt File", str(Path.home()), "Markdown / Text Files (*.md *.txt *.prompt);;All Files (*)"
        )
        if selected:
            try:
                content = Path(selected).read_text(encoding="utf-8", errors="ignore")
                self.editor.setPlainText(content)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Load Failed", f"Could not read file:\n{e}")

    def get_text(self) -> str:
        return self.editor.toPlainText().strip()


class PipelineWindow(QtWidgets.QMainWindow):
    pipeline_activity = QtCore.pyqtSignal(str)
    def __init__(self):
        super().__init__()
        self.pipeline = TaskPipeline()
        self.pipeline_activity.connect(self.append_pipeline_log)
        self.pipeline.event_callback = self.pipeline_activity.emit
        self.worker = None

        # Determine initial preferred agent (e.g. Antigravity KDE in KDE desktop)
        known_agents = discover_agents()
        is_kde = ("KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "")) or (os.environ.get("DESKTOP_SESSION") == "plasma")
        if is_kde and known_agents.get("antigravity-kde", {}).get("running"):
            init_agent = "antigravity-kde"
        elif known_agents.get("antigravity", {}).get("running"):
            init_agent = "antigravity"
        elif known_agents.get("antigravity-kde", {}).get("running"):
            init_agent = "antigravity-kde"
        else:
            init_agent = None

        # Auto-detect current active project based on active agent
        cur_slug, cur_title, cur_path = detect_current_project(self.pipeline.get_base_dir(), agent=init_agent)
        self.current_slug = cur_slug or "dev-os"
        self.current_title = cur_title or "Dev Os"
        self.current_path = cur_path or str(Path(self.pipeline.get_base_dir()) / self.current_slug)

        self.setWindowTitle("DevOS AI Command Pipeline & Scheduler")
        self.setObjectName("devos-ai-pipeline")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        icon = get_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.resize(1180, 680)
        try:
            screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
            target_w = min(1200, max(800, screen.width() - 30))
            target_h = min(680, max(500, screen.height() - 40))
            self.resize(target_w, target_h)
            self.move(max(0, (screen.width() - target_w) // 2), max(0, (screen.height() - target_h) // 2))
        except Exception:
            pass
        self.setStyleSheet(STYLE)
        self.is_running = False
        self.draft_prompts = []
        self.project_page = 0
        self.card_nav_states = {}
        self.last_grouped_sig = None
        self.init_ui()

        # Timer for refreshing queue and ticking countdowns
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_queue)
        self.timer.start(1000)

        # Worker timer for executing next pipeline task if running or checking status
        self.runner_timer = QTimer(self)
        self.runner_timer.timeout.connect(self.run_step)
        self.runner_timer.start(2500)

    def init_ui(self):
        central = QtWidgets.QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(18, 14, 18, 14)
        main_layout.setSpacing(10)

        # Header
        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setSpacing(12)

        icon_lbl = QtWidgets.QLabel()
        app_icon = get_app_icon()
        if not app_icon.isNull():
            icon_lbl.setPixmap(app_icon.pixmap(42, 42))
        header_layout.addWidget(icon_lbl)

        header_vbox = QtWidgets.QVBoxLayout()
        header_vbox.setSpacing(2)
        title = QtWidgets.QLabel("DevOS AI Command Pipeline")
        title.setObjectName("title")
        subtitle = QtWidgets.QLabel("Parallel agents · 1-by-1 per agent · Real 429 pauses shared Google quota")
        subtitle.setObjectName("subtitle")
        header_vbox.addWidget(title)
        header_vbox.addWidget(subtitle)
        header_layout.addLayout(header_vbox, stretch=1)

        # Top Control Buttons
        btn_batch_top = QtWidgets.QPushButton("⚡ Batch 20 Projects...")
        btn_batch_top.setObjectName("accent_action")
        btn_batch_top.setToolTip("Auto-generate 20 separate project folders with 1st spec prompt + shared 2-5 prompts")
        btn_batch_top.clicked.connect(self.open_batch_dialog)
        header_layout.addWidget(btn_batch_top)

        btn_import_specs = QtWidgets.QPushButton("📁 Import Specs...")
        btn_import_specs.setObjectName("small_btn")
        btn_import_specs.setStyleSheet("background-color: #1e293b; color: #38bdf8; font-size: 11px; padding: 6px 12px; border: 1px solid #334155; border-radius: 6px;")
        btn_import_specs.setToolTip("Batch import all .md project specs from a folder and auto-attach multi-agent steps")
        btn_import_specs.clicked.connect(self.import_specs_folder)
        header_layout.addWidget(btn_import_specs)

        self.btn_run = QtWidgets.QPushButton("Run Pipeline")
        self.btn_run.setObjectName("primary")
        self.btn_run.clicked.connect(self.toggle_runner)
        header_layout.addWidget(self.btn_run)

        btn_clear = QtWidgets.QPushButton("Clear Queue")
        btn_clear.clicked.connect(self.clear_queue)
        header_layout.addWidget(btn_clear)

        btn_clear_alerts = QtWidgets.QPushButton("Clear Alerts")
        btn_clear_alerts.setObjectName("small_btn")
        btn_clear_alerts.setStyleSheet(
            "background-color: #7c2d12; color: #fed7aa; font-size: 11px; "
            "padding: 6px 12px; border: 1px solid #ea580c; border-radius: 6px;"
        )
        btn_clear_alerts.setToolTip("Dismiss all stacked Pipeline Stall / DevOS AI Pipeline desktop notifications")
        btn_clear_alerts.clicked.connect(self.clear_alerts)
        header_layout.addWidget(btn_clear_alerts)

        main_layout.addLayout(header_layout)

        # Toast Banner for Instant Visual Action Feedback
        self.toast_banner = QtWidgets.QLabel("")
        self.toast_banner.setObjectName("toast_banner")
        self.toast_banner.setAlignment(Qt.AlignCenter)
        self.toast_banner.hide()
        main_layout.addWidget(self.toast_banner)

        # Rate Limit Alert Banner (Dynamic)
        self.banner_frame = QtWidgets.QFrame()
        self.banner_frame.setObjectName("banner_rate_limit")
        banner_box = QtWidgets.QHBoxLayout(self.banner_frame)
        banner_box.setContentsMargins(14, 8, 14, 8)

        self.banner_tag = QtWidgets.QLabel("RATE LIMIT")
        self.banner_tag.setObjectName("tag_label")
        banner_box.addWidget(self.banner_tag)

        self.banner_text = QtWidgets.QLabel("")
        self.banner_text.setStyleSheet("color: #fef3c7; font-weight: 500;")
        banner_box.addWidget(self.banner_text, stretch=1)

        self.btn_banner_switch = QtWidgets.QPushButton("Auto-Failover to Antigravity")
        self.btn_banner_switch.setObjectName("accent_warning")
        self.btn_banner_switch.clicked.connect(self.failover_all_rate_limited)
        banner_box.addWidget(self.btn_banner_switch)

        self.banner_frame.hide()
        main_layout.addWidget(self.banner_frame)

        # Premium control strip — modes, blueprints, scorecard
        premium_bar = QtWidgets.QFrame()
        premium_bar.setObjectName("banner_strip")
        premium_row = QtWidgets.QHBoxLayout(premium_bar)
        premium_row.setContentsMargins(12, 6, 12, 6)
        premium_row.setSpacing(8)
        prem_tag = QtWidgets.QLabel("PREMIUM")
        prem_tag.setObjectName("tag_label")
        premium_row.addWidget(prem_tag)
        premium_row.addWidget(QtWidgets.QLabel("Mode"))
        self.mode_combo = QComboBox()
        self.mode_combo.setMinimumWidth(140)
        if premium:
            for key, meta in premium.MODES.items():
                self.mode_combo.addItem(meta["label"], key)
            cur = premium.get_mode(self.pipeline.context)
            idx = self.mode_combo.findData(cur)
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)
        self.mode_combo.currentIndexChanged.connect(self.on_premium_mode_changed)
        self.mode_combo.setToolTip("Balanced · Quality (gates) · Overnight (auto-failover) · Speed")
        premium_row.addWidget(self.mode_combo)
        premium_row.addWidget(QtWidgets.QLabel("Blueprint"))
        self.blueprint_combo = QComboBox()
        self.blueprint_combo.setMinimumWidth(200)
        self.blueprint_combo.addItem("Choose a blueprint…", "")
        if premium:
            for bp in premium.list_blueprints():
                self.blueprint_combo.addItem(f"{bp['title']} ({bp['steps']} steps)", bp["id"])
        premium_row.addWidget(self.blueprint_combo)
        btn_bp = QtWidgets.QPushButton("Queue Blueprint")
        btn_bp.setObjectName("accent_action")
        btn_bp.setToolTip("Add a curated multi-phase project (SaaS, API, Landing, QA) in one click")
        btn_bp.clicked.connect(self.queue_premium_blueprint)
        premium_row.addWidget(btn_bp)
        self.scorecard_lbl = QtWidgets.QLabel("Scorecard —")
        self.scorecard_lbl.setStyleSheet("color:#94a3b8; font-size:11px; font-weight:600;")
        premium_row.addWidget(self.scorecard_lbl, stretch=1)
        main_layout.addWidget(premium_bar)

        # =====================================================================
        # CONTENT SPLITTER: Left (Project Builder) | Right (Queue & KPI)
        # =====================================================================
        content_splitter = QtWidgets.QSplitter(Qt.Horizontal)
        content_splitter.setObjectName("content_splitter")
        content_splitter.setHandleWidth(8)
        content_splitter.setStyleSheet("QSplitter::handle { background-color: #1e293b; border-radius: 4px; margin: 4px 1px; }")

        # ---------------------------------------------------------------------
        # LEFT PANEL: Multi-Project Builder & Console
        # ---------------------------------------------------------------------
        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(10)

        # Base Project Directory Selection Bar
        base_dir_card = QtWidgets.QFrame()
        base_dir_card.setObjectName("banner_strip")
        base_dir_layout = QtWidgets.QHBoxLayout(base_dir_card)
        base_dir_layout.setContentsMargins(12, 6, 12, 6)
        base_dir_layout.setSpacing(8)

        base_badge = QtWidgets.QLabel("WORKSPACE")
        base_badge.setObjectName("tag_label")
        base_dir_layout.addWidget(base_badge)

        self.base_dir_input = QLineEdit()
        self.base_dir_input.setText(self.pipeline.get_base_dir())
        self.base_dir_input.setPlaceholderText("Base directory where project folders will be created...")
        self.base_dir_input.editingFinished.connect(self.on_base_dir_changed)
        base_dir_layout.addWidget(self.base_dir_input, stretch=1)

        btn_browse_dir = QtWidgets.QPushButton("Browse...")
        btn_browse_dir.setObjectName("small_btn")
        btn_browse_dir.clicked.connect(self.browse_base_dir)
        base_dir_layout.addWidget(btn_browse_dir)

        left_layout.addWidget(base_dir_card)

        # Main Input Console Form
        form_card = QtWidgets.QFrame()
        form_card.setObjectName("card")
        form_layout = QtWidgets.QVBoxLayout(form_card)
        form_layout.setContentsMargins(14, 12, 14, 12)
        form_layout.setSpacing(10)

        # 1. Target Agent Selection
        agent_row = QtWidgets.QHBoxLayout()
        agent_row.setSpacing(8)

        lbl_step1 = QtWidgets.QLabel("1. Agent:")
        lbl_step1.setObjectName("field_label")
        agent_row.addWidget(lbl_step1)

        self.agent_combo = QtWidgets.QComboBox()
        self.agent_combo.setMinimumWidth(240)
        self.agent_combo.addItem("✨ Multi-Agent Hybrid (Antigravity + DevOS Code)", "multi")
        known = discover_agents()
        is_kde_session = ("KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "")) or (
            os.environ.get("DESKTOP_SESSION") == "plasma"
        )
        default_index = 0

        idx = 1
        for k, v in known.items():
            if v.get("running"):
                label = f"● {v['name']} [Running]"
            elif v.get("available"):
                label = f"○ {v['name']} [Ready]" if k == "local" else f"○ {v['name']} [Installed]"
            else:
                label = f"○ {v['name']} [Not Installed]"
            self.agent_combo.addItem(label, k)

            if is_kde_session and k == "antigravity-kde" and v.get("running"):
                default_index = idx
            elif not is_kde_session and k == "antigravity" and v.get("running") and default_index == 0:
                default_index = idx
            elif v.get("running") and default_index == 0:
                default_index = idx
            idx += 1

        self.agent_combo.setCurrentIndex(default_index)
        agent_row.addWidget(self.agent_combo)

        # Live status badge next to dropdown
        self.agent_status_lbl = QtWidgets.QLabel()
        self.agent_status_lbl.setObjectName("badge_cyan")
        agent_row.addWidget(self.agent_status_lbl)

        agent_row.addStretch()

        btn_seo = QtWidgets.QPushButton("SEO Preset")
        btn_seo.setToolTip("Auto-fill prompt for best ranking repo name & 400-char SEO description")
        btn_seo.setStyleSheet("background-color: #1e293b; color: #38bdf8; font-size: 11px; padding: 4px 8px; border: 1px solid #334155; border-radius: 5px;")
        btn_seo.clicked.connect(self.fill_seo_prompt)
        agent_row.addWidget(btn_seo)

        form_layout.addLayout(agent_row)

        # 2. CURRENT WORKING PROJECT SECTION
        cur_section = QtWidgets.QFrame()
        cur_section.setObjectName("section_current")
        cur_layout = QtWidgets.QVBoxLayout(cur_section)
        cur_layout.setContentsMargins(12, 8, 12, 8)
        cur_layout.setSpacing(5)

        cur_header = QtWidgets.QHBoxLayout()
        cur_badge = QtWidgets.QLabel("2. CURRENT ACTIVE PROJECT")
        cur_badge.setObjectName("badge_cyan")
        cur_header.addWidget(cur_badge)

        cur_header.addStretch()

        btn_rescan_cur = QtWidgets.QPushButton("Re-Detect")
        btn_rescan_cur.setObjectName("small_btn")
        btn_rescan_cur.setToolTip("Re-scan running agent process and workspace storage for open project")
        btn_rescan_cur.setStyleSheet("background-color: #0f172a; color: #38bdf8; font-size: 10px; padding: 2px 6px; border: 1px solid #1e293b; border-radius: 4px;")
        btn_rescan_cur.clicked.connect(lambda: self.refresh_current_project(manual=True))
        cur_header.addWidget(btn_rescan_cur)

        btn_reset_cur = QtWidgets.QPushButton("Reset")
        btn_reset_cur.setObjectName("small_btn")
        btn_reset_cur.setToolTip("Reset active working project back to dev-os")
        btn_reset_cur.setStyleSheet("background-color: #1e293b; color: #94a3b8; font-size: 10px; padding: 2px 6px; border: 1px solid #334155; border-radius: 4px;")
        btn_reset_cur.clicked.connect(self.reset_current_project)
        cur_header.addWidget(btn_reset_cur)

        btn_del_folder = QtWidgets.QPushButton("🗑 Delete Folder")
        btn_del_folder.setObjectName("danger_small")
        btn_del_folder.setToolTip("Permanently delete this project folder from disk")
        btn_del_folder.setStyleSheet("background-color: #450a0a; color: #fca5a5; font-size: 10px; padding: 2px 6px; border: 1px solid #7f1d1d; border-radius: 4px;")
        btn_del_folder.clicked.connect(self.delete_current_project_folder)
        cur_header.addWidget(btn_del_folder)

        cur_layout.addLayout(cur_header)

        # Row 2: Title & slug (word-wrap enabled, never forces parent width)
        self.cur_proj_title_lbl = QtWidgets.QLabel(f"{self.current_title} ({self.current_slug})")
        self.cur_proj_title_lbl.setStyleSheet("font-weight: 700; color: #38bdf8; font-size: 12px;")
        self.cur_proj_title_lbl.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.cur_proj_title_lbl.setWordWrap(True)
        cur_layout.addWidget(self.cur_proj_title_lbl)

        # Row 3: Folder path
        self.cur_proj_path_lbl = QtWidgets.QLabel(f"Path: {self.current_path}")
        self.cur_proj_path_lbl.setObjectName("path_info")
        self.cur_proj_path_lbl.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.cur_proj_path_lbl.setWordWrap(True)
        cur_layout.addWidget(self.cur_proj_path_lbl)

        # Command input for current project
        cur_tools_row = QtWidgets.QHBoxLayout()
        cur_tools_row.setSpacing(6)
        cur_tools_lbl = QtWidgets.QLabel("Commands / Prompts:")
        cur_tools_lbl.setStyleSheet("color: #64748b; font-size: 10px; font-weight: 600;")
        cur_tools_lbl.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        cur_tools_row.addWidget(cur_tools_lbl)
        cur_tools_row.addStretch()

        btn_cur_load = QtWidgets.QPushButton("📄 Load File")
        btn_cur_load.setObjectName("small_btn")
        btn_cur_load.setToolTip("Load prompt from markdown or text file")
        btn_cur_load.setStyleSheet("background-color: #0f172a; color: #38bdf8; font-size: 10px; padding: 2px 7px; border: 1px solid #1e293b; border-radius: 4px;")
        btn_cur_load.clicked.connect(self.load_cur_prompt_file)
        cur_tools_row.addWidget(btn_cur_load)

        btn_cur_sep = QtWidgets.QPushButton("+ '---'")
        btn_cur_sep.setObjectName("small_btn")
        btn_cur_sep.setToolTip("Insert '---' separator to split subsequent commands")
        btn_cur_sep.setStyleSheet("background-color: #1e1b4b; color: #a5b4fc; font-size: 10px; padding: 2px 7px; border: 1px solid #312e81; border-radius: 4px;")
        btn_cur_sep.clicked.connect(self.insert_cur_step_separator)
        cur_tools_row.addWidget(btn_cur_sep)

        btn_cur_upper = QtWidgets.QPushButton("▲ Upper")
        btn_cur_upper.setObjectName("small_btn")
        btn_cur_upper.setToolTip("Navigate cursor up to the previous '---' command step")
        btn_cur_upper.setStyleSheet("background-color: #1e1b4b; color: #a5b4fc; font-size: 10px; padding: 2px 7px; border: 1px solid #312e81; border-radius: 4px;")
        btn_cur_upper.clicked.connect(self.navigate_cur_prompt_prev)
        cur_tools_row.addWidget(btn_cur_upper)

        btn_cur_down = QtWidgets.QPushButton("▼ Next")
        btn_cur_down.setObjectName("small_btn")
        btn_cur_down.setToolTip("Navigate cursor down to the next '---' command step")
        btn_cur_down.setStyleSheet("background-color: #0f172a; color: #38bdf8; font-size: 10px; padding: 2px 7px; border: 1px solid #1e293b; border-radius: 4px;")
        btn_cur_down.clicked.connect(self.navigate_cur_prompt_next)
        cur_tools_row.addWidget(btn_cur_down)

        btn_cur_steps = QtWidgets.QPushButton("✨ Auto-add group")
        btn_cur_steps.setObjectName("small_btn")
        btn_cur_steps.setToolTip("Pick a saved step group; all its steps append serially")
        btn_cur_steps.setStyleSheet("background-color: #064e3b; color: #6ee7b7; font-size: 10px; padding: 2px 7px; border: 1px solid #047857; border-radius: 4px;")
        btn_cur_steps.clicked.connect(self.append_cur_steps_25)
        cur_tools_row.addWidget(btn_cur_steps)

        btn_cur_steps_edit = QtWidgets.QPushButton("⚙")
        btn_cur_steps_edit.setObjectName("small_btn")
        btn_cur_steps_edit.setToolTip("Create/edit named step groups (1–6 steps each)")
        btn_cur_steps_edit.setStyleSheet("background-color: #1e1b4b; color: #a5b4fc; font-size: 10px; padding: 2px 6px; border: 1px solid #312e81; border-radius: 4px;")
        btn_cur_steps_edit.clicked.connect(self.open_steps_25_template_editor)
        cur_tools_row.addWidget(btn_cur_steps_edit)

        btn_cur_expand = QtWidgets.QPushButton("⛶ Expand")
        btn_cur_expand.setObjectName("small_btn")
        btn_cur_expand.setToolTip("Open full-screen prompt editor modal")
        btn_cur_expand.setStyleSheet("background-color: #1e293b; color: #f1f5f9; font-size: 10px; padding: 2px 7px; border: 1px solid #334155; border-radius: 4px;")
        btn_cur_expand.clicked.connect(self.open_cur_prompt_editor)
        cur_tools_row.addWidget(btn_cur_expand)

        cur_layout.addLayout(cur_tools_row)

        cur_cmd_row = QtWidgets.QHBoxLayout()
        cur_cmd_row.setSpacing(8)

        self.current_prompt_input = QTextEdit()
        self.current_prompt_input.setPlaceholderText(
            f"Commands for Current Project '{self.current_slug}'... (Optional: leave empty to proceed to next project)"
        )
        self.current_prompt_input.setMinimumHeight(60)
        self.current_prompt_input.setMaximumHeight(85)
        self.current_prompt_input.textChanged.connect(self.update_cur_prompt_metrics)
        cur_cmd_row.addWidget(self.current_prompt_input, stretch=1)

        btn_add_current = QtWidgets.QPushButton("+ Queue to Current")
        btn_add_current.setObjectName("accent_action")
        btn_add_current.clicked.connect(lambda: self.add_current_project_tasks())
        cur_cmd_row.addWidget(btn_add_current)

        cur_layout.addLayout(cur_cmd_row)

        self.cur_prompt_metrics_lbl = QtWidgets.QLabel("💡 Tip: Enter multi-line prompts freely. Separate steps with '---'.")
        self.cur_prompt_metrics_lbl.setStyleSheet("color: #64748b; font-size: 10px;")
        self.cur_prompt_metrics_lbl.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.cur_prompt_metrics_lbl.setWordWrap(True)
        cur_layout.addWidget(self.cur_prompt_metrics_lbl)

        current_toggle = QtWidgets.QPushButton("Show detected current project (optional)")
        current_toggle.setCheckable(True)
        current_toggle.toggled.connect(cur_section.setVisible)
        form_layout.addWidget(current_toggle)
        form_layout.addWidget(cur_section)
        cur_section.hide()

        # 3. ADD ANOTHER PROJECT / NEXT PROJECT (DYNAMIC PROJECT NUMBERING)
        next_section = QtWidgets.QFrame()
        next_section.setObjectName("section_next")
        next_layout = QtWidgets.QVBoxLayout(next_section)
        next_layout.setContentsMargins(12, 10, 12, 10)
        next_layout.setSpacing(7)
        next_layout.setAlignment(Qt.AlignTop)

        next_header = QtWidgets.QHBoxLayout()
        self.next_badge_lbl = QtWidgets.QLabel("3. ADD NEXT PROJECT (#2)")
        self.next_badge_lbl.setObjectName("badge_indigo")
        self.next_badge_lbl.setFixedHeight(30)
        self.next_badge_lbl.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
        next_header.addWidget(self.next_badge_lbl)

        next_header.addStretch()
        next_layout.addLayout(next_header)

        # Project Title & Slug inputs
        meta_row = QtWidgets.QHBoxLayout()
        meta_row.setSpacing(8)

        self.next_title_input = QLineEdit()
        self.next_title_input.setPlaceholderText("Next Project Title (e.g. 'Build Laravel Auth API')...")
        self.next_title_input.textChanged.connect(self.on_next_title_changed)
        self.next_title_input.returnPressed.connect(lambda: self.next_prompt_input.setFocus())
        meta_row.addWidget(self.next_title_input, stretch=2)

        self.next_slug_input = QLineEdit()
        self.next_slug_input.setPlaceholderText("Folder Slug (auto-generated)")
        self.next_slug_input.textChanged.connect(self.update_next_target_preview)
        self.next_slug_input.returnPressed.connect(lambda: self.next_prompt_input.setFocus())
        meta_row.addWidget(self.next_slug_input, stretch=1)

        next_layout.addLayout(meta_row)

        # Folder location preview
        self.next_target_preview_lbl = QtWidgets.QLabel("")
        self.next_target_preview_lbl.setStyleSheet("color: #a5b4fc; font-size: 11px; font-family: monospace;")
        self.next_target_preview_lbl.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.next_target_preview_lbl.setWordWrap(True)
        next_layout.addWidget(self.next_target_preview_lbl)

        # Commands toolbar for next project
        next_tools_row = QtWidgets.QHBoxLayout()
        next_tools_row.setSpacing(6)
        next_tools_lbl = QtWidgets.QLabel("Specification / Prompts:")
        next_tools_lbl.setStyleSheet("color: #64748b; font-size: 10px; font-weight: 600;")
        next_tools_lbl.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        next_tools_row.addWidget(next_tools_lbl)
        next_tools_row.addStretch()

        btn_next_load = QtWidgets.QPushButton("📄 Load Spec (.md/.txt)")
        btn_next_load.setObjectName("small_btn")
        btn_next_load.setToolTip("Load 5,000+ word specification file from disk")
        btn_next_load.setStyleSheet("background-color: #0f172a; color: #38bdf8; font-size: 10px; padding: 2px 7px; border: 1px solid #1e293b; border-radius: 4px;")
        btn_next_load.clicked.connect(self.load_next_prompt_file)
        next_tools_row.addWidget(btn_next_load)

        btn_next_steps = QtWidgets.QPushButton("✨ Auto-add group")
        btn_next_steps.setObjectName("small_btn")
        btn_next_steps.setToolTip("Pick a saved step group; stages Step 1 then appends that group’s steps in order")
        btn_next_steps.setStyleSheet("background-color: #064e3b; color: #6ee7b7; font-size: 10px; padding: 2px 7px; border: 1px solid #047857; border-radius: 4px;")
        btn_next_steps.clicked.connect(self.append_next_steps_25)
        next_tools_row.addWidget(btn_next_steps)

        btn_next_steps_edit = QtWidgets.QPushButton("⚙")
        btn_next_steps_edit.setObjectName("small_btn")
        btn_next_steps_edit.setToolTip("Create/edit named step groups (1–6 steps each)")
        btn_next_steps_edit.setStyleSheet("background-color: #1e1b4b; color: #a5b4fc; font-size: 10px; padding: 2px 6px; border: 1px solid #312e81; border-radius: 4px;")
        btn_next_steps_edit.clicked.connect(self.open_steps_25_template_editor)
        next_tools_row.addWidget(btn_next_steps_edit)

        btn_next_expand = QtWidgets.QPushButton("⛶ Expand")
        btn_next_expand.setObjectName("small_btn")
        btn_next_expand.setToolTip("Open full-screen prompt editor modal")
        btn_next_expand.setStyleSheet("background-color: #1e293b; color: #f1f5f9; font-size: 10px; padding: 2px 7px; border: 1px solid #334155; border-radius: 4px;")
        btn_next_expand.clicked.connect(self.open_next_prompt_editor)
        next_tools_row.addWidget(btn_next_expand)

        next_layout.addLayout(next_tools_row)

        # Commands input for next project
        next_cmd_row = QtWidgets.QHBoxLayout()
        next_cmd_row.setSpacing(8)

        self.next_prompt_input = QTextEdit()
        self.next_prompt_input.setPlaceholderText("Paste one complete prompt, then click Add Prompt. Add more prompts before submitting the project.")
        self.next_prompt_input.setMinimumHeight(65)
        self.next_prompt_input.setMaximumHeight(75)
        self.next_prompt_input.textChanged.connect(self.update_next_prompt_metrics)
        next_cmd_row.addWidget(self.next_prompt_input, stretch=1)

        self.btn_add_next = QtWidgets.QPushButton("+ Add Project #2 to Pipeline")
        self.btn_add_next.setObjectName("primary")
        self.btn_add_next.clicked.connect(lambda: self.add_next_project_tasks())
        self.btn_stage_prompt = QtWidgets.QPushButton("+ Add Prompt")
        self.btn_stage_prompt.setObjectName("primary")
        self.btn_stage_prompt.clicked.connect(self.stage_prompt)
        next_cmd_row.addWidget(self.btn_stage_prompt)

        next_layout.addLayout(next_cmd_row)

        self.next_prompt_metrics_lbl = QtWidgets.QLabel("💡 Tip: Multi-line / 5,000+ word specs preserved as 1 step. Use '---' to separate sequential steps.")
        self.next_prompt_metrics_lbl.setStyleSheet("color: #64748b; font-size: 10px;")
        self.next_prompt_metrics_lbl.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.next_prompt_metrics_lbl.setWordWrap(True)
        next_layout.addWidget(self.next_prompt_metrics_lbl)

        self.draft_list = QtWidgets.QListWidget()
        self.draft_list.setMinimumHeight(85)
        self.draft_list.setMaximumHeight(85)
        self.draft_list.itemDoubleClicked.connect(lambda _: self.edit_draft_prompt())
        next_layout.addWidget(self.draft_list)
        self.draft_controls = QtWidgets.QWidget()
        draft_controls = QtWidgets.QHBoxLayout(self.draft_controls)
        draft_controls.setContentsMargins(0, 0, 0, 0)
        for label, callback in [("↑ Move up", lambda: self.move_draft_prompt(-1)),
                                ("↓ Move down", lambda: self.move_draft_prompt(1)),
                                ("Edit", self.edit_draft_prompt), ("Remove", self.remove_draft_prompt)]:
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            draft_controls.addWidget(button)
        next_layout.addWidget(self.draft_controls)
        self.draft_list.hide()
        self.draft_controls.hide()

        # GitHub Automation Row for next project
        gh_row = QtWidgets.QHBoxLayout()
        gh_row.setSpacing(8)

        self.gh_check = QtWidgets.QCheckBox("Auto-Create GitHub Repo (README included)")
        gh_row.addWidget(self.gh_check)

        self.gh_name_input = QLineEdit()
        self.gh_name_input.setPlaceholderText("Repo Name")
        self.gh_name_input.setMaximumWidth(140)
        gh_row.addWidget(self.gh_name_input)

        self.gh_desc_input = QLineEdit()
        self.gh_desc_input.setPlaceholderText("Description")
        gh_row.addWidget(self.gh_desc_input, stretch=1)

        next_layout.addLayout(gh_row)
        next_layout.addWidget(self.btn_add_next)
        self.update_next_prompt_metrics()
        form_layout.addWidget(next_section)

        # Quick Batch 20-Projects Bar
        btn_batch_inline = QtWidgets.QPushButton("⚡ Batch 20-Projects Generator (1st Prompt + Steps 2-5 Shared)")
        btn_batch_inline.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1e1b4b, stop:1 #312e81); "
            "color: #c7d2fe; font-weight: 700; padding: 7px 12px; border: 1px solid #4338ca; border-radius: 7px;"
        )
        btn_batch_inline.setToolTip("Open generator to create 20 projects with 5 prompts each in 1 click")
        btn_batch_inline.clicked.connect(self.open_batch_dialog)
        form_layout.addWidget(btn_batch_inline)

        left_layout.addWidget(form_card)
        left_layout.addStretch()

        left_scroll = QtWidgets.QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left_widget)
        content_splitter.addWidget(left_scroll)

        # ---------------------------------------------------------------------
        # RIGHT PANEL: KPI Metrics, Visual Projects Queue & Execution Log
        # ---------------------------------------------------------------------
        right_widget = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(8)

        # KPI Metrics Overview Card Bar
        self.stats_bar = QtWidgets.QFrame()
        self.stats_bar.setObjectName("stats_bar")
        stats_layout = QtWidgets.QHBoxLayout(self.stats_bar)
        stats_layout.setContentsMargins(12, 6, 12, 6)
        stats_layout.setSpacing(8)

        def make_kpi(label_text, default_val="0"):
            frame = QtWidgets.QFrame()
            frame.setObjectName("kpi_card")
            vl = QtWidgets.QVBoxLayout(frame)
            vl.setContentsMargins(8, 5, 8, 5)
            vl.setSpacing(1)
            num = QtWidgets.QLabel(default_val)
            num.setObjectName("kpi_num")
            lbl = QtWidgets.QLabel(label_text)
            lbl.setObjectName("kpi_label")
            vl.addWidget(num)
            vl.addWidget(lbl)
            return frame, num

        self.card_projects, self.kpi_projects_val = make_kpi("PROJECTS", "0")
        self.card_tasks, self.kpi_tasks_val = make_kpi("TOTAL STEPS", "0")
        self.card_completed, self.kpi_completed_val = make_kpi("COMPLETED", "0 (0%)")
        self.card_status, self.kpi_status_val = make_kpi("PIPELINE STATUS", "IDLE")
        self.card_success, self.kpi_success_val = make_kpi("SUCCESS RATE", "—")
        self.card_avg, self.kpi_avg_val = make_kpi("AVG STEP", "—")

        stats_layout.addWidget(self.card_projects)
        stats_layout.addWidget(self.card_tasks)
        stats_layout.addWidget(self.card_completed)
        stats_layout.addWidget(self.card_success)
        stats_layout.addWidget(self.card_avg)
        stats_layout.addWidget(self.card_status)
        right_layout.addWidget(self.stats_bar)

        # Queue Header Row
        queue_header_row = QtWidgets.QHBoxLayout()
        list_header = QtWidgets.QLabel("Project queue")
        list_header.setStyleSheet("font-weight: 700; color: #94a3b8; font-size: 13px;")
        queue_header_row.addWidget(list_header)

        self.queue_badge_lbl = QtWidgets.QLabel("0 Projects • 0 Steps")
        self.queue_badge_lbl.setStyleSheet(
            "background-color: #0e1e38; color: #38bdf8; font-size: 11px; font-weight: 700; "
            "padding: 3px 8px; border-radius: 4px; border: 1px solid #1e3a68;"
        )
        queue_header_row.addWidget(self.queue_badge_lbl)
        queue_header_row.addStretch()

        btn_clear_all_projects = QtWidgets.QPushButton("🗑 Clear All Projects")
        btn_clear_all_projects.setObjectName("danger_small")
        btn_clear_all_projects.setStyleSheet(
            "background-color: #450a0a; color: #fca5a5; font-size: 11px; font-weight: 700; "
            "padding: 3px 10px; border: 1px solid #7f1d1d; border-radius: 5px;"
        )
        btn_clear_all_projects.setToolTip("Delete all projects and commands from the queue")
        btn_clear_all_projects.clicked.connect(lambda: self.clear_queue())
        queue_header_row.addWidget(btn_clear_all_projects)

        right_layout.addLayout(queue_header_row)

        # Scroll Area for Project Pipeline Cards
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(240)
        self.scroll_content = QtWidgets.QWidget()
        self.task_list_layout = QtWidgets.QVBoxLayout(self.scroll_content)
        self.task_list_layout.setContentsMargins(0, 0, 0, 0)
        self.task_list_layout.setSpacing(10)
        self.task_list_layout.addStretch()
        self.scroll.setWidget(self.scroll_content)
        right_layout.addWidget(self.scroll, stretch=1)

        pagination = QtWidgets.QHBoxLayout()
        self.prev_project_btn = QtWidgets.QPushButton("← Previous project")
        self.next_project_btn = QtWidgets.QPushButton("Next project →")
        self.project_page_label = QtWidgets.QLabel()
        self.prev_project_btn.clicked.connect(lambda: self.change_project_page(-1))
        self.next_project_btn.clicked.connect(lambda: self.change_project_page(1))
        pagination.addWidget(self.prev_project_btn)
        pagination.addWidget(self.project_page_label, 1, Qt.AlignCenter)
        pagination.addWidget(self.next_project_btn)
        right_layout.addLayout(pagination)
        log_controls = QtWidgets.QHBoxLayout()
        log_controls.addWidget(QtWidgets.QLabel("Activity log"))
        log_controls.addStretch()
        clear_logs_btn = QtWidgets.QPushButton("Clear Logs")
        clear_logs_btn.clicked.connect(self.clear_logs)
        log_controls.addWidget(clear_logs_btn)
        clear_alerts_btn = QtWidgets.QPushButton("Clear Alerts")
        clear_alerts_btn.setToolTip("Dismiss stacked DevOS AI Pipeline desktop notifications")
        clear_alerts_btn.clicked.connect(self.clear_alerts)
        log_controls.addWidget(clear_alerts_btn)
        right_layout.addLayout(log_controls)

        # Live Execution Output Box
        self.log_box = QtWidgets.QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(80)
        self.log_box.setMaximumHeight(100)
        self.log_box.document().setMaximumBlockCount(500)
        self.log_box.setPlaceholderText("Pipeline activity and agent dispatch log will stream here...")
        self.log_box.setStyleSheet("background-color: #050811; border: 1px solid #1a2436; color: #94a3b8; font-family: monospace; font-size: 11px;")
        right_layout.addWidget(self.log_box)
        for line in self.pipeline.recent_events():
            self.append_pipeline_log(line)

        left_widget.setMinimumWidth(320)
        right_widget.setMinimumWidth(280)
        content_splitter.addWidget(right_widget)
        content_splitter.setCollapsible(0, False)
        content_splitter.setCollapsible(1, False)
        w_left = int(self.width() * 0.52)
        w_right = max(280, self.width() - w_left)
        content_splitter.setSizes([w_left, w_right])
        main_layout.addWidget(content_splitter, stretch=1)

        self.agent_combo.currentIndexChanged.connect(self.on_agent_changed)
        self.on_agent_changed(self.agent_combo.currentIndex())
        self.refresh_queue()

    # Compatibility aliases
    @property
    def prompt_input(self):
        return self.next_prompt_input

    @property
    def project_title_input(self):
        return self.next_title_input

    @property
    def project_slug_input(self):
        return self.next_slug_input

    def add_task(self):
        self.add_next_project_tasks()

    def on_agent_changed(self, index: int = -1):
        if index < 0 and hasattr(self, "agent_combo"):
            index = self.agent_combo.currentIndex()
        if not hasattr(self, "agent_combo") or index < 0:
            return

        agent_key = self.agent_combo.itemData(index)
        if agent_key == "multi":
            if hasattr(self, "agent_status_lbl"):
                self.agent_status_lbl.setText("Multi-Agent: Collaborative Routing")
                self.agent_status_lbl.setStyleSheet(
                    "background-color: #3b0764; color: #d8b4fe; border: 1px solid #9333ea; padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 700;"
                )
            return

        known = discover_agents()
        agent_info = known.get(agent_key, {})
        is_running = agent_info.get("running", False)
        pid = agent_info.get("pid")

        if hasattr(self, "agent_status_lbl"):
            if is_running:
                self.agent_status_lbl.setText(f"Live: Running (PID {pid})")
                self.agent_status_lbl.setStyleSheet(
                    "background-color: #022c22; color: #34d399; border: 1px solid #059669; padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 700;"
                )
            elif agent_info.get("available"):
                ready_txt = "Ready" if agent_key == "local" else "Installed"
                self.agent_status_lbl.setText(f"Status: {ready_txt}")
                self.agent_status_lbl.setStyleSheet(
                    "background-color: #1e293b; color: #94a3b8; border: 1px solid #334155; padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 600;"
                )
            else:
                self.agent_status_lbl.setText("Status: Not Installed")
                self.agent_status_lbl.setStyleSheet(
                    "background-color: #2a1215; color: #f87171; border: 1px solid #7f1d1d; padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 600;"
                )

        self.refresh_current_project(agent=agent_key)

    def refresh_current_project(self, agent: Optional[str] = None, manual: bool = False):
        if agent is None and hasattr(self, "agent_combo"):
            agent = self.agent_combo.currentData()

        cur_slug, cur_title, cur_path = detect_current_project(self.pipeline.get_base_dir(), agent=agent)
        if not cur_slug:
            cur_slug = "dev-os"
            cur_title = "Dev Os"
            cur_path = str(Path(self.pipeline.get_base_dir()) / cur_slug)

        prev_slug = getattr(self, "current_slug", None)
        self.current_slug = cur_slug
        self.current_title = cur_title or cur_slug.replace("-", " ").title()
        self.current_path = cur_path or str(Path(self.pipeline.get_base_dir()) / self.current_slug)

        if hasattr(self, "cur_proj_title_lbl"):
            self.cur_proj_title_lbl.setText(f"{self.current_title} ({self.current_slug})")
            self.cur_proj_path_lbl.setText(f"Path: {self.current_path}")
            self.current_prompt_input.setPlaceholderText(
                f"Enter command(s) for Current Project '{self.current_slug}'... (Optional: leave empty to proceed to next project)"
            )

        if hasattr(self, "log_box") and (manual or (prev_slug and prev_slug != cur_slug)):
            known = discover_agents()
            ag_name = known.get(agent, {}).get("name", (agent or "Agent").title())
            self.log_box.append(
                f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Detected active project for {ag_name}: '{self.current_title}' [{self.current_slug}] ({self.current_path})"
            )

    def reset_current_project(self, *args, **kwargs):
        """Reset Section 2 active project back to default dev-os workspace."""
        base_dir = self.pipeline.get_base_dir()
        self.current_slug = "dev-os"
        self.current_title = "Dev Os"
        self.current_path = str(Path(base_dir) / self.current_slug)

        if hasattr(self, "cur_proj_title_lbl"):
            self.cur_proj_title_lbl.setText(f"{self.current_title} ({self.current_slug})")
            self.cur_proj_path_lbl.setText(f"Path: {self.current_path}")
            self.current_prompt_input.setPlaceholderText(
                f"Enter command(s) for Current Project '{self.current_slug}'... (Optional: leave empty to proceed to next project)"
            )
            self.current_prompt_input.clear()

        if hasattr(self, "show_toast"):
            self.show_toast("Active project reset to 'dev-os'.")
        if hasattr(self, "log_box"):
            self.log_box.append(
                f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Active project manually reset to dev-os ({self.current_path})"
            )

    def delete_current_project_folder(self, *args, **kwargs):
        """Delete current project folder from disk after user confirmation."""
        slug = getattr(self, "current_slug", "dev-os")
        path_str = getattr(self, "current_path", "")
        if not path_str or slug in ("dev-os", ""):
            QtWidgets.QMessageBox.information(
                self,
                "Cannot Delete Default Project",
                f"Project '{slug}' is the root workspace default and cannot be deleted from here.",
            )
            return

        folder = Path(path_str)
        if not folder.exists():
            QtWidgets.QMessageBox.information(
                self,
                "Folder Does Not Exist",
                f"The folder '{folder}' does not exist on disk.\nResetting active project back to dev-os.",
            )
            self.reset_current_project()
            return

        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm Delete Folder",
            f"Are you sure you want to permanently delete project '{slug}' from disk?\n\nPath:\n{folder}\n\nThis cannot be undone!",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            try:
                shutil.rmtree(folder)
                if hasattr(self, "show_toast"):
                    self.show_toast(f"Deleted folder '{slug}'.", is_error=False)
                if hasattr(self, "log_box"):
                    self.log_box.append(
                        f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Deleted project folder: {folder}"
                    )
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Deletion Failed", f"Could not delete '{folder}':\n{e}")
                return
            self.reset_current_project()

    def on_next_title_changed(self, text):
        self.next_slug_input.setText(to_slug(text))
        self.update_next_target_preview()

    def update_next_target_preview(self):
        slug = self.next_slug_input.text().strip()
        base = self.pipeline.get_base_dir()
        if slug:
            target_path = Path(base) / slug
            exists_tag = " [EXISTS]" if target_path.exists() else " [WILL AUTO-CREATE LOCAL FOLDER ON EXECUTION]"
            self.next_target_preview_lbl.setText(f"Target Folder: {target_path}{exists_tag}")
        else:
            self.next_target_preview_lbl.setText("")

    def on_base_dir_changed(self):
        txt = self.base_dir_input.text().strip()
        if txt and Path(txt).is_dir():
            configured = self.pipeline.set_base_dir(txt)
            self.log_box.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Projects base directory set to: {configured}")
            self.refresh_current_project()
            self.update_next_target_preview()
            self.refresh_queue()

    def browse_base_dir(self):
        cur = self.pipeline.get_base_dir()
        selected = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Projects Base Directory", cur)
        if selected:
            configured = self.pipeline.set_base_dir(selected)
            self.base_dir_input.setText(configured)
            self.log_box.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Projects base directory set to: {configured}")
            self.refresh_current_project()
            self.update_next_target_preview()
            self.refresh_queue()

    def fill_seo_prompt(self):
        title = self.next_title_input.text().strip() or self.current_title or "this project"
        prompt = (
            f"Based on {title}, give me the best github repo name with 400 character description "
            "for reaching organically to rank or any related search our repo will be searchable rank in google or github"
        )
        self.next_prompt_input.setText(prompt)
        self.gh_check.setChecked(True)
        self.log_box.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Loaded SEO Ranking Prompt Preset into input.")

    def update_next_prompt_metrics(self):
        words = len(self.next_prompt_input.toPlainText().split())
        self.next_prompt_metrics_lbl.setText(
            f"{len(self.draft_prompts)} prompts staged • {words:,} words in editor • Add Prompt keeps the full text as one step.")

    def refresh_draft_prompts(self, selected=-1):
        has_prompts = bool(self.draft_prompts)
        self.draft_list.setVisible(has_prompts)
        self.draft_controls.setVisible(has_prompts)
        self.draft_list.clear()
        for index, prompt in enumerate(self.draft_prompts):
            words = prompt.split()
            preview = " ".join(words[:5]) + (" …" if len(words) > 5 else "")
            self.draft_list.addItem(f"{index + 1}. {preview}  ({len(words):,} words)")
        self.draft_list.setCurrentRow(selected)
        self.update_next_prompt_metrics()

    def stage_prompt(self):
        prompt = self.next_prompt_input.toPlainText().strip()
        if not prompt:
            self.next_prompt_input.setFocus()
            return
        self.draft_prompts.append(prompt)
        self.next_prompt_input.clear()
        self.refresh_draft_prompts(len(self.draft_prompts) - 1)

    def move_draft_prompt(self, direction):
        index = self.draft_list.currentRow()
        target = index + direction
        if 0 <= index < len(self.draft_prompts) and 0 <= target < len(self.draft_prompts):
            self.draft_prompts[index], self.draft_prompts[target] = self.draft_prompts[target], self.draft_prompts[index]
            self.refresh_draft_prompts(target)

    def remove_draft_prompt(self):
        index = self.draft_list.currentRow()
        if 0 <= index < len(self.draft_prompts):
            self.draft_prompts.pop(index)
            self.refresh_draft_prompts(min(index, len(self.draft_prompts) - 1))

    def edit_draft_prompt(self):
        index = self.draft_list.currentRow()
        if not 0 <= index < len(self.draft_prompts):
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(f"Edit prompt {index + 1}")
        dialog.resize(760, 540)
        layout = QtWidgets.QVBoxLayout(dialog)
        editor = QtWidgets.QPlainTextEdit(self.draft_prompts[index])
        layout.addWidget(editor)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec_() == QtWidgets.QDialog.Accepted and editor.toPlainText().strip():
            self.draft_prompts[index] = editor.toPlainText().strip()
            self.refresh_draft_prompts(index)

    def change_project_page(self, direction):
        self.project_page += direction
        self.refresh_queue()
        self.scroll.verticalScrollBar().setValue(0)

    @queue_error_to_log
    def clear_logs(self):
        self.pipeline.clear_events()
        self.log_box.clear()

    def clear_alerts(self):
        # Runs the Plasma max-id close loop (old stall toasts used ids ~1000+).
        clear_pipeline_notifications()
        self.toast_banner.setText("All desktop alerts cleared.")
        self.toast_banner.show()
        QtCore.QTimer.singleShot(2500, self.toast_banner.hide)

    def update_cur_prompt_metrics(self):
        text = self.current_prompt_input.toPlainText().strip()
        words = len(text.split()) if text else 0
        chars = len(text)
        steps = split_prompts(text)
        count = len(steps)
        if not text:
            self.cur_prompt_metrics_lbl.setText("💡 Tip: Enter multi-line prompts freely. Separate steps with '---'.")
        elif count == 1:
            self.cur_prompt_metrics_lbl.setText(f"📝 1 Step ({words:,} words, {chars:,} chars)")
        else:
            self.cur_prompt_metrics_lbl.setText(f"📝 {count} Steps ({words:,} words)")

    def insert_next_step_separator(self):
        cursor = self.next_prompt_input.textCursor()
        cursor.insertText("\n\n---\n\n")
        self.next_prompt_input.setFocus()

    def append_next_steps_25(self):
        anchor = self.sender() if isinstance(self.sender(), QtWidgets.QWidget) else self
        group = choose_step_group(anchor)
        if not group:
            if not list_step_groups():
                self.open_steps_25_template_editor()
                if hasattr(self, "toast_banner"):
                    self.toast_banner.setText("Save a step group, then click Auto-add again.")
                    self.toast_banner.setStyleSheet(
                        "background-color: #451a03; color: #fcd34d; font-weight: 700; font-size: 12px; "
                        "padding: 8px 14px; border-radius: 8px; border: 1px solid #d97706;"
                    )
                    self.toast_banner.show()
                    QtCore.QTimer.singleShot(3500, self.toast_banner.hide)
            return
        steps = list(group.get("steps") or [])
        if not steps:
            return
        # Keep Step 1 from the editor as its own draft item, then add group steps serially.
        if self.next_prompt_input.toPlainText().strip():
            self.stage_prompt()
        self.draft_prompts.extend(steps)
        self.refresh_draft_prompts(len(self.draft_prompts) - 1)
        if hasattr(self, "toast_banner"):
            self.toast_banner.setText(
                f"✔ Added group “{group.get('name', 'Group')}”: {len(steps)} step(s) in order."
            )
            self.toast_banner.setStyleSheet(
                "background-color: #064e3b; color: #34d399; font-weight: 700; font-size: 13px; "
                "padding: 8px 16px; border-radius: 8px; border: 1px solid #059669;"
            )
            self.toast_banner.show()
            QtCore.QTimer.singleShot(3500, self.toast_banner.hide)

    def open_next_prompt_editor(self):
        title = self.next_title_input.text().strip() or "Next Project"
        initial = self.next_prompt_input.toPlainText()
        dlg = PromptEditorDialog(initial_text=initial, project_name=title, parent=self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.next_prompt_input.setPlainText(dlg.get_text())

    def load_next_prompt_file(self):
        selected, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Specification / Prompt File", str(Path.home()), "Markdown / Text Files (*.md *.txt *.prompt);;All Files (*)"
        )
        if selected:
            try:
                content = Path(selected).read_text(encoding="utf-8", errors="ignore")
                self.next_prompt_input.setPlainText(content)
                if hasattr(self, "show_toast"):
                    self.show_toast(f"Loaded {len(content.split()):,} words from {Path(selected).name}")
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "File Load Error", f"Could not load file:\n{e}")

    def insert_cur_step_separator(self):
        cursor = self.current_prompt_input.textCursor()
        cursor.insertText("\n\n---\n\n")
        self.current_prompt_input.setFocus()

    def append_cur_steps_25(self):
        anchor = self.sender() if isinstance(self.sender(), QtWidgets.QWidget) else self
        group = choose_step_group(anchor)
        if not group:
            if not list_step_groups():
                self.open_steps_25_template_editor()
                if hasattr(self, "toast_banner"):
                    self.toast_banner.setText("Save a step group, then click Auto-add again.")
                    self.toast_banner.setStyleSheet(
                        "background-color: #451a03; color: #fcd34d; font-weight: 700; font-size: 12px; "
                        "padding: 8px 14px; border-radius: 8px; border: 1px solid #d97706;"
                    )
                    self.toast_banner.show()
                    QtCore.QTimer.singleShot(3500, self.toast_banner.hide)
            return
        steps = list(group.get("steps") or [])
        if not steps:
            return
        current = self.current_prompt_input.toPlainText().rstrip()
        append_txt = format_step_pack_for_editor(steps)
        self.current_prompt_input.setPlainText(current + append_txt if current else append_txt.lstrip())
        if hasattr(self, "toast_banner"):
            self.toast_banner.setText(
                f"✔ Appended “{group.get('name', 'Group')}” ({len(steps)} steps). "
                "Queue to Current runs them serially."
            )
            self.toast_banner.setStyleSheet(
                "background-color: #064e3b; color: #34d399; font-weight: 700; font-size: 13px; "
                "padding: 8px 16px; border-radius: 8px; border: 1px solid #059669;"
            )
            self.toast_banner.show()
            QtCore.QTimer.singleShot(3500, self.toast_banner.hide)

    def open_steps_25_template_editor(self):
        dlg = Steps25TemplateDialog(parent=self)
        dlg.exec_()

    def open_cur_prompt_editor(self):
        title = getattr(self, "current_title", "Current Project")
        initial = self.current_prompt_input.toPlainText()
        dlg = PromptEditorDialog(initial_text=initial, project_name=title, parent=self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.current_prompt_input.setPlainText(dlg.get_text())

    def load_cur_prompt_file(self):
        selected, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Specification / Prompt File", str(Path.home()), "Markdown / Text Files (*.md *.txt *.prompt);;All Files (*)"
        )
        if selected:
            try:
                content = Path(selected).read_text(encoding="utf-8", errors="ignore")
                self.current_prompt_input.setPlainText(content)
                if hasattr(self, "show_toast"):
                    self.show_toast(f"Loaded {len(content.split()):,} words from {Path(selected).name}")
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "File Load Error", f"Could not load file:\n{e}")

    def navigate_next_prompt_next(self, *args, **kwargs):
        """Navigate cursor forward to the next '---' command step."""
        text = self.next_prompt_input.toPlainText()
        cursor = self.next_prompt_input.textCursor()
        pos = cursor.position()
        match = re.search(r'(?:\r?\n|^)\s*(?:-{3,}|={3,}|###\s*Step\s*\d+|\[Step\s*\d+\])\s*(?:\r?\n|$)', text[pos:])
        if match:
            new_pos = pos + match.end()
            cursor.setPosition(new_pos)
            self.next_prompt_input.setTextCursor(cursor)
            self.next_prompt_input.ensureCursorVisible()

    def navigate_next_prompt_prev(self, *args, **kwargs):
        """Navigate cursor backward to the upper (previous) '---' command step."""
        text = self.next_prompt_input.toPlainText()
        cursor = self.next_prompt_input.textCursor()
        pos = max(0, cursor.position() - 4)
        matches = list(re.finditer(r'(?:\r?\n|^)\s*(?:-{3,}|={3,}|###\s*Step\s*\d+|\[Step\s*\d+\])\s*(?:\r?\n|$)', text[:pos]))
        if matches:
            target = matches[-1]
            cursor.setPosition(target.end())
            self.next_prompt_input.setTextCursor(cursor)
            self.next_prompt_input.ensureCursorVisible()
        else:
            cursor.setPosition(0)
            self.next_prompt_input.setTextCursor(cursor)
            self.next_prompt_input.ensureCursorVisible()

    def navigate_cur_prompt_next(self, *args, **kwargs):
        """Navigate cursor forward to the next '---' command step in current project input."""
        text = self.current_prompt_input.toPlainText()
        cursor = self.current_prompt_input.textCursor()
        pos = cursor.position()
        match = re.search(r'(?:\r?\n|^)\s*(?:-{3,}|={3,}|###\s*Step\s*\d+|\[Step\s*\d+\])\s*(?:\r?\n|$)', text[pos:])
        if match:
            new_pos = pos + match.end()
            cursor.setPosition(new_pos)
            self.current_prompt_input.setTextCursor(cursor)
            self.current_prompt_input.ensureCursorVisible()

    def navigate_cur_prompt_prev(self, *args, **kwargs):
        """Navigate cursor backward to the upper (previous) '---' command step in current project input."""
        text = self.current_prompt_input.toPlainText()
        cursor = self.current_prompt_input.textCursor()
        pos = max(0, cursor.position() - 4)
        matches = list(re.finditer(r'(?:\r?\n|^)\s*(?:-{3,}|={3,}|###\s*Step\s*\d+|\[Step\s*\d+\])\s*(?:\r?\n|$)', text[:pos]))
        if matches:
            target = matches[-1]
            cursor.setPosition(target.end())
            self.current_prompt_input.setTextCursor(cursor)
            self.current_prompt_input.ensureCursorVisible()
        else:
            cursor.setPosition(0)
            self.current_prompt_input.setTextCursor(cursor)
            self.current_prompt_input.ensureCursorVisible()

    @queue_error_to_log
    def add_current_project_tasks(self, *args, **kwargs):
        if self.busy():
            self.log_box.append("Wait for the current task to finish before changing the queue.")
            return

        raw_text = self.current_prompt_input.toPlainText().strip()
        if not raw_text:
            self.log_box.append("Type a command above for the current project, or use Section 3 to add a new project.")
            return

        commands = split_prompts(raw_text)
        if not commands:
            return

        os.makedirs(self.current_path, exist_ok=True)
        agent = self.agent_combo.currentData()
        for idx, prompt in enumerate(commands):
            step_agent = agent
            if agent == "multi":
                hybrid_cycle = ["antigravity", "antigravity", "local", "local", "antigravity"]
                step_agent = hybrid_cycle[idx % len(hybrid_cycle)]
            self.pipeline.add(
                prompt=prompt,
                agent=step_agent,
                project=self.current_path,
                project_title=self.current_title,
                project_slug=self.current_slug,
                create_repo=False,
                notify_desktop=False,
            )

        self.current_prompt_input.clear()
        count = len(commands)
        self.log_box.append(
            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Queued {count} step(s) into CURRENT project '{self.current_title}' [{self.current_slug}]"
        )
        notify("Tasks Added", f"[{self.current_slug}] Queued {count} step(s)")
        if hasattr(self, "toast_banner"):
            self.toast_banner.setText(f"✔ Queued {count} step(s) into current project '{self.current_title}'!")
            self.toast_banner.setStyleSheet(
                "background-color: #064e3b; color: #34d399; font-weight: 700; font-size: 13px; "
                "padding: 8px 16px; border-radius: 8px; border: 1px solid #059669;"
            )
            self.toast_banner.show()
            QtCore.QTimer.singleShot(3500, self.toast_banner.hide)
        self.refresh_queue()

    @queue_error_to_log
    def add_next_project_tasks(self, *args, **kwargs):
        if self.busy():
            self.log_box.append("Wait for the current task to finish before changing the queue.")
            return

        raw_text = self.next_prompt_input.toPlainText().strip()
        if not raw_text and not self.draft_prompts:
            if hasattr(self, "toast_banner"):
                self.toast_banner.setText("⚠️ Please enter command(s) or prompt before clicking Add.")
                self.toast_banner.setStyleSheet(
                    "background-color: #451a03; color: #fcd34d; font-weight: 700; font-size: 12px; "
                    "padding: 8px 14px; border-radius: 8px; border: 1px solid #d97706;"
                )
                self.toast_banner.show()
                QtCore.QTimer.singleShot(3500, self.toast_banner.hide)
            self.next_prompt_input.setFocus()
            return

        commands = list(self.draft_prompts) + ([raw_text] if raw_text else [])
        if not commands:
            return

        title = self.next_title_input.text().strip()
        slug = self.next_slug_input.text().strip()

        if not slug:
            if title:
                slug = to_slug(title)
            else:
                slug = to_slug(commands[0][:35])

        if not title:
            title = slug.replace("-", " ").title()

        agent = self.agent_combo.currentData()
        create_repo = self.gh_check.isChecked()
        repo_name = self.gh_name_input.text().strip() or (slug if create_repo else "")
        repo_desc = self.gh_desc_input.text().strip()

        base_dir = self.pipeline.get_base_dir()
        proj_dir = str(Path(base_dir) / slug)
        os.makedirs(proj_dir, exist_ok=True)

        for idx, prompt in enumerate(commands):
            is_repo = create_repo if idx == 0 else False
            step_agent = agent
            if agent == "multi":
                hybrid_cycle = ["antigravity", "antigravity", "local", "local", "antigravity"]
                step_agent = hybrid_cycle[idx % len(hybrid_cycle)]
            self.pipeline.add(
                prompt=prompt,
                agent=step_agent,
                project=proj_dir,
                project_title=title,
                project_slug=slug,
                create_repo=is_repo,
                repo_name=repo_name if is_repo else "",
                repo_desc=repo_desc if is_repo else "",
                notify_desktop=False,
            )

        self.draft_prompts.clear()
        self.refresh_draft_prompts()
        self.next_prompt_input.clear()
        self.next_title_input.clear()
        self.next_slug_input.clear()
        self.next_target_preview_lbl.setText("")
        self.gh_name_input.clear()
        self.gh_desc_input.clear()
        self.gh_check.setChecked(False)

        count = len(commands)
        tag = f" [GH Repo: {repo_name}]" if create_repo else ""
        self.log_box.append(
            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Queued project '{title}' [folder: {slug}] with {count} step(s){tag}"
        )
        notify("Project Added", f"[{slug}] Added '{title}' with {count} step(s)")
        self.next_title_input.setFocus()
        groups = get_grouped_projects(self.pipeline.list())
        self.project_page = next(i for i, group in enumerate(groups) if group["slug"] == slug)
        self.refresh_queue()

        total_projects = len(get_grouped_projects(self.pipeline.list()))
        next_num = total_projects + 1

        if hasattr(self, "toast_banner"):
            self.toast_banner.setText(f"✔ Successfully added Project #{total_projects} '{title}' ({count} step(s))! Ready for Project #{next_num}.")
            self.toast_banner.setStyleSheet(
                "background-color: #064e3b; color: #34d399; font-weight: 700; font-size: 13px; "
                "padding: 10px 16px; border-radius: 8px; border: 1px solid #059669;"
            )
            self.toast_banner.show()
            QtCore.QTimer.singleShot(4000, self.toast_banner.hide)

        # Smooth auto-scroll down to the newly queued project in the list!
        QtCore.QTimer.singleShot(100, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()
        ))

    def open_batch_dialog(self):
        agent = self.agent_combo.currentData() if hasattr(self, "agent_combo") else "multi"
        dlg = BatchProjectDialog(self.pipeline, self, default_agent=agent or "multi")
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.refresh_queue()
            if hasattr(self, "toast_banner"):
                tasks = self.pipeline.list()
                grouped = get_grouped_projects(tasks)
                self.toast_banner.setText(f"✔ Generated batch projects into pipeline ({len(grouped)} projects, {len(tasks)} steps)!")
                self.toast_banner.setStyleSheet(
                    "background-color: #064e3b; color: #34d399; font-weight: 700; font-size: 13px; "
                    "padding: 10px 16px; border-radius: 8px; border: 1px solid #059669;"
                )
                self.toast_banner.show()
                QtCore.QTimer.singleShot(4000, self.toast_banner.hide)
            QtCore.QTimer.singleShot(100, lambda: self.scroll.verticalScrollBar().setValue(
                self.scroll.verticalScrollBar().maximum()
            ))

    def on_premium_mode_changed(self, *_args):
        if not premium or not hasattr(self, "mode_combo"):
            return
        mode = self.mode_combo.currentData()
        if not mode:
            return
        try:
            settings = premium.set_mode(self.pipeline.context, mode)
            self.pipeline._save_context()
            self.log_box.append(
                f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Premium mode → {settings['label']}: {settings['hint']}"
            )
            notify("Pipeline Mode", f"{settings['label']}: {settings['hint'][:80]}")
            self.refresh_queue()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Mode", str(exc))

    def queue_premium_blueprint(self):
        if not premium:
            QtWidgets.QMessageBox.warning(self, "Blueprint", "Premium module unavailable.")
            return
        bp_id = self.blueprint_combo.currentData() if hasattr(self, "blueprint_combo") else ""
        if not bp_id:
            QtWidgets.QMessageBox.information(self, "Blueprint", "Choose a blueprint first.")
            return
        meta = premium.BLUEPRINTS[bp_id]
        title, ok = QtWidgets.QInputDialog.getText(
            self, "Queue Blueprint", "Project title:", text=meta["title"]
        )
        if not ok or not title.strip():
            return
        agent = self.agent_combo.currentData() if hasattr(self, "agent_combo") else "antigravity"
        agent = agent or "antigravity"
        if agent == "multi":
            agent = "antigravity"
        slug = to_slug(title)
        steps = premium.expand_blueprint(bp_id)
        ids = self.pipeline.add_commands(
            steps, agent=agent, project_title=title.strip(), project_slug=slug, notify_desktop=True
        )
        self.log_box.append(
            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Queued blueprint '{bp_id}' "
            f"as '{title.strip()}' ({len(ids)} premium phases) on {agent}"
        )
        if hasattr(self, "toast_banner"):
            self.toast_banner.setText(f"✔ Premium blueprint queued · {len(ids)} phases · {title.strip()}")
            self.toast_banner.setStyleSheet(
                "background-color: #064e3b; color: #34d399; font-weight: 700; font-size: 13px; "
                "padding: 10px 16px; border-radius: 8px; border: 1px solid #059669;"
            )
            self.toast_banner.show()
            QtCore.QTimer.singleShot(4000, self.toast_banner.hide)
        self.refresh_queue()

    def refresh_queue(self):
        tasks = self.pipeline.list()

        # Check rate-limit banner status
        rate_limited_tasks = [t for t in tasks if t["status"] == "RATE_LIMITED"]
        if rate_limited_tasks:
            t = rate_limited_tasks[0]
            retry_str = t.get("retry_at", "")
            if retry_str:
                try:
                    dt = datetime.datetime.fromisoformat(retry_str)
                    now = datetime.datetime.now()
                    rem = int((dt - now).total_seconds())
                    if rem > 0:
                        mins, secs = divmod(rem, 60)
                        self.banner_text.setText(
                            f"<b>Usage Limit Active on {t['agent'].upper()}:</b> Auto-resuming at <b>{dt.strftime('%I:%M %p')}</b> "
                            f"(in {mins}m {secs:02d}s). DevOS timer is active."
                        )
                        self.banner_frame.show()
                    else:
                        self.banner_frame.hide()
                except Exception:
                    self.banner_frame.hide()
            else:
                self.banner_frame.hide()
        else:
            self.banner_frame.hide()

        # Update base directory input if empty
        if not self.base_dir_input.text():
            self.base_dir_input.setText(self.pipeline.get_base_dir())

        # Group tasks by project
        grouped = get_grouped_projects(tasks)

        # Update KPI dashboard numbers
        total_projects = len(grouped)
        total_tasks = len(tasks)
        completed_tasks = sum(1 for t in tasks if t["status"] == "COMPLETED")
        running_tasks = [t for t in tasks if t["status"] == "RUNNING"]

        self.kpi_projects_val.setText(f"{total_projects}")
        self.kpi_tasks_val.setText(f"{total_tasks}")
        if premium and hasattr(self, "kpi_success_val"):
            try:
                sc = premium.scorecard_view(self.pipeline.context, tasks)
                self.kpi_success_val.setText(f"{sc['success_rate']}%")
                avg = sc.get("avg_seconds") or 0
                if avg >= 3600:
                    self.kpi_avg_val.setText(f"{avg/3600:.1f}h")
                elif avg >= 60:
                    self.kpi_avg_val.setText(f"{avg/60:.0f}m")
                else:
                    self.kpi_avg_val.setText(f"{avg:.0f}s" if avg else "—")
                mode_label = sc.get("mode_label") or "Balanced"
                live = sc.get("live") or {}
                self.scorecard_lbl.setText(
                    f"Scorecard · {mode_label} · "
                    f"{sc['completed']} ok / {sc['failed']} fail · "
                    f"live R{live.get('running',0)} S{live.get('submitted',0)} Q{live.get('queued',0)}"
                )
            except Exception:
                pass
        pct = int((completed_tasks / total_tasks * 100)) if total_tasks > 0 else 0
        self.kpi_completed_val.setText(f"{completed_tasks}/{total_tasks} ({pct}%)")

        next_num = total_projects + 1
        if hasattr(self, "next_badge_lbl"):
            self.next_badge_lbl.setText(f"3. ADD NEXT PROJECT (#{next_num})")
        if hasattr(self, "next_title_input") and not self.next_title_input.text():
            self.next_title_input.setPlaceholderText(f"Next Project #{next_num} Title (e.g. 'Build Laravel Auth API')...")
        if hasattr(self, "btn_add_next"):
            self.btn_add_next.setText(f"+ Add Project #{next_num} to Pipeline")
        if hasattr(self, "queue_badge_lbl"):
            self.queue_badge_lbl.setText(f"{total_projects} Project(s) • {total_tasks} Step(s)")

        if self.is_running and running_tasks:
            curr_task = running_tasks[0]
            self.kpi_status_val.setText(f"RUNNING: {len(running_tasks)} / 2")
            self.kpi_status_val.setStyleSheet("color: #38bdf8; font-size: 14px; font-weight: 800;")
        elif rate_limited_tasks:
            self.kpi_status_val.setText("RATE-LIMITED COOLDOWN")
            self.kpi_status_val.setStyleSheet("color: #fbbf24; font-size: 14px; font-weight: 800;")
        elif self.is_running:
            self.kpi_status_val.setText("ACTIVE (WAITING)")
            self.kpi_status_val.setStyleSheet("color: #34d399; font-size: 14px; font-weight: 800;")
        else:
            self.kpi_status_val.setText("IDLE / PAUSED")
            self.kpi_status_val.setStyleSheet("color: #94a3b8; font-size: 14px; font-weight: 800;")

        self.project_page = max(0, min(self.project_page, total_projects - 1))
        self.project_page_label.setText(f"Project {self.project_page + 1 if total_projects else 0} of {total_projects}")
        self.prev_project_btn.setEnabled(self.project_page > 0)
        self.next_project_btn.setEnabled(self.project_page + 1 < total_projects)

        # Check if queue tasks data changed before doing a destructive rebuild
        grouped_sig = [(p.get("slug"), [(t.get("id"), t.get("status"), t.get("retry_at"), t.get("status_message")) for t in p.get("tasks", [])]) for p in grouped]
        grouped_sig = (self.project_page, grouped_sig)
        if grouped_sig == getattr(self, "last_grouped_sig", None):
            return
        self.last_grouped_sig = grouped_sig

        # Rebuild list items
        while self.task_list_layout.count() > 1:
            item = self.task_list_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

        if not grouped:
            empty_lbl = QtWidgets.QLabel("Pipeline queue is empty. Enter commands for current project or add another project above to start.")
            empty_lbl.setStyleSheet("color: #64748b; font-style: italic; padding: 28px;")
            empty_lbl.setAlignment(Qt.AlignCenter)
            self.task_list_layout.insertWidget(0, empty_lbl)
        else:
            for idx, proj_data in enumerate(grouped[self.project_page:self.project_page + 1]):
                card = ProjectPipelineCard(
                    project_data=proj_data,
                    on_failover=self.failover_single_task,
                    on_confirm=self.confirm_completed,
                    on_delete_task=self.delete_single_task,
                    on_delete_project=self.delete_single_project,
                    on_update_task=self.update_single_task_prompt,
                    on_add_prompt=self.add_prompt_to_project,
                    on_move_prompt=self.move_project_prompt,
                    parent=self,
                )
                self.task_list_layout.insertWidget(idx, card)

    @queue_error_to_log
    def add_prompt_to_project(self, slug):
        if self.busy():
            self.append_pipeline_log("Wait for the current queue operation, then add the prompt.")
            return
        project = next((p for p in get_grouped_projects(self.pipeline.list()) if p['slug'] == slug), None)
        if not project:
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(f"Add Prompt — {project['title']}")
        dialog.resize(760, 540)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(QtWidgets.QLabel("One full prompt = one step in this project. Paste the entire specification below."))
        editor = QtWidgets.QPlainTextEdit()
        layout.addWidget(editor)
        agents = QtWidgets.QComboBox()
        for key, info in discover_agents().items():
            agents.addItem(info['name'], key)
        agents.setCurrentIndex(max(0, agents.findData(project['tasks'][-1]['agent'])))
        layout.addWidget(agents)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Save).setText("Add Prompt")
        buttons.button(QtWidgets.QDialogButtonBox.Save).setEnabled(False)
        editor.textChanged.connect(lambda: buttons.button(QtWidgets.QDialogButtonBox.Save).setEnabled(bool(editor.toPlainText().strip())))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        self.editing_queue = True
        try:
            if dialog.exec_() == QtWidgets.QDialog.Accepted:
                self.pipeline.append_project_prompt(slug, editor.toPlainText(), agents.currentData())
                self.last_grouped_sig = None
                self.refresh_queue()
        finally:
            self.editing_queue = False

    @queue_error_to_log
    def move_project_prompt(self, task_id, direction):
        if self.busy():
            return
        self.pipeline.move_project_prompt(task_id, direction)
        self.last_grouped_sig = None
        self.refresh_queue()

    @queue_error_to_log
    def retry_task(self, task_id):
        if self.busy():
            return
        task = next((t for t in self.pipeline.list() if t['id'] == task_id), None)
        if not task or task['status'] != 'FAILED':
            return
        self.pipeline.update_task(task_id, {'status': 'QUEUED', 'retry_at': None, 'output': None,
                                           'status_message': 'Retry queued'})
        self.pipeline.emit_event(f"{task_id}: retry queued by user.")
        self.last_grouped_sig = None
        self.refresh_queue()

    def update_single_task_prompt(self, task_id: str, new_prompt: str):
        try:
            self.pipeline.update_task(task_id, {"prompt": new_prompt})
            if hasattr(self, "show_toast"):
                self.show_toast("✓ Step prompt updated successfully!")
            self.last_grouped_sig = None
            self.refresh_queue()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Update Failed", f"Could not update task prompt:\n{e}")

    def append_pipeline_log(self, line):
        self.log_box.moveCursor(QtGui.QTextCursor.End)
        self.log_box.insertPlainText(line + "\n")
        self.log_box.ensureCursorVisible()

    def toggle_runner(self):
        if not self.is_running:
            self.is_running = True
            self.btn_run.setText("Pause Pipeline")
            self.btn_run.setStyleSheet("background-color: #eab308; color: black; font-weight: 700;")
            self.log_box.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting pipeline runner...")
            self.runner_timer.start(2500)
            self.run_step()
        else:
            self.is_running = False
            self.btn_run.setText("Run Pipeline")
            self.btn_run.setObjectName("primary")
            self.btn_run.setStyleSheet("")
            self.runner_timer.stop()
            self.log_box.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Pipeline paused by user.")
            # Default: stop new work AND abort in-flight local/queued agent steps so
            # Pause actually frees the UI (Close must not hang on artisan serve etc.).
            inflight = [t for t in self.pipeline.list() if t.get("status") in ("RUNNING", "SUBMITTED")]
            if inflight:
                answer = QtWidgets.QMessageBox.question(
                    self,
                    "Stop current work?",
                    "Pause already stops the next task.\n\n"
                    "Also stop work that is still running now?\n\n"
                    "Yes = abort in-flight steps + stop local coding workers "
                    "(recommended — lets you close this window).\n"
                    "No = only pause the queue; current step keeps going.",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.Yes,
                )
                if answer == QtWidgets.QMessageBox.Yes:
                    aborted = self.pipeline.abort_inflight(
                        reason="Aborted by user pause",
                        task_ids=[t["id"] for t in inflight],
                    )
                    self.log_box.append(
                        f"[{datetime.datetime.now().strftime('%H:%M:%S')}] "
                        f"Aborted {aborted} in-flight task(s) and stopped local workers."
                    )
                    # Stop GUI worker thread observing/dispatching
                    if self.worker is not None and self.worker.isRunning():
                        self.worker.requestInterruption()
                        self.worker.wait(1500)
                    self.refresh_queue()

    def busy(self):
        return self.is_running and self.worker is not None and self.worker.isRunning() and not getattr(self.worker, 'observe_only', False)

    def run_step(self):
        if self.busy() or getattr(self, "editing_queue", False):
            return
        if not self.is_running and not any(t.get('status') in ('RUNNING', 'SUBMITTED') for t in self.pipeline.queue):
            return
        self.worker = PipelineWorker(self.pipeline, self, observe_only=not self.is_running)
        self.worker.progress.connect(self.append_pipeline_log)
        self.worker.result.connect(self.step_finished)
        self.worker.start()

    def step_finished(self, error):
        if error:
            self.log_box.append("Pipeline error: " + error)
        self.refresh_queue()
        tasks = self.pipeline.list()
        pending = [t for t in tasks if t["status"] not in ("COMPLETED", "FAILED")]
        running = [t for t in pending if t["status"] in ("RUNNING", "SUBMITTED")]
        failed = [t for t in tasks if t["status"] == "FAILED"]

        if not pending and self.is_running:
            self.toggle_runner()
            failed_count = len(failed)
            self.log_box.append(f"Finished with {failed_count} failed tasks." if failed_count else "All pipeline commands completed successfully!")
        elif failed and not running and self.is_running and all(t["status"] == "FAILED" or any(f.get("project") == t.get("project") for f in failed) for t in pending):
            self.toggle_runner()
            self.log_box.append("Pipeline paused: a task failed. Resolve or remove it before continuing.")
        elif running and self.is_running:
            # Task is actively executing in background agent (e.g. Antigravity)
            # Keep runner timer alive so it auto-detects completion and triggers the next step!
            pass

    @queue_error_to_log
    def confirm_completed(self, task_id):
        if self.busy():
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            "Verify task result",
            "Have you checked in the agent that this task completed successfully? This allows the next task to run."
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return
        for task in self.pipeline.queue:
            if task["id"] == task_id and task["status"] == "SUBMITTED":
                self.pipeline.update_task(task_id, {"status": "COMPLETED", "completion_verified_by_user": True})
                self.refresh_queue()
                break

    @queue_error_to_log
    def delete_single_task(self, task_id: str):
        if self.busy():
            self.log_box.append("Wait for the current task to finish before removing tasks.")
            return
        self.pipeline.delete_task(task_id, force=True)
        self.log_box.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Removed task {task_id}")
        self.refresh_queue()

    @queue_error_to_log
    def delete_single_project(self, project_slug: str):
        if self.busy():
            self.log_box.append("Wait for the current task to finish before removing projects.")
            return
        self.pipeline.delete_project(project_slug, force=True)
        self.log_box.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Removed project '{project_slug}' from pipeline.")
        if hasattr(self, "toast_banner"):
            self.toast_banner.setText(f"🗑 Removed project '{project_slug}' from queue.")
            self.toast_banner.setStyleSheet(
                "background-color: #450a0a; color: #fca5a5; font-weight: 700; font-size: 13px; "
                "padding: 8px 14px; border-radius: 8px; border: 1px solid #dc2626;"
            )
            self.toast_banner.show()
            QtCore.QTimer.singleShot(3500, self.toast_banner.hide)
        self.refresh_queue()

    def closeEvent(self, event):
        dispatch_alive = any(t.is_alive() for t in getattr(self.pipeline, "_dispatch_threads", []))
        worker_busy = self.worker is not None and self.worker.isRunning()
        if self.busy() or dispatch_alive or (worker_busy and self.is_running):
            answer = QtWidgets.QMessageBox.question(
                self,
                "Close Pipeline?",
                "Work is still running in the background.\n\n"
                "Yes = pause, abort in-flight steps, stop local workers, then close.\n"
                "No = keep this window open.",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.Yes,
            )
            if answer != QtWidgets.QMessageBox.Yes:
                self.log_box.append(
                    "Close cancelled — pause first or wait for the current step, "
                    "or choose Yes to force-stop."
                )
                event.ignore()
                return
            self.is_running = False
            self.runner_timer.stop()
            self.btn_run.setText("Run Pipeline")
            self.btn_run.setObjectName("primary")
            self.btn_run.setStyleSheet("")
            try:
                self.pipeline.abort_inflight(reason="Aborted because Pipeline window was closed")
            except Exception as exc:
                self.log_box.append(f"Abort during close: {exc}")
            if self.worker is not None and self.worker.isRunning():
                self.worker.requestInterruption()
                self.worker.wait(1500)
            event.accept()
            return
        # Paused with leftover dispatch threads: still allow close after a soft stop
        if dispatch_alive and not self.is_running:
            try:
                self.pipeline.stop_local_workers()
                self.pipeline.stop_dispatch_threads(timeout=0.8)
            except Exception:
                pass
        event.accept()

    def _failover_target_agent(self, task_agent: str) -> str:
        """Pick a failover agent that does not re-hit an already cooled Google Antigravity quota."""
        slot = self.pipeline.agent_slot(task_agent)
        cooled = self.pipeline._cooled_agent_slots()
        if slot == "antigravity" or "antigravity" in cooled:
            return "local"
        return "antigravity"

    @queue_error_to_log
    def failover_single_task(self, task_id: str):
        if self.busy():
            self.log_box.append("Wait for the current task to finish before changing the queue.")
            return
        for t in self.pipeline.queue:
            if t["id"] == task_id:
                target = self._failover_target_agent(t.get("agent", ""))
                self.pipeline.update_task(task_id, {"agent": target, "status": "QUEUED", "retry_at": None})
                self.log_box.append(
                    f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Task {task_id} switched to {target} "
                    f"(Antigravity/KDE share one Google quota)."
                )
                self.refresh_queue()
                break

    @queue_error_to_log
    def failover_all_rate_limited(self):
        if self.busy():
            self.log_box.append("Wait for the current task to finish before changing the queue.")
            return
        switched = []
        for t in self.pipeline.queue:
            if t["status"] == "RATE_LIMITED":
                target = self._failover_target_agent(t.get("agent", ""))
                self.pipeline.update_task(t["id"], {"agent": target, "status": "QUEUED", "retry_at": None})
                switched.append(f"{t['id']}→{target}")
        self.log_box.append(
            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Rate-limited tasks switched: "
            + (", ".join(switched) if switched else "none")
            + ". Antigravity and Antigravity KDE share one Google account limit."
        )
        self.refresh_queue()

    @queue_error_to_log
    def import_specs_folder(self):
        if self.busy():
            self.log_box.append("Wait for the current task to finish before importing projects.")
            return

        default_dir = str(Path.home() / "project" / "dev-os" / "specs")
        if not os.path.exists(default_dir):
            default_dir = str(Path.home() / "project" / "dev-os")
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Folder Containing Project Specs (.md files)", default_dir
        )
        if not folder:
            return

        folder_path = Path(folder)
        spec_files = sorted(list(folder_path.glob("*.md")) + list(folder_path.glob("*.txt")))
        if not spec_files:
            QtWidgets.QMessageBox.information(
                self, "No Spec Files Found", f"No .md or .txt specification files found in:\n{folder}"
            )
            return

        agent = self.agent_combo.currentData() or "antigravity"
        base_dir = self.pipeline.get_base_dir()
        count_projects = 0
        count_steps = 0

        # Multi-agent shared workflow for steps 2 to 5
        shared_steps = [
            ("codex", "Step 2: Add comprehensive unit and integration tests with mocks."),
            ("local", "Step 3: Create multi-stage Dockerfile, docker-compose.yml, and CI/CD workflow."),
            ("local", "Step 4: Generate API documentation, OpenAPI/Swagger specs, and README.md."),
            ("antigravity", "Step 5: Run security audit, lint code, and optimize performance bottlenecks."),
        ]

        for sf in spec_files:
            content = sf.read_text(encoding="utf-8", errors="ignore").strip()
            if not content:
                continue
            lines = content.splitlines()
            first_line = lines[0].strip()
            if first_line.startswith("#"):
                title = first_line.lstrip("#").strip()
                prompt1 = "\n".join(lines[1:]).strip() or content
            else:
                title = sf.stem.replace("_", " ").replace("-", " ").title()
                prompt1 = content

            slug = to_slug(title)
            proj_dir = str(Path(base_dir) / slug)
            os.makedirs(proj_dir, exist_ok=True)

            # Step 1: Full application specification
            self.pipeline.add(
                prompt=prompt1,
                agent=agent,
                project=proj_dir,
                project_title=title,
                project_slug=slug,
                create_repo=True,
            )
            count_steps += 1

            # Steps 2-5: Shared multi-agent steps
            for step_agent, step_prompt in shared_steps:
                self.pipeline.add(
                    prompt=step_prompt,
                    agent=step_agent,
                    project=proj_dir,
                    project_title=title,
                    project_slug=slug,
                    create_repo=False,
                )
                count_steps += 1
            count_projects += 1

        self.log_box.append(
            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ⚡ Batch Imported {count_projects} projects ({count_steps} total steps) from '{folder}'"
        )
        self.refresh_queue()

    @queue_error_to_log
    @queue_error_to_log
    def clear_queue(self, *args, **kwargs):
        if self.busy():
            self.log_box.append("Wait for the current task to finish before changing the queue.")
            return
        if self.is_running:
            self.toggle_runner()
        count = len(self.pipeline.list())
        try:
            self.pipeline.clear(force=True)
        except Exception:
            self.pipeline.queue = []
            self.pipeline._save()
        self.project_page = 0
        self.log_box.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Pipeline cleared ({count} tasks removed).")
        if hasattr(self, "toast_banner"):
            self.toast_banner.setText(f"🗑 Cleared all projects from pipeline ({count} tasks removed).")
            self.toast_banner.setStyleSheet(
                "background-color: #450a0a; color: #fca5a5; font-weight: 700; font-size: 13px; "
                "padding: 8px 14px; border-radius: 8px; border: 1px solid #dc2626;"
            )
            self.toast_banner.show()
            QtCore.QTimer.singleShot(3500, self.toast_banner.hide)
        self.refresh_queue()


def main():
    import sys as _dialog_sys
    from pathlib import Path as _DialogPath
    _dialog_sys.path.insert(0, str(_DialogPath(__file__).resolve().parent.parent))
    from devos_dialogs import install as _install_dialog_style
    from app_identity import prepare as prepare_identity
    prepare_identity("devos-ai-pipeline")
    app = QtWidgets.QApplication(sys.argv)
    _install_dialog_style(app)
    app.setDesktopFileName("devos-ai-pipeline")
    from app_identity import apply as apply_identity, show_window
    apply_identity(app, "devos-ai-pipeline")
    app.setApplicationName("devos-ai-pipeline")
    app.setApplicationDisplayName("DevOS AI Command Pipeline")
    icon = get_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    win = PipelineWindow()
    if not icon.isNull():
        win.setWindowIcon(icon)
    show_window(win, "devos-ai-pipeline")
    if "--run" in sys.argv:
        QtCore.QTimer.singleShot(0, win.toggle_runner)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
