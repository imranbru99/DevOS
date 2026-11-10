"""Exercise the repository explorer, without changing the user's preferences."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import runpy
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MODULE = runpy.run_path(str(ROOT / 'build/includes.chroot/usr/local/bin/devos-files'))

class ExplorerStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = MODULE['QApplication'].instance() or MODULE['QApplication']([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cls = MODULE['WindowsFileExplorer']
        self.old = (self.cls.CONFIG_DIR, self.cls.SETTINGS_FILE, self.cls.PINNED_FILE)
        self.cls.CONFIG_DIR = self.temp.name
        self.cls.SETTINGS_FILE = self.temp.name + '/settings.json'
        self.cls.PINNED_FILE = self.temp.name + '/pins.json'
        self.windows = []

    def tearDown(self):
        for w in self.windows:
            w.close()
        self.cls.CONFIG_DIR, self.cls.SETTINGS_FILE, self.cls.PINNED_FILE = self.old
        self.temp.cleanup()

    def window(self, *args, **kwargs):
        w = self.cls(*args, **kwargs)
        self.windows.append(w)
        return w

    def test_drive_properties_distinguish_reserved_space_from_usage(self):
        drive = dict(title="Data (D:)", letter="D", label="Data", path="/dev/sdb1",
                     mount=self.temp.name, fstype="ext4", total=916 * 2**30,
                     free=869 * 2**30, used=2**30)
        dialog = MODULE["WindowsDrivePropertiesDialog"](drive)
        labels = [label.text() for label in dialog.findChildren(MODULE["QLabel"])]
        self.assertIn("EXT4", labels)
        self.assertIn("Available space:", labels)
        self.assertIn("System reserved:", labels)
        pie = dialog.findChild(MODULE["DrivePieWidget"])
        self.assertEqual((pie.used, pie.free, pie.reserved), (2**30, 869 * 2**30, 46 * 2**30))
        dialog.close()

    def test_only_the_root_owned_recovery_directory_is_protected(self):
        recovery = MODULE["is_volume_recovery_folder"]
        path = self.temp.name + "/lost+found"
        protected = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=0)
        with patch("os.path.ismount", return_value=True), patch("os.stat", return_value=protected):
            self.assertTrue(recovery(path))
            self.assertFalse(recovery(self.temp.name + "/ordinary"))
        with patch("os.path.ismount", return_value=False):
            self.assertFalse(recovery(path))
        protected.st_uid = 1000
        with patch("os.path.ismount", return_value=True), patch("os.stat", return_value=protected):
            self.assertFalse(recovery(path))

    def test_recycle_bin_failure_leaves_the_source_in_place(self):
        source = Path(self.temp.name) / "keep.txt"
        source.write_text("keep me")
        worker = MODULE["FileOpWorker"]("trash", [str(source)])
        with (
            patch("os.path.expanduser", side_effect=lambda path: path.replace("~", self.temp.name)),
            patch("shutil.which", return_value=None),
            patch("os.rename", side_effect=PermissionError("blocked")),
        ):
            errors = worker._trash()
        self.assertTrue(errors)
        self.assertEqual(source.read_text(), "keep me")

    def test_picker_resumes_explorer_but_explicit_folder_wins(self):
        folder = Path(self.temp.name) / 'chosen'
        folder.mkdir()
        self.window(str(folder))
        self.assertEqual(self.window(picker_mode=True)._current_path, str(folder))
        self.assertEqual(self.window(self.temp.name, picker_mode=True)._current_path, self.temp.name)

    def test_long_filter_does_not_expand_dialog(self):
        w = self.window(self.temp.name, picker_mode=True, picker_options={
            'filters': [('Images (' + '*.png ' * 200 + ')', ['*.png'])]})
        w.show()
        self.app.processEvents()
        self.assertLessEqual(w.width(), self.app.primaryScreen().availableGeometry().width())

    def test_latest_screenshot_is_first(self):
        folder = Path(self.temp.name) / 'Screenshots'
        folder.mkdir()
        for name, timestamp in [('old.png', 100), ('new.png', 200)]:
            p = folder / name
            p.touch()
            os.utime(p, (timestamp, timestamp))
        w = self.window(str(folder), picker_mode=True)
        self.assertEqual(w.table_view.item(0, 0).text(), 'new.png')

    def test_sort_is_shared_by_views_and_restored(self):
        for name in ('a.txt', 'b.txt'):
            (Path(self.temp.name) / name).touch()
        w = self.window(self.temp.name)
        w.table_view.sortItems(0, MODULE['Qt'].DescendingOrder)
        table_names = [w.table_view.item(r, 0).text() for r in range(w.table_view.rowCount())]
        icon_names = [w.list_view.item(r).text() for r in range(w.list_view.count())]
        self.assertEqual(table_names, icon_names)
        other = self.window(self.temp.name)
        self.assertEqual(other.table_view.horizontalHeader().sortIndicatorOrder(), MODULE['Qt'].DescendingOrder)

    def test_upload_resume_overrides_application_default(self):
        folder = Path(self.temp.name) / 'Screenshots'
        folder.mkdir()
        self.window(str(folder))
        w = self.window(self.temp.name, picker_mode=True, picker_options={'resume': True})
        self.assertEqual(w._current_path, str(folder))
        self.assertTrue(w.btn_cut.isHidden())
        self.assertTrue(w.btn_compress.isHidden())

    def test_new_screenshot_appears_without_reopening(self):
        from PyQt5.QtTest import QTest
        w = self.window(self.temp.name, picker_mode=True)
        w.search_box.setText('new')
        (Path(self.temp.name) / 'new.png').touch()
        QTest.qWait(700)
        names = [w.table_view.item(r, 0).text() for r in range(w.table_view.rowCount())]
        self.assertIn('new.png', names)
        self.assertEqual(w.search_box.text(), 'new')

    def test_quick_access_is_populated_on_direct_folder_start(self):
        w = self.window(self.temp.name, picker_mode=True)
        labels = [w.qa_sidebar_layout.itemAt(i).widget().text() for i in range(w.qa_sidebar_layout.count())]
        for name in ('Desktop', 'Downloads', 'Documents', 'Pictures', 'Music', 'Videos'):
            self.assertIn(name, labels)

    def test_icon_preference_survives_reopening(self):
        w = self.window(self.temp.name)
        w.toggle_view_mode()
        self.assertEqual(self.window(self.temp.name)._view_mode, 'icons')

    def test_extensions_are_display_only_and_search_uses_real_name(self):
        (Path(self.temp.name) / 'report.txt').touch()
        w = self.window(self.temp.name)
        w._settings.update(extensions=False, wildcards=True)
        w.refresh()
        w.search_box.setText('*.txt')
        matches = [w.table_view.item(r, 0) for r in range(w.table_view.rowCount()) if not w.table_view.isRowHidden(r)]
        self.assertEqual([item.text() for item in matches], ['report'])
        self.assertTrue(matches[0].data(MODULE['Qt'].UserRole).endswith('report.txt'))

    def test_appearance_preferences_apply(self):
        w = self.window(self.temp.name)
        w._settings.update(compact=True, status_bar=False)
        w._apply_appearance()
        self.assertEqual(w.table_view.verticalHeader().defaultSectionSize(), 28)
        self.assertTrue(w.status.isHidden())

    def test_new_window_setting_dispatches_real_folder(self):
        from unittest.mock import patch
        folder = Path(self.temp.name) / 'child'
        folder.mkdir()
        w = self.window(self.temp.name)
        w._settings['new_window'] = True
        item = next(w.table_view.item(r, 0) for r in range(w.table_view.rowCount()) if w.table_view.item(r, 0).text() == 'child')
        with patch.dict(w._on_table_item_double_clicked.__globals__, open_in_new_window=lambda path: self.assertEqual(path, str(folder))):
            w._on_table_item_double_clicked(item)
        self.assertEqual(w._current_path, self.temp.name)
