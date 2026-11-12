#!/usr/bin/env python3
import os
import sys
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "components", "features"))

import feature_catalog as catalog
import features_cli as cli
import first_boot_notice as notice


class TestFeaturesAndNotice(unittest.TestCase):
    def test_hidden_system_emoji_launcher_can_be_enabled_and_disabled(self):
        emoji = catalog.feature("emoji")
        with tempfile.TemporaryDirectory() as temporary:
            override = Path(temporary, "override")
            system = Path(temporary, "system")
            system.mkdir()
            launcher = "devos-emoji.desktop"
            source = Path(ROOT, "build/includes.chroot/usr/share/applications", launcher)
            (system / launcher).write_bytes(source.read_bytes())
            with patch.object(cli, "OVERRIDE_DIR", str(override)), patch.object(cli, "SYSTEM_APP_DIR", str(system)):
                self.assertFalse(cli.builtin_on(emoji))
                cli.set_builtin_visibility(emoji, True)
                self.assertTrue(cli.builtin_on(emoji))
                entry = (override / launcher).read_text(encoding="utf-8")
                self.assertIn("X-KDE-Shortcuts=Meta+.", entry)
                self.assertNotIn("Hidden=true", entry)
                cli.set_builtin_visibility(emoji, False)
                self.assertFalse(cli.builtin_on(emoji))
                cli.set_builtin_visibility(emoji, True)
                self.assertEqual((override / launcher).read_text(encoding="utf-8"), entry)

    def test_preserve_writes_empty_app_selection_into_target(self):
        module = Path(ROOT) / ("build/includes.chroot/usr/lib/x86_64-linux-gnu/"
                               "calamares/modules/devospreserve/main.py")
        with tempfile.TemporaryDirectory(dir=ROOT) as target:
            values = {"rootMountPoint": target, "devos_selected_features": "", "username": "devos"}
            calamares = SimpleNamespace(globalstorage=SimpleNamespace(value=values.get))
            with patch.dict(sys.modules, {"libcalamares": calamares}), patch("os.path.ismount", return_value=True):
                runpy.run_path(str(module))["run"]()
            saved = Path(target) / "var/lib/DevOS/install-choices.json"
            self.assertEqual(json.loads(saved.read_text()), {"devos_selected_features": "", "username": "devos"})

    def test_empty_installer_choice_does_not_keep_or_download_apps(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            path = Path(temp) / "choices.json"
            # Unknown packagechooser ids are ignored; empty primary means none.
            path.write_text(json.dumps({
                "devos_selected_features": "",
                "packagechooser_features": "not-a-real-feature",
            }))
            with (
                patch.object(cli, "write_choice") as write_choice,
                patch.object(cli, "installed_ids", return_value=["vscode", "phonelink"]),
                patch.object(cli, "set_feature_menu_visibility") as visibility,
                patch.object(cli, "MARKER_DIR", temp),
                patch.object(cli, "remove_unselected_desktop_shortcuts"),
                patch.object(cli, "webapp_enabled", return_value=False),
                patch.object(cli, "write_webapp_policy"),
                patch.object(cli, "write_state") as state,
                patch.object(cli, "enable_service") as service,
            ):
                self.assertEqual(cli.installer_plan(str(path)), 0)
            write_choice.assert_called_once_with([])
            self.assertEqual(state.call_args.kwargs["pending"], [])
            self.assertEqual(set(state.call_args.kwargs["removing"]), {"vscode", "phonelink"})
            visibility.assert_any_call(catalog.feature("phonelink"), False)
            visibility.assert_any_call(catalog.feature("libreoffice"), False)
            service.assert_called_once()
            self.assertFalse(path.exists())

    def test_empty_primary_falls_back_to_packagechooser_features(self):
        # Calamares packageChoice sometimes survives when the DevOS GS key is empty.
        self.assertEqual(
            cli.selection_from_gs({
                "devos_selected_features": "",
                "packagechooser_features": "chrome,vscode",
            }),
            catalog.parse_selection("chrome,vscode"),
        )
        self.assertEqual(
            cli.selection_from_gs({"devos_selected_features": "chrome"}),
            ["chrome"],
        )

    def test_later_ids_install_nothing_optional(self):
        self.assertEqual(catalog.later_ids(), [])

    def test_phonelink_ships_hidden_until_ticked(self):
        phonelink = catalog.feature("phonelink")
        self.assertIsNotNone(phonelink)
        self.assertIn("devos-phonelink.desktop", phonelink["builtin"]["desktop"])
        hidden = Path(ROOT) / "build/includes.chroot/usr/local/share/applications/devos-phonelink.desktop"
        self.assertTrue(hidden.is_file())
        self.assertIn("X-DevOS-Hidden=true", hidden.read_text(encoding="utf-8"))

    def test_installer_plan_enables_only_ticked_builtins(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            path = Path(temp) / "choices.json"
            path.write_text(json.dumps({"devos_selected_features": "phonelink,devosnotes"}))
            with (
                patch.object(cli, "write_choice"),
                patch.object(cli, "installed_ids", return_value=["phonelink", "devosnotes", "share"]),
                patch.object(cli, "set_feature_menu_visibility") as visibility,
                patch.object(cli, "MARKER_DIR", temp),
                patch.object(cli, "remove_unselected_desktop_shortcuts"),
                patch.object(cli, "webapp_enabled", return_value=False),
                patch.object(cli, "write_webapp_policy"),
                patch.object(cli, "write_state"),
                patch.object(cli, "enable_service"),
            ):
                self.assertEqual(cli.installer_plan(str(path)), 0)
            enabled = {call.args[0]["id"] for call in visibility.call_args_list if call.args[1] is True}
            disabled = {call.args[0]["id"] for call in visibility.call_args_list if call.args[1] is False}
            self.assertIn("phonelink", enabled)
            self.assertIn("devosnotes", enabled)
            self.assertNotIn("phonelink", disabled)
            self.assertIn("share", disabled)
            self.assertIn("backup", disabled)

    def test_missing_explicit_choice_ignores_legacy_or_unrelated_keys(self):
        # Unknown "features" / garbage ids yield nothing; known packagechooser ids count.
        self.assertEqual(
            cli.selection_from_gs({"features": "whatsapp", "packagechooser_features": "not-a-feature"}),
            None,
        )
        self.assertEqual(
            cli.selection_from_gs({"packagechooser_features": "vscode"}),
            ["vscode"],
        )
        self.assertIsNone(cli.selection_from_gs({"devos_selected_features": ["vscode", 1]}))
        self.assertEqual(cli.selection_from_gs({"devos_selected_features": ""}), [])
        self.assertEqual(cli.selection_from_gs({"devos_selected_features": ["vscode"]}), ["vscode"])

    def test_browser_policy_uses_only_chosen_active_web_apps(self):
        windows = catalog.feature("winapp")
        other = catalog.feature("m365web")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            stock = Path(ROOT, "build/includes.chroot/usr/share/applications/devos-web-winapp.desktop")
            win = path / "winapp.desktop"
            win.write_bytes(stock.read_bytes())
            office = path / "m365web.desktop"
            office.write_text(cli.webapp_entry(other), encoding="utf-8")
            policy = path / "policy.json"
            with patch.object(cli, "webapp_path", side_effect=lambda f: str(path / (f["id"] + ".desktop"))):
                self.assertFalse(cli.is_installed(windows))
                with patch.object(cli, "read_choice", return_value=["winapp"]):
                    cli.write_webapp_policy(str(policy))
                    self.assertFalse(policy.exists())
                    win.write_text(cli.webapp_entry(windows), encoding="utf-8")
                    cli.write_webapp_policy(str(policy))
                    data = json.loads(policy.read_text(encoding="utf-8"))
                    self.assertEqual([entry["url"] for entry in data["WebAppInstallForceList"]],
                                     [windows["webapp"]["url"]])
                with patch.object(cli, "read_choice", return_value=[]):
                    cli.write_webapp_policy(str(policy))
                    self.assertFalse(policy.exists())

    def test_winapps_packages_valid(self):
        """Verify winapps does not request non-existent packages like dxvk/vkd3d."""
        winapps = catalog.feature("winapps")
        self.assertIsNotNone(winapps)
        self.assertNotIn("dxvk", winapps.get("apt", []))
        self.assertNotIn("vkd3d", winapps.get("apt", []))
        self.assertIn("wine", winapps.get("apt", []))
        self.assertIn("wine64", winapps.get("apt", []))
        self.assertIn("winetricks", winapps.get("apt", []))
        self.assertIn("libvkd3d1", winapps.get("apt", []))

    def test_notice_messages(self):
        title, body = notice.start_message({"pending": ["winapps"]})
        self.assertEqual(title, "Setting up your apps")
        self.assertIn("1 app you picked during install", body)

        done_title, done_body = notice.done_message({"pending": [], "failed": {}})
        self.assertEqual(done_title, "Your apps are ready")

        fail_title, fail_body = notice.done_message({"pending": ["winapps"], "failed": {"winapps": "error"}})
        self.assertEqual(fail_title, "Some apps didn't install")
        self.assertIn("Windows apps (.exe, .msi)", fail_body)

    def test_needs_notice_with_done_marker(self):
        with tempfile.TemporaryDirectory() as td:
            marker = os.path.join(td, "first_boot_notice.done")
            orig_marker = notice.DONE_MARKER
            try:
                notice.DONE_MARKER = marker
                # Without marker and pending apps -> needs notice
                self.assertTrue(notice.needs_notice({"pending": ["winapps"]}))

                # With marker and not running -> suppressed
                with open(marker, "w") as f:
                    f.write("1")
                self.assertFalse(notice.needs_notice({"pending": ["winapps"], "running": False}))

                # With marker but actively running -> needs notice
                self.assertTrue(notice.needs_notice({"pending": ["winapps"], "running": True}))
            finally:
                notice.DONE_MARKER = orig_marker

    def test_sddm_devos_theme_files_exist(self):
        theme_dir = os.path.join(ROOT, "build", "includes.chroot", "usr", "share", "sddm", "themes", "devos")
        self.assertTrue(os.path.isdir(theme_dir))
        self.assertTrue(os.path.isfile(os.path.join(theme_dir, "Main.qml")))
        self.assertTrue(os.path.isfile(os.path.join(theme_dir, "theme.conf")))
        self.assertTrue(os.path.isfile(os.path.join(theme_dir, "metadata.desktop")))
        self.assertTrue(os.path.isfile(os.path.join(theme_dir, "background.png")))
        self.assertTrue(os.path.isfile(os.path.join(theme_dir, "logo.png")))

    def test_sddm_config_uses_devos_theme(self):
        conf_path = os.path.join(ROOT, "build", "includes.chroot", "etc", "sddm.conf.d", "devos-theme.conf")
        with open(conf_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Current=devos", content)
        self.assertIn("DisplayServer=x11", content)


if __name__ == "__main__":
    unittest.main()
