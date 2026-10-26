"""Security fixes must target the Ubuntu archive even on a branded DevOS OS."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components/security"))
spec = importlib.util.spec_from_file_location("devos_security_updates", ROOT / "components/security/updates.py")
updates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updates)


class SecurityUpdateTests(unittest.TestCase):
    def test_branded_identity_still_matches_ubuntu_security_origins(self):
        text = updates.unattended_conf().replace("${distro_id}", "DevOS").replace("${distro_codename}", "resolute")
        origins = [line.strip().strip('";') for line in text.splitlines()
                   if line.strip().startswith('"Ubuntu')]
        self.assertEqual(origins, ["Ubuntu:resolute", "Ubuntu:resolute-security",
                                  "UbuntuESMApps:resolute-apps-security",
                                  "UbuntuESM:resolute-infra-security"])
        self.assertNotIn("Ubuntu:resolute-updates", origins)

    def test_enable_disable_preserves_no_automatic_reboot(self):
        with tempfile.TemporaryDirectory() as root:
            for enabled in (True, False):
                updates.set_enabled(enabled, root=root)
                text = (Path(root) / updates.CONF.lstrip("/")).read_text()
                self.assertEqual(updates.parse_enabled(text), enabled)
                self.assertIn('Unattended-Upgrade::Automatic-Reboot "false";', text)

    def test_missing_security_engine_is_a_failure(self):
        calls = []
        def runner(argv):
            calls.append(argv)
            return (127, "", "not installed") if argv[0] == "unattended-upgrade" else (0, "", "")
        result = updates.upgrade_now(runner=runner, snapshot={"status": "UNAVAILABLE"})
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["steps"][-1]["step"], "security")
        self.assertFalse(any(c[0] == "flatpak" for c in calls))

    def test_origin_repair_preserves_disabled_updates_and_custom_settings(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / updates.CONF.lstrip("/")
            path.parent.mkdir(parents=True)
            old = updates.unattended_conf(False).replace('"Ubuntu:', '"${distro_id}:')
            old = old.replace('"UbuntuESMApps:', '"${distro_id}ESMApps:')
            old = old.replace('"UbuntuESM:', '"${distro_id}ESM:')
            old += '\n// Keep my local policy\n'
            path.write_text(old)
            self.assertTrue(updates.repair_origins(root))
            self.assertFalse(updates.parse_enabled(path.read_text()))
            self.assertIn('// Keep my local policy', path.read_text())
            self.assertNotIn('${distro_id}', path.read_text())
            self.assertFalse(updates.repair_origins(root))

    def test_refresh_failure_stops_before_upgrading(self):
        calls = []
        def runner(argv):
            calls.append(argv)
            return 100, "", "repository unavailable"
        result = updates.upgrade_now(runner=runner, snapshot={"status": "CREATED"})
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "apt-get")

    def test_success_refreshes_before_security_and_optional_apps(self):
        calls = []
        def runner(argv):
            calls.append(argv)
            return (127, "", "not installed") if argv[0] == "flatpak" else (0, "", "")
        result = updates.upgrade_now(runner=runner, snapshot={"status": "UNAVAILABLE"})
        self.assertEqual(result["status"], "DONE")
        self.assertEqual([c[0] for c in calls], ["apt-get", "unattended-upgrade", "flatpak"])
        self.assertTrue(result["steps"][-1]["skipped"])

    def test_failed_snapshot_does_not_start_updates(self):
        def runner(argv):
            self.fail("No update command should run after snapshot failure")
        result = updates.upgrade_now(runner=runner, snapshot={"status": "FAILED"})
        self.assertEqual(result["status"], "ABORTED")


if __name__ == "__main__":
    unittest.main()
