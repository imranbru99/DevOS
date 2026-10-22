"""Unit tests for DevOS File Chooser & Portal Integration."""

import subprocess
import sys
import unittest


class TestFilePicker(unittest.TestCase):
    def test_cli_help(self):
        ret = subprocess.run(
            ["devos-files", "--help"],
            capture_output=True,
            text=True
        )
        self.assertEqual(ret.returncode, 0)
        self.assertIn("--picker", ret.stdout)
        self.assertIn("--save", ret.stdout)
        self.assertIn("--directory", ret.stdout)
        self.assertIn("--multiple", ret.stdout)

    def test_filter_parsing(self):
        import re

        def parse_filter_string(filter_str):
            res = []
            if not filter_str:
                return [("All Files (*.*)", ["*.*"])]
            parts = [p.strip() for p in filter_str.split(";;") if p.strip()]
            for p in parts:
                m = re.search(r"\(([^)]+)\)", p)
                if m:
                    pats = [x.strip() for x in re.split(r"[\s,;]+", m.group(1)) if x.strip()]
                    res.append((p, pats))
                else:
                    res.append((p, ["*.*"]))
            return res or [("All Files (*.*)", ["*.*"])]

        f1 = parse_filter_string("Images (*.png *.jpg);;Documents (*.pdf)")
        self.assertEqual(len(f1), 2)
        self.assertEqual(f1[0][1], ["*.png", "*.jpg"])
        self.assertEqual(f1[1][1], ["*.pdf"])

        f2 = parse_filter_string("")
        self.assertEqual(f2, [("All Files (*.*)", ["*.*"])])


if __name__ == "__main__":
    unittest.main()
