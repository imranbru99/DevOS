"""Hands-free publishes a Passive tray icon, which Plasma keeps in the ^ menu."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "components/assistant/overlay.py"


class VoiceTrayTests(unittest.TestCase):
    def test_hands_free_icon_reports_passive(self):
        text = OVERLAY.read_text(encoding="utf-8")
        tray = text.split("class HandsFreeTray", 1)[1]
        self.assertIn("class HandsFreeTray(QtCore.QObject)", text)
        self.assertNotIn("class HandsFreeTray(QtWidgets.QSystemTrayIcon)", text)
        self.assertIn('return "Passive"', text)
        self.assertIn("RegisterStatusNotifierItem", tray)
        self.assertIn("org.kde.StatusNotifierItem", text)
        self.assertIn('return "devos-voice"', text)
        # The old Active icon is only a fallback when DBus registration fails.
        self.assertIn("QSystemTrayIcon", tray)
        self.assertLess(tray.index("_register_sni"), tray.index("_use_fallback"))


if __name__ == "__main__":
    unittest.main()
