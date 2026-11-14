"""Unit tests for DevOS File Chooser & Portal Integration."""

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORTAL = ROOT / "build/includes.chroot/usr/local/bin/devos-portal-filechooser"
SERVICE = ROOT / "build/includes.chroot/etc/systemd/user/devos-portal-filechooser.service"
FILES_BIN = ROOT / "build/includes.chroot/usr/local/bin/devos-files"
PORTALS_CONF = ROOT / "build/includes.chroot/etc/xdg/xdg-desktop-portal/portals.conf"
KDE_PORTALS_CONF = ROOT / "build/includes.chroot/etc/xdg/xdg-desktop-portal/kde-portals.conf"


class TestFilePicker(unittest.TestCase):
    def test_cli_help(self):
        if not FILES_BIN.is_file():
            self.skipTest("devos-files missing from ISO tree")
        text = FILES_BIN.read_text(encoding="utf-8", errors="replace")
        for flag in ("--picker", "--save", "--directory", "--multiple"):
            self.assertIn(flag, text)
        # Runtime --help needs PyQt5 (present on DevOS, not always in CI).
        ret = subprocess.run(
            ["python3", str(FILES_BIN), "--help"],
            capture_output=True,
            text=True,
        )
        if ret.returncode != 0 and "PyQt5" in (ret.stderr or ""):
            self.skipTest("PyQt5 not installed in this environment")
        self.assertEqual(ret.returncode, 0, ret.stderr)
        self.assertIn("--picker", ret.stdout)

    def test_portal_resolves_existing_devos_files_not_missing_local_path(self):
        """Missing ~/.local/bin/devos-files must not block /usr/local/bin fallback."""
        text = PORTAL.read_text(encoding="utf-8")
        self.assertIn("os.path.isfile(c)", text)
        self.assertIn("os.access(c, os.X_OK)", text)
        self.assertIn('"/usr/local/bin/devos-files"', text)
        # Old bug pattern: expanduser() alone is always a truthy string.
        self.assertNotRegex(
            text,
            r'or os\.path\.expanduser\("~/\.local/bin/devos-files"\)\s*'
            r'or os\.path\.expanduser\("~/\.gemini/antigravity/bin/devos-files"\)\s*'
            r'or "/usr/local/bin/devos-files"',
        )

    def test_portal_service_inherits_display_env(self):
        text = SERVICE.read_text(encoding="utf-8")
        self.assertIn("PassEnvironment=DISPLAY", text)
        self.assertNotIn("Environment=DISPLAY=:1", text)
        self.assertNotIn("Environment=XDG_RUNTIME_DIR=/run/user/1000", text)
        self.assertIn("PATH=/usr/local/bin", text)

    def test_portals_conf_does_not_force_kwallet_secret(self):
        for path in (PORTALS_CONF, KDE_PORTALS_CONF):
            text = path.read_text(encoding="utf-8")
            self.assertIn("FileChooser=devos;kde;", text)
            # Preference lines only — comments may still mention the backend.
            prefs = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
            self.assertFalse(any(ln.startswith("org.freedesktop.impl.portal.Secret=") for ln in prefs))

    def test_filter_parsing(self):
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

        f_chrome = parse_filter_string("PDF Document (*.[pP][dD][fF]);;PNG Image (*.[pP][nN][gG])")
        self.assertEqual(len(f_chrome), 2)
        self.assertEqual(f_chrome[0][0], "PDF Document (*.pdf)")
        self.assertEqual(f_chrome[0][1], ["*.pdf"])
        self.assertEqual(f_chrome[1][0], "PNG Image (*.png)")
        self.assertEqual(f_chrome[1][1], ["*.png"])

        self.assertEqual(clean_glob_pattern("Makkar.[pP][dD][fF]"), "Makkar.pdf")
        self.assertEqual(clean_glob_pattern("screenshot.[pP][nN][gG]"), "screenshot.png")

        f2 = parse_filter_string("")
        self.assertEqual(f2, [("All Files (*.*)", ["*.*"])])


if __name__ == "__main__":
    unittest.main()
