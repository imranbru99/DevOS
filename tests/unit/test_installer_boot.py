"""Guards for the live-USB -> installer -> installed-disk path.

Each of these broke a real-hardware boot once: the live session landed on a
bare terminal instead of the installer.
"""

import ast
import configparser
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
CHROOT = ROOT / "build" / "includes.chroot"
CAL = CHROOT / "etc" / "calamares"


def read(path):
    return Path(path).read_text(encoding="utf-8")


class InstallerBootTests(unittest.TestCase):
    def test_security_setup_does_not_hold_up_live_or_installed_boot(self):
        unit = configparser.ConfigParser()
        unit.read(CHROOT / "etc/systemd/system/devos-security-firstboot.service")
        self.assertEqual(unit["Unit"]["ConditionKernelCommandLine"], "!boot=casper")
        self.assertEqual(unit["Service"]["Type"], "exec")

    def test_live_chooser_advances_after_elapsed_time_on_slow_graphics(self):
        path = CHROOT / "usr/local/share/devos/boot_ui.py"
        source = ast.parse(read(path))
        starter = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "Starter")
        tick = next(node for node in starter.body if isinstance(node, ast.FunctionDef) and node.name == "tick")
        clock = iter((105.0, 112.0, 117.0))
        choices = []
        namespace = {"time": SimpleNamespace(monotonic=lambda: next(clock)), "OPTIONS": ("try",)}
        exec(compile(ast.Module(body=[tick], type_ignores=[]), str(path), "exec"), namespace)
        view = SimpleNamespace(_last_tick=100.0, phase=0.0, _bg_accum=0.0, _bgs=(),
                               mode="intro", _intro_left=4.5, _countdown_accum=0.0,
                               countdown=12, cover=lambda: None, update=lambda: None,
                               _update_countdown_label=lambda: None, on_option_chosen=choices.append)
        view.show_chooser = lambda: setattr(view, "mode", "chooser")
        namespace["tick"](view)
        self.assertEqual(view.mode, "chooser")
        namespace["tick"](view)
        self.assertEqual(view.countdown, 5)
        namespace["tick"](view)
        self.assertEqual(choices, ["try"])

    def test_desktop_shortcuts_have_parseable_headers_and_bundled_branding(self):
        desktop = CHROOT / "etc/skel/Desktop"
        icons = CHROOT / "usr/share/icons/hicolor/scalable/apps"
        shortcuts = list(desktop.glob("*.desktop"))
        self.assertTrue(shortcuts)
        for path in shortcuts:
            with self.subTest(shortcut=path.name):
                data = path.read_bytes()
                self.assertTrue(data.startswith(b"[Desktop Entry]\n"))
                fields = dict(re.findall(r"^(Name|Exec|Icon)=(.+)$", data.decode("utf-8"), re.M))
                self.assertEqual(set(fields), {"Name", "Exec", "Icon"})
                if fields["Icon"].startswith("devos-"):
                    self.assertTrue((icons / (fields["Icon"] + ".svg")).is_file())
        self.assertIn("Exec=/usr/local/bin/devos dashboard\n", read(desktop / "devos-dashboard.desktop"))

    def test_sddm_session_is_one_existing_file(self):
        # SDDM takes one session name, not a comma list; an unknown name leaves
        # autologin without a session.
        for rel in ("etc/sddm.conf.d/autologin.conf",
                    "usr/local/sbin/devos-force-installer-session"):
            text = read(CHROOT / rel)
            for value in re.findall(r"^Session=(\S+)$", text, re.M):
                self.assertNotIn(",", value, rel)
                name = value if value.endswith(".desktop") else value + ".desktop"
                self.assertTrue((CHROOT / "usr/share/xsessions" / name).is_file(), value)

    def test_calamares_instances_unique_and_declared(self):
        text = read(CAL / "settings.conf")
        head, seq = text.split("\nsequence:", 1)
        ids = re.findall(r"^\s+- id: (\S+)", head, re.M)
        self.assertEqual(len(ids), len(set(ids)), "duplicate instance id: Calamares will not start")
        for config in re.findall(r"^\s+config: (\S+)", head, re.M):
            self.assertTrue((CAL / "modules" / config).is_file(), config)
        for inst in re.findall(r"^\s+- \w+@(\S+)", seq, re.M):
            self.assertIn(inst, ids, "sequence uses undeclared instance " + inst)

    def test_installer_gui_uses_exit_code_and_sticky_safe_mode(self):
        gui = read(CHROOT / "usr/local/bin/devos-install-gui")
        self.assertIn("rc=$?", gui)
        self.assertIn("/run/devos-installer-safe-mode", gui)
        self.assertNotIn(': > "$log"', gui)

    def test_installed_system_drops_live_session(self):
        fin = read(CHROOT / "usr/local/sbin/devos-install-finalize")
        for needle in ("purge --no-triggers --force-depends casper",
                       "zz-devos-install.conf", "devos-install.desktop",
                       "devos-force-installer.service", "sudoers.d/devos"):
            self.assertIn(needle, fin)


if __name__ == "__main__":
    unittest.main()
