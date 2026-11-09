"""DevOS color schemes must keep readable text on every surface.

Light scheme: near-black text on white/light backgrounds (Settings labels).
Dark scheme: light text on dark backgrounds.
View fields must never be near-black while Window is light (blacked-out inputs).
"""
from __future__ import annotations

import os
import re
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


def parse_colors(path: str) -> dict[str, dict[str, tuple[int, int, int]]]:
    sections: dict[str, dict[str, tuple[int, int, int]]] = {}
    current = None
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if line.startswith("[") and line.endswith("]"):
                current = line[1:-1]
                sections[current] = {}
                continue
            if current is None or "=" not in line:
                continue
            key, value = line.split("=", 1)
            nums = re.fullmatch(r"(\d+),(\d+),(\d+)", value.strip())
            if nums:
                sections[current][key] = tuple(int(x) for x in nums.groups())
    return sections


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (c / 255.0 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


class TestColorContrast(unittest.TestCase):
    light = os.path.join(ROOT, "build/includes.chroot/usr/share/color-schemes/DevOS-Light.colors")
    dark = os.path.join(ROOT, "build/includes.chroot/usr/share/color-schemes/DevOS.colors")

    def test_light_scheme_text_is_near_black_on_light_surfaces(self):
        colors = parse_colors(self.light)
        for group in ("Colors:Window", "Colors:View", "Colors:Button", "Colors:Tooltip"):
            bg = colors[group]["BackgroundNormal"]
            fg = colors[group]["ForegroundNormal"]
            inactive = colors[group]["ForegroundInactive"]
            self.assertGreater(luminance(bg), 0.85, group)
            self.assertLess(luminance(fg), 0.2, group)
            self.assertLess(luminance(inactive), 0.45, group)
            # Contrast-ish: background much lighter than text
            self.assertGreater(luminance(bg) - luminance(fg), 0.65, group)

    def test_light_view_fields_are_not_black_blocks(self):
        colors = parse_colors(self.light)
        view_bg = colors["Colors:View"]["BackgroundNormal"]
        window_bg = colors["Colors:Window"]["BackgroundNormal"]
        self.assertGreater(luminance(view_bg), 0.9)
        self.assertGreater(luminance(window_bg), 0.85)
        # Both light — never dark View on light Window
        self.assertGreater(luminance(view_bg), 0.7)

    def test_dark_scheme_text_is_light_on_dark_surfaces(self):
        colors = parse_colors(self.dark)
        for group in ("Colors:Window", "Colors:View", "Colors:Button"):
            bg = colors[group]["BackgroundNormal"]
            fg = colors[group]["ForegroundNormal"]
            self.assertLess(luminance(bg), 0.25, group)
            self.assertGreater(luminance(fg), 0.7, group)

    def test_defaults_are_coherent_light_stack(self):
        skel = open(os.path.join(ROOT, "build/includes.chroot/etc/skel/.config/kdeglobals"), encoding="utf-8").read()
        self.assertIn("ColorScheme=DevOS-Light", skel)
        self.assertIn("widgetStyle=Breeze", skel)
        self.assertIn("Colors:Complementary", skel)
        self.assertIn("248,250,252", skel)
        defaults = open(
            os.path.join(
                ROOT,
                "build/includes.chroot/usr/share/plasma/look-and-feel/org.devos.desktop/contents/defaults",
            ),
            encoding="utf-8",
        ).read()
        self.assertIn("Colors:Complementary", defaults)
        self.assertIn("widgetStyle=Breeze", defaults)

    def test_light_complementary_is_dark_for_overlays(self):
        """Spectacle Save/Cancel and lock/logout UIs use Complementary."""
        colors = parse_colors(self.light)
        group = "Colors:Complementary"
        bg = colors[group]["BackgroundNormal"]
        fg = colors[group]["ForegroundNormal"]
        self.assertLess(luminance(bg), 0.25, group)
        self.assertGreater(luminance(fg), 0.7, group)
        self.assertGreater(luminance(fg) - luminance(bg), 0.5, group)

    def test_xdg_kdeglobals_complementary_matches_light_scheme(self):
        """Embedded /etc/xdg/kdeglobals must not reintroduce light Complementary."""
        xdg = parse_colors(os.path.join(ROOT, "build/includes.chroot/etc/xdg/kdeglobals"))
        scheme = parse_colors(self.light)
        self.assertEqual(
            xdg["Colors:Complementary"]["BackgroundNormal"],
            scheme["Colors:Complementary"]["BackgroundNormal"],
        )
        self.assertEqual(
            xdg["Colors:Complementary"]["ForegroundNormal"],
            scheme["Colors:Complementary"]["ForegroundNormal"],
        )
        self.assertLess(luminance(xdg["Colors:Complementary"]["BackgroundNormal"]), 0.25)

    def test_dark_scheme_has_header_set(self):
        colors = parse_colors(self.dark)
        self.assertIn("Colors:Header", colors)
        self.assertLess(luminance(colors["Colors:Header"]["BackgroundNormal"]), 0.25)
        self.assertGreater(luminance(colors["Colors:Header"]["ForegroundNormal"]), 0.7)


if __name__ == "__main__":
    unittest.main()
