"""Exercise the repository explorer, without changing the user's preferences."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import runpy
import tempfile
import unittest
from pathlib import Path

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
