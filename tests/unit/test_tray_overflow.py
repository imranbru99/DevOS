"""The speaker must follow the Plasma 6 tray containment, not only the applet copy."""

import importlib.machinery
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "build/includes.chroot/usr/local/bin/devos-tray-overflow"


def load_overflow():
    loader = importlib.machinery.SourceFileLoader("devos_tray_overflow", str(SCRIPT))
    spec = importlib.util.spec_from_loader("devos_tray_overflow", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


APPLET_HIDDEN = (
    "[Containments][3][Applets][7]\n"
    "plugin=org.kde.plasma.systemtray\n"
    "\n"
    "[Containments][3][Applets][7][Configuration]\n"
    "SystrayContainmentId=19\n"
    "\n"
    "[Containments][3][Applets][7][Configuration][General]\n"
    "showAllItems=false\n"
    "extraItems=org.kde.plasma.volume\n"
    "hiddenItems=org.kde.plasma.volume,devos-sound,microphone\n"
    "knownItems=org.kde.plasma.volume\n"
    "pin=false\n"
    "shownItems=\n"
    "\n"
    "[Containments][19]\n"
    "plugin=org.kde.plasma.private.systemtray\n"
    "\n"
    "[Containments][19][General]\n"
    "showAllItems=false\n"
    "extraItems=org.kde.plasma.volume,org.kde.plasma.networkmanagement\n"
    "knownItems=org.kde.plasma.volume,org.kde.plasma.networkmanagement\n"
    "shownItems=org.kde.plasma.volume\n"
)


class TrayOverflowTests(unittest.TestCase):
    def test_applet_hide_list_does_not_mask_the_live_containment(self):
        mod = load_overflow()
        lines = APPLET_HIDDEN.splitlines(keepends=True)
        want = {"org.kde.plasma.volume", "devos-sound", "microphone"}
        self.assertFalse(mod.policies_satisfied(lines, want))
        updated = "".join(mod.write_policy(lines, want))
        self.assertIn("[Containments][19][General]", updated)
        containment = updated.split("[Containments][19][General]", 1)[1]
        hidden = next(
            line for line in containment.splitlines() if line.startswith("hiddenItems=")
        )
        self.assertIn("org.kde.plasma.volume", hidden)
        self.assertIn("devos-sound", hidden)
        shown = next(
            line for line in containment.splitlines() if line.startswith("shownItems=")
        )
        self.assertEqual(shown, "shownItems=")
        self.assertTrue(mod.policies_satisfied(updated.splitlines(keepends=True), want))

    def test_missing_containment_general_is_created(self):
        mod = load_overflow()
        raw = (
            "[Containments][3][Applets][7]\n"
            "plugin=org.kde.plasma.systemtray\n"
            "\n"
            "[Containments][8]\n"
            "plugin=org.kde.plasma.private.systemtray\n"
            "formfactor=2\n"
        )
        lines = raw.splitlines(keepends=True)
        updated = "".join(mod.write_policy(lines, {"org.kde.plasma.volume"}))
        self.assertIn("[Containments][8][General]", updated)
        self.assertIn("[Containments][3][Applets][7][General]", updated)
        self.assertIn("org.kde.plasma.volume", updated)
        self.assertTrue(
            mod.policies_satisfied(
                updated.splitlines(keepends=True), {"org.kde.plasma.volume"}
            )
        )


if __name__ == "__main__":
    unittest.main()
