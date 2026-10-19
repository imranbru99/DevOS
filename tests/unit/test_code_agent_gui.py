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


if __name__ == "__main__":
    unittest.main()


