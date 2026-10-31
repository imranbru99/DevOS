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

        def clean_glob_pattern(pat):
            if not pat:
                return pat
            cleaned = re.sub(r"\[([a-zA-Z0-9])(?:[^\]])*\]", lambda m: m.group(1).lower(), pat)
            cleaned = cleaned.replace("?", "")
            return cleaned

        def parse_filter_string(filter_str):
            res = []
            if not filter_str:
                return [("All Files (*.*)", ["*.*"])]
            parts = [p.strip() for p in filter_str.split(";;") if p.strip()]
            for p in parts:
                m = re.search(r"\(([^)]+)\)", p)
                if m:
                    raw_pats = [x.strip() for x in re.split(r"[\s,;]+", m.group(1)) if x.strip()]
                    cleaned_pats = [clean_glob_pattern(x) for x in raw_pats]
                    cleaned_label = clean_glob_pattern(p)
                    res.append((cleaned_label, cleaned_pats))
                else:
                    res.append((clean_glob_pattern(p), ["*.*"]))
            return res or [("All Files (*.*)", ["*.*"])]

        f1 = parse_filter_string("Images (*.png *.jpg);;Documents (*.pdf)")
        self.assertEqual(len(f1), 2)
        self.assertEqual(f1[0][1], ["*.png", "*.jpg"])
        self.assertEqual(f1[1][1], ["*.pdf"])

        # Test bracket regex character classes from Chrome/Chromium
        f_chrome = parse_filter_string("PDF Document (*.[pP][dD][fF]);;PNG Image (*.[pP][nN][gG])")
        self.assertEqual(len(f_chrome), 2)
        self.assertEqual(f_chrome[0][0], "PDF Document (*.pdf)")
        self.assertEqual(f_chrome[0][1], ["*.pdf"])
        self.assertEqual(f_chrome[1][0], "PNG Image (*.png)")
        self.assertEqual(f_chrome[1][1], ["*.png"])

        # Test filename normalization
        self.assertEqual(clean_glob_pattern("Makkar.[pP][dD][fF]"), "Makkar.pdf")
        self.assertEqual(clean_glob_pattern("screenshot.[pP][nN][gG]"), "screenshot.png")

        f2 = parse_filter_string("")
        self.assertEqual(f2, [("All Files (*.*)", ["*.*"])])


if __name__ == "__main__":
    unittest.main()
