#!/usr/bin/env python3
"""
Unit tests for DevOS AI Code Agent GUI, Persistence, and Dynamic Contextual Controls.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

CODE_AGENT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/code-agent"))
sys.path.insert(0, CODE_AGENT_PATH)

from PyQt5 import QtCore, QtGui, QtWidgets
import agent_gui as gui



class TestCodeAgentGUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_config_path = gui.CONFIG_PATH
        gui.CONFIG_PATH = os.path.join(self.temp_dir, "test-config.json")

    def tearDown(self):
        gui.CONFIG_PATH = self.orig_config_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_app_icon_found(self):
        icon = gui.get_app_icon()
        self.assertFalse(icon.isNull(), "Application icon should be resolved and valid.")

    def test_folder_persistence(self):
        test_project = os.path.join(self.temp_dir, "my-test-project")
        os.makedirs(test_project, exist_ok=True)

        gui.record_opened_folder(test_project)
        self.assertEqual(gui.get_last_opened_folder(), test_project)

        cfg = gui.get_persisted_config()
        self.assertEqual(cfg.get("last_folder"), test_project)
        self.assertIn(test_project, cfg.get("recent_folders", []))

    def test_agent_window_auto_loads_last_project(self):
        test_project = os.path.join(self.temp_dir, "auto-project")
        os.makedirs(test_project, exist_ok=True)
        gui.record_opened_folder(test_project)

        win = gui.AgentWindow(capable=(True, "Ready"))
        self.assertEqual(win.folder, test_project)
        self.assertIn("auto-project", win.path_label.text())

    def test_buttons_hidden_when_idle(self):
        win = gui.AgentWindow(capable=(True, "Ready"))
        win._set_pending(None)

        self.assertTrue(win.diff_btn_box.isHidden(), "Diff buttons must be hidden when there are no changes.")
        self.assertTrue(win.term_btn_box.isHidden(), "Terminal buttons must be hidden when there is no command.")

    def test_buttons_revealed_on_pending_action(self):
        class DummyEditAction:
            kind = "edit"
            title = "Edit main.py"
            diff = "--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-old\n+new"

        class DummyCommandAction:
            kind = "command"
            command = "pytest tests/"

        win = gui.AgentWindow(capable=(True, "Ready"))

        # When pending edit arrives:
        win._set_pending(DummyEditAction())
        self.assertFalse(win.diff_btn_box.isHidden(), "Diff buttons must become visible on edit action.")
        self.assertTrue(win.term_btn_box.isHidden(), "Terminal buttons must remain hidden on edit action.")

        # When pending command arrives:
        win._set_pending(DummyCommandAction())
        self.assertTrue(win.diff_btn_box.isHidden(), "Diff buttons must be hidden on command action.")
        self.assertFalse(win.term_btn_box.isHidden(), "Terminal buttons must become visible on command action.")

        # When action cleared:
        win._set_pending(None)
        self.assertTrue(win.diff_btn_box.isHidden())
        self.assertTrue(win.term_btn_box.isHidden())
    def test_stop_btn_hidden_when_idle(self):
        win = gui.AgentWindow(capable=(True, "Ready"))
        self.assertTrue(win.stop_btn.isHidden(), "Stop button must be hidden when idle / never fired run.")
        self.assertTrue(win.send_btn.isEnabled(), "Run agent button must be enabled when idle.")

    def test_stop_btn_lifecycle(self):
        win = gui.AgentWindow(capable=(True, "Ready"))
        win.composer.setPlainText("Test task")

        # Simulate starting run
        win.send_btn.setEnabled(False)
        win.stop_btn.setEnabled(True)
        win.stop_btn.setVisible(True)
        self.assertFalse(win.stop_btn.isHidden(), "Stop button must be visible when running.")
        self.assertFalse(win.send_btn.isEnabled(), "Run agent button must be disabled when running.")

        # Simulate finishing
        win.on_finished()
        self.assertTrue(win.stop_btn.isHidden(), "Stop button must be hidden after finishing.")
    def test_ai_badge_reflects_health(self):
        win = gui.AgentWindow(capable=(True, "Ready"))
        self.assertTrue(hasattr(win, "ai_badge"))
        # Verify initial check executed
        win._check_ai_status()
        self.assertIn(win.ai_badge.property("state"), ["online", "offline"])

    def test_code_agent_health_check_functions(self):
        # find_ai_server_py returns valid file
        server_py = gui.core.find_ai_server_py()
        self.assertIsNotNone(server_py)
        self.assertTrue(os.path.isfile(server_py))

        # check_ai_health responds with boolean
        res = gui.core.check_ai_health()
        self.assertIsInstance(res, bool)

    def test_auto_commands_policy(self):
        policy = gui.core.ApprovalPolicy(auto_reads=True, auto_edits=False, auto_commands=True)
        self.assertFalse(policy.needs_approval("run_command"))
        self.assertFalse(policy.needs_approval("read_file"))
        self.assertTrue(policy.needs_approval("write_file"))

        win = gui.AgentWindow(capable=(True, "Ready"))
        self.assertTrue(hasattr(win, "auto_commands"))
        self.assertFalse(win.auto_commands.isChecked())
        win.auto_commands.setChecked(True)
        self.assertTrue(win.policy.auto_commands)
        self.assertIn("Auto-commands: ON", win.status.text())

    def test_responsive_window_sizing(self):
        win = gui.AgentWindow(capable=(True, "Ready"))
        screen = QtWidgets.QApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            self.assertLessEqual(win.width(), geom.width())
            self.assertLessEqual(win.height(), geom.height())

    def test_composer_enter_submits(self):
        composer = gui.AgentComposer()
        submitted = []
        composer.submit_requested.connect(lambda: submitted.append(True))

        # Regular Enter key press
        event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Return, QtCore.Qt.NoModifier)
        composer.keyPressEvent(event)
        self.assertEqual(len(submitted), 1, "Enter without Shift must emit submit_requested")

    def test_composer_shift_enter_newlines(self):
        composer = gui.AgentComposer()
        submitted = []
        composer.submit_requested.connect(lambda: submitted.append(True))

        # Shift+Enter key press
        event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Return, QtCore.Qt.ShiftModifier)
        composer.keyPressEvent(event)
        self.assertEqual(len(submitted), 0, "Shift+Enter must not emit submit_requested")
        self.assertIn("\n", composer.toPlainText(), "Shift+Enter must insert a newline")

    def test_composer_image_paste_and_drop(self):
        composer = gui.AgentComposer()
        attached = []
        composer.image_attached.connect(attached.append)

        # 1. Clipboard image data
        img = QtGui.QImage(32, 32, QtGui.QImage.Format_RGB32)
        img.fill(QtGui.QColor("blue"))
        mime = QtCore.QMimeData()
        mime.setImageData(img)
        self.assertTrue(composer.canInsertFromMimeData(mime))
        composer.insertFromMimeData(mime)
        self.assertEqual(len(attached), 1)
        self.assertTrue(os.path.exists(attached[0]))

        # 2. File URL image
        test_img = os.path.join(self.temp_dir, "test_pic.png")
        img.save(test_img, "PNG")
        mime_url = QtCore.QMimeData()
        mime_url.setUrls([QtCore.QUrl.fromLocalFile(test_img)])
        self.assertTrue(composer.canInsertFromMimeData(mime_url))
        composer.insertFromMimeData(mime_url)
        self.assertEqual(len(attached), 2)
        self.assertEqual(attached[1], test_img)

        # 3. Plain text paste does not trigger image attach
        mime_text = QtCore.QMimeData()
        mime_text.setText("hello world")
        composer.insertFromMimeData(mime_text)
        self.assertEqual(len(attached), 2)
        self.assertIn("hello world", composer.toPlainText())

    def test_attachment_bar_lifecycle(self):
        win = gui.AgentWindow(capable=(True, "Ready"))
        self.assertTrue(win.attachment_bar.isHidden(), "Attachment bar should be hidden by default")

        test_img = os.path.join(self.temp_dir, "test.png")
        img = QtGui.QImage(16, 16, QtGui.QImage.Format_RGB32)
        img.fill(QtGui.QColor("green"))
        img.save(test_img, "PNG")

        win.add_attachment(test_img)
        self.assertIn(test_img, win.attached_images)
        self.assertFalse(win.attachment_bar.isHidden(), "Attachment bar should be visible after adding attachment")

        # Removing attachment
        win.remove_attachment(test_img)
        self.assertNotIn(test_img, win.attached_images)
        self.assertTrue(win.attachment_bar.isHidden(), "Attachment bar should be hidden when attachments empty")

    def test_send_incorporates_images_and_clears_attachments(self):
        win = gui.AgentWindow(capable=(True, "Ready"))
        test_project = os.path.join(self.temp_dir, "send-proj")
        os.makedirs(test_project, exist_ok=True)
        win.set_folder(test_project)

        test_img = os.path.join(self.temp_dir, "error_screenshot.png")
        img = QtGui.QImage(16, 16, QtGui.QImage.Format_RGB32)
        img.fill(QtGui.QColor("yellow"))
        img.save(test_img, "PNG")

        win.add_attachment(test_img)
        win.composer.setPlainText("Fix the syntax error")

        # Mock AgentWorker to prevent spawning real thread
        class DummyWorker(QtCore.QObject):
            event = QtCore.pyqtSignal(str, object)
            approval = QtCore.pyqtSignal(object)
            failed = QtCore.pyqtSignal(str)
            finished = QtCore.pyqtSignal()
            def start(self): pass

        orig_worker = gui.AgentWorker
        captured_task = []
        captured_kwargs = []
        try:
            def mock_worker(folder, task, policy, llm, *args, **kwargs):
                captured_task.append(task)
                captured_kwargs.append(kwargs)
                return DummyWorker()
            gui.AgentWorker = mock_worker

            win.send()
            self.assertEqual(len(captured_task), 1)
            self.assertIn("Fix the syntax error", captured_task[0])
            self.assertIn("Attached image:", captured_task[0])
            self.assertEqual(len(win.attached_images), 0, "Attached images should be cleared after send")
            self.assertTrue(win.attachment_bar.isHidden())
        finally:
            gui.AgentWorker = orig_worker

    def test_multi_turn_history_passed_to_worker(self):
        """Verify that previous conversation turns are passed to AgentWorker."""
        win = gui.AgentWindow(capable=(True, "Ready"))
        win.set_folder(self.temp_dir)
        win.transcript = [
            ["user", "can u run this"],
            ["agent", "run_command command: python3 main.py"],
            ["user", "why failed to show landing page"],
            ["agent", ""]
        ]
        win.composer.setPlainText("what is the fix")

        class DummyWorker(QtCore.QObject):
            event = QtCore.pyqtSignal(str, object)
            approval = QtCore.pyqtSignal(object)
            failed = QtCore.pyqtSignal(str)
            finished = QtCore.pyqtSignal()
            def start(self): pass

        orig_worker = gui.AgentWorker
        captured_history = []
        try:
            def mock_worker(folder, task, policy, llm, *args, **kwargs):
                captured_history.append(kwargs.get("history", []))
                return DummyWorker()
            gui.AgentWorker = mock_worker

            win.send()
            self.assertEqual(len(captured_history), 1)
            hist = captured_history[0]
            self.assertGreaterEqual(len(hist), 2)
            self.assertEqual(hist[0]["role"], "user")
            self.assertEqual(hist[0]["content"], "can u run this")
            self.assertEqual(hist[1]["role"], "assistant")
        finally:
            gui.AgentWorker = orig_worker

    def test_workspace_detect_run_info_node(self):
        """Test workspace entrypoint detection for package.json dev script."""
        pkg_json = os.path.join(self.temp_dir, "package.json")
        with open(pkg_json, "w") as f:
            json.dump({"name": "my-app", "scripts": {"dev": "vite", "build": "vite build"}}, f)
        ws = gui.core.Workspace(self.temp_dir)
        info = ws.detect_run_info()
        self.assertIsNotNone(info)
        self.assertIn("npm run dev", info["command"])
        self.assertIn("http://localhost:5173", info["preview_url"])

    def test_workspace_detect_run_info_python_fastapi(self):
        """Test workspace entrypoint detection for main.py with FastAPI."""
        main_py = os.path.join(self.temp_dir, "main.py")
        with open(main_py, "w") as f:
            f.write("from fastapi import FastAPI\napp = FastAPI()\n")
        ws = gui.core.Workspace(self.temp_dir)
        info = ws.detect_run_info()
        self.assertIsNotNone(info)
        self.assertIn("uvicorn", info["command"])
        self.assertIn("http://localhost:8000", info["preview_url"])

    def test_workspace_detect_run_info_static_html(self):
        """Test workspace entrypoint detection for static index.html."""
        idx_html = os.path.join(self.temp_dir, "index.html")
        with open(idx_html, "w") as f:
            f.write("<!DOCTYPE html><html><body><h1>Landing Page</h1></body></html>")
        ws = gui.core.Workspace(self.temp_dir)
        info = ws.detect_run_info()
        self.assertIsNotNone(info)
        self.assertIn("http.server", info["command"])
        self.assertIn("http://localhost:3000", info["preview_url"])

    def test_providers_load_and_active_engine(self):
        """Test provider configuration and active engine retrieval."""
        orig_p_config = gui.providers.CONFIG_FILE
        try:
            gui.providers.CONFIG_FILE = os.path.join(self.temp_dir, "prov-config.json")
            conf = gui.providers.load_config()
            self.assertIn("active_provider", conf)
            
            gui.providers.set_active_engine("gemini", model="gemini-2.0-flash", api_key="test_key_123")
            engine = gui.providers.get_active_engine()
            self.assertEqual(engine["provider"], "gemini")
            self.assertEqual(engine["model"], "gemini-2.0-flash")
            self.assertEqual(engine["api_key"], "test_key_123")
        finally:
            gui.providers.CONFIG_FILE = orig_p_config

    def test_engine_settings_dialog(self):
        """Test EngineSettingsDialog instantiates and updates fields correctly."""
        dlg = gui.EngineSettingsDialog()
        self.assertIsNotNone(dlg.provider_combo)
        self.assertGreaterEqual(dlg.provider_combo.count(), 4)
        # Select Groq
        idx = dlg.provider_combo.findData("groq")
        self.assertGreaterEqual(idx, 0)
        dlg.provider_combo.setCurrentIndex(idx)
        self.assertIn("300+", dlg.speed_badge.text())

    def test_chat_scroll_and_jump_to_latest(self):
        """Test jump to latest button visibility and auto scroll mechanics."""
        win = gui.AgentWindow(capable=(True, "Ready"))
        self.assertIsNotNone(win.jump_to_latest_btn)
        self.assertTrue(win._auto_scroll_to_bottom)
        self.assertFalse(win.jump_to_latest_btn.isVisible())

        # Simulate user scrolling up
        win._on_chat_scroll(0)
        # Calling scroll_to_bottom resets flag and hides jump button
        win.scroll_to_bottom()
        self.assertTrue(win._auto_scroll_to_bottom)
        self.assertFalse(win.jump_to_latest_btn.isVisible())

    def test_inspector_tabs_auto_switch(self):
        """Test inspector tabs auto-switch on edit and command actions."""
        win = gui.AgentWindow(capable=(True, "Ready"))
        self.assertIsNotNone(win.tabs)
        self.assertEqual(win.tabs.count(), 3)

        # Trigger edit action
        act_edit = gui.core.Action(kind="edit", tool="apply_patch", title="Update file", diff="--- a/f\n+++ b/f\n")
        win._show_change(act_edit)
        self.assertEqual(win.tabs.currentWidget(), win.diff_card)
        self.assertIn("Pending", win.tabs.tabText(0))

        # Trigger command action
        act_cmd = gui.core.Action(kind="command", tool="run_command", title="Run server", command="npm run dev")
        win._set_pending(act_cmd)
        self.assertEqual(win.tabs.currentWidget(), win.term_card)

    def test_action_prompts_with_polite_phrasing(self):
        """Action prompts with polite phrasing like 'can you make...' must not be discarded as questions."""
        agent = gui.core.CodeAgent(gui.core.Workspace(self.temp_dir), llm=None, approve=lambda a: True)
        self.assertTrue(
            agent.should_continue_task("I will build the landing page.", "can you make the landign page and run the full application", 0),
            "Build prompts with 'can you make...' must continue when 0 files changed."
        )
        self.assertTrue(
            agent.should_continue_task("I will start building.", "so build now", 0),
            "'so build now' must continue when 0 files changed."
        )
        # But pure questions should not force continue
        self.assertFalse(
            agent.should_continue_task("This is how it works.", "why is the landing page blank?", 0),
            "Pure questions must not force continuation."
        )

    def test_repetition_guard_prevents_stalling_loop(self):
        """When a model repeats conversational filler without tools, repetition guard must halt cleanly."""
        class MockEchoLLM:
            def chat(self, messages, on_token=None, should_stop=None, options=None):
                return "I will start building the landing page and running the full application."

        recorded_events = []
        def on_event(kind, payload):
            recorded_events.append((kind, payload))

        agent = gui.core.CodeAgent(
            gui.core.Workspace(self.temp_dir),
            llm=MockEchoLLM(),
            approve=lambda a: True,
            on_event=on_event,
            max_steps=20
        )
        res = agent.run("so build now")
        replies = [p for k, p in recorded_events if k == "reply"]
        # It must NOT loop 20 or 12 times: two filler replies plus one forced attempt, then stop.
        self.assertLessEqual(len(replies), 3, "Agent must not repeat conversational filler across steps.")
        self.assertIn("did not write any files", res)


    def test_prompt_queue_lifecycle(self):
        """When a task is running, new prompts must queue cleanly, show queue UI, and auto-dequeue."""
        win = gui.AgentWindow(capable=(True, "Ready"))
        self.assertEqual(len(win.prompt_queue), 0)
        self.assertFalse(win.queue_bar.isVisible())

        # Simulate active worker
        win.worker = "dummy_active_worker"

        # User submits a new prompt while worker is active
        win.composer.setPlainText("tell me this application summery")
        win.send()

        # Composer must be cleared immediately, prompt added to queue, and queue bar shown
        self.assertEqual(win.composer.toPlainText(), "")
        self.assertEqual(len(win.prompt_queue), 1)
        self.assertEqual(win.prompt_queue[0][0], "tell me this application summery")
        self.assertFalse(win.queue_bar.isHidden())
        self.assertIn("tell me this application summery", win.queue_label.text())

        # User clears queue
        win.clear_queue()
        self.assertEqual(len(win.prompt_queue), 0)
        self.assertTrue(win.queue_bar.isHidden())

    def test_code_agent_execute_command_and_edit(self):
        """Verify CodeAgent has _command, _edit, and _read, and execute() works without attribute errors."""
        agent = gui.core.CodeAgent(
            gui.core.Workspace(self.temp_dir),
            llm=None,
            approve=lambda a: True,
            policy=gui.core.ApprovalPolicy(auto_reads=True, auto_edits=True, auto_commands=True)
        )
        self.assertTrue(hasattr(agent, "_command"))
        self.assertTrue(hasattr(agent, "_edit"))
        self.assertTrue(hasattr(agent, "_read"))

        # Test command execution
        cmd_call = gui.core.ToolCall("run_command", {"command": "echo 'devos test'"})
        res = agent.execute(cmd_call)
        self.assertIn("devos test", res)

    def test_empty_chat_shows_welcome_with_suggestions(self):
        win = gui.AgentWindow(folder=self.temp_dir, capable=(True, "Ready"))
        win._render_if_dirty()
        text = win.chat.toPlainText()
        self.assertIn("What should we build?", text)
        self.assertIn("Understand this project", text)

    def test_streaming_tail_render_matches_full_render(self):
        """While the agent streams, only the last message is replaced; the result must equal a full render."""
        class Busy:
            pass
        win = gui.AgentWindow(folder=self.temp_dir, capable=(True, "Ready"))
        win.worker = Busy()
        win.transcript = [["user", "build it"], ["agent", "Working on it."], ["agent", ""]]
        win._dirty = True
        win._render_if_dirty()
        for chunk in ("```tool write_file\npath: a.py\n---\nX = 1\n", "Y = 2\n```", "\nAll done."):
            win.transcript[-1][1] += chunk
            win._dirty = True
            win._render_if_dirty()
        incremental = win.chat.toPlainText()

        fresh = gui.AgentWindow(folder=self.temp_dir, capable=(True, "Ready"))
        fresh.worker = Busy()
        fresh.transcript = [list(item) for item in win.transcript]
        fresh._dirty = True
        fresh._render_if_dirty()
        self.assertEqual(incremental, fresh.chat.toPlainText())
        self.assertIn("a.py", incremental)
        win.worker = fresh.worker = None

    def test_tool_calls_render_as_compact_rows(self):
        out = gui.message_html("Plan.\n```tool write_file\npath: app/x.py\n---\nA = 1\nB = 2\n```")
        self.assertIn("Wrote", out)
        self.assertIn("app/x.py", out)
        self.assertIn("+2", out)
        live = gui.message_html("```tool write_file\npath: app/x.py\n---\nA = 1\n", is_generating=True)
        self.assertIn("Writing", live)

    def test_phase_and_speed_events_update_the_window(self):
        win = gui.AgentWindow(folder=self.temp_dir, capable=(True, "Ready"))
        win.on_event("plan", ["Skeleton", "Models"])
        win.on_event("phase", {"index": 2, "total": 2, "title": "Models"})
        self.assertIn("Phase 2 of 2", win.step_chip.text())
        win.on_event("speed", {"tokens_per_sec": 5.6, "seconds": 12.0})
        self.assertIn("5.6 tok/s", win.speed_label.text())


    def test_go_bar_appears_when_a_saved_brief_waits_for_approval(self):
        brief_dir = os.path.join(self.temp_dir, ".devos")
        os.makedirs(brief_dir)
        with open(os.path.join(brief_dir, "brief.json"), "w") as handle:
            json.dump({"title": "Shoply", "protocol": True, "asked": True, "next": 1,
                       "phases": [{"n": 1, "title": "Foundation", "text": "x"}, {"n": 2, "title": "Money", "text": "y"}]}, handle)
        win = gui.AgentWindow(folder=self.temp_dir, capable=(True, "Ready"))
        win.show()
        self.assertTrue(win.go_bar.isVisible())
        self.assertIn("Phase 1 of 2", win.go_label.text())
        sent = []
        win.send = lambda: sent.append(win.composer.toPlainText())
        win.go_all_btn.click()
        self.assertEqual(sent, ["go all"])
        win.close()

    def test_go_bar_hidden_without_a_brief(self):
        win = gui.AgentWindow(folder=self.temp_dir, capable=(True, "Ready"))
        win.show()
        self.assertFalse(win.go_bar.isVisible())
        win.close()

    def test_phase_report_replaces_the_empty_placeholder(self):
        win = gui.AgentWindow(folder=self.temp_dir, capable=(True, "Ready"))
        win.transcript = [["user", "go"], ["agent", ""]]
        win.on_event("phase", {"index": 1, "total": 2, "title": "Foundation"})
        self.assertEqual(win.transcript[1][0], "note")
        win.on_event("report", "Phase 1 done.")
        self.assertEqual(win.transcript[-1], ["agent", "Phase 1 done."])


    def test_numbered_lists_keep_their_numbers_and_code_stars_do_not_break_bold(self):
        out = gui._prose("**Questions**\n1. First question\n2. Second question\n- a bullet\nUse `**` and **bold** here")
        self.assertIn(">1.<", out)
        self.assertIn(">2.<", out)
        self.assertIn("•", out)
        self.assertNotIn("**", out.replace("&nbsp;**&nbsp;", ""))
        self.assertIn("white-space:pre-wrap", gui.message_html("```php\n<?php echo 1;\n```"))

    def test_done_event_works_without_an_agent_and_counts_files(self):
        win = gui.AgentWindow(folder=self.temp_dir, capable=(True, "Ready"))

        class FakeWorker:
            agent = type("A", (), {"changed": ["a.py", "a.py", "b.py"]})()

        win.worker = FakeWorker()
        win.transcript = [["user", "go"], ["agent", ""]]
        win.on_event("done", "Status text.")
        self.assertEqual(win.transcript[1][1], "Status text.")
        self.assertIn("2 files changed", win.transcript[-1][1])
        win.worker = None
        win.on_event("done", "again")                      # no worker at all: still no crash

    def test_phase_rows_in_the_roadmap_follow_phase_events(self):
        win = gui.AgentWindow(folder=self.temp_dir, capable=(True, "Ready"))
        win.on_event("task_init", {"topic": "T", "task": "T", "plan": ["Phase 1 — A", "Phase 2 — B"]})
        win.on_event("phase", {"index": 1, "total": 2, "title": "A"})
        win.on_event("step", {"title": "Edit x.py", "kind": "edit"})          # tool steps stay out of the phase list
        self.assertEqual(win.plan.count(), 2)
        win.on_event("phase_done", {"index": 1, "ok": True})
        win.on_event("phase", {"index": 2, "total": 2, "title": "B"})
        win.on_event("phase_done", {"index": 2, "ok": False})
        self.assertIn(gui.STEP_ICON["done"], win.plan.item(0).text())
        self.assertIn(gui.STEP_ICON["failed"], win.plan.item(1).text())
        self.assertEqual(win.plan_progress.value(), 50)


if __name__ == "__main__":
    unittest.main()




