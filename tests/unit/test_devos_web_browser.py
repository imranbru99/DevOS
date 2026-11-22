"""DevOS Browser must render modern sites with a current engine."""

import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
        return handle.read()


class TestDevOSWebBrowser(unittest.TestCase):
    def test_launcher_uses_current_chrome_and_keeps_a_fallback(self):
        text = read("build/includes.chroot/usr/local/bin/devos-web-browser")
        self.assertIn("/usr/bin/google-chrome-stable", text)
        self.assertIn("--class=devos-browser", text)
        self.assertIn("CHROME_DESKTOP=devos-browser.desktop", text)
        self.assertIn("--incognito", text)
        self.assertIn("web_browser.py", text)

    def test_builtin_window_enables_javascript_and_does_not_mark_the_client(self):
        text = read("components/browser/web_browser.py")
        image = read("build/includes.chroot/usr/local/share/devos/components/browser/web_browser.py")
        self.assertEqual(text, image)
        self.assertIn("JavascriptEnabled", text)
        self.assertIn("WebGLEnabled", text)
        self.assertNotIn("DevOSBrowser/2.0", text)
        self.assertNotIn('setText("Sec"', text)
        desktop = read("build/includes.chroot/usr/share/applications/devos-browser.desktop")
        self.assertIn("Exec=/usr/local/bin/devos-web-browser %U", desktop)
        self.assertIn("Name=DevOS Browser", desktop)


if __name__ == "__main__":
    unittest.main()
