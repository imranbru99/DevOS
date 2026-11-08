#!/usr/bin/env python3
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, os.path.join(ROOT, "components", "kids"))
sys.path.insert(0, os.path.join(ROOT, "components", "settings"))
sys.path.insert(0, os.path.join(ROOT, "components", "ai-agent"))


class TestParentalPin(unittest.TestCase):
    def test_set_verify_clear(self):
        import parental

        with tempfile.TemporaryDirectory() as tmp:
            parental.CONFIG_DIR = tmp
            parental.CONFIG_PATH = os.path.join(tmp, "parental.json")
            self.assertFalse(parental.pin_is_set())
            parental.set_pin("2468")
            self.assertTrue(parental.pin_is_set())
            self.assertTrue(parental.verify_pin("2468"))
            self.assertFalse(parental.verify_pin("0000"))
            parental.clear_pin()
            self.assertFalse(parental.pin_is_set())


class TestHwQualify(unittest.TestCase):
    def test_report_shape(self):
        import hw_qualify

        report = hw_qualify.build_report()
        self.assertIn("qualification", report)
        self.assertIn("secure_boot", report)
        self.assertIn("gpu", report)
        self.assertIn("grade", report["qualification"])


class TestSmartShell(unittest.TestCase):
    def test_command_not_found(self):
        import smart_shell

        r = smart_shell.SmartShellHealer.diagnose_failure("foo", "bash: foo: command not found", 127)
        self.assertEqual(r["status"], "AUTO_HEAL_READY")
        self.assertIn("devos app search", r["suggested_fix"])

    def test_hook_prints(self):
        import smart_shell

        hook = smart_shell.bash_hook()
        self.assertIn("PROMPT_COMMAND", hook)


if __name__ == "__main__":
    unittest.main()
