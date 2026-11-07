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
from antigravity_connection import (
    connection_environment,
    ensure_connection,
    bind_project,
    hub_ready,
    workspace_ready,
    wait_until_agent_ready,
)


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

    def test_workspace_ready_detects_project_folder(self):
        project = self.home / "proj"
        project.mkdir()
        ws = self.home / ".config/Antigravity-KDE/User/workspaceStorage/abc123"
        ws.mkdir(parents=True)
        (ws / "workspace.json").write_text(json.dumps({"folder": project.as_uri()}))
        with patch("pathlib.Path.home", return_value=self.home):
            self.assertTrue(workspace_ready("antigravity-kde", str(project)))
            self.assertFalse(workspace_ready("antigravity-kde", str(self.home / "other")))

    def test_hub_ready_accepts_test_token_without_live_process(self):
        env = {"ANTIGRAVITY_LS_ADDRESS": "127.0.0.1:9", "ANTIGRAVITY_CSRF_TOKEN": "test-token"}
        with patch("antigravity_connection.connection_environment", return_value=env), \
             patch("antigravity_connection.is_port_alive", return_value=False), \
             patch("antigravity_connection._live_hub_process_for_profile", return_value=None):
            self.assertTrue(hub_ready("antigravity-kde", env))

    def test_wait_until_agent_ready_blocks_until_hub_and_workspace(self):
        project = self.home / "proj"
        project.mkdir()
        env = {"ANTIGRAVITY_LS_ADDRESS": "127.0.0.1:46463", "ANTIGRAVITY_CSRF_TOKEN": "test-token"}
        ticks = {"n": 0}
        events = []

        def hub_side(profile="antigravity", e=None):
            ticks["n"] += 1
            return ticks["n"] >= 3

        def ws_side(profile, proj):
            return ticks["n"] >= 3

        with patch("antigravity_connection.connection_environment", return_value=env), \
             patch("antigravity_connection.hub_ready", side_effect=hub_side), \
             patch("antigravity_connection.workspace_ready", side_effect=ws_side), \
             patch("antigravity_connection.ide_process_uptime", return_value=60.0), \
             patch("antigravity_connection.time.sleep"):
            out = wait_until_agent_ready(
                "antigravity-kde",
                str(project),
                emit=events.append,
                timeout=5,
                launched_at=None,
            )
        self.assertEqual(out, env)
        self.assertGreaterEqual(ticks["n"], 3)

    def test_wait_until_agent_ready_times_out(self):
        clock = {"t": 0.0}

        def mono():
            clock["t"] += 0.6
            return clock["t"]

        with patch("antigravity_connection.connection_environment", return_value=None), \
             patch("antigravity_connection.hub_ready", return_value=False), \
             patch("antigravity_connection.workspace_ready", return_value=False), \
             patch("antigravity_connection.ide_process_uptime", return_value=None), \
             patch("antigravity_connection.time.sleep"), \
             patch("antigravity_connection.time.monotonic", side_effect=mono):
            with self.assertRaises(RuntimeError) as ctx:
                wait_until_agent_ready("antigravity-kde", "/tmp", timeout=1, launched_at=None)
            self.assertIn("did not become ready", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

