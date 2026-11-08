#!/usr/bin/env python3
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "install_ping", ROOT / "components" / "install-ping" / "install_ping.py"
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


class InstallPingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.pending = self.dir / "install-ping.pending"
        self.done = self.dir / "install-ping.done"
        self._patchers = [
            mock.patch.object(mod, "STATE_DIR", self.dir),
            mock.patch.object(mod, "PENDING", self.pending),
            mock.patch.object(mod, "DONE", self.done),
            mock.patch.object(mod.subprocess, "run", return_value=mock.Mock()),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        self.tmp.cleanup()

    def test_mark_pending_then_once_success(self):
        mod.mark_pending()
        self.assertTrue(self.pending.is_file())
        with mock.patch.object(mod, "send_ping", return_value=True):
            self.assertEqual(mod.run_once(), 0)
        self.assertTrue(self.done.is_file())
        self.assertFalse(self.pending.is_file())

    def test_once_fails_keeps_pending(self):
        mod.mark_pending()
        with mock.patch.object(mod, "send_ping", return_value=False):
            self.assertEqual(mod.run_once(), 1)
        self.assertTrue(self.pending.is_file())
        self.assertFalse(self.done.is_file())

    def test_done_skips(self):
        self.done.write_text("done\n")
        with mock.patch.object(mod, "send_ping") as ping:
            self.assertEqual(mod.run_once(), 0)
            ping.assert_not_called()


if __name__ == "__main__":
    unittest.main()
