"""Guards for the live-USB -> installer -> installed-disk path.

Each of these broke a real-hardware boot once: the live session landed on a
bare terminal instead of the installer.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHROOT = ROOT / "build" / "includes.chroot"
CAL = CHROOT / "etc" / "calamares"


def read(path):
    return Path(path).read_text(encoding="utf-8")


class InstallerBootTests(unittest.TestCase):
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
