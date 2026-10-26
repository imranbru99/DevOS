"""Cached rootfs gate detects damaged native executables without rewriting files."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('package_integrity', Path(__file__).resolve().parents[2] / 'build/verify-package-binaries.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class BinaryIntegrityTests(unittest.TestCase):
    def test_detects_modified_library_and_preserves_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            info = root / 'var/lib/dpkg/info'
            info.mkdir(parents=True)
            lib = root / 'usr/lib/libexample.so'
            lib.parent.mkdir(parents=True)
            original = b'\x7fELF' + b'original payload'
            lib.write_bytes(original)
            (info / 'example:amd64.md5sums').write_text(hashlib.md5(original).hexdigest() + '  usr/lib/libexample.so\n')
            self.assertEqual(checker.mismatches(root), [])
            lib.write_bytes(original + b'damage')
            problems = checker.mismatches(root)
            self.assertEqual(problems[0]['package'], 'example:amd64')
            self.assertEqual(problems[0]['path'], 'usr/lib/libexample.so')
            self.assertEqual(lib.read_bytes(), original + b'damage')

    def test_intentionally_branded_text_is_not_an_elf_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            info = root / 'var/lib/dpkg/info'; info.mkdir(parents=True)
            script = root / 'usr/bin/example'; script.parent.mkdir(parents=True)
            script.write_text('#!/bin/sh\necho DevOS\n')
            (info / 'example.md5sums').write_text('0'*32 + '  usr/bin/example\n')
            self.assertEqual(checker.mismatches(root), [])


if __name__ == '__main__': unittest.main()
