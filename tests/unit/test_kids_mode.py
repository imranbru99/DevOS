import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('kids_mode', Path(__file__).resolve().parents[2] / 'components/kids/kids_mode.py')
kids = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kids)

class KidsKeys(unittest.TestCase):
    def test_parent_exit_chords(self):
        self.assertTrue(kids.exit_chord('k', True, True, False))
        self.assertTrue(kids.exit_chord('K', True, False, True))
        for args in [('k', False, True, False), ('k', True, False, False),
                     ('x', True, True, False), ('k', True, True, False, True)]:
            self.assertFalse(kids.exit_chord(*args))
