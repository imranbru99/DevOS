import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys_path = os.path.join(ROOT, "components", "clipboard")
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from PyQt5 import QtWidgets

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

import quick_selection


class TestQuickSelection(unittest.TestCase):
    def test_get_and_clear_primary_text(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="test selection")
            text = quick_selection.get_primary_text()
            self.assertEqual(text, "test selection")

            quick_selection.clear_primary_text()
            mock_run.assert_called_with(
                ["wl-copy", "--clear", "--primary"],
                check=False,
                stdout=subprocess.DEVNULL if hasattr(subprocess, "DEVNULL") else None,
                stderr=subprocess.DEVNULL if hasattr(subprocess, "DEVNULL") else None,
                timeout=0.2,
            )

    def test_selection_pill_ui_has_only_copy_and_close(self):
        pill = quick_selection.SelectionPill()
        self.assertTrue(hasattr(pill, "btn_copy"))
        self.assertTrue(hasattr(pill, "btn_close"))
        self.assertEqual(pill.btn_copy.text(), "📋 Copy")
        self.assertEqual(pill.btn_close.text(), "✕")

        # Must not contain Cut, Capture, AI, Search in the layout
        buttons = pill.findChildren(QtWidgets.QPushButton)
        button_texts = [b.text() for b in buttons]
        self.assertIn("📋 Copy", button_texts)
        self.assertIn("✕", button_texts)
        self.assertNotIn("✂️ Cut", button_texts)
        self.assertNotIn("📸 Capture", button_texts)
        self.assertNotIn("🤖 AI", button_texts)
        self.assertNotIn("🔍 Search", button_texts)

    def test_popup_and_copy(self):
        pill = quick_selection.SelectionPill()
        pill.popup_for_text("Hello DevOS", x=200, y=200)
        self.assertEqual(pill.selected_text, "Hello DevOS")
        self.assertTrue(pill.isVisible())

        with patch("subprocess.run") as mock_run:
            pill.on_copy(deselect=False)
            self.assertFalse(pill.isVisible())


if __name__ == "__main__":
    unittest.main()
