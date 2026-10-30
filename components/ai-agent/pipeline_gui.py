#!/usr/bin/env python3
"""DevOS AI Multi-Agent Task Pipeline & Rate-Limit Scheduler - Visual GUI.

Visual dashboard for managing, queuing, and monitoring sequential AI tasks
organized by project slug across ChatGPT/Codex, Google Antigravity, and DevOS Local AI
with automatic rate-limit detection, base folder selection, and automatic local project creation.
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
from PyQt5.QtGui import QIcon
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
QWidget {
    background-color: #0b0f1a;
    color: #e2e8f0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px;
}
QFrame#card {
    background-color: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 10px;
}
QFrame#project_card {
    background-color: #0d1527;
    border: 1px solid #1e293b;
    border-radius: 10px;
}
QFrame#project_card:hover {
    border-color: #334155;
}
QFrame#step_row {
    background-color: #070c18;
    border: 1px solid #1a2234;
    border-radius: 6px;
}
QFrame#step_row:hover {
    border-color: #243049;
}
QFrame#banner_rate_limit {
    background-color: #2a1b06;
    border: 1px solid #d97706;
    border-radius: 8px;
}
QLabel#title {
    font-size: 20px;
    font-weight: 700;
    color: #f8fafc;
}
QLabel#subtitle {
    color: #94a3b8;
    font-size: 13px;
}
QLabel#badge_agent {
    font-weight: 700;
    font-size: 11px;
    padding: 3px 8px;
    border-radius: 5px;
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
    padding: 2px 7px;
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
    padding: 7px 16px;
    font-weight: 600;
    color: #f8fafc;
}
QPushButton:hover {
    background-color: #334155;
    border-color: #475569;
}
QPushButton#primary {
    background-color: #0284c7;
    border: 1px solid #38bdf8;
    color: #ffffff;
}
QPushButton#primary:hover {
    background-color: #0369a1;
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
    background-color: #450a0a;
    border: 1px solid #991b1b;
    color: #fca5a5;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 700;
    border-radius: 5px;
}
QPushButton#danger_small:hover {
    background-color: #7f1d1d;
    color: #ffffff;
}
QComboBox, QLineEdit, QTextEdit {
    background-color: #0f172a;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 10px;
    color: #f8fafc;
}
QComboBox:focus, QLineEdit:focus, QTextEdit:focus {
    border: 1px solid #38bdf8;
}
QProgressBar {
    background-color: #1e293b;
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #38bdf8;
    border-radius: 3px;
}
QScrollArea {
    border: none;
    background-color: transparent;
}
QScrollBar:vertical {
    border: none;
    background: #0b0f1a;
    width: 8px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #334155;
    min-height: 20px;
    border-radius: 4px;
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
        layout.setContentsMargins(12, 8, 12, 8)
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
        status_text = f"Status: {status}"
        status_color = "#94a3b8"

        if status == "RUNNING":
            status_text = "⚡ RUNNING: In progress..."
            status_color = "#38bdf8"
        elif status == "RATE_LIMITED":
            retry_at = self.task.get("retry_at", "")
            if retry_at:
                try:
                    dt = datetime.datetime.fromisoformat(retry_at)
                    status_text = f"⏸ RATE LIMITED: Cooldown active until {dt.strftime('%I:%M %p')}"
                except Exception:
                    status_text = "⏸ RATE LIMITED"
            status_color = "#fbbf24"
        elif status == "SUBMITTED":
            status_text = "Submitted • verify completion in the agent"
            status_color = "#fbbf24"
        elif status == "COMPLETED":
            status_text = "✓ COMPLETED"
            status_color = "#34d399"
        elif status == "FAILED":
            status_text = "✗ FAILED"
            status_color = "#f87171"

        status_lbl = QtWidgets.QLabel(status_text)
        status_lbl.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {status_color};")
        center_box.addWidget(status_lbl)

        layout.addLayout(center_box, stretch=1)

        # GitHub Repo Link button if repo was created
        github_url = self.task.get("github_url")
        if github_url:
            btn_repo = QtWidgets.QPushButton("🐙 Open GitHub")
            btn_repo.setObjectName("small_btn")
            btn_repo.setToolTip(github_url)
            btn_repo.setStyleSheet("background-color: #238636; color: white; font-weight: 600; padding: 4px 10px; border-radius: 5px;")
            btn_repo.clicked.connect(lambda: subprocess.Popen(["xdg-open", github_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            layout.addWidget(btn_repo)

        if status == "SUBMITTED" and self.on_confirm:
            btn_confirm = QtWidgets.QPushButton("✓ Confirm completed")
            btn_confirm.setObjectName("small_btn")
            btn_confirm.clicked.connect(lambda: self.on_confirm(self.task["id"]))
            layout.addWidget(btn_confirm)

        # Failover action button if rate limited
        if status == "RATE_LIMITED" and self.on_failover:
            btn_failover = QtWidgets.QPushButton("⚡ Switch to Antigravity")
            btn_failover.setObjectName("accent_warning")
            btn_failover.setStyleSheet("padding: 4px 8px; font-size: 11px;")
            btn_failover.setToolTip("Skip rate-limit cooldown and execute via Antigravity immediately")
            btn_failover.clicked.connect(lambda: self.on_failover(self.task["id"]))
            layout.addWidget(btn_failover)

        # Delete step button (if QUEUED or FAILED)
        if status in ("QUEUED", "FAILED") and self.on_delete:
            btn_del = QtWidgets.QPushButton("✕")
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
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)

        # Header Bar
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(10)

        title_vbox = QtWidgets.QVBoxLayout()
        title_vbox.setSpacing(3)

        title_hbox = QtWidgets.QHBoxLayout()
        title_hbox.setSpacing(8)

        icon_lbl = QtWidgets.QLabel("📁")
        icon_lbl.setStyleSheet("font-size: 16px;")
        title_hbox.addWidget(icon_lbl)

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
        path_lbl = QtWidgets.QLabel(f"Local Path: {proj_dir}")
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
            status_text = f"⚡ RUNNING ({curr_idx}/{total_tasks})"
            status_color = "#38bdf8"
            bg_color = "#032b43"
        elif rate_limited_tasks:
            status_text = "⏸ RATE LIMITED"
            status_color = "#fbbf24"
            bg_color = "#2a1b06"
        elif failed_tasks:
            status_text = "✗ FAILED"
            status_color = "#f87171"
            bg_color = "#450a0a"
        elif submitted_tasks:
            status_text = "⏳ SUBMITTED"
            status_color = "#fbbf24"
            bg_color = "#2a1b06"
        elif completed_tasks == total_tasks and total_tasks > 0:
            status_text = f"✓ ALL {total_tasks} COMPLETED"
            status_color = "#34d399"
            bg_color = "#064e3b"
        else:
            status_text = f"⏳ QUEUED ({total_tasks} steps)"
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
            btn_folder = QtWidgets.QPushButton("📂 Open Folder")
            btn_folder.setObjectName("small_btn")
            btn_folder.setToolTip(f"Open {proj_dir} in file manager")
            btn_folder.clicked.connect(lambda: self.open_local_folder(proj_dir))
            header.addWidget(btn_folder)

        # Open GitHub button if project has github url
        gh_url = self.project_data.get("github_url")
        if gh_url:
            btn_gh = QtWidgets.QPushButton("🐙 GitHub")
            btn_gh.setObjectName("small_btn")
            btn_gh.setStyleSheet("background-color: #238636; color: white; font-weight: 600; padding: 4px 10px; border-radius: 5px;")
            btn_gh.clicked.connect(lambda: subprocess.Popen(["xdg-open", gh_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            header.addWidget(btn_gh)

        # Delete project button (only if not currently running)
        if not running_tasks and self.on_delete_project:
            btn_del_proj = QtWidgets.QPushButton("✕")
            btn_del_proj.setObjectName("danger_small")
            btn_del_proj.setToolTip(f"Remove project '{slug}' and its commands from queue")
            btn_del_proj.clicked.connect(lambda: self.on_delete_project(slug))
            header.addWidget(btn_del_proj)

        main_layout.addLayout(header)

        # Progress bar (if more than 1 task)
        if total_tasks > 1:
            pbar = QtWidgets.QProgressBar()
            pbar.setMaximum(total_tasks)
            pbar.setValue(completed_tasks)
            pbar.setTextVisible(False)
            main_layout.addWidget(pbar)

        # Step rows container
        steps_vbox = QtWidgets.QVBoxLayout()
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

        main_layout.addLayout(steps_vbox)

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
            status_text = "⚡ RUNNING: In progress..."
            status_color = "#38bdf8"
        elif status == "RATE_LIMITED":
            retry_at = self.task.get("retry_at", "")
            if retry_at:
                try:
                    dt = datetime.datetime.fromisoformat(retry_at)
                    status_text = f"⏸ RATE LIMITED: Cooldown active until {dt.strftime('%I:%M %p')}"
                except Exception:
                    status_text = "⏸ RATE LIMITED"
            status_color = "#fbbf24"
        elif status == "SUBMITTED":
            status_text = "Submitted • verify completion in the agent"
            status_color = "#fbbf24"
        elif status == "COMPLETED":
            status_text = "✓ COMPLETED"
            status_color = "#34d399"
        elif status == "FAILED":
            status_text = "✗ FAILED"
            status_color = "#f87171"

        status_lbl = QtWidgets.QLabel(status_text)
        status_lbl.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {status_color};")
        center_box.addWidget(status_lbl)

        layout.addLayout(center_box, stretch=1)

        github_url = self.task.get("github_url")
        if github_url:
            btn_repo = QtWidgets.QPushButton("🐙 Open GitHub")
            btn_repo.setToolTip(github_url)
            btn_repo.setStyleSheet("background-color: #238636; color: white; font-weight: 600; padding: 6px 12px; border-radius: 6px;")
            btn_repo.clicked.connect(lambda: subprocess.Popen(["xdg-open", github_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            layout.addWidget(btn_repo)

        if status == "SUBMITTED" and self.on_confirm:
            button = QtWidgets.QPushButton("Confirm completed")
            button.clicked.connect(lambda: self.on_confirm(self.task["id"]))
            layout.addWidget(button)

        if status == "RATE_LIMITED" and self.on_failover:
            btn_failover = QtWidgets.QPushButton("⚡ Switch to Antigravity")
            btn_failover.setObjectName("accent_warning")
            btn_failover.setToolTip("Skip rate-limit cooldown and execute via Antigravity immediately")
            btn_failover.clicked.connect(lambda: self.on_failover(self.task["id"]))
            layout.addWidget(btn_failover)


class PipelineWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.pipeline = TaskPipeline()
        self.worker = None
        self.setWindowTitle("DevOS AI Command Pipeline & Scheduler")
        self.setObjectName("devos-ai-pipeline")
        icon = get_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.resize(920, 780)
        self.setStyleSheet(STYLE)
        self.init_ui()

        # Timer for refreshing queue and ticking countdowns
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_queue)
        self.timer.start(1000)

        # Worker timer for executing next pipeline task if running
        self.is_running = False
        self.runner_timer = QTimer(self)
        self.runner_timer.timeout.connect(self.run_step)

    def init_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(14)

        # Header
        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setSpacing(14)

        icon_lbl = QtWidgets.QLabel()
        app_icon = get_app_icon()
        if not app_icon.isNull():
            icon_lbl.setPixmap(app_icon.pixmap(46, 46))
        header_layout.addWidget(icon_lbl)

        header_vbox = QtWidgets.QVBoxLayout()
        title = QtWidgets.QLabel("DevOS AI Command Pipeline")
        title.setObjectName("title")
        subtitle = QtWidgets.QLabel("Serial multi-agent execution & auto-scheduling across ChatGPT, Antigravity & Local AI")
        subtitle.setObjectName("subtitle")
        header_vbox.addWidget(title)
        header_vbox.addWidget(subtitle)
        header_layout.addLayout(header_vbox, stretch=1)

        # Top Control Buttons
        self.btn_run = QtWidgets.QPushButton("▶ Run Pipeline")
        self.btn_run.setObjectName("primary")
        self.btn_run.clicked.connect(self.toggle_runner)
        header_layout.addWidget(self.btn_run)

        btn_clear = QtWidgets.QPushButton("Clear")
        btn_clear.clicked.connect(self.clear_queue)
        header_layout.addWidget(btn_clear)

        main_layout.addLayout(header_layout)

        # Rate Limit Alert Banner (Dynamic)
        self.banner_frame = QtWidgets.QFrame()
        self.banner_frame.setObjectName("banner_rate_limit")
        banner_box = QtWidgets.QHBoxLayout(self.banner_frame)
        banner_box.setContentsMargins(16, 12, 16, 12)

        self.banner_icon = QtWidgets.QLabel("⏳")
        self.banner_icon.setStyleSheet("font-size: 20px;")
        banner_box.addWidget(self.banner_icon)

        self.banner_text = QtWidgets.QLabel("")
        self.banner_text.setStyleSheet("color: #fef3c7; font-weight: 500;")
        banner_box.addWidget(self.banner_text, stretch=1)

        self.btn_banner_switch = QtWidgets.QPushButton("⚡ Auto-Failover to Antigravity")
        self.btn_banner_switch.setObjectName("accent_warning")
        self.btn_banner_switch.clicked.connect(self.failover_all_rate_limited)
        banner_box.addWidget(self.btn_banner_switch)

        self.banner_frame.hide()
        main_layout.addWidget(self.banner_frame)

        # Base Project Directory Selection Bar
        base_dir_card = QtWidgets.QFrame()
        base_dir_card.setObjectName("card")
        base_dir_layout = QtWidgets.QHBoxLayout(base_dir_card)
        base_dir_layout.setContentsMargins(14, 10, 14, 10)
        base_dir_layout.setSpacing(10)

        base_icon = QtWidgets.QLabel("📁")
        base_icon.setStyleSheet("font-size: 16px;")
        base_dir_layout.addWidget(base_icon)

        base_label = QtWidgets.QLabel("Projects Base Directory:")
        base_label.setStyleSheet("font-weight: 600; color: #94a3b8;")
        base_dir_layout.addWidget(base_label)

        self.base_dir_input = QLineEdit()
        self.base_dir_input.setText(self.pipeline.get_base_dir())
        self.base_dir_input.setPlaceholderText("Select base directory where project folders will be created...")
        self.base_dir_input.editingFinished.connect(self.on_base_dir_changed)
        base_dir_layout.addWidget(self.base_dir_input, stretch=1)

        btn_browse_dir = QtWidgets.QPushButton("📂 Browse...")
        btn_browse_dir.setObjectName("small_btn")
        btn_browse_dir.setToolTip("Select root folder where all project slug folders will be created")
        btn_browse_dir.clicked.connect(self.browse_base_dir)
        base_dir_layout.addWidget(btn_browse_dir)

        main_layout.addWidget(base_dir_card)

        # Add Task Input Form Card
        form_card = QtWidgets.QFrame()
        form_card.setObjectName("card")
        form_layout = QtWidgets.QVBoxLayout(form_card)
        form_layout.setContentsMargins(16, 14, 16, 14)
        form_layout.setSpacing(10)

        # Form Title & Preset
        form_title_row = QtWidgets.QHBoxLayout()
        form_title = QtWidgets.QLabel("Queue Projects & Commands in Pipeline")
        form_title.setStyleSheet("font-weight: 600; font-size: 14px; color: #f8fafc;")
        form_title_row.addWidget(form_title)
        form_title_row.addStretch()

        btn_seo = QtWidgets.QPushButton("⚡ SEO Repo Ranking Preset")
        btn_seo.setToolTip("Auto-fill prompt for best ranking repo name & 400-char SEO description")
        btn_seo.setStyleSheet("background-color: #1e293b; color: #38bdf8; font-size: 11px; padding: 4px 8px; border: 1px solid #334155; border-radius: 6px;")
        btn_seo.clicked.connect(self.fill_seo_prompt)
        form_title_row.addWidget(btn_seo)

        form_layout.addLayout(form_title_row)

        # Project Info Row (Project Selector, Title, Slug)
        project_row = QtWidgets.QHBoxLayout()
        project_row.setSpacing(10)

        self.project_combo = QtWidgets.QComboBox()
        self.project_combo.addItem("+ New Project...", "")
        self.project_combo.currentIndexChanged.connect(self.on_project_combo_changed)
        project_row.addWidget(self.project_combo)

        self.project_title_input = QLineEdit()
        self.project_title_input.setPlaceholderText("Project Title (e.g. 'Build Laravel Authentication API', 'Payment Service')...")
        self.project_title_input.textChanged.connect(self.on_project_title_changed)
        project_row.addWidget(self.project_title_input, stretch=2)

        self.project_slug_input = QLineEdit()
        self.project_slug_input.setPlaceholderText("slug (auto-generated: 'laravel-auth')")
        project_row.addWidget(self.project_slug_input, stretch=1)

        form_layout.addLayout(project_row)

        # Commands & Agent Row
        cmd_row = QtWidgets.QHBoxLayout()
        cmd_row.setSpacing(10)

        self.agent_combo = QtWidgets.QComboBox()
        known = discover_agents()
        for k, v in known.items():
            avail_bullet = "● " if v.get("available") else "○ "
            self.agent_combo.addItem(f"{avail_bullet}{v['name']}", k)
        cmd_row.addWidget(self.agent_combo)

        self.prompt_input = QTextEdit()
        self.prompt_input.setPlaceholderText("Enter command or prompt. (Enter multiple commands on separate lines to queue sequential steps)...")
        self.prompt_input.setMaximumHeight(70)
        cmd_row.addWidget(self.prompt_input, stretch=1)

        btn_add = QtWidgets.QPushButton("+ Queue Commands")
        btn_add.setObjectName("primary")
        btn_add.clicked.connect(self.add_task)
        cmd_row.addWidget(btn_add)

        form_layout.addLayout(cmd_row)

        # GitHub Automation Row
        gh_row = QtWidgets.QHBoxLayout()
        gh_row.setSpacing(10)

        self.gh_check = QtWidgets.QCheckBox("🐙 Auto-Create GitHub Repo & Push Code (README included)")
        self.gh_check.setStyleSheet("color: #38bdf8; font-weight: 500;")
        gh_row.addWidget(self.gh_check)

        self.gh_name_input = QLineEdit()
        self.gh_name_input.setPlaceholderText("Repo Name (defaults to slug)")
        self.gh_name_input.setMaximumWidth(220)
        gh_row.addWidget(self.gh_name_input)

        self.gh_desc_input = QLineEdit()
        self.gh_desc_input.setPlaceholderText("Description (e.g. 'Production auth module')")
        gh_row.addWidget(self.gh_desc_input, stretch=1)

        form_layout.addLayout(gh_row)
        main_layout.addWidget(form_card)

        # Task List Area
        list_header = QtWidgets.QLabel("Pipeline Queue (Sequential Multi-Project Order)")
        list_header.setStyleSheet("font-weight: 600; color: #94a3b8; margin-top: 4px;")
        main_layout.addWidget(list_header)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QtWidgets.QWidget()
        self.task_list_layout = QtWidgets.QVBoxLayout(self.scroll_content)
        self.task_list_layout.setContentsMargins(0, 0, 0, 0)
        self.task_list_layout.setSpacing(12)
        self.task_list_layout.addStretch()
        self.scroll.setWidget(self.scroll_content)
        main_layout.addWidget(self.scroll, stretch=1)

        # Live Execution Output Box
        self.log_box = QtWidgets.QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(105)
        self.log_box.setPlaceholderText("Pipeline activity and agent dispatch log will stream here...")
        self.log_box.setStyleSheet("background-color: #060912; border: 1px solid #1e293b; color: #94a3b8; font-family: monospace; font-size: 11px;")
        main_layout.addWidget(self.log_box)

        self.refresh_queue()

    def on_base_dir_changed(self):
        txt = self.base_dir_input.text().strip()
        if txt and Path(txt).is_dir():
            configured = self.pipeline.set_base_dir(txt)
            self.log_box.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Projects base directory set to: {configured}")
            self.refresh_queue()

    def browse_base_dir(self):
        cur = self.pipeline.get_base_dir()
        selected = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Projects Base Directory", cur)
        if selected:
            configured = self.pipeline.set_base_dir(selected)
            self.base_dir_input.setText(configured)
            self.log_box.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Projects base directory set to: {configured}")
            self.refresh_queue()

    def on_project_title_changed(self, text):
        if self.project_combo.currentIndex() <= 0:
            self.project_slug_input.setText(to_slug(text))

    def on_project_combo_changed(self, index):
        if index <= 0:
            self.project_title_input.clear()
            self.project_slug_input.clear()
        else:
            slug = self.project_combo.itemData(index)
            # Find matching project from pipeline
            tasks = self.pipeline.list()
            matched = [t for t in tasks if t.get("project_slug") == slug]
            if matched:
                title = matched[0].get("project_title") or slug.replace("-", " ").title()
                self.project_title_input.setText(title)
                self.project_slug_input.setText(slug)

    def fill_seo_prompt(self):
        title = self.project_title_input.text().strip() or "this project"
        prompt = (
            f"Based on {title}, give me the best github repo name with 400 character description "
            "for reaching organically to rank or any related search our repo will be searchable rank in google or github"
        )
        self.prompt_input.setText(prompt)
        self.gh_check.setChecked(True)
        self.log_box.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Loaded SEO Ranking Prompt Preset into input.")

    @queue_error_to_log
    def add_task(self):
        if self.busy():
            self.log_box.append("Wait for the current task to finish before changing the queue.")
            return

        raw_text = self.prompt_input.toPlainText().strip()
        if not raw_text:
            return

        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
        if not lines:
            return

        title = self.project_title_input.text().strip()
        slug = self.project_slug_input.text().strip()

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
            self.pipeline.add(
                prompt=prompt,
                agent=agent,
                project=proj_dir,
                project_title=title,
                project_slug=slug,
                create_repo=is_repo,
                repo_name=repo_name,
                repo_desc=repo_desc,
            )

        self.prompt_input.clear()
        self.gh_name_input.clear()
        self.gh_desc_input.clear()
        self.gh_check.setChecked(False)

        count = len(lines)
        tag = f" [🐙 GH Repo: {repo_name}]" if create_repo else ""
        self.log_box.append(
            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Queued {count} step(s) under project '{title}' [📁 {slug}]{tag}"
        )
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

        # Update project combo choices without resetting if user is typing
        current_data = self.project_combo.currentData()
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItem("+ New Project...", "")
        for proj in grouped:
            self.project_combo.addItem(f"📁 {proj['title']} ({proj['slug']})", proj['slug'])
        if current_data:
            idx = self.project_combo.findData(current_data)
            if idx >= 0:
                self.project_combo.setCurrentIndex(idx)
        self.project_combo.blockSignals(False)

        # Rebuild list items
        while self.task_list_layout.count() > 1:
            item = self.task_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not grouped:
            empty_lbl = QtWidgets.QLabel("Pipeline queue is empty. Enter project title and command(s) above to start a sequential workflow.")
            empty_lbl.setStyleSheet("color: #64748b; font-style: italic; padding: 24px;")
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
            self.btn_run.setText("⏸ Pause Pipeline")
            self.btn_run.setStyleSheet("background-color: #eab308; color: black;")
            self.log_box.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting pipeline runner...")
            self.runner_timer.start(2500)
            self.run_step()
        else:
            self.is_running = False
            self.btn_run.setText("▶ Run Pipeline")
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
