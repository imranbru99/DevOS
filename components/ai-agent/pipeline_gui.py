#!/usr/bin/env python3
"""DevOS AI Multi-Agent Task Pipeline & Rate-Limit Scheduler - Visual GUI.

Visual dashboard for managing, queuing, and monitoring sequential AI tasks
across ChatGPT/Codex, Google Antigravity, and DevOS Local AI with automatic
rate-limit detection and countdown timers.
"""

import datetime
import functools
import os
import sys
import time
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, QTimer, QCoreApplication
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QLineEdit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components" / "ai-agent"))
from task_pipeline import TaskPipeline, parse_reset_time, discover_agents, is_agent_working


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


class TaskCard(QtWidgets.QFrame):
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

        # GitHub Repo Link button if repo was created
        github_url = self.task.get("github_url")
        if github_url:
            btn_repo = QtWidgets.QPushButton("🐙 Open GitHub")
            btn_repo.setToolTip(github_url)
            btn_repo.setStyleSheet("background-color: #238636; color: white; font-weight: 600; padding: 6px 12px; border-radius: 6px;")
            btn_repo.clicked.connect(lambda: subprocess.Popen(["xdg-open", github_url]))
            layout.addWidget(btn_repo)

        if status == "SUBMITTED" and self.on_confirm:
            button = QtWidgets.QPushButton("Confirm completed")
            button.clicked.connect(lambda: self.on_confirm(self.task["id"]))
            layout.addWidget(button)

        # Failover action button if rate limited
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
        self.resize(880, 720)
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
        main_layout.setSpacing(16)

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

        # Add Task Input Form Card
        form_card = QtWidgets.QFrame()
        form_card.setObjectName("card")
        form_layout = QtWidgets.QVBoxLayout(form_card)
        form_layout.setContentsMargins(16, 14, 16, 14)
        form_layout.setSpacing(10)

        form_title_row = QtWidgets.QHBoxLayout()
        form_title = QtWidgets.QLabel("Queue a New Command in Chain")
        form_title.setStyleSheet("font-weight: 600; font-size: 14px; color: #f8fafc;")
        form_title_row.addWidget(form_title)
        form_title_row.addStretch()

        btn_seo = QtWidgets.QPushButton("⚡ SEO Repo Ranking Preset")
        btn_seo.setToolTip("Auto-fill prompt for best ranking repo name & 400-char SEO description")
        btn_seo.setStyleSheet("background-color: #1e293b; color: #38bdf8; font-size: 11px; padding: 4px 8px; border: 1px solid #334155; border-radius: 6px;")
        btn_seo.clicked.connect(self.fill_seo_prompt)
        form_title_row.addWidget(btn_seo)

        form_layout.addLayout(form_title_row)

        input_row = QtWidgets.QHBoxLayout()
        input_row.setSpacing(10)

        self.agent_combo = QtWidgets.QComboBox()
        known = discover_agents()
        for k, v in known.items():
            avail_bullet = "● " if v.get("available") else "○ "
            self.agent_combo.addItem(f"{avail_bullet}{v['name']}", k)
        input_row.addWidget(self.agent_combo)

        self.prompt_input = QLineEdit()
        self.prompt_input.setPlaceholderText("Enter command or prompt (e.g. 'Build Laravel authentication API')...")
        self.prompt_input.returnPressed.connect(self.add_task)
        input_row.addWidget(self.prompt_input, stretch=1)

        btn_add = QtWidgets.QPushButton("+ Queue Command")
        btn_add.setObjectName("primary")
        btn_add.clicked.connect(self.add_task)
        input_row.addWidget(btn_add)

        form_layout.addLayout(input_row)

        # GitHub Automation Row
        gh_row = QtWidgets.QHBoxLayout()
        gh_row.setSpacing(10)

        self.gh_check = QtWidgets.QCheckBox("🐙 Auto-Create GitHub Repo & Push Code (README included)")
        self.gh_check.setStyleSheet("color: #38bdf8; font-weight: 500;")
        gh_row.addWidget(self.gh_check)

        self.gh_name_input = QLineEdit()
        self.gh_name_input.setPlaceholderText("Repo Name (e.g. 'laravel-auth' or auto)")
        self.gh_name_input.setMaximumWidth(220)
        gh_row.addWidget(self.gh_name_input)

        self.gh_desc_input = QLineEdit()
        self.gh_desc_input.setPlaceholderText("Description (e.g. 'Production auth module')")
        gh_row.addWidget(self.gh_desc_input, stretch=1)

        form_layout.addLayout(gh_row)
        main_layout.addWidget(form_card)

        # Task List Area
        list_header = QtWidgets.QLabel("Pipeline Queue (Sequential Order)")
        list_header.setStyleSheet("font-weight: 600; color: #94a3b8; margin-top: 6px;")
        main_layout.addWidget(list_header)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QtWidgets.QWidget()
        self.task_list_layout = QtWidgets.QVBoxLayout(self.scroll_content)
        self.task_list_layout.setContentsMargins(0, 0, 0, 0)
        self.task_list_layout.setSpacing(10)
        self.task_list_layout.addStretch()
        self.scroll.setWidget(self.scroll_content)
        main_layout.addWidget(self.scroll, stretch=1)

        # Live Execution Output Box
        self.log_box = QtWidgets.QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(110)
        self.log_box.setPlaceholderText("Pipeline activity and agent dispatch log will stream here...")
        self.log_box.setStyleSheet("background-color: #060912; border: 1px solid #1e293b; color: #94a3b8; font-family: monospace; font-size: 11px;")
        main_layout.addWidget(self.log_box)

        self.refresh_queue()

    def fill_seo_prompt(self):
        prompt = (
            "Based on this project, give me the best github repo name with 400 character description "
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
        prompt = self.prompt_input.text().strip()
        if not prompt:
            return
        agent = self.agent_combo.currentData()
        create_repo = self.gh_check.isChecked()
        repo_name = self.gh_name_input.text().strip()
        repo_desc = self.gh_desc_input.text().strip()

        self.pipeline.add(
            prompt,
            agent=agent,
            create_repo=create_repo,
            repo_name=repo_name,
            repo_desc=repo_desc,
        )
        self.prompt_input.clear()
        self.gh_name_input.clear()
        self.gh_desc_input.clear()
        self.gh_check.setChecked(False)

        tag = f" [🐙 GH Repo: {repo_name or 'auto'}]" if create_repo else ""
        self.log_box.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Queued [{agent.upper()}]{tag}: {prompt}")
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

        # Rebuild list items
        # Clear existing items except bottom stretch
        while self.task_list_layout.count() > 1:
            item = self.task_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not tasks:
            empty_lbl = QtWidgets.QLabel("Pipeline queue is empty. Type a command above to start a sequential workflow.")
            empty_lbl.setStyleSheet("color: #64748b; font-style: italic; padding: 20px;")
            empty_lbl.setAlignment(Qt.AlignCenter)
            self.task_list_layout.insertWidget(0, empty_lbl)
        else:
            for idx, task in enumerate(tasks):
                card = TaskCard(task, on_failover=self.failover_single_task, on_confirm=self.confirm_completed)
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
        answer = QtWidgets.QMessageBox.question(self, "Verify task result",
            "Have you checked in the agent that this task completed successfully? This allows the next task to run.")
        if answer != QtWidgets.QMessageBox.Yes:
            return
        for task in self.pipeline.queue:
            if task["id"] == task_id and task["status"] == "SUBMITTED":
                self.pipeline.update_task(task_id, {"status":"COMPLETED", "completion_verified_by_user":True})
                self.refresh_queue()
                break

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
                self.pipeline.update_task(task_id, {"agent":"antigravity", "status":"QUEUED", "retry_at":None})
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
                self.pipeline.update_task(t["id"], {"agent":"antigravity", "status":"QUEUED", "retry_at":None})
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
    # Keep confirmation and input dialogs consistent across DevOS apps.
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
    QCoreApplication.setApplicationName("devos-ai-pipeline")
    QCoreApplication.setApplicationDisplayName("DevOS AI Command Pipeline")
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
