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
from task_pipeline import (
    TaskPipeline,
    parse_reset_time,
    extract_repo_metadata,
    discover_agents,
    to_slug,
    get_grouped_projects,
)


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

    def test_to_slug_conversion(self):
        self.assertEqual(to_slug("Build Laravel authentication API"), "build-laravel-authentication-api")
        self.assertEqual(to_slug("Payment Gateway: Stripe & PayPal!"), "payment-gateway-stripe-paypal")
        self.assertEqual(to_slug("Don't Repeat Yourself (DRY)"), "dont-repeat-yourself-dry")
        self.assertEqual(to_slug("   spaces   and---hyphens   "), "spaces-and-hyphens")
        self.assertEqual(to_slug(""), "project")

    def test_base_dir_configuration(self):
        custom_base = Path(self.test_dir) / "custom_projects"
        self.pipeline.set_base_dir(str(custom_base))
        self.assertEqual(self.pipeline.get_base_dir(), str(custom_base.resolve()))
        self.assertTrue(custom_base.exists())

    def test_add_with_title_and_slug(self):
        custom_base = Path(self.test_dir) / "workspace"
        self.pipeline.set_base_dir(str(custom_base))
        tid = self.pipeline.add(
            "Scaffold API controllers",
            agent="local",
            project_title="E-Commerce API",
            project_slug="ecommerce-api",
        )
        task = self.pipeline.list()[0]
        self.assertEqual(task["id"], tid)
        self.assertEqual(task["project_title"], "E-Commerce API")
        self.assertEqual(task["project_slug"], "ecommerce-api")
        self.assertEqual(task["project"], str(custom_base / "ecommerce-api"))

    def test_grouped_projects(self):
        self.pipeline.add("Task A1", agent="local", project_title="Project A", project_slug="proj-a")
        self.pipeline.add("Task A2", agent="local", project_title="Project A", project_slug="proj-a")
        self.pipeline.add("Task B1", agent="local", project_title="Project B", project_slug="proj-b")

        tasks = self.pipeline.list()
        grouped = get_grouped_projects(tasks)
        self.assertEqual(len(grouped), 2)
        self.assertEqual(grouped[0]["slug"], "proj-a")
        self.assertEqual(len(grouped[0]["tasks"]), 2)
        self.assertEqual(grouped[1]["slug"], "proj-b")
        self.assertEqual(len(grouped[1]["tasks"]), 1)

    @patch("task_pipeline.notify")
    @patch("task_pipeline.is_agent_working", return_value=False)
    def test_auto_create_project_folder_on_execute(self, *_):
        custom_base = Path(self.test_dir) / "devos_work"
        self.pipeline.set_base_dir(str(custom_base))
        self.pipeline.add("Run migration", agent="local", project_title="Auth Module", project_slug="auth-module")

        target_dir = custom_base / "auth-module"
        self.assertFalse(target_dir.exists())

        with patch.object(self.pipeline, "_dispatch", return_value=(True, "Migration completed")) as dispatch:
            self.assertTrue(self.pipeline.execute_next())
            self.assertTrue(target_dir.exists())
            self.assertTrue(target_dir.is_dir())
            self.assertEqual(dispatch.call_args[0][0]["project"], str(target_dir))
        self.assertEqual(self.pipeline.list()[0]["status"], "COMPLETED")

    @patch("task_pipeline.notify")
    @patch("task_pipeline.is_agent_working", return_value=False)
    def test_multi_project_sequential_execution(self, *_):
        custom_base = Path(self.test_dir) / "multi_work"
        self.pipeline.set_base_dir(str(custom_base))

        self.pipeline.add("Proj1 Step 1", agent="local", project_title="P1", project_slug="p1")
        self.pipeline.add("Proj1 Step 2", agent="local", project_title="P1", project_slug="p1")
        self.pipeline.add("Proj2 Step 1", agent="local", project_title="P2", project_slug="p2")

        with patch.object(self.pipeline, "_dispatch", return_value=(True, "OK")):
            # Step 1 of P1
            self.assertTrue(self.pipeline.execute_next())
            self.assertTrue((custom_base / "p1").exists())
            self.assertFalse((custom_base / "p2").exists())

            # Step 2 of P1
            self.assertTrue(self.pipeline.execute_next())
            self.assertTrue((custom_base / "p1").exists())
            self.assertFalse((custom_base / "p2").exists())

            # P1 finished, now P2 runs and its folder is auto-created!
            self.assertTrue(self.pipeline.execute_next())
            self.assertTrue((custom_base / "p2").exists())

        statuses = [t["status"] for t in self.pipeline.list()]
        self.assertEqual(statuses, ["COMPLETED", "COMPLETED", "COMPLETED"])

    def test_delete_project_and_task(self):
        t1 = self.pipeline.add("Task 1", agent="local", project_slug="p1")
        t2 = self.pipeline.add("Task 2", agent="local", project_slug="p1")
        t3 = self.pipeline.add("Task 3", agent="local", project_slug="p2")

        # Delete single task
        self.pipeline.delete_task(t1)
        self.assertEqual(len(self.pipeline.list()), 2)
        self.assertNotIn(t1, [t["id"] for t in self.pipeline.list()])

        # Delete entire project p1
        self.pipeline.delete_project("p1")
        self.assertEqual(len(self.pipeline.list()), 1)
        self.assertEqual(self.pipeline.list()[0]["project_slug"], "p2")


if __name__ == "__main__":
    unittest.main()
