#!/usr/bin/env python3
"""Generate bold, visible Plymouth splash assets for DevOS."""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "build/includes.chroot/usr/share/plymouth/themes/devos"


def lerp(a, b, t):
    return a + (b - a) * t


def gradient_backdrop(w=1920, h=1080, phase: float = 0.0) -> Image.Image:
    """Deep night sky with cyan light rivers — phase shifts for motion frames."""
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        v = y / (h - 1)
        r = int(lerp(5, 10, v))
        g = int(lerp(12, 28, v))
        b = int(lerp(28, 55, v))
        for x in range(w):
            u = x / (w - 1)
            wave = 0.5 + 0.5 * math.sin((u * 4.2 + v * 1.7 + phase) * math.pi)
            wave2 = 0.5 + 0.5 * math.sin((u * 1.3 - v * 3.1 + phase * 1.4) * math.pi)
            glow = wave * 0.65 + wave2 * 0.45
            # Stronger cyan so motion reads clearly on phone videos / TVs.
            px[x, y] = (
                min(255, int(r + glow * 35)),
                min(255, int(g + glow * 120)),
                min(255, int(b + glow * 180)),
            )
    # Soft diagonal light beams that travel with phase
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    shift = int((phase % 2.0) * h * 0.22)
    for i, alpha in enumerate((70, 50, 34)):
        y0 = int(h * (0.08 + i * 0.18) + shift) % h
        draw.polygon(
            [(0, y0), (w, y0 - 140 - i * 40), (w, y0 + 90 + i * 20), (0, y0 + 180)],
            fill=(56, 189, 248, alpha),
        )
    overlay = overlay.filter(ImageFilter.GaussianBlur(70))
    base = img.convert("RGBA")
    base = Image.alpha_composite(base, overlay)
    # Speckle stars
    stars = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(stars)
    for n in range(220):
        x = (n * 97 + 41 + int(phase * 40)) % w
        y = (n * 53 + 17) % h
        a = 50 + (n * 13) % 150
        sdraw.ellipse((x, y, x + 2, y + 2), fill=(186, 230, 253, a))
    stars = stars.filter(ImageFilter.GaussianBlur(0.6))
    return Image.alpha_composite(base, stars)


def soft_orb(size: int, color: tuple[int, int, int], peak: int = 200) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cx = cy = size / 2
    rmax = size / 2
    px = img.load()
    for y in range(size):
        for x in range(size):
            d = math.hypot(x - cx, y - cy) / rmax
            if d >= 1:
                continue
            fall = (1 - d) ** 2.2
            a = int(peak * fall)
            px[x, y] = (*color, a)
    return img.filter(ImageFilter.GaussianBlur(2))


def track(w=420, h=12) -> Image.Image:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=(30, 41, 59, 220))
    draw.rounded_rectangle((1, 1, w - 2, h - 2), radius=h // 2 - 1, outline=(56, 189, 248, 90))
    return img


def thumb(w=110, h=12) -> Image.Image:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=(56, 189, 248, 255))
    glow = img.filter(ImageFilter.GaussianBlur(3))
    return Image.alpha_composite(glow, img)


def dot(size=18) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((1, 1, size - 2, size - 2), fill=(125, 211, 252, 255))
    return img.filter(ImageFilter.GaussianBlur(0.8))


def logo(size: int = 192) -> Image.Image:
    """Bright cyan mark — readable on TVs even when filmed."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    m = size // 10
    draw.ellipse((m, m, size - m, size - m), outline=(56, 189, 248, 255), width=max(6, size // 18))
    draw.ellipse((size // 3, size // 3, size * 2 // 3, size * 2 // 3), fill=(125, 211, 252, 255))
    glow = img.filter(ImageFilter.GaussianBlur(4))
    return Image.alpha_composite(glow, img)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # 8 motion frames — render small then upscale (fast) for clear background motion.
    frames = 8
    for i in range(frames):
        phase = i / frames * 2.0
        small = gradient_backdrop(640, 360, phase=phase)
        frame = small.resize((1280, 720), Image.Resampling.LANCZOS)
        frame.save(OUT / ("backdrop_%d.png" % i), optimize=True)
        if i == 0:
            frame.save(OUT / "backdrop.png", optimize=True)
    soft_orb(640, (34, 211, 238), peak=230).save(OUT / "orb_cyan.png", optimize=True)
    soft_orb(520, (14, 165, 233), peak=210).save(OUT / "orb_sky.png", optimize=True)
    soft_orb(480, (56, 189, 248), peak=180).save(OUT / "orb_glow.png", optimize=True)
    track(w=480, h=14).save(OUT / "track.png", optimize=True)
    thumb(w=150, h=14).save(OUT / "thumb.png", optimize=True)
    dot(size=22).save(OUT / "dot.png", optimize=True)
    logo(192).save(OUT / "logo.png", optimize=True)
    logo(192).save(OUT / "watermark.png", optimize=True)
    print("Wrote Plymouth motion frames + assets to", OUT)


if __name__ == "__main__":
    main()
