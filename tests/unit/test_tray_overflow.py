"""Plasma 6 keeps tray visibility on the private system-tray containment."""
import importlib.machinery
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "build/includes.chroot/usr/local/bin/devos-tray-overflow"


def load():
    loader = importlib.machinery.SourceFileLoader("devos_tray_overflow", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


SAMPLE = """\
[Containments][3][Applets][7]
plugin=org.kde.plasma.systemtray

[Containments][3][Applets][7][Configuration]
SystrayContainmentId=8

[Containments][3][Applets][7][Configuration][General]
showAllItems=false
hiddenItems=org.kde.plasma.clipboard
shownItems=
scaleIconsToFit=true

[Containments][8]
plugin=org.kde.plasma.private.systemtray

[Containments][8][General]
showAllItems=true
hiddenItems=org.kde.plasma.clipboard
shownItems=microphone,org.kde.plasma.volume
scaleIconsToFit=true

[Containments][3][Applets][8]
plugin=org.kde.plasma.digitalclock
"""


class TrayOverflowTests(unittest.TestCase):
    def test_hide_list_is_written_to_the_private_containment(self):
        mod = load()
        lines = SAMPLE.splitlines(keepends=True)
        hidden = {"devos-voice", "microphone", "org.kde.plasma.volume"}
        updated = "".join(mod.write_policy(lines, hidden))
        self.assertIn("SystrayContainmentId=8", updated)
        self.assertIn("scaleIconsToFit=true", updated)
        self.assertIn("plugin=org.kde.plasma.digitalclock", updated)
        containment = updated.split("[Containments][8][General]", 1)[1].split("[Containments][3][Applets][8]", 1)[0]
        self.assertIn("devos-voice", containment)
        self.assertIn("microphone", containment)
        self.assertIn("org.kde.plasma.volume", containment)
        self.assertNotIn("shownItems=microphone", containment)
        self.assertNotIn("pin=", containment)
        self.assertIn("showAllItems=false", containment)
        applet = updated.split("[Containments][3][Applets][7][Configuration][General]", 1)[1].split(
            "[Containments][8]", 1
        )[0]
        self.assertIn("devos-voice", applet)
        self.assertIn("pin=false", applet)

    def test_applet_list_alone_is_not_enough_when_a_containment_exists(self):
        mod = load()
        lines = SAMPLE.splitlines(keepends=True)
        want = {"devos-voice", "microphone"}
        self.assertFalse(mod.policy_is_complete(lines, want))
        updated = mod.write_policy(lines, want)
        self.assertTrue(mod.policy_is_complete(updated, want))

    def test_live_script_updates_the_tray_without_reloading_the_footer(self):
        mod = load()
        script = mod.live_hide_script({"devos-voice", "microphone"})
        self.assertIn('"devos-voice"', script)
        self.assertIn('"microphone"', script)
        self.assertIn('writeConfig("hiddenItems"', script)
        self.assertIn("desktopById", script)
        self.assertNotIn("reloadConfig", script)
        self.assertNotIn("icontasks", script)
        self.assertNotIn("restart", script)
        self.assertNotIn("plasmashell", script)
        once = SCRIPT.read_text(encoding="utf-8").split("def once", 1)[1].split("def watch", 1)[0]
        self.assertNotIn("restart_plasmashell()", once)
        self.assertIn("apply_live", once)

    def test_skel_hides_the_microphone_in_the_containment_plasma_reads(self):
        mod = load()
        skel = (
            ROOT / "build/includes.chroot/etc/skel/.config/plasma-org.kde.plasma.desktop-appletsrc"
        ).read_text(encoding="utf-8")
        self.assertIn("plugin=org.kde.plasma.private.systemtray", skel)
        self.assertIn("SystrayContainmentId=10", skel)
        lines = skel.splitlines(keepends=True)
        self.assertEqual(mod.systray_containment_ids(lines), ["10"])
        self.assertTrue(mod.policy_is_complete(lines, set(mod.ALWAYS_HIDE)))


if __name__ == "__main__":
    unittest.main()
