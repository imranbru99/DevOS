"""DevOS Calculator math, without opening a window."""

import importlib.machinery
import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CALC = os.path.join(ROOT, "build", "includes.chroot", "usr", "local", "bin", "devos-calculator")
DESKTOP = os.path.join(ROOT, "build", "includes.chroot", "usr", "share", "applications", "devos-calculator.desktop")


def load():
    loader = importlib.machinery.SourceFileLoader("devos_calculator", CALC)
    return loader.load_module()


class TestCalculator(unittest.TestCase):
    def setUp(self):
        self.mod = load()
        self.engine = self.mod.Engine()

    def press(self, *keys):
        engine = self.engine
        for key in keys:
            if key in "0123456789":
                engine.digit(key)
            elif key == ".":
                engine.dot()
            elif key in "+-*/":
                engine.operator(key)
            elif key == "=":
                engine.equals()
            elif key == "%":
                engine.percent()
            elif key == "n":
                engine.negate()
            elif key == "c":
                engine.clear_all()
            elif key == "e":
                engine.clear_entry()
            elif key == "b":
                engine.backspace()
            else:
                raise AssertionError(key)

    def test_addition_matches_the_number_on_the_old_window(self):
        self.press("8", "8", "+", "2", "0", "0", "=")
        self.assertEqual(self.engine.entry, "288")
        self.assertIn("288", self.engine.display())

    def test_left_to_right_and_repeat_equals(self):
        self.press("1", "+", "2", "*", "3", "=")
        self.assertEqual(self.engine.entry, "9")
        self.engine.clear_all()
        self.press("5", "+", "3", "=", "=")
        self.assertEqual(self.engine.entry, "11")

    def test_divide_by_zero_and_percent(self):
        self.press("1", "/", "0", "=")
        self.assertEqual(self.engine.error, "Cannot divide by zero")
        self.engine.clear_all()
        self.press("2", "0", "0", "+", "1", "0", "%", "=")
        self.assertEqual(self.engine.entry, "220")
        self.engine.clear_all()
        self.press("5", "0", "*", "1", "0", "%", "=")
        self.assertEqual(self.engine.entry, "5")

    def test_unary_and_memory(self):
        self.press("9")
        self.engine.unary("sqrt")
        self.assertEqual(self.engine.entry, "3")
        self.engine.clear_all()
        self.press("4")
        self.engine.unary("sqr")
        self.assertEqual(self.engine.entry, "16")
        self.engine.clear_all()
        self.press("4")
        self.engine.unary("inv")
        self.assertEqual(self.engine.entry, "0.25")
        self.engine.memory_store()
        self.press("c", "1", "0")
        self.engine.memory_recall()
        self.assertEqual(self.engine.entry, "0.25")
        self.engine.memory_clear()
        self.assertFalse(self.engine.has_memory)

    def test_backspace_negate_and_paste(self):
        self.press("1", "2", "b", "n")
        self.assertEqual(self.engine.entry, "-1")
        self.assertTrue(self.engine.paste("1,234.5"))
        self.assertEqual(self.engine.entry, "1234.5")
        self.assertEqual(self.engine.display(), "1,234.5")

    def test_menu_opens_devos_calculator_not_kcalc(self):
        text = open(DESKTOP, encoding="utf-8").read()
        self.assertIn("Name=Calculator", text)
        self.assertIn("Exec=/usr/local/bin/devos-calculator", text)
        self.assertIn("StartupWMClass=devos-calculator", text)
        self.assertNotIn("Exec=kcalc", text)
        self.assertNotIn("StartupWMClass=kcalc", text)
        program = open(CALC, encoding="utf-8").read()
        self.assertIn("modern-calculator", program)
        self.assertIn('setWindowTitle("Calculator")', program)
        fix = open(
            os.path.join(ROOT, "build", "includes.chroot", "usr", "local", "bin", "devos-fix-calculator"),
            encoding="utf-8",
        ).read()
        self.assertIn("devos-calculator", fix)
        self.assertIn("kcalc.real", fix)
        debrand = open(
            os.path.join(ROOT, "build", "includes.chroot", "usr", "local", "sbin", "devos-debrand-desktop"),
            encoding="utf-8",
        ).read()
        self.assertIn("/usr/lib/devos/kcalc.real", debrand)
        self.assertIn("exec -a devos-calculator /usr/local/bin/devos-calculator", debrand)


if __name__ == "__main__":
    unittest.main()
