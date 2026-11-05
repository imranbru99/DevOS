"""
Unit tests for Antigravity Connection Discovery & Multi-Profile Routing.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components" / "ai-agent"))
from antigravity_connection import connection_environment, ensure_connection, bind_project


class TestAntigravityConnection(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.home = Path(self.test_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch.dict(os.environ, {}, clear=True)
    def test_daemon_discovery_for_antigravity_kde(self):
        """Test that hub_<port>.json in daemon directory is automatically discovered."""
        daemon_dir = self.home / ".gemini/antigravity-kde/daemon"
        daemon_dir.mkdir(parents=True, exist_ok=True)
        hub_file = daemon_dir / "hub_42645.json"
        current_pid = os.getpid()
        hub_file.write_text(json.dumps({
            "pid": current_pid,
            "httpPort": 42645,
            "csrfToken": "test-token-123",
        }))

        with patch("pathlib.Path.home", return_value=self.home):
            env = connection_environment(profile="antigravity-kde")

        self.assertIsNotNone(env)
        self.assertEqual(env.get("ANTIGRAVITY_LS_ADDRESS"), "127.0.0.1:42645")
        self.assertEqual(env.get("ANTIGRAVITY_CSRF_TOKEN"), "test-token-123")

    @patch.dict(os.environ, {}, clear=True)
    def test_custom_profile_api_config(self):
        """Test that ~/.config/devos/{profile}-api.json is honored."""
        config_dir = self.home / ".config/devos"
        config_dir.mkdir(parents=True, exist_ok=True)
        api_json = config_dir / "antigravity-kde-api.json"
        api_json.write_text(json.dumps({
            "ANTIGRAVITY_LS_ADDRESS": "127.0.0.1:55555",
            "ANTIGRAVITY_CSRF_TOKEN": "custom-cfg-token",
        }))

        with patch("pathlib.Path.home", return_value=self.home):
            env = connection_environment(profile="antigravity-kde")

        self.assertIsNotNone(env)
        self.assertEqual(env.get("ANTIGRAVITY_LS_ADDRESS"), "127.0.0.1:55555")
        self.assertEqual(env.get("ANTIGRAVITY_CSRF_TOKEN"), "custom-cfg-token")

    @patch.dict(os.environ, {
        "GEMINI_APP_DATA_DIR": "antigravity-kde",
        "ANTIGRAVITY_LS_ADDRESS": "127.0.0.1:42645",
        "ANTIGRAVITY_CSRF_TOKEN": "token-kde-env",
    }, clear=True)
    def test_profile_environment_segregation(self):
        """KDE environment variables should not leak to standard Antigravity profile."""
        with patch("pathlib.Path.home", return_value=self.home):
            kde_env = connection_environment(profile="antigravity-kde")
            # For standard antigravity, with empty home and no process running, it shouldn't inherit KDE env
            ag_env = connection_environment(profile="antigravity")

        self.assertIsNotNone(kde_env)
        self.assertEqual(kde_env.get("ANTIGRAVITY_LS_ADDRESS"), "127.0.0.1:42645")
        self.assertIsNone(ag_env)

    def test_bind_project_creates_workspace(self):
        """Verify bind_project creates a project record and assigns ANTIGRAVITY_PROJECT_ID."""
        project_dir = self.home / "my-test-proj"
        project_dir.mkdir(parents=True, exist_ok=True)
        base_env = {"ANTIGRAVITY_LS_ADDRESS": "127.0.0.1:42645", "ANTIGRAVITY_CSRF_TOKEN": "tok"}

        with patch("pathlib.Path.home", return_value=self.home):
            bound = bind_project(base_env, str(project_dir))

        self.assertIn("ANTIGRAVITY_PROJECT_ID", bound)
        self.assertTrue((self.home / f".gemini/config/projects/{bound['ANTIGRAVITY_PROJECT_ID']}.json").is_file())


if __name__ == "__main__":
    unittest.main()

