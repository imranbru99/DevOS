#!/usr/bin/env python3
"""DevOS Flagship Luxury Wallpaper Generator.

Renders an ultra-premium, modern 3D fluid ribbon wallpaper for DevOS.
Designed to replace flat/dark defaults with a vibrant, luminous, high-end
flagship OS background while preserving maximum legibility for desktop icons
and the bottom taskbar.

Outputs:
  - build/includes.chroot/usr/share/wallpapers/DevOS/DevOS-Default.png
  - build/includes.chroot/usr/share/wallpapers/DevOS/metadata.json
  - build/includes.chroot/usr/share/wallpapers/DevOS/contents/images/2560x1440.png
  - build/includes.chroot/usr/share/wallpapers/DevOS/contents/screenshot.png
"""

import json
import math
from pathlib import Path
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "build" / "includes.chroot" / "usr" / "share" / "wallpapers" / "DevOS"

W, H = 2560, 1440
THUMB_W, THUMB_H = 400, 225
F32 = np.float32


def hexc(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)], F32)


def smoothstep(e0: float, e1: float, v: np.ndarray) -> np.ndarray:
    t = np.clip((v - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def grad(t: np.ndarray, stops: list) -> np.ndarray:
    t = np.asarray(t, F32)
    pos = [p for p, _ in stops]
    out = np.empty(t.shape + (3,), F32)
    for ch in range(3):
        out[..., ch] = np.interp(t, pos, [c[ch] for _, c in stops])
    return out


def generate_flagship_wallpaper() -> Image.Image:
    # Coordinate grids normalized by height
    x = ((np.arange(W, dtype=F32) + 0.5) / H)[None, :]
    y = ((np.arange(H, dtype=F32) + 0.5) / H)[:, None]
    A = W / H

    # 1. Base Gradient - Deep midnight sapphire to royal indigo
    bg_top = hexc("050914")
    bg_mid = hexc("0a1329")
    bg_bot = hexc("0d1938")

    t_bg = y[:, 0] / 1.0
    bg_col = np.empty((H, 3), F32)
    for ch in range(3):
        bg_col[:, ch] = np.interp(t_bg, [0.0, 0.45, 1.0], [bg_top[ch], bg_mid[ch], bg_bot[ch]])
    img = np.ascontiguousarray(np.broadcast_to(bg_col[:, None, :], (H, W, 3))).astype(F32)

    # Ambient radial glows to give the display rich optical depth
    def add_glow(img, cx, cy, rx, ry, color, strength):
        d2 = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
        glow = np.exp(-d2) * strength
        img += glow[..., None] * color[None, None, :]

    add_glow(img, 1.30, 0.48, 0.70, 0.60, hexc("1d4ed8"), 0.55)   # Royal blue ambient
    add_glow(img, 1.55, 0.65, 0.50, 0.50, hexc("7c3aed"), 0.45)   # Violet ambient
    add_glow(img, 1.15, 0.35, 0.45, 0.40, hexc("06b6d4"), 0.35)   # Cyan highlight ambient
    add_glow(img, 1.65, 0.30, 0.40, 0.35, hexc("db2777"), 0.25)   # Magenta ambient

    # Multi-layered 3D ribbons with surface normal lighting and specular edges
    def add_ribbon(img, *, origin, angle, waves, width, twist_freq, colors, srange, fill_gain=1.0, edge_gain=1.0):
        ox, oy = origin
        a = math.radians(angle)
        ca, sa = math.cos(a), math.sin(a)
        X = x - ox
        Y = y - oy
        s = X * ca + Y * sa
        t = -X * sa + Y * ca

        c = np.zeros_like(s)
        dc = np.zeros_like(s)
        for amp, fr, ph in waves:
            arg = fr * s + ph
            c += amp * np.sin(arg)
            dc += amp * fr * np.cos(arg)

        hw = width * (1.0 + 0.35 * np.sin(1.8 * s + 0.5))
        dhw = width * 0.35 * 1.8 * np.cos(1.8 * s + 0.5)
        tw = np.cos(twist_freq * s + 0.8)
        dtw = -twist_freq * np.sin(twist_freq * s + 0.8)
        g = hw * tw
        dg = dhw * tw + hw * dtw

        s0, s1 = srange
        fade = smoothstep(s0, s0 + 0.35, s) * smoothstep(s1, s1 - 0.35, s)

        rel = t - c
        ag = np.abs(g) + 1e-4
        inside = np.clip((ag - np.abs(rel)) / (1.0 / H) * 0.5 + 0.5, 0.0, 1.0)
        o = np.clip(rel / ag, -1.0, 1.0)

        # 3D surface normal lighting simulation (diffuse + specular reflection)
        norm_z = np.sqrt(np.maximum(1.0 - o * o, 0.0))
        shading = 0.55 + 0.45 * norm_z + 0.35 * np.maximum(o * 0.7 + norm_z * 0.7, 0.0) ** 3

        stops = [(i / (len(colors) - 1), colors[i]) for i in range(len(colors))]
        fcol = grad((o + 1.0) * 0.5, stops)
        body = (inside * fade * shading * fill_gain)[..., None] * fcol
        img += body

        # Rim specular edge illumination
        for sign in (-1.0, 1.0):
            edge_pos = c + sign * g
            edge_slope = dc + sign * dg
            d_edge = np.abs(t - edge_pos) / np.sqrt(1.0 + edge_slope * edge_slope)
            core = np.exp(-(d_edge / 0.0012) ** 2) * 1.2
            glow = np.exp(-d_edge / 0.006) * 0.4
            rim_col = grad(np.array(0.5 + 0.5 * sign), stops)
            edge_light = ((core + glow) * fade * edge_gain)[..., None] * (rim_col * 0.75 + hexc("ffffff") * 0.25)
            img += edge_light

    # Ribbon 1: Deep royal indigo/violet back ribbon
    add_ribbon(img, origin=(1.45, 0.58), angle=35,
               waves=[(0.12, 1.8, 0.5), (0.04, 4.2, 1.2)],
               width=0.16, twist_freq=2.2,
               colors=[hexc("1e1b4b"), hexc("4338ca"), hexc("6366f1"), hexc("7c3aed")],
               srange=(-0.85, 0.95), fill_gain=0.75, edge_gain=0.6)

    # Ribbon 2: Majestic central vibrant ribbon: Azure Blue -> Electric Cyan -> Royal Violet
    add_ribbon(img, origin=(1.25, 0.68), angle=-24,
               waves=[(0.14, 2.1, 0.2), (0.05, 4.8, 1.5)],
               width=0.12, twist_freq=2.6,
               colors=[hexc("0284c7"), hexc("00d4ff"), hexc("38bdf8"), hexc("818cf8"), hexc("c084fc")],
               srange=(-0.95, 1.15), fill_gain=0.85, edge_gain=1.1)

    # Ribbon 3: Luminous fuchsia / rose crest ribbon
    add_ribbon(img, origin=(1.38, 0.52), angle=-32,
               waves=[(0.10, 1.9, 1.8), (0.03, 5.5, 0.4)],
               width=0.08, twist_freq=3.0,
               colors=[hexc("7c3aed"), hexc("a855f7"), hexc("ec4899"), hexc("f43f5e")],
               srange=(-0.75, 0.95), fill_gain=0.80, edge_gain=0.95)

    # Ribbon 4: Slender high-speed light stream (radiant cyan / pearl white)
    add_ribbon(img, origin=(1.18, 0.78), angle=-16,
               waves=[(0.08, 2.5, 1.0), (0.02, 6.2, 0.8)],
               width=0.035, twist_freq=3.8,
               colors=[hexc("22d3ee"), hexc("e0f2fe"), hexc("ffffff")],
               srange=(-0.70, 0.90), fill_gain=0.65, edge_gain=1.4)

    # Ribbon 5: Gentle ambient secondary fold
    add_ribbon(img, origin=(1.50, 0.42), angle=48,
               waves=[(0.07, 2.8, 2.0), (0.02, 6.0, 0.0)],
               width=0.065, twist_freq=3.2,
               colors=[hexc("2563eb"), hexc("60a5fa"), hexc("a78bfa")],
               srange=(-0.65, 0.75), fill_gain=0.70, edge_gain=0.8)

    # Desktop Icon Ergonomics:
    # Gently taper brightness in the top-left area where the 12 desktop icons live
    # so white text labels remain crisp, sharp, and 100% legible with zero eye strain.
    icon_mask = 1.0 - 0.40 * np.exp(-(((x - 0.35) / 0.55) ** 2 + ((y - 0.28) / 0.38) ** 2))
    img *= icon_mask[..., None]

    # Taskbar ergonomics (bottom 44px dark shelf)
    taskbar_shelf = smoothstep(0.96, 0.88, y / 1.0)
    img = img * (0.80 + 0.20 * taskbar_shelf[..., None])

    # Vignette (gentle subtle outer corner falloff)
    r_vig = np.sqrt(((x - A / 2.0) / (A / 2.0)) ** 2 * 0.7 + ((y - 0.5) / 0.5) ** 2 * 0.7)
    vignette = 1.0 - 0.28 * smoothstep(0.40, 1.30, r_vig)
    img *= vignette[..., None]

    # Film grain dither to prevent banding on 8-bit displays
    rng = np.random.RandomState(42)
    dith = (rng.uniform(-0.7, 0.7, (H, W, 1)) + rng.uniform(-0.7, 0.7, (H, W, 1))).astype(F32) / 255.0
    img = np.clip(img + dith, 0.0, 1.0)

    out_arr = (img * 255.0).astype(np.uint8)
    return Image.fromarray(out_arr, "RGB")


def main():
    print("==> Rendering DevOS Flagship Luxury Wallpaper...")
    im = generate_flagship_wallpaper()

    # Ensure output directories exist
    images_dir = OUT_DIR / "contents" / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # 1. Main PNG file (direct path referenced by SDDM, lockscreen, and scripts)
    default_png = OUT_DIR / "DevOS-Default.png"
    im.save(default_png, "PNG", optimize=True)
    print(f"Saved: {default_png} ({default_png.stat().st_size // 1024} KB)")

    # 2. KDE Plasma wallpaper package image (contents/images/2560x1440.png)
    pkg_img = images_dir / "2560x1440.png"
    im.save(pkg_img, "PNG", optimize=True)
    print(f"Saved: {pkg_img}")

    # 3. KDE Plasma wallpaper package metadata (metadata.json)
    meta = {
        "KPlugin": {
            "Id": "DevOS",
            "Name": "DevOS Flagship",
            "Authors": [{"Name": "DevOS"}],
            "License": "CC-BY-SA-4.0"
        }
    }
    meta_path = OUT_DIR / "metadata.json"
    meta_path.write_text(json.dumps(meta, indent=4) + "\n", encoding="utf-8")
    print(f"Saved: {meta_path}")

    # 4. Thumbnail screenshot for KDE wallpaper selector (400x225)
    thumb_path = OUT_DIR / "contents" / "screenshot.png"
    thumb = im.resize((THUMB_W, THUMB_H), Image.LANCZOS)
    thumb.save(thumb_path, "PNG", optimize=True)
    print(f"Saved: {thumb_path}")

    print("==> Successfully generated all DevOS Flagship wallpaper assets.")


if __name__ == "__main__":
    main()
