#!/usr/bin/env python3
"""
Unit tests for DevOS AI Code Agent GUI, Persistence, and Dynamic Contextual Controls.
"""

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


if __name__ == "__main__":
    unittest.main()


