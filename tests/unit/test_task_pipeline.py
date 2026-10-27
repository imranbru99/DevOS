"""
Tests for DevOS AI Multi-Agent Task Pipeline & Rate-Limit Scheduler.
"""

import os
import sys
import datetime
import unittest
from pathlib import Path
import tempfile
import shutil
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components" / "ai-agent"))
from task_pipeline import TaskPipeline, parse_reset_time, extract_repo_metadata, discover_agents


class TestTaskPipeline(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.state_file = Path(self.test_dir) / "test_pipeline.json"
        self.context_file = Path(self.test_dir) / "test_context.json"
        self.pipeline = TaskPipeline(state_file=self.state_file, context_file=self.context_file)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_discover_agents(self):
        agents = discover_agents()
        self.assertIn("antigravity", agents)
        self.assertIn("chatgpt", agents)
        self.assertIn("claude", agents)
        self.assertIn("aider", agents)
        self.assertIn("local", agents)

    def test_parse_reset_time_from_codex_banner(self):
        # Text from user's screenshot
        text = "You're out of Codex and Work usage. Add credits or upgrade your plan — or wait for usage to reset on 10:46 AM"
        target = parse_reset_time(text)
        self.assertIsNotNone(target)
        self.assertEqual(target.hour, 10)
        self.assertEqual(target.minute, 47)  # 10:46 + 1 min safety buffer

    def test_extract_repo_metadata(self):
        sample = "Project built successfully!\nrepo: devos-quantum-cache\ndescription: Ultra-fast kernel caching library\n"
        name, desc = extract_repo_metadata(sample)
        self.assertEqual(name, "devos-quantum-cache")
        self.assertEqual(desc, "Ultra-fast kernel caching library")

    def test_context_interpolation(self):
        self.pipeline.context["github_repo"] = "https://github.com/imranbru99/devos-quantum-cache"
        self.pipeline._save_context()

        self.pipeline.add("Deploy {github_repo} to production", agent="local")
        task = self.pipeline.list()[0]
        self.assertEqual(task["prompt"], "Deploy {github_repo} to production")

        # Test execute_next interpolation
        prompt = task["prompt"]
        for k, v in self.pipeline.context.items():
            prompt = prompt.replace(f"{{{k}}}", str(v))
        self.assertEqual(prompt, "Deploy https://github.com/imranbru99/devos-quantum-cache to production")

    def test_queue_add_and_list(self):
        tid1 = self.pipeline.add("Build authentication module", agent="chatgpt", create_repo=True, repo_name="auth-api")
        tid2 = self.pipeline.add("Write unit tests and run suite", agent="antigravity")

        tasks = self.pipeline.list()
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["id"], tid1)
        self.assertEqual(tasks[0]["agent"], "chatgpt")
        self.assertTrue(tasks[0]["create_repo"])
        self.assertEqual(tasks[0]["repo_name"], "auth-api")
        self.assertEqual(tasks[1]["id"], tid2)
        self.assertEqual(tasks[1]["agent"], "antigravity")

    def test_clear_queue(self):
        self.pipeline.add("Task 1", agent="chatgpt")
        self.pipeline.clear()
        self.assertEqual(len(self.pipeline.list()), 0)

    @patch("task_pipeline.notify")
    @patch("task_pipeline.is_agent_working", return_value=False)
    def test_delayed_task_cannot_run_early_or_be_overtaken(self, *_):
        self.pipeline.add("first", agent="local", delay_seconds=600)
        self.pipeline.add("second", agent="local")
        with patch.object(self.pipeline, "_dispatch") as dispatch:
            self.assertFalse(self.pipeline.execute_next())
            dispatch.assert_not_called()

    @patch("task_pipeline.notify")
    @patch("task_pipeline.is_agent_working", return_value=False)
    def test_submitted_is_not_completed_and_blocks_following_task(self, *_):
        self.pipeline.add("first", agent="antigravity")
        self.pipeline.add("second", agent="local")
        with patch.object(self.pipeline, "_dispatch", return_value=(False, "SUBMITTED: accepted")) as dispatch:
            self.assertTrue(self.pipeline.execute_next())
            self.assertEqual(self.pipeline.queue[0]["status"], "SUBMITTED")
            self.assertFalse(self.pipeline.execute_next())
            self.assertEqual(dispatch.call_count, 1)

    def test_missing_codex_does_not_simulate_success(self):
        with patch("task_pipeline.discover_agents", return_value={"chatgpt": {"bin": None}}):
            ok, output = self.pipeline._dispatch({"agent": "chatgpt", "prompt": "hello"})
        self.assertFalse(ok)
        self.assertIn("not installed", output)

    def test_provider_uses_the_selected_project_directory(self):
        from types import SimpleNamespace
        agents={'claude': {'bin':'/mock/claude'}}
        with patch('task_pipeline.discover_agents',return_value=agents), patch('task_pipeline.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='done',stderr='')) as run:
            ok,_=self.pipeline._dispatch({'agent':'claude','prompt':'review','project':self.test_dir})
        self.assertTrue(ok)
        self.assertEqual(run.call_args.kwargs['cwd'],self.test_dir)

    @patch("task_pipeline.notify")
    @patch("task_pipeline.is_agent_working", return_value=False)
    def test_dispatch_exception_is_saved_as_failure(self, *_):
        self.pipeline.add("task", agent="local")
        with patch.object(self.pipeline, "_dispatch", side_effect=OSError("missing executable")):
            self.assertTrue(self.pipeline.execute_next())
        self.assertEqual(self.pipeline.queue[0]["status"], "FAILED")
        self.assertIn("missing executable", self.pipeline.queue[0]["output"])

    @patch("task_pipeline.notify")
    def test_ids_are_unique_and_state_save_is_atomic(self, *_):
        with patch("task_pipeline.time.time", return_value=123):
            first = self.pipeline.add("one", agent="local")
            second = self.pipeline.add("two", agent="local")
        self.assertNotEqual(first, second)
        old = self.state_file.read_bytes()
        with patch("task_pipeline.os.replace", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.pipeline._save()
        self.assertEqual(self.state_file.read_bytes(), old)
        self.assertEqual(list(Path(self.test_dir).glob(".pipeline-*")), [])

    @patch("task_pipeline.notify")
    def test_two_windows_do_not_overwrite_each_others_queued_tasks(self, *_):
        other = TaskPipeline(self.state_file, self.context_file)
        self.pipeline.add("one", agent="local")
        other.add("two", agent="local")
        loaded = TaskPipeline(self.state_file, self.context_file)
        self.assertEqual([t["prompt"] for t in loaded.list()], ["one", "two"])

    @patch("task_pipeline.notify")
    @patch("task_pipeline.is_agent_working", return_value=False)
    def test_failed_task_stops_dependent_task(self, *_):
        self.pipeline.add("first", agent="local")
        self.pipeline.add("dependent", agent="local")
        with patch.object(self.pipeline, "_dispatch", return_value=(False, "failed")) as dispatch:
            self.pipeline.execute_next()
            self.assertFalse(self.pipeline.execute_next())
            self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(self.pipeline.list()[1]["status"], "QUEUED")

    def test_pipeline_gui_initialization(self):
        from PyQt5 import QtWidgets
        import pipeline_gui
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["--platform", "offscreen"])
        win = pipeline_gui.PipelineWindow()
        self.assertIsNotNone(win)
        self.assertIn("DevOS AI Command Pipeline", win.windowTitle())
        win.close()


if __name__ == "__main__":
    unittest.main()
