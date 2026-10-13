"""
Unit tests for DevOS Notepad session persistence (crash-safe restore of tabs),
atomic writes, and encoding / line-ending preservation. No display needed.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

SYS_PATH_NOTEPAD = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/notepad"))
sys.path.insert(0, SYS_PATH_NOTEPAD)

import notepad  # noqa: E402
from notepad import SessionStore, TabState  # noqa: E402


class TestNotepad(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="notepad-test-")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self._env = mock.patch.dict(os.environ, {"HOME": self.home})
        self._env.start()
        self.docs = os.path.join(self.tmp, "docs")
        os.makedirs(self.docs)

    def tearDown(self):
        self._env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _file(self, name, data):
        path = os.path.join(self.docs, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def _read(self, path):
        with open(path, "rb") as fh:
            return fh.read()

    def _file_tab(self, path, dirty=False, content=None, **kw):
        text, fmt, mtime, size = notepad.read_text_file(path)
        return TabState(path=path, title=os.path.basename(path), dirty=dirty,
                        content=text if content is None else content,
                        encoding=fmt.encoding, eol=fmt.eol, fallback=fmt.fallback,
                        disk_mtime=mtime, disk_size=size, **kw)

    # ------------------------------------------------------------------
    def test_01_store_location_uses_home(self):
        store = SessionStore()
        self.assertEqual(store.base_dir, os.path.join(self.home, ".local", "share", "devos", "notepad"))

    def test_02_atomic_write_survives_crash_before_replace(self):
        path = os.path.join(self.tmp, "doc.txt")
        notepad.atomic_write_bytes(path, b"old content")
        with mock.patch("notepad.os.replace", side_effect=OSError("power cut")):
            with self.assertRaises(OSError):
                notepad.atomic_write_bytes(path, b"new content that never lands")
        self.assertEqual(self._read(path), b"old content")
        leftovers = [n for n in os.listdir(self.tmp) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])
        notepad.atomic_write_bytes(path, b"new content")
        self.assertEqual(self._read(path), b"new content")

    def test_03_atomic_write_keeps_permissions(self):
        if os.name == "nt":
            self.skipTest("POSIX permissions")
        path = os.path.join(self.tmp, "script.sh")
        notepad.atomic_write_bytes(path, b"#!/bin/sh\n")
        os.chmod(path, 0o750)
        notepad.atomic_write_bytes(path, b"#!/bin/sh\necho hi\n")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o750)

    def test_04_restore_full_session(self):
        clean_path = self._file("clean.txt", b"clean file\nline two\n")
        dirty_path = self._file("dirty.txt", b"original\n")
        store = SessionStore()
        untitled = TabState(title="Untitled", dirty=True, content="unsaved scratch\nnotes é中",
                            cursor=7, anchor=3, scroll=2, wrap=False)
        clean = self._file_tab(clean_path, cursor=5, scroll=1)
        dirty = self._file_tab(dirty_path, dirty=True, content="original\nplus my unsaved edit\n",
                               cursor=12)
        store.save([untitled, clean, dirty], active_id=dirty.id)

        tabs, active = SessionStore().restore()
        self.assertEqual([t.id for t in tabs], [untitled.id, clean.id, dirty.id])
        self.assertEqual(active, dirty.id)
        r_untitled, r_clean, r_dirty = tabs
        self.assertIsNone(r_untitled.path)
        self.assertTrue(r_untitled.dirty)
        self.assertEqual(r_untitled.content, "unsaved scratch\nnotes é中")
        self.assertEqual((r_untitled.cursor, r_untitled.anchor, r_untitled.scroll), (7, 3, 2))
        self.assertFalse(r_untitled.wrap)
        self.assertFalse(r_clean.dirty)
        self.assertEqual(r_clean.content, "clean file\nline two\n")
        self.assertEqual((r_clean.cursor, r_clean.scroll), (5, 1))
        self.assertIsNone(r_clean.disk_status)
        self.assertTrue(r_dirty.dirty)
        self.assertEqual(r_dirty.content, "original\nplus my unsaved edit\n")
        self.assertEqual(r_dirty.cursor, 12)
        self.assertIsNone(r_dirty.disk_status)
        # clean file content is not duplicated into the store
        self.assertFalse(os.path.exists(store.content_path(clean.id)))
        self.assertTrue(os.path.exists(store.content_path(untitled.id)))

    def test_05_corrupted_session_falls_back_to_backup(self):
        store = SessionStore()
        tab = TabState(dirty=True, content="generation one")
        store.save([tab], tab.id)
        tab2 = TabState(dirty=True, content="second tab")
        store.save([tab, tab2], tab2.id)
        self.assertTrue(os.path.exists(store.backup_path))
        with open(store.session_path, "wb") as fh:
            fh.write(b'{"version": 1, "tabs": [ {"id": "trunc')  # half-written
        session = SessionStore().load()
        self.assertIsNotNone(session)
        self.assertEqual(session.source, "backup")
        self.assertEqual([t.id for t in session.tabs], [tab.id])
        self.assertEqual(session.tabs[0].content, "generation one")
        # a save while the main file is corrupt must not destroy the good backup
        store3 = SessionStore()
        store3.load()
        store3.save([TabState(dirty=True, content="new")], None)
        self.assertEqual(json.loads(self._read(store.backup_path))["tabs"][0]["id"], tab.id)

    def test_06_missing_session_returns_nothing(self):
        self.assertIsNone(SessionStore().load())
        self.assertEqual(SessionStore().restore(), ([], None))

    def test_07_file_changed_on_disk_detection(self):
        path = self._file("watched.txt", b"v1\n")
        store = SessionStore()
        tab = self._file_tab(path, dirty=True, content="v1\nmine\n")
        self.assertIsNone(SessionStore.check_disk(tab))
        store.save([tab], tab.id)
        time.sleep(0.01)
        with open(path, "wb") as fh:
            fh.write(b"v2 from another app\n")
        os.utime(path, ns=(tab.disk_mtime + 5_000_000_000, tab.disk_mtime + 5_000_000_000))
        self.assertEqual(SessionStore.check_disk(tab), "changed")
        tabs, _ = SessionStore().restore()
        self.assertEqual(tabs[0].disk_status, "changed")
        self.assertEqual(tabs[0].content, "v1\nmine\n")  # our version is kept until the user decides
        os.unlink(path)
        self.assertEqual(SessionStore.check_disk(tab), "missing")

    def test_08_clean_tab_reloads_newer_disk_content(self):
        path = self._file("clean.txt", b"old\n")
        store = SessionStore()
        tab = self._file_tab(path)
        store.save([tab], tab.id)
        with open(path, "wb") as fh:
            fh.write(b"newer text\n")
        tabs, _ = SessionStore().restore()
        self.assertEqual(tabs[0].content, "newer text\n")
        self.assertFalse(tabs[0].dirty)

    def test_09_crlf_round_trip(self):
        path = self._file("win.txt", b"one\r\ntwo\r\nthree\r\n")
        text, fmt, _m, _s = notepad.read_text_file(path)
        self.assertEqual(text, "one\ntwo\nthree\n")
        self.assertEqual(fmt.eol, "\r\n")
        notepad.write_text_file(path, text + "four\n", fmt.encoding, fmt.eol)
        self.assertEqual(self._read(path), b"one\r\ntwo\r\nthree\r\nfour\r\n")
        lf = self._file("unix.txt", b"a\nb\n")
        text, fmt, _m, _s = notepad.read_text_file(lf)
        self.assertEqual(fmt.eol, "\n")
        notepad.write_text_file(lf, text, fmt.encoding, fmt.eol)
        self.assertEqual(self._read(lf), b"a\nb\n")

    def test_10_crlf_survives_session_restore(self):
        path = self._file("win.txt", b"x\r\ny\r\n")
        store = SessionStore()
        tab = self._file_tab(path, dirty=True, content="x\ny\nz\n")
        store.save([tab], tab.id)
        restored = SessionStore().restore()[0][0]
        self.assertEqual(restored.eol, "\r\n")
        notepad.write_text_file(path, restored.content, restored.encoding, restored.eol)
        self.assertEqual(self._read(path), b"x\r\ny\r\nz\r\n")

    def test_11_utf8_bom_preserved(self):
        path = self._file("bom.txt", b"\xef\xbb\xbfh\xc3\xa9llo\n")
        text, fmt, _m, _s = notepad.read_text_file(path)
        self.assertEqual(text, "héllo\n")
        self.assertEqual(fmt.encoding, notepad.ENC_UTF8_BOM)
        notepad.write_text_file(path, text + "more\n", fmt.encoding, fmt.eol)
        self.assertEqual(self._read(path), b"\xef\xbb\xbfh\xc3\xa9llo\nmore\n")

    def test_12_utf16_bom_preserved(self):
        raw = b"\xff\xfe" + "hi\r\nthere".encode("utf-16-le")
        path = self._file("u16.txt", raw)
        text, fmt, _m, _s = notepad.read_text_file(path)
        self.assertEqual((text, fmt.encoding, fmt.eol), ("hi\nthere", notepad.ENC_UTF16LE, "\r\n"))
        notepad.write_text_file(path, text, fmt.encoding, fmt.eol)
        self.assertEqual(self._read(path), raw)

    def test_13_latin1_fallback_flagged(self):
        path = self._file("legacy.txt", b"caf\xe9 cr\xe8me\n")
        text, fmt, _m, _s = notepad.read_text_file(path)
        self.assertTrue(fmt.fallback)
        self.assertEqual(fmt.encoding, notepad.ENC_LATIN1)
        self.assertEqual(text, "café crème\n")
        notepad.write_text_file(path, text, fmt.encoding, fmt.eol)
        self.assertEqual(self._read(path), b"caf\xe9 cr\xe8me\n")
        with self.assertRaises(UnicodeEncodeError):
            notepad.encode_text("中", notepad.ENC_LATIN1)
        _t, utf8 = notepad.decode_bytes("café".encode("utf-8"))
        self.assertFalse(utf8.fallback)

    def test_14_only_changed_tabs_rewritten(self):
        store = SessionStore()
        a = TabState(dirty=True, content="alpha")
        b = TabState(dirty=True, content="beta")
        c = TabState(dirty=True, content="gamma")
        self.assertEqual(sorted(store.save([a, b, c], a.id)), sorted([a.id, b.id, c.id]))
        self.assertEqual(store.save([a, b, c], a.id), [])
        b.content = "beta edited"
        self.assertEqual(store.save([a, b, c], a.id), [b.id])
        # generation counters let the GUI skip even building the text
        calls = []
        a.generation = 1
        a.content = lambda: calls.append(1) or "alpha"
        store.save([a, b, c], a.id)
        store.save([a, b, c], a.id)
        self.assertEqual(len(calls), 1)
        a.generation = 2
        a.content = lambda: "alpha 2"
        self.assertEqual(store.save([a, b, c], a.id), [a.id])
        # a freshly loaded store does not rewrite unchanged restored tabs
        store2 = SessionStore()
        tabs, active = store2.restore()
        self.assertEqual(store2.save(tabs, active), [])

    def test_15_closed_tab_content_cleaned_up(self):
        store = SessionStore()
        a = TabState(dirty=True, content="keep")
        b = TabState(dirty=True, content="closed")
        store.save([a, b], a.id)
        store.save([a], a.id)
        store.save([a], None)  # second generation: b is no longer in .bak either
        self.assertTrue(os.path.exists(store.content_path(a.id)))
        self.assertFalse(os.path.exists(store.content_path(b.id)))

    def test_16_start_new_session_ignores_stored_session(self):
        store = SessionStore()
        tab = TabState(dirty=True, content="old stuff")
        store.save([tab], tab.id)
        settings = store.load_settings()
        self.assertEqual(settings["startup"], notepad.STARTUP_CONTINUE)
        settings["startup"] = notepad.STARTUP_NEW
        store.save_settings(settings)
        fresh = SessionStore()
        self.assertEqual(fresh.load_settings()["startup"], notepad.STARTUP_NEW)
        self.assertEqual(fresh.restore(), ([], None))
        self.assertEqual(len(SessionStore().restore({"startup": "continue"})[0]), 1)

    def test_17_stale_temp_files_removed_on_load(self):
        store = SessionStore()
        tab = TabState(dirty=True, content="x")
        store.save([tab], tab.id)
        junk = os.path.join(store.base_dir, ".session.json.abc123.tmp")
        with open(junk, "wb") as fh:
            fh.write(b"{half")
        SessionStore().load()
        self.assertFalse(os.path.exists(junk))

    def test_18_time_date_format(self):
        import datetime
        self.assertEqual(notepad.format_time_date(datetime.datetime(2026, 3, 7, 14, 5)), "2:05 PM 3/7/2026")
        self.assertEqual(notepad.format_time_date(datetime.datetime(2026, 12, 31, 0, 9)), "12:09 AM 12/31/2026")


if __name__ == "__main__":
    unittest.main()
