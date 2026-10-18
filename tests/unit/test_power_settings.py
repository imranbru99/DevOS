"""
Unit tests for DevOS Power & Sleep Settings Manager.
Covers config loading/saving, power source telemetry, screen timeout calculations,
and assistant routing for power & sleep settings.
"""

import os
import sys
import tempfile
import unittest

SYS_PATH_POWER = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/power"))
SYS_PATH_ASSISTANT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/assistant"))
sys.path.insert(0, SYS_PATH_POWER)
sys.path.insert(0, SYS_PATH_ASSISTANT)

import power_settings as ps
from tools import route, Action


class TestPowerSettings(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg_path = os.path.join(self.tmp, "power.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_config(self):
        cfg = ps.load_config(os.path.join(self.tmp, "nonexistent.json"))
        self.assertEqual(cfg["screen_timeout_plugged"], 600)
        self.assertEqual(cfg["screen_timeout_battery"], 300)
        self.assertEqual(cfg["sleep_timeout_plugged"], 1800)
        self.assertEqual(cfg["power_mode"], "balanced")

    def test_save_and_load_config(self):
        custom = {
            "screen_timeout_plugged": 300,
            "sleep_timeout_plugged": 900,
            "power_mode": "performance",
        }
        ok = ps.save_config(custom, self.cfg_path)
        self.assertTrue(ok)
        loaded = ps.load_config(self.cfg_path)
        self.assertEqual(loaded["screen_timeout_plugged"], 300)
        self.assertEqual(loaded["sleep_timeout_plugged"], 900)
        self.assertEqual(loaded["power_mode"], "performance")

    def test_timeout_choices_defined(self):
        self.assertIn(60, ps.TIMEOUT_MAP)
        self.assertIn(300, ps.TIMEOUT_MAP)
        self.assertIn(600, ps.TIMEOUT_MAP)
        self.assertIn(1800, ps.TIMEOUT_MAP)
        self.assertIn(0, ps.TIMEOUT_MAP)
        self.assertEqual(ps.TIMEOUT_MAP[0], "Never")

    def test_power_source_detection(self):
        src = ps.get_power_source()
        self.assertIn("has_battery", src)
        self.assertIn("charging", src)
        self.assertIn("status", src)

    def test_assistant_routes_power_settings(self):
        queries = [
            "open power settings",
            "sleep time setting",
            "screen timeout",
            "turn off screen settings",
            "change sleep time",
        ]
        for q in queries:
            res = route(q)
            self.assertTrue(res.handled, f"Query '{q}' was not handled")
            self.assertEqual(len(res.actions), 1, f"Expected 1 action for '{q}'")
            action = res.actions[0]
            self.assertEqual(action.name, "open_settings")
            self.assertEqual(action.args.get("page"), "devos-power")

    def test_assistant_routes_power_actions(self):
        res_shutdown = route("shut down the pc")
        self.assertTrue(res_shutdown.handled)
        self.assertEqual(res_shutdown.actions[0].name, "power")
        self.assertEqual(res_shutdown.actions[0].args.get("op"), "poweroff")

        res_restart = route("restart this computer")
        self.assertTrue(res_restart.handled)
        self.assertEqual(res_restart.actions[0].name, "power")
        self.assertEqual(res_restart.actions[0].args.get("op"), "reboot")

        res_sleep = route("put computer to sleep")
        self.assertTrue(res_sleep.handled)
        self.assertEqual(res_sleep.actions[0].name, "power")
        self.assertEqual(res_sleep.actions[0].args.get("op"), "suspend")


if __name__ == "__main__":
    unittest.main()
