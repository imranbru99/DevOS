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
import os
import re
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
    get_grouped_projects,
    detect_current_project,
    list_existing_projects,
)


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
            return method(self, *args, **kwargs)
        except (OSError, RuntimeError, ValueError) as exc:
            self.log_box.append("Queue unchanged: " + str(exc))
    return wrapped


class PipelineWorker(QtCore.QThread):
    result = QtCore.pyqtSignal(str)

    def __init__(self, pipeline, parent):
        super().__init__(parent)
        self.pipeline = pipeline

    def run(self):
        try:
            self.pipeline.execute_next()
            self.result.emit("")
        except Exception as exc:
            self.result.emit(str(exc))


class StepRow(QtWidgets.QFrame):
    def __init__(self, step_idx: int, task: dict, on_failover=None, on_confirm=None, on_delete=None, parent=None):
        super().__init__(parent)
        self.step_idx = step_idx
        self.task = task
        self.on_failover = on_failover
        self.on_confirm = on_confirm
        self.on_delete = on_delete
        self.setObjectName("step_row")
        self.init_ui()

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

        prompt_lbl = QtWidgets.QLabel(self.task.get("prompt", ""))
        prompt_lbl.setWordWrap(True)
        prompt_lbl.setStyleSheet("font-size: 12px; font-weight: 500; color: #f1f5f9;")
        center_box.addWidget(prompt_lbl)

        status = self.task.get("status", "QUEUED")
        status_text = f"○ Queued"
        status_color = "#94a3b8"

        if status == "RUNNING":
            status_text = "⚡ Running: Execution in progress..."
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
            status_text = "✖ Failed"
            status_color = "#f87171"

        status_lbl = QtWidgets.QLabel(status_text)
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

        # Failover action button if rate limited
        if status == "RATE_LIMITED" and self.on_failover:
            btn_failover = QtWidgets.QPushButton("Switch to Antigravity")
            btn_failover.setObjectName("accent_warning")
            btn_failover.setStyleSheet("padding: 4px 8px; font-size: 11px;")
            btn_failover.setToolTip("Skip rate-limit cooldown and execute via Antigravity immediately")
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
    def __init__(self, project_data: dict, on_failover=None, on_confirm=None, on_delete_task=None, on_delete_project=None, parent=None):
        super().__init__(parent)
        self.project_data = project_data
        self.on_failover = on_failover
        self.on_confirm = on_confirm
        self.on_delete_task = on_delete_task
        self.on_delete_project = on_delete_project
        self.setObjectName("project_card")
        self.init_ui()

    def init_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(10)

        # Header Bar
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(10)

        title_vbox = QtWidgets.QVBoxLayout()
        title_vbox.setSpacing(3)

        title_hbox = QtWidgets.QHBoxLayout()
        title_hbox.setSpacing(8)

        tag_badge = QtWidgets.QLabel("PROJECT")
        tag_badge.setObjectName("tag_label")
        title_hbox.addWidget(tag_badge)

        title_lbl = QtWidgets.QLabel(self.project_data.get("title", "Project"))
        title_lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #f8fafc;")
        title_hbox.addWidget(title_lbl)

        slug = self.project_data.get("slug", "project")
        slug_badge = QtWidgets.QLabel(f"slug: {slug}")
        slug_badge.setObjectName("badge_slug")
        title_hbox.addWidget(slug_badge)

        title_hbox.addStretch()
        title_vbox.addLayout(title_hbox)

        # Local Path info
        proj_dir = self.project_data.get("dir", "")
        path_lbl = QtWidgets.QLabel(f"Path: {proj_dir}")
        path_lbl.setObjectName("path_info")
        path_lbl.setToolTip(proj_dir)
        title_vbox.addWidget(path_lbl)

        header.addLayout(title_vbox, stretch=1)

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

        status_pill = QtWidgets.QLabel(status_text)
        status_pill.setStyleSheet(
            f"background-color: {bg_color}; color: {status_color}; font-size: 11px; font-weight: 700; "
            f"padding: 4px 10px; border-radius: 5px; border: 1px solid {status_color}44;"
        )
        header.addWidget(status_pill)

        # Open Folder button
        if proj_dir:
            btn_folder = QtWidgets.QPushButton("Open Folder")
            btn_folder.setObjectName("small_btn")
            btn_folder.setToolTip(f"Open {proj_dir} in file manager")
            btn_folder.clicked.connect(lambda: self.open_local_folder(proj_dir))
            header.addWidget(btn_folder)

        # Open GitHub button if project has github url
        gh_url = self.project_data.get("github_url")
        if gh_url:
            btn_gh = QtWidgets.QPushButton("GitHub")
            btn_gh.setObjectName("small_btn")
            btn_gh.setStyleSheet("background-color: #238636; color: white; font-weight: 600; padding: 4px 10px; border-radius: 5px;")
            btn_gh.clicked.connect(lambda: subprocess.Popen(["xdg-open", gh_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            header.addWidget(btn_gh)

        # Delete project button (only if not currently running)
        if not running_tasks and self.on_delete_project:
            btn_del_proj = QtWidgets.QPushButton("X")
            btn_del_proj.setObjectName("danger_small")
            btn_del_proj.setToolTip(f"Remove project '{slug}' and its commands from queue")
            btn_del_proj.clicked.connect(lambda: self.on_delete_project(slug))
            header.addWidget(btn_del_proj)

        # Toggle Expand/Collapse button
        self.btn_toggle = QtWidgets.QPushButton("▲")
        self.btn_toggle.setObjectName("small_btn")
        self.btn_toggle.setFixedWidth(28)
        self.btn_toggle.setToolTip("Expand or collapse project steps")
        self.btn_toggle.clicked.connect(self.toggle_steps)
        header.addWidget(self.btn_toggle)

        main_layout.addLayout(header)

        # Progress bar (if more than 1 task)
        if total_tasks > 1:
            pbar = QtWidgets.QProgressBar()
            pbar.setMaximum(total_tasks)
            pbar.setValue(completed_tasks)
            pbar.setTextVisible(False)
            main_layout.addWidget(pbar)

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
            )
            steps_vbox.addWidget(row)

        main_layout.addWidget(self.steps_container)

        # Auto-collapse completed projects to keep the view clean
        if completed_tasks == total_tasks and total_tasks > 0:
            self.steps_container.setVisible(False)
            self.btn_toggle.setText("▼")

    def toggle_steps(self):
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
            btn_failover.setToolTip("Skip rate-limit cooldown and execute via Antigravity immediately")
            btn_failover.clicked.connect(lambda: self.on_failover(self.task["id"]))
            layout.addWidget(btn_failover)


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

        step25_lbl = QtWidgets.QLabel("Steps 2–5 Shared Engineering Steps (Applied to ALL projects):")
        step25_lbl.setStyleSheet("font-weight: 700; color: #a78bfa;")
        rl.addWidget(step25_lbl)

        self.step25_text = QtWidgets.QTextEdit()
        self.step25_text.setPlainText(
            "Step 2: Add comprehensive unit and integration tests with 90%+ code coverage.\n"
            "Step 3: Create production multi-stage Dockerfile, docker-compose.yml, and CI/CD workflow.\n"
            "Step 4: Audit code for security vulnerabilities, sanitize inputs, and verify OWASP compliance.\n"
            "Step 5: Generate complete API documentation, endpoint markdown, and production README.md."
        )
        rl.addWidget(self.step25_text)

        # Agent & GitHub options
        opt_row = QtWidgets.QHBoxLayout()
        self.agent_combo = QtWidgets.QComboBox()
        self.agent_combo.addItem("✨ Multi-Agent Hybrid (Antigravity + KDE Studio + Local)", "multi")
        self.agent_combo.addItem("Antigravity AI (Primary CLI)", "antigravity")
        self.agent_combo.addItem("Antigravity Studio (KDE GUI)", "antigravity-kde")
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
        shared_steps = [s.strip() for s in self.step25_text.toPlainText().splitlines() if s.strip()]

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
            )

            # Steps 2-5
            hybrid_cycle = ["antigravity-kde", "local", "local", "antigravity-kde"]
            for idx, shared_prompt in enumerate(shared_steps):
                step_agent = hybrid_cycle[idx % len(hybrid_cycle)] if agent == "multi" else agent
                self.pipeline.add(
                    prompt=shared_prompt,
                    agent=step_agent,
                    project=proj_dir,
                    project_title=title,
                    project_slug=slug,
                    create_repo=False,
                )

        self.accept()


class PipelineWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.pipeline = TaskPipeline()
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
            target_w = min(1260, max(960, screen.width() - 40))
            target_h = min(690, max(540, screen.height() - 50))
            self.resize(target_w, target_h)
            self.move((screen.width() - target_w) // 2, (screen.height() - target_h) // 2)
        except Exception:
            pass
        self.setStyleSheet(STYLE)
        self.is_running = False
        self.init_ui()

        # Timer for refreshing queue and ticking countdowns
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_queue)
        self.timer.start(1000)

        # Worker timer for executing next pipeline task if running
        self.runner_timer = QTimer(self)
        self.runner_timer.timeout.connect(self.run_step)

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
        subtitle = QtWidgets.QLabel("Serial multi-agent execution & auto-scheduling across ChatGPT, Antigravity & Local AI")
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

        btn_clear = QtWidgets.QPushButton("Clear")
        btn_clear.clicked.connect(self.clear_queue)
        header_layout.addWidget(btn_clear)

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
        self.agent_combo.addItem("✨ Multi-Agent Hybrid (Antigravity + KDE Studio + Local)", "multi")
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
        cur_layout.setContentsMargins(12, 9, 12, 9)
        cur_layout.setSpacing(6)

        cur_header = QtWidgets.QHBoxLayout()
        cur_badge = QtWidgets.QLabel("2. CURRENT ACTIVE PROJECT")
        cur_badge.setObjectName("badge_cyan")
        cur_header.addWidget(cur_badge)

        self.cur_proj_title_lbl = QtWidgets.QLabel(f"{self.current_title} ({self.current_slug})")
        self.cur_proj_title_lbl.setStyleSheet("font-weight: 700; color: #f8fafc; font-size: 12px;")
        cur_header.addWidget(self.cur_proj_title_lbl)

        cur_header.addStretch()

        btn_rescan_cur = QtWidgets.QPushButton("Re-Detect")
        btn_rescan_cur.setObjectName("small_btn")
        btn_rescan_cur.setToolTip("Re-scan running agent process and workspace storage for open project")
        btn_rescan_cur.setStyleSheet("background-color: #0f172a; color: #38bdf8; font-size: 10px; padding: 2px 6px; border: 1px solid #1e293b; border-radius: 4px;")
        btn_rescan_cur.clicked.connect(lambda: self.refresh_current_project(manual=True))
        cur_header.addWidget(btn_rescan_cur)

        cur_layout.addLayout(cur_header)

        self.cur_proj_path_lbl = QtWidgets.QLabel(f"Path: {self.current_path}")
        self.cur_proj_path_lbl.setObjectName("path_info")
        cur_layout.addWidget(self.cur_proj_path_lbl)

        # Command input for current project
        cur_cmd_row = QtWidgets.QHBoxLayout()
        cur_cmd_row.setSpacing(8)

        self.current_prompt_input = QTextEdit()
        self.current_prompt_input.setPlaceholderText(
            f"Commands for Current Project '{self.current_slug}'... (Optional: leave empty to proceed to next project)"
        )
        self.current_prompt_input.setMaximumHeight(50)
        cur_cmd_row.addWidget(self.current_prompt_input, stretch=1)

        btn_add_current = QtWidgets.QPushButton("+ Queue to Current")
        btn_add_current.setObjectName("accent_action")
        btn_add_current.clicked.connect(self.add_current_project_tasks)
        cur_cmd_row.addWidget(btn_add_current)

        cur_layout.addLayout(cur_cmd_row)
        form_layout.addWidget(cur_section)

        # 3. ADD ANOTHER PROJECT / NEXT PROJECT (DYNAMIC PROJECT NUMBERING)
        next_section = QtWidgets.QFrame()
        next_section.setObjectName("section_next")
        next_layout = QtWidgets.QVBoxLayout(next_section)
        next_layout.setContentsMargins(12, 10, 12, 10)
        next_layout.setSpacing(7)

        next_header = QtWidgets.QHBoxLayout()
        self.next_badge_lbl = QtWidgets.QLabel("3. ADD NEXT PROJECT (#2)")
        self.next_badge_lbl.setObjectName("badge_indigo")
        next_header.addWidget(self.next_badge_lbl)

        next_desc = QtWidgets.QLabel("Auto-creates local project folder, then executes commands")
        next_desc.setStyleSheet("color: #94a3b8; font-size: 11px;")
        next_header.addWidget(next_desc)

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
        next_layout.addWidget(self.next_target_preview_lbl)

        # Commands input for next project
        next_cmd_row = QtWidgets.QHBoxLayout()
        next_cmd_row.setSpacing(8)

        self.next_prompt_input = QTextEdit()
        self.next_prompt_input.setPlaceholderText("Enter command(s) for this project (enter multiple lines for sequential steps)...")
        self.next_prompt_input.setMaximumHeight(54)
        next_cmd_row.addWidget(self.next_prompt_input, stretch=1)

        self.btn_add_next = QtWidgets.QPushButton("+ Add Project #2 to Pipeline")
        self.btn_add_next.setObjectName("primary")
        self.btn_add_next.clicked.connect(self.add_next_project_tasks)
        next_cmd_row.addWidget(self.btn_add_next)

        next_layout.addLayout(next_cmd_row)

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

        content_splitter.addWidget(left_widget)

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

        stats_layout.addWidget(self.card_projects)
        stats_layout.addWidget(self.card_tasks)
        stats_layout.addWidget(self.card_completed)
        stats_layout.addWidget(self.card_status)
        right_layout.addWidget(self.stats_bar)

        # Queue Header Row
        queue_header_row = QtWidgets.QHBoxLayout()
        list_header = QtWidgets.QLabel("Pipeline Queue (Sequential Multi-Project Order)")
        list_header.setStyleSheet("font-weight: 700; color: #94a3b8; font-size: 13px;")
        queue_header_row.addWidget(list_header)

        self.queue_badge_lbl = QtWidgets.QLabel("0 Projects • 0 Steps")
        self.queue_badge_lbl.setStyleSheet(
            "background-color: #0e1e38; color: #38bdf8; font-size: 11px; font-weight: 700; "
            "padding: 3px 8px; border-radius: 4px; border: 1px solid #1e3a68;"
        )
        queue_header_row.addWidget(self.queue_badge_lbl)
        queue_header_row.addStretch()
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

        # Live Execution Output Box
        self.log_box = QtWidgets.QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(85)
        self.log_box.setPlaceholderText("Pipeline activity and agent dispatch log will stream here...")
        self.log_box.setStyleSheet("background-color: #050811; border: 1px solid #1a2436; color: #94a3b8; font-family: monospace; font-size: 11px;")
        right_layout.addWidget(self.log_box)

        content_splitter.addWidget(right_widget)
        content_splitter.setSizes([500, 680])
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
        if cur_slug:
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

    @queue_error_to_log
    def add_current_project_tasks(self):
        if self.busy():
            self.log_box.append("Wait for the current task to finish before changing the queue.")
            return

        raw_text = self.current_prompt_input.toPlainText().strip()
        if not raw_text:
            self.log_box.append("Type a command above for the current project, or use Section 3 to add a new project.")
            return

        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
        if not lines:
            return

        agent = self.agent_combo.currentData()
        for idx, prompt in enumerate(lines):
            step_agent = agent
            if agent == "multi":
                hybrid_cycle = ["antigravity", "antigravity-kde", "local", "local", "antigravity-kde"]
                step_agent = hybrid_cycle[idx % len(hybrid_cycle)]
            self.pipeline.add(
                prompt=prompt,
                agent=step_agent,
                project=self.current_path,
                project_title=self.current_title,
                project_slug=self.current_slug,
                create_repo=False,
            )

        self.current_prompt_input.clear()
        count = len(lines)
        self.log_box.append(
            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Queued {count} step(s) into CURRENT project '{self.current_title}' [{self.current_slug}]"
        )
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
    def add_next_project_tasks(self):
        if self.busy():
            self.log_box.append("Wait for the current task to finish before changing the queue.")
            return

        raw_text = self.next_prompt_input.toPlainText().strip()
        if not raw_text:
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

        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
        if not lines:
            return

        title = self.next_title_input.text().strip()
        slug = self.next_slug_input.text().strip()

        if not slug:
            if title:
                slug = to_slug(title)
            else:
                slug = to_slug(lines[0][:35])

        if not title:
            title = slug.replace("-", " ").title()

        agent = self.agent_combo.currentData()
        create_repo = self.gh_check.isChecked()
        repo_name = self.gh_name_input.text().strip() or (slug if create_repo else "")
        repo_desc = self.gh_desc_input.text().strip()

        base_dir = self.pipeline.get_base_dir()
        proj_dir = str(Path(base_dir) / slug)

        for idx, prompt in enumerate(lines):
            is_repo = create_repo if idx == 0 else False
            step_agent = agent
            if agent == "multi":
                hybrid_cycle = ["antigravity", "antigravity-kde", "local", "local", "antigravity-kde"]
                step_agent = hybrid_cycle[idx % len(hybrid_cycle)]
            self.pipeline.add(
                prompt=prompt,
                agent=step_agent,
                project=proj_dir,
                project_title=title,
                project_slug=slug,
                create_repo=is_repo,
                repo_name=repo_name,
                repo_desc=repo_desc,
            )

        self.next_prompt_input.clear()
        self.next_title_input.clear()
        self.next_slug_input.clear()
        self.next_target_preview_lbl.setText("")
        self.gh_name_input.clear()
        self.gh_desc_input.clear()
        self.gh_check.setChecked(False)

        count = len(lines)
        tag = f" [GH Repo: {repo_name}]" if create_repo else ""
        self.log_box.append(
            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Queued project '{title}' [folder: {slug}] with {count} step(s){tag}"
        )
        self.next_title_input.setFocus()
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
            self.kpi_status_val.setText(f"RUNNING: {curr_task.get('agent', '').upper()}")
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

        # Rebuild list items
        while self.task_list_layout.count() > 1:
            item = self.task_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not grouped:
            empty_lbl = QtWidgets.QLabel("Pipeline queue is empty. Enter commands for current project or add another project above to start.")
            empty_lbl.setStyleSheet("color: #64748b; font-style: italic; padding: 28px;")
            empty_lbl.setAlignment(Qt.AlignCenter)
            self.task_list_layout.insertWidget(0, empty_lbl)
        else:
            for idx, proj_data in enumerate(grouped):
                card = ProjectPipelineCard(
                    project_data=proj_data,
                    on_failover=self.failover_single_task,
                    on_confirm=self.confirm_completed,
                    on_delete_task=self.delete_single_task,
                    on_delete_project=self.delete_single_project,
                )
                self.task_list_layout.insertWidget(idx, card)

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

    def busy(self):
        return self.worker is not None and self.worker.isRunning()

    def run_step(self):
        if not self.is_running or self.busy():
            return
        self.worker = PipelineWorker(self.pipeline, self)
        self.worker.result.connect(self.step_finished)
        self.worker.start()

    def step_finished(self, error):
        if error:
            self.log_box.append("Pipeline error: " + error)
        self.refresh_queue()
        tasks = self.pipeline.list()
        pending = [t for t in tasks if t["status"] not in ("COMPLETED", "FAILED")]
        blocked = any(t["status"] in ("RUNNING", "SUBMITTED") for t in pending) or (bool(pending) and any(t["status"] == "FAILED" for t in tasks))
        if (not pending or blocked or error) and self.is_running:
            self.toggle_runner()
            if blocked:
                self.log_box.append("Paused: resolve the failed task or verify submitted work before continuing.")
            elif not pending:
                failed = any(t["status"] == "FAILED" for t in tasks)
                self.log_box.append("Finished with failed tasks." if failed else "All pipeline commands completed.")

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
        self.pipeline.delete_task(task_id)
        self.log_box.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Removed task {task_id}")
        self.refresh_queue()

    @queue_error_to_log
    def delete_single_project(self, project_slug: str):
        if self.busy():
            self.log_box.append("Wait for the current task to finish before removing projects.")
            return
        self.pipeline.delete_project(project_slug)
        self.log_box.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Removed project '{project_slug}' from pipeline.")
        self.refresh_queue()

    def closeEvent(self, event):
        if self.busy():
            self.log_box.append("Pause stops the next task; wait for the current command to finish before closing.")
            event.ignore()
        else:
            event.accept()

    @queue_error_to_log
    def failover_single_task(self, task_id: str):
        if self.busy():
            self.log_box.append("Wait for the current task to finish before changing the queue.")
            return
        for t in self.pipeline.queue:
            if t["id"] == task_id:
                self.pipeline.update_task(task_id, {"agent": "antigravity", "status": "QUEUED", "retry_at": None})
                self.log_box.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Task {task_id} switched to Antigravity!")
                self.refresh_queue()
                break

    @queue_error_to_log
    def failover_all_rate_limited(self):
        if self.busy():
            self.log_box.append("Wait for the current task to finish before changing the queue.")
            return
        for t in self.pipeline.queue:
            if t["status"] == "RATE_LIMITED":
                self.pipeline.update_task(t["id"], {"agent": "antigravity", "status": "QUEUED", "retry_at": None})
        self.log_box.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] All rate-limited tasks switched to Antigravity!")
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
    def clear_queue(self):
        if self.busy():
            self.log_box.append("Wait for the current task to finish before changing the queue.")
            return
        self.pipeline.clear()
        self.log_box.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Pipeline cleared.")
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
    from app_identity import apply as apply_identity
    apply_identity(app, "devos-ai-pipeline")
    app.setApplicationName("devos-ai-pipeline")
    app.setApplicationDisplayName("DevOS AI Command Pipeline")
    icon = get_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    win = PipelineWindow()
    if not icon.isNull():
        win.setWindowIcon(icon)
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
