"""Load the real greeter in isolation; never contact the display manager."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
THEME = ROOT / "build/includes.chroot/usr/share/sddm/themes/devos"
GREETER = shutil.which("sddm-greeter-qt6")


@unittest.skipUnless(GREETER, "requires the Qt 6 SDDM greeter")
class LoginThemeRuntimeTests(unittest.TestCase):
    def test_theme_loads_and_resolves_account_and_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            theme = Path(temporary) / "theme"
            shutil.copytree(THEME, theme)
            main = theme / "Main.qml"
            source = main.read_text()
            end = source.rfind("}")
            # Test mode supplies the real SDDM models and a disconnected proxy.
            source = source[:end] + '''
    Timer {
        interval: 200; running: true
        onTriggered: {
            if (users.count > 0 && (!root.userName || !root.displayName))
                throw new Error("Account model did not resolve")
            if (sessions.count > 0 && sessions.currentIndex < 0)
                throw new Error("No desktop session selected")
            console.log("DEVOS_THEME_READY")
        }
    }
''' + source[end:]
            main.write_text(source)
            environment = dict(os.environ, QT_QPA_PLATFORM="offscreen",
                               QT_QUICK_BACKEND="software",
                               QT_QPA_PLATFORMTHEME="", QT_STYLE_OVERRIDE="",
                               QT_QUICK_CONTROLS_STYLE="Basic")
            process = subprocess.Popen(
                [GREETER, "--test-mode", "--theme", str(theme)],
                env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True)
            try:
                output, _ = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                output, _ = process.communicate(timeout=5)
            self.assertIn("DEVOS_THEME_READY", output, output)
            for error in ("ReferenceError", "TypeError", "Error:",
                          "is not installed", "Cannot assign", "failed to load"):
                self.assertNotIn(error, output, output)


if __name__ == "__main__":
    unittest.main()
