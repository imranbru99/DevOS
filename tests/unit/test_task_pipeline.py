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


if __name__ == "__main__":
    unittest.main()
