import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "components/optimizer"))
import auto_cleanup
import optimizer


@unittest.skipIf(os.getuid() == 0, "Automatic cleanup deliberately refuses root")
class AutoCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.now = time.time() + 40 * auto_cleanup.DAY

    def tearDown(self):
        self.tmp.cleanup()

    def file(self, relative):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"cache" * 100)
        return path

    def clean(self, **kwargs):
        return auto_cleanup.auto_clean(str(self.home), now=self.now, held_inodes=set(), **kwargs)

    def test_only_allowlisted_stale_cache_is_removed(self):
        stale = self.file(".cache/thumbnails/normal/old.png")
        keep = [self.file(p) for p in ("Downloads/old.zip", "Videos/Screencasts/recording.mp4",
                ".cache/whisper/model.pt", ".cache/mesa_shader_cache/game", ".config/chrome/Cookies",
                ".local/share/Trash/files/document", ".cache/otherapp/cache", ".cache/devos/state.db")]
        fresh = self.file(".cache/thumbnails/normal/fresh.png")
        os.utime(fresh, (self.now, self.now))
        result = self.clean()
        self.assertEqual(result["files"], 1)
        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())
        self.assertTrue(all(p.exists() for p in keep))

    def test_preview_does_not_delete_and_reports_allocated_space(self):
        stale = self.file(".cache/devos/temporary/file")
        result = self.clean(dry_run=True)
        self.assertEqual(result["files"], 1)
        self.assertEqual(result["bytes"], stale.stat().st_blocks * 512)
        self.assertTrue(stale.exists())

    def test_scheduled_preview_creates_no_state_or_lock_files(self):
        self.file(".cache/devos/temporary/file")
        with patch.object(auto_cleanup, "open_files", return_value=set()):
            auto_cleanup.run_scheduled(str(self.home), dry_run=True)
        self.assertFalse((self.home / ".local").exists())

    def test_symlinked_parent_directory_and_leaf_are_preserved(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        secret = outside / "precious"
        secret.write_bytes(b"original")
        (self.home / ".cache").symlink_to(outside, target_is_directory=True)
        self.clean()
        self.assertEqual(secret.read_bytes(), b"original")
        (self.home / ".cache").unlink()
        cache = self.home / ".cache/thumbnails"
        cache.mkdir(parents=True)
        (cache / "link").symlink_to(secret)
        (cache / "subdir").symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.clean()["files"], 0)
        self.assertEqual(secret.read_bytes(), b"original")

    def test_open_and_hardlinked_files_are_preserved(self):
        path = self.file(".cache/thumbnails/open")
        inode = path.stat()
        linked = self.file(".cache/thumbnails/hardlink")
        os.link(linked, self.home / "important")
        result = auto_cleanup.auto_clean(str(self.home), now=self.now, held_inodes={(inode.st_dev, inode.st_ino)})
        self.assertEqual(result["files"], 0)
        self.assertTrue(path.exists())
        self.assertTrue(linked.exists())

    def test_cannot_verify_open_files_means_no_deletion(self):
        path = self.file(".cache/thumbnails/keep")
        with patch.object(auto_cleanup, "open_files", side_effect=RuntimeError("inaccessible")):
            result = auto_cleanup.auto_clean(str(self.home), now=self.now)
        self.assertEqual(result["skipped"], "inaccessible")
        self.assertTrue(path.exists())

    def test_work_is_bounded_and_config_can_disable_it(self):
        for index in range(10):
            self.file(f".cache/thumbnails/{index}.png")
        with patch.object(auto_cleanup, "MAX_FILES", 2):
            self.assertLessEqual(self.clean()["scanned"], 2)
        config = self.home / "config.json"
        optimizer.save_config(dict(auto_cleanup=False), str(config))
        self.assertFalse(optimizer.load_config(str(config))["auto_cleanup"])

    def test_root_refused_even_for_preview(self):
        with patch.object(auto_cleanup.os, "getuid", return_value=0):
            self.assertIn("never root", self.clean()["skipped"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
