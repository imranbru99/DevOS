#!/usr/bin/env python3
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

ARCHIVE_BIN = os.path.join(ROOT, "build", "includes.chroot", "usr", "local", "bin", "devos-archive")
FILES_BIN = os.path.join(ROOT, "build", "includes.chroot", "usr", "local", "bin", "devos-files")
MENU_DIR = os.path.join(ROOT, "build", "includes.chroot", "usr", "share", "kio", "servicemenus")


class TestArchiveFeatures(unittest.TestCase):
    def test_binaries_and_servicemenus_exist(self):
        self.assertTrue(os.path.isfile(ARCHIVE_BIN), "devos-archive binary must exist")
        self.assertTrue(os.access(ARCHIVE_BIN, os.X_OK), "devos-archive must be executable")

        archive_desktop = os.path.join(MENU_DIR, "devos-archive.desktop")
        extract_desktop = os.path.join(MENU_DIR, "devos-extract.desktop")
        self.assertTrue(os.path.isfile(archive_desktop), "devos-archive.desktop must exist")
        self.assertTrue(os.path.isfile(extract_desktop), "devos-extract.desktop must exist")

        with open(archive_desktop, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("Compress to ZIP file", content)
            self.assertIn("Add to .7z archive", content)
            self.assertIn("devos-archive", content)

        with open(extract_desktop, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("Extract All…", content)
            self.assertIn("Extract Here", content)
            self.assertIn("devos-archive", content)

    def test_compression_and_extraction(self):
        from importlib.machinery import SourceFileLoader
        import importlib.util
        loader = SourceFileLoader("devos_archive", ARCHIVE_BIN)
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("devos_archive", loader))
        loader.exec_module(mod)

        with tempfile.TemporaryDirectory() as td:
            f1 = os.path.join(td, "sample.txt")
            with open(f1, "w") as f:
                f.write("Hello DevOS Archive")

            # Test ZIP compression
            zip_out = mod.compress_zip([f1])
            self.assertTrue(os.path.isfile(zip_out))
            self.assertTrue(zip_out.endswith("sample.zip"))

            # Test 7z compression
            z7_out = mod.compress_7z([f1])
            self.assertTrue(os.path.isfile(z7_out))
            self.assertTrue(z7_out.endswith("sample.7z"))

            # Test extraction to folder
            mod.extract_folder(zip_out)
            extracted_folder = os.path.join(td, "sample")
            self.assertTrue(os.path.isdir(extracted_folder))
            self.assertTrue(os.path.isfile(os.path.join(extracted_folder, "sample.txt")))

    def test_file_explorer_context_menu_has_compression(self):
        with open(FILES_BIN, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("Compress to ZIP file", content)
            self.assertIn("7-Zip", content)
            self.assertIn("Add to archive…", content)
            self.assertIn("action_compress_zip", content)
            self.assertIn("action_compress_7z", content)


if __name__ == "__main__":
    unittest.main()
