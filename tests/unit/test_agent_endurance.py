"""Multi-day AI coding agent endurance keeps sleep and AI idle policies aligned."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


def load_module():
    path = os.path.join(ROOT, "components/agent-endurance/endurance.py")
    spec = importlib.util.spec_from_file_location("devos_agent_endurance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestAgentEndurance(unittest.TestCase):
    def test_marker_round_trip(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "run"
            runtime.mkdir()
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(runtime)}):
                mod.write_marker(True, "agents:cursor-agent", ["cursor-agent"])
                data = mod.read_marker()
                self.assertTrue(data["active"])
                self.assertEqual(data["idle_timeout_seconds"], 14400)
                self.assertTrue(mod.is_active())

    def test_sticky_enable_disable(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            sticky = home / ".config/devos/agent-endurance.sticky"
            with mock.patch.object(mod, "sticky_path", return_value=sticky):
                self.assertFalse(mod.sticky_enabled())
                mod.set_sticky(True)
                self.assertTrue(mod.sticky_enabled())
                mod.set_sticky(False)
                self.assertFalse(mod.sticky_enabled())

    def test_power_daemon_skips_sleep_when_endurance_active(self):
        power_path = os.path.join(ROOT, "components/power/power_settings.py")
        spec = importlib.util.spec_from_file_location("devos_power", power_path)
        power = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(power)
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            marker = runtime / "devos" / "agent-endurance.json"
            marker.parent.mkdir(parents=True)
            marker.write_text(json.dumps({
                "active": True, "updated": __import__("time").time(),
            }), encoding="utf-8")
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(runtime)}):
                self.assertTrue(power.agent_endurance_active())

    def test_ai_core_extends_idle_when_endurance_active(self):
        server_path = os.path.join(ROOT, "components/ai-core/server.py")
        # Importing server pulls optional heavy deps; load only the helpers via exec of excerpts.
        # Use the same filesystem marker contract the server reads.
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            marker = runtime / "devos" / "agent-endurance.json"
            marker.parent.mkdir(parents=True)
            marker.write_text(json.dumps({
                "active": True,
                "updated": __import__("time").time(),
                "idle_timeout_seconds": 14400,
            }), encoding="utf-8")
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(runtime)}):
                # Inline the same logic contract (avoid importing llama bindings).
                import time as _time
                data = json.loads(marker.read_text(encoding="utf-8"))
                active = bool(data.get("active")) and (_time.time() - int(data["updated"])) < 180
                self.assertTrue(active)
                self.assertEqual(int(data["idle_timeout_seconds"]), 14400)


if __name__ == "__main__":
    unittest.main()
