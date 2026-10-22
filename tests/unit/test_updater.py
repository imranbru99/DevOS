import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


updater = load("devos_updater", ROOT / "components/updater/updater.py")
packager = load("devos_packager", ROOT / "tools/package-update.py")


def bundle(entries):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as archive:
        for name, body, kind in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(body) if kind == tarfile.REGTYPE else 0
            archive.addfile(member, io.BytesIO(body) if member.isfile() else None)
    return buf.getvalue()


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "etc").mkdir()
        (self.root / "etc/os-release").write_text('VERSION_ID="26.04"\n')
        self.files = {"components/demo.py": (b"print('new')\n", 0o111)}
        self.manifest = {"version": "v26.04.1", "ubuntu_series": ["26.04"]}

    def test_paths_are_confined(self):
        for path in ("/etc/shadow", "components/../../etc/shadow", "overlay/etc/passwd", "components/./x", "components/a\\b"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                updater.destination(path)
        self.assertEqual(updater.destination("overlay/usr/local/bin/devos"), "usr/local/bin/devos")

    def test_desktop_destinations_are_explicit(self):
        self.assertEqual(updater.destination("overlay/usr/share/applications/devos-kids-mode.desktop"),
                         "usr/share/applications/devos-kids-mode.desktop")
        with self.assertRaises(ValueError):
            updater.destination("overlay/usr/share/applications/other.desktop")

    def test_only_missing_known_runtime_packages_are_installed(self):
        def run(argv, **kwargs):
            return mock.Mock(returncode=1 if argv[-1] == "gir1.2-gtklayershell-0.1" else 0,
                             stdout="installed")
        with mock.patch.object(updater.subprocess, "run", side_effect=run) as command:
            updater.prepare_dependencies({"components/kids/kids_mode.py": (b"", 0)})
        self.assertEqual(command.call_args_list[-1].args[0],
                         ["apt-get", "install", "-y", "--no-install-recommends", "gir1.2-gtklayershell-0.1"])
        with mock.patch.object(updater.subprocess, "run") as command:
            updater.prepare_dependencies(self.files)
            command.assert_not_called()

    def test_symlinks_and_duplicates_are_rejected(self):
        for entries in ([('components/x', b'', tarfile.SYMTYPE)],
                        [('components/x', b'x', tarfile.REGTYPE)] * 2):
            with self.assertRaises(ValueError):
                updater.unpack(bundle(entries))

    def test_checksum_failure_is_rejected(self):
        manifest = {"format": 1, "version": "v1", "files": {"components/x": "0" * 64}}
        data = bundle([('manifest.json', json.dumps(manifest).encode(), tarfile.REGTYPE),
                       ('components/x', b'corrupt', tarfile.REGTYPE)])
        with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
            updater.unpack(data)

    def test_packager_and_updater_agree(self):
        (self.root / "components").mkdir()
        (self.root / "components/demo.py").write_bytes(b"#!/usr/bin/python3\nprint('ok')\n")
        dest = packager.package(self.root, self.root / "out", "v26.04.1")
        manifest, files = updater.unpack(dest.read_bytes())
        self.assertEqual(manifest["version"], "v26.04.1")
        updater.install(self.root, manifest, files)
        installed = self.root / "usr/local/share/devos/components/demo.py"
        self.assertEqual(installed.read_bytes(), files["components/demo.py"][0])
        self.assertEqual(installed.stat().st_mode & 0o777, 0o755)

    def test_wrong_ubuntu_base_is_rejected_before_writing(self):
        (self.root / "etc/os-release").write_text('VERSION_ID="24.04"\n')
        with self.assertRaisesRegex(ValueError, "different Ubuntu base"):
            updater.install(self.root, self.manifest, self.files)
        self.assertFalse((self.root / updater.STATE).exists())

    def test_successful_update_can_be_rolled_back(self):
        target = self.root / updater.destination("components/demo.py")
        target.parent.mkdir(parents=True)
        target.write_text("old\n")
        updater.install(self.root, self.manifest, self.files)
        self.assertIn("new", target.read_text())
        updater.rollback(self.root)
        self.assertEqual(target.read_text(), "old\n")
        self.assertFalse((self.root / updater.STATE / "installed.json").exists())

    def test_rollback_refuses_files_from_before_an_os_base_change(self):
        updater.install(self.root, self.manifest, self.files)
        (self.root / "etc/os-release").write_text('VERSION_ID="24.04"\n')
        with self.assertRaisesRegex(ValueError, "Ubuntu base changed"):
            updater.rollback(self.root)

    def test_failed_install_restores_existing_and_removes_new_files(self):
        target = self.root / updater.destination("components/demo.py")
        target.parent.mkdir(parents=True)
        target.write_text("old\n")
        original = updater.atomic_write
        count = 0

        def fail(path, body, mode):
            nonlocal count
            count += 1
            if count == 3:
                raise OSError("disk failure")
            original(path, body, mode)

        files = {**self.files, "components/new.py": (b"new", 0)}
        with mock.patch.object(updater, "atomic_write", side_effect=fail):
            with self.assertRaises(OSError):
                updater.install(self.root, self.manifest, files)
        self.assertEqual(target.read_text(), "old\n")
        self.assertFalse((target.parent / "new.py").exists())

    def test_existing_symlink_cannot_escape_install_root(self):
        target = self.root / "usr/local/share/devos"
        target.mkdir(parents=True)
        (target / "components").symlink_to(self.root / "etc", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            updater.install(self.root, self.manifest, self.files)

    def test_release_tag_cannot_inject_an_api_path(self):
        with self.assertRaises(ValueError):
            updater.release("../../evil")

    def test_check_cannot_trigger_an_os_upgrade(self):
        with mock.patch.object(updater.subprocess, "call") as call:
            with self.assertRaises(SystemExit):
                updater.main(["--check", "--os-upgrade"])
            call.assert_not_called()

    def test_check_does_not_install(self):
        info = {"tag_name": "v1", "assets": [{"name": name, "browser_download_url": "https://example.com/" + name}
                                               for name in (updater.ASSET, updater.ASSET + ".sha256")]}
        with mock.patch.object(updater, "release", return_value=info), mock.patch.object(updater, "install") as install:
            updater.update(check=True)
            install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
