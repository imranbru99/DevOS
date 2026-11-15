"""The KDE keyring toast stays gone without opening the KWallet window."""

import importlib.machinery
import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "build/includes.chroot/usr/local/bin/devos-kwallet-compat"
CHROOT = ROOT / "build/includes.chroot"


def load_compat():
    loader = importlib.machinery.SourceFileLoader("devos_kwallet_compat", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TestKWalletCompatFiles(unittest.TestCase):
    def test_real_wallet_stays_disabled(self):
        # The unlock dialog blocks the screen. The silent service replaces it.
        for rel in (
            "etc/xdg/kwalletrc",
            "etc/skel/.config/kwalletrc",
        ):
            text = (CHROOT / rel).read_text(encoding="utf-8")
            self.assertIn("Enabled=false", text)
        for rel in ("etc/xdg/kded5rc", "etc/xdg/kded6rc"):
            text = (CHROOT / rel).read_text(encoding="utf-8")
            self.assertIn("autoload=false", text)

    def test_service_answers_legacy_and_current_names(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        desktop = (CHROOT / "etc/xdg/autostart/devos-kwallet-compat.desktop").read_text(encoding="utf-8")
        self.assertIn("Exec=/usr/local/bin/devos-kwallet-compat", desktop)
        self.assertIn("X-KDE-autostart-phase=0", desktop)
        self.assertIn("NoDisplay=true", desktop)
        for name in ("org.kde.kwalletd", "org.kde.kwalletd5", "org.kde.kwalletd6"):
            body = (CHROOT / "usr/local/share/dbus-1/services" / f"{name}.service").read_text(encoding="utf-8")
            self.assertIn(f"Name={name}", body)
            self.assertIn("Exec=/usr/local/bin/devos-kwallet-compat", body)
        launcher = (CHROOT / "usr/local/share/applications/kwalletd.desktop").read_text(encoding="utf-8")
        self.assertIn("NoDisplay=true", launcher)
        apply_desktop = (CHROOT / "usr/local/bin/devos-apply-desktop").read_text(encoding="utf-8")
        self.assertIn("devos-kwallet-compat", apply_desktop)

    def test_ides_do_not_force_plaintext_keyring(self):
        # --password-store=basic makes safeStorage report encryption unavailable,
        # which is the toast in the screenshot. The silent wallet is the store.
        for rel in (
            "usr/local/bin/antigravity-kde",
            "usr/local/bin/devos-antigravity",
        ):
            text = (CHROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn("\n    --password-store=basic", text)
            self.assertNotIn("\n    --password-store=basic \\", text)
            self.assertIn("devos-kwallet-compat", text)
        # Agent browsers still isolate themselves from the desktop Chrome profile.
        agent = (ROOT / "components/ai-agent/agent_browser.py").read_text(encoding="utf-8")
        self.assertIn("--password-store=basic", agent)


class TestWalletStore(unittest.TestCase):
    def setUp(self):
        self.module = load_compat()
        self.tmp = tempfile.TemporaryDirectory()
        self.store = self.module.WalletStore(Path(self.tmp.name) / "wallet.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_chromium_key_roundtrip(self):
        self.assertTrue(self.store.is_enabled())
        self.assertEqual(self.store.network_wallet(), "kdewallet")
        handle = self.store.open_wallet("kdewallet", "chromium")
        self.assertGreater(handle, 0)
        folder = "Chromium Keys"
        key = "Chromium Safe Storage"
        self.assertFalse(self.store.has_folder(handle, folder, "chromium"))
        self.assertTrue(self.store.create_folder(handle, folder, "chromium"))
        self.assertTrue(self.store.has_folder(handle, folder, "chromium"))
        self.assertFalse(self.store.has_entry(handle, folder, key, "chromium"))
        self.assertEqual(self.store.write_password(handle, folder, key, "c2VjcmV0LWtleQ==", "chromium"), 0)
        self.assertTrue(self.store.has_entry(handle, folder, key, "chromium"))
        self.assertEqual(self.store.entry_type(handle, folder, key, "chromium"), 1)
        self.assertEqual(self.store.read_password(handle, folder, key, "chromium"), "c2VjcmV0LWtleQ==")
        mode = stat.S_IMODE(os.stat(self.store.path).st_mode)
        self.assertEqual(mode, 0o600)
        reloaded = self.module.WalletStore(self.store.path)
        self.assertEqual(reloaded.read_password(handle, folder, key, "chromium"), "c2VjcmV0LWtleQ==")
        self.assertEqual(self.store.remove_entry(handle, folder, key, "chromium"), 0)
        self.assertFalse(self.store.has_entry(handle, folder, key, "chromium"))
        self.assertEqual(self.store.close_wallet(handle, False, "chromium"), 0)

    def test_rejects_bad_handle_and_huge_secret(self):
        self.assertFalse(self.store.has_entry(99, "Chromium Keys", "Chromium Safe Storage", "app"))
        handle = self.store.open_wallet("kdewallet", "app")
        self.assertEqual(self.store.write_password(handle, "Chromium Keys", "k", "x" * (64 * 1024 + 1), "app"), 1)
        self.assertFalse(self.store.has_entry(handle, "Chromium Keys", "k", "app"))


class TestKWalletDBus(unittest.TestCase):
    def test_probe_on_legacy_path(self):
        gi = importlib.util.find_spec("gi")
        dbus_daemon = subprocess.call(["bash", "-lc", "command -v dbus-daemon"], stdout=subprocess.DEVNULL)
        if gi is None or dbus_daemon != 0:
            self.skipTest("python3-gi and dbus-daemon are required")
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "wallet.json"
            runtime = Path(tmp) / "runtime"
            runtime.mkdir()
            client = textwrap.dedent(
                f"""
                import importlib.machinery
                import importlib.util
                import os, sys, time
                os.environ["DEVOS_KWALLET_STORE"] = {str(store)!r}
                os.environ["XDG_RUNTIME_DIR"] = {str(runtime)!r}
                loader = importlib.machinery.SourceFileLoader("compat", {str(SCRIPT)!r})
                spec = importlib.util.spec_from_loader(loader.name, loader)
                compat = importlib.util.module_from_spec(spec)
                loader.exec_module(compat)
                import subprocess
                from gi.repository import Gio, GLib
                proc = subprocess.Popen([{str(SCRIPT)!r}], env=os.environ.copy())
                try:
                    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                    deadline = time.time() + 10
                    while time.time() < deadline and not compat.name_is_owned("org.kde.kwalletd"):
                        time.sleep(0.05)
                    for bus_name in ("org.kde.kwalletd", "org.kde.kwalletd5", "org.kde.kwalletd6"):
                        if not compat.name_is_owned(bus_name):
                            sys.exit("bus name was not claimed: " + bus_name)
                    for path in ("/modules/kwalletd", "/modules/kwalletd5", "/modules/kwalletd6"):
                        proxy = Gio.DBusProxy.new_sync(
                            bus, Gio.DBusProxyFlags.NONE, None,
                            "org.kde.kwalletd", path, "org.kde.KWallet", None)
                        enabled = proxy.call_sync("isEnabled", None, Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
                        wallet = proxy.call_sync("networkWallet", None, Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
                        if enabled is not True or wallet != "kdewallet":
                            sys.exit(f"bad probe on {{path}}: {{enabled}} {{wallet}}")
                    handle = proxy.call_sync(
                        "open", GLib.Variant("(sxs)", ("kdewallet", 0, "chromium")),
                        Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
                    wrote = proxy.call_sync(
                        "writePassword",
                        GLib.Variant("(issss)", (handle, "Chromium Keys", "Chromium Safe Storage", "abc", "chromium")),
                        Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
                    kind = proxy.call_sync(
                        "entryType",
                        GLib.Variant("(isss)", (handle, "Chromium Keys", "Chromium Safe Storage", "chromium")),
                        Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
                    secret = proxy.call_sync(
                        "readPassword",
                        GLib.Variant("(isss)", (handle, "Chromium Keys", "Chromium Safe Storage", "chromium")),
                        Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
                    if wrote != 0 or kind != 1 or secret != "abc":
                        sys.exit(f"roundtrip failed {{wrote}} {{kind}} {{secret}}")
                    # A second copy must leave the first owning the name.
                    second = subprocess.run([{str(SCRIPT)!r}], env=os.environ.copy(), timeout=20)
                    if second.returncode != 0 or not compat.name_is_owned("org.kde.kwalletd"):
                        sys.exit(f"second copy disturbed the service: {{second.returncode}}")
                finally:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                """
            )
            env = os.environ.copy()
            env["DEVOS_KWALLET_STORE"] = str(store)
            env["XDG_RUNTIME_DIR"] = str(runtime)
            result = subprocess.run(
                ["dbus-run-session", "--", sys.executable, "-c", client],
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
            )
            if result.returncode != 0:
                self.fail(result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
