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
        general = updated.split("[Containments][3][Applets][7][General]", 1)[1].split("[Containments][3][Applets][7][Configuration]", 1)[0]
        self.assertIn("devos-voice", general)
        self.assertIn("microphone", general)
        self.assertIn("showAllItems=false", general)
        self.assertNotIn("shownItems=microphone", general)

    def test_applet_list_alone_is_not_enough_when_a_containment_exists(self):
        mod = load()
        lines = SAMPLE.splitlines(keepends=True)
        want = {"devos-voice", "microphone"}
        self.assertFalse(mod.policy_is_complete(lines, want))
        updated = mod.write_policy(lines, want)
        self.assertTrue(mod.policy_is_complete(updated, want))

    def test_live_script_updates_the_tray_without_reloading_the_footer(self):
        mod = load()
        script = mod.live_hide_script({"devos-voice", "microphone", "org.kde.plasma.cameraindicator"})
        self.assertIn('"devos-voice"', script)
        self.assertIn('"microphone"', script)
        self.assertIn('"org.kde.plasma.cameraindicator"', script)
        self.assertIn('writeConfig("hiddenItems"', script)
        self.assertIn('writeConfig("showAllItems", false)', script)
        self.assertIn('writeConfig("shownItems"', script)
        self.assertIn("desktopById", script)
        # The panel widget itself is a target. A stale containment id must not
        # be the only place the list is written.
        self.assertIn("targets = [widgets[w]]", script)
        self.assertIn("panelList = panels()", script)
        self.assertNotIn("var panels = panels()", script)
        self.assertIn("devos-tray-ok", script)
        self.assertIn("busctl", SCRIPT.read_text(encoding="utf-8"))
        self.assertIn("microphone moved under the status menu", SCRIPT.read_text(encoding="utf-8"))
        self.assertNotIn("reloadConfig", script)
        self.assertNotIn("icontasks", script)
        self.assertNotIn("restart", script)
        self.assertNotIn("plasmashell", script)
        self.assertNotIn("hiding", script)
        pin = mod.pin_footer_script()
        self.assertIn("panelList = panels()", pin)
        self.assertNotIn("var panels = panels()", pin)
        self.assertIn('hiding = "none"', pin)
        self.assertIn("dodgewindows", pin)
        self.assertIn("footer-none", pin)
        self.assertNotIn("reloadConfig", pin)
        self.assertNotIn("plasmashell", pin)
        once = SCRIPT.read_text(encoding="utf-8").split("def once", 1)[1].split("def watch", 1)[0]
        self.assertNotIn("restart_plasmashell()", once)
        self.assertIn("apply_live", once)
        self.assertIn("pin_footer", once)
        self.assertIn("notify_running_shell", once)

    def test_notify_pokes_the_running_tray_without_restarting_it(self):
        mod = load()
        lines = SAMPLE.splitlines(keepends=True)
        hidden = {"devos-voice", "org.kde.plasma.cameraindicator"}
        commands = mod.notify_commands(lines, hidden)
        self.assertTrue(commands)
        joined = "\n".join(" ".join(cmd) for cmd in commands)
        self.assertIn("--notify", joined)
        self.assertIn("hiddenItems", joined)
        self.assertIn("showAllItems", joined)
        self.assertIn("--group 8", joined)
        self.assertIn("devos-voice", joined)
        self.assertNotIn("plasmashell", joined)
        self.assertNotIn("reloadConfig", joined)

    def test_skel_hides_the_microphone_in_the_containment_plasma_reads(self):
        mod = load()
        skel = (
            ROOT / "build/includes.chroot/etc/skel/.config/plasma-org.kde.plasma.desktop-appletsrc"
        ).read_text(encoding="utf-8")
        self.assertIn("plugin=org.kde.plasma.private.systemtray", skel)
        self.assertIn("SystrayContainmentId=10", skel)
        lines = skel.splitlines(keepends=True)
        self.assertEqual(mod.systray_containment_ids(lines), ["10"])
        self.assertIn("[Containments][3][Applets][7][General]", skel)
        self.assertTrue(mod.policy_is_complete(lines, set(mod.ALWAYS_HIDE)))


if __name__ == "__main__":
    unittest.main()
