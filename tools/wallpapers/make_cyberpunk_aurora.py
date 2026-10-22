#!/usr/bin/env python3
"""DevOS Flagship Wallpaper - Cyberpunk & Digital Aurora Edition.

Procedurally renders an ultra-high-definition (2560x1440 / 4K) abstract Cyberpunk & Digital Aurora
wallpaper for DevOS.

Visual Elements:
- Deep obsidian and midnight cosmic canvas (#02040a to #060a18)
- Flowing digital aurora borealis curtains (electric cyan, neon turquoise, ultra-violet, cyber magenta, emerald glow)
- 3D harmonic wave interference creating realistic drapery & folds of northern lights
- Luminous laser horizon and cyber light particles
- Desktop ergonomics: Top-left icon safe zone with pristine contrast, dark taskbar shelf
- No logos, no text: Pure abstract high-tech visual luxury
"""

import json
import math
import os
import shutil
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
BUILD_WP = ROOT / "build" / "includes.chroot" / "usr" / "share" / "wallpapers"
USER_WP = Path(os.path.expanduser("~/.local/share/wallpapers"))

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


def add_dither(img: np.ndarray, strength: float = 1.0) -> np.ndarray:
    rng = np.random.RandomState(42)
    dith = (rng.uniform(-0.6, 0.6, (H, W, 1)) + rng.uniform(-0.6, 0.6, (H, W, 1))).astype(F32) * (strength / 255.0)
    return np.clip(img + dith, 0.0, 1.0)


def render_cyberpunk_aurora(width: int = W, height: int = H) -> Image.Image:
    print(f"--> Computing Cyberpunk Aurora coordinate fields ({width}x{height})...")
    x = ((np.arange(width, dtype=F32) + 0.5) / height)[None, :]
    y = ((np.arange(height, dtype=F32) + 0.5) / height)[:, None]
    aspect = width / height

    # 1. Base Gradient: Deep Obsidian Cosmic Night
    # Sky descends from deepest space black into deep midnight indigo
    t_bg = y[:, 0]
    bg_stops = [
        (0.00, hexc("020308")),  # Deep space void
        (0.35, hexc("040713")),  # Midnight abyss
        (0.65, hexc("070e24")),  # Deep royal navy
        (0.85, hexc("0a122e")),  # Horizon atmospheric indigo
        (1.00, hexc("050916")),  # Lower ground base
    ]
    bg_col = np.empty((height, 3), F32)
    for ch in range(3):
        bg_col[:, ch] = np.interp(t_bg, [p for p, _ in bg_stops], [c[ch] for _, c in bg_stops])
    img = np.ascontiguousarray(np.broadcast_to(bg_col[:, None, :], (height, width, 3))).astype(F32)

    # 2. Digital Aurora Curtains
    # An aurora curtain is modeled as a vertical fold of light that undulates across the sky
    # with height-dependent shimmer, vertical streaks, and rich harmonic oscillation.
    print("--> Simulating multi-tier digital aurora curtains...")

    def add_aurora_curtain(
        img,
        *,
        base_y: float,
        amplitude: float,
        curtain_height: float,
        color_stops: list,
        frequencies: list,
        streak_density: float = 80.0,
        intensity: float = 1.0,
        x_start: float = 0.3,
        x_end: float = 2.0,
    ):
        # Base undulating baseline curve y = f(x)
        curve = np.zeros_like(x)
        for amp, freq, phase in frequencies:
            curve += amp * np.sin(freq * x + phase)
        baseline = base_y + curve

        # Distance above baseline
        dist_above = baseline - y
        in_curtain = dist_above >= 0.0

        # Vertical intensity profile: bright sharp lower rim, soft decaying upper ray
        rel_h = np.clip(dist_above / curtain_height, 0.0, 1.0)
        # Sharp glowing bottom edge with long vertical rays
        v_profile = np.exp(-rel_h * 2.8) * np.sin(rel_h * math.pi) ** 0.55 * in_curtain

        # Vertical curtain folds & light streaks (aurora ray structure)
        vertical_rays = 0.55 + 0.45 * np.sin(x * streak_density + np.sin(y * 12.0) * 0.4)
        secondary_rays = 0.70 + 0.30 * np.cos(x * (streak_density * 1.6) - y * 4.0)
        shimmer = vertical_rays * secondary_rays

        # Color mapping across height of curtain
        curtain_colors = grad(rel_h, color_stops)

        # Horizontal fade (fade on left for desktop icons, fade on far right edge)
        h_fade = smoothstep(x_start, x_start + 0.35, x) * smoothstep(x_end, x_end - 0.25, x)

        curtain_light = (v_profile * shimmer * h_fade * intensity)[..., None] * curtain_colors
        img += curtain_light

        # Bottom glowing ion edge (concentrated neon line)
        d_edge = np.abs(y - baseline)
        edge_glow = np.exp(-((d_edge / 0.008) ** 2)) * (h_fade * intensity * 0.75)
        rim_color = color_stops[0][1] * 0.6 + hexc("ffffff") * 0.4
        img += edge_glow[..., None] * rim_color

    # Aurora Curtain 1: Ethereal Ultra-Violet & Deep Violet Backdrop
    add_aurora_curtain(
        img,
        base_y=0.62,
        amplitude=0.15,
        curtain_height=0.55,
        color_stops=[
            (0.00, hexc("7c3aed")),  # Vivid violet
            (0.35, hexc("8b5cf6")),  # Purple ray
            (0.70, hexc("6366f1")),  # Indigo transition
            (1.00, hexc("1e1b4b")),  # Space fade
        ],
        frequencies=[(0.09, 2.2, 0.4), (0.04, 5.1, 1.8), (0.02, 11.0, 0.9)],
        streak_density=65.0,
        intensity=0.85,
        x_start=0.35,
        x_end=1.95,
    )

    # Aurora Curtain 2: Vibrant Electric Cyan & Turquoise Main Wave
    add_aurora_curtain(
        img,
        base_y=0.56,
        amplitude=0.12,
        curtain_height=0.48,
        color_stops=[
            (0.00, hexc("00f5d4")),  # Brilliant neon turquoise
            (0.25, hexc("06b6d4")),  # Electric cyan
            (0.60, hexc("0284c7")),  # Ocean azure
            (1.00, hexc("0369a1")),  # Deep cyan
        ],
        frequencies=[(0.11, 2.8, 1.2), (0.05, 6.2, 0.5), (0.02, 14.0, 2.1)],
        streak_density=90.0,
        intensity=1.10,
        x_start=0.40,
        x_end=1.90,
    )

    # Aurora Curtain 3: Cyber Magenta & Hot Pink Dynamic Crest
    add_aurora_curtain(
        img,
        base_y=0.50,
        amplitude=0.10,
        curtain_height=0.42,
        color_stops=[
            (0.00, hexc("f43f5e")),  # Neon Rose / Hot Pink
            (0.30, hexc("ec4899")),  # Magenta
            (0.65, hexc("d946ef")),  # Electric Orchid
            (1.00, hexc("7c3aed")),  # Violet fade
        ],
        frequencies=[(0.08, 3.4, 2.5), (0.03, 7.5, 1.1), (0.015, 16.0, 0.3)],
        streak_density=110.0,
        intensity=0.95,
        x_start=0.55,
        x_end=1.85,
    )

    # Aurora Curtain 4: Luminous Arctic Emerald Flare
    add_aurora_curtain(
        img,
        base_y=0.46,
        amplitude=0.08,
        curtain_height=0.38,
        color_stops=[
            (0.00, hexc("10b981")),  # Radiant emerald
            (0.35, hexc("34d399")),  # Mint neon
            (0.70, hexc("059669")),  # Deep emerald
            (1.00, hexc("064e3b")),  # Dark forest fade
        ],
        frequencies=[(0.07, 3.8, 3.2), (0.03, 8.8, 2.0)],
        streak_density=75.0,
        intensity=0.75,
        x_start=0.65,
        x_end=1.80,
    )

    # 3. Luminous Neon Digital Horizon & Perspective Light Grid
    print("--> Rendering neon horizon & atmospheric depth...")
    horizon_y = 0.72

    # Atmospheric horizon glow (diffuse neon bloom across horizon line)
    d_horiz = np.abs(y - horizon_y)
    horiz_bloom = np.exp(-((d_horiz / 0.12) ** 2)) * 0.45
    horiz_core = np.exp(-((d_horiz / 0.0035) ** 2)) * 1.25

    # Horizon color blend: Cyan to Magenta to Violet
    h_grad = grad(
        (x[0, :] / aspect),
        [
            (0.00, hexc("06b6d4")),
            (0.40, hexc("3b82f6")),
            (0.70, hexc("d946ef")),
            (1.00, hexc("00f5d4")),
        ],
    )
    horiz_light = (horiz_bloom + horiz_core)[..., None] * h_grad[None, :, :]
    # Horizon fade on far left for clean icon visibility
    h_fade_left = smoothstep(0.20, 0.50, x)
    img += horiz_light * h_fade_left[..., None]

    # Subtle futuristic perspective digital mesh beneath the horizon
    ground_mask = (y > horizon_y).astype(F32)
    z_depth = 1.0 / np.maximum(0.0001, y - horizon_y)
    x_proj = (x - aspect * 0.55) * z_depth

    # Smooth subtle cyber grid lines
    line_v = np.exp(-(((np.sin(x_proj * 1.8)) ** 2) / 0.015)) * 0.28
    line_h = np.exp(-(((np.sin(z_depth * 0.7)) ** 2) / 0.020)) * 0.22
    grid_lines = np.maximum(line_v, line_h) * ground_mask
    grid_fade = smoothstep(0.0, 0.06, y - horizon_y) * smoothstep(1.0, 0.75, y) * h_fade_left
    img += (grid_lines * grid_fade)[..., None] * hexc("00f5d4") * 0.45
    img += (grid_lines * grid_fade)[..., None] * hexc("ec4899") * 0.25

    # 4. Fluid 3D Energy Ribbon Weaving Through the Aurora
    print("--> Adding 3D luminous cyber ribbon...")
    def add_cyber_ribbon(ox, oy, angle, waves, width, colors, intensity=1.0):
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

        hw = width * (1.0 + 0.35 * np.sin(2.0 * s + 0.4))
        fade = smoothstep(-1.1, -0.6, s) * smoothstep(1.2, 0.7, s) * smoothstep(0.35, 0.65, x)

        rel = t - c
        inside = np.clip((hw - np.abs(rel)) / (1.0 / height) * 0.6 + 0.5, 0.0, 1.0)
        norm_t = np.clip(rel / (hw + 1e-4), -1.0, 1.0)

        stops = [(i / (len(colors) - 1), colors[i]) for i in range(len(colors))]
        col = grad((norm_t + 1.0) * 0.5, stops)

        # Translucent glass energy lighting
        shading = 0.6 + 0.4 * np.sqrt(np.maximum(1.0 - norm_t * norm_t, 0.0))
        img[...] += (inside * fade * shading * intensity)[..., None] * col

        # Rim light edges
        for sign in (-1.0, 1.0):
            d_edge = np.abs(t - (c + sign * hw))
            core = np.exp(-((d_edge / 0.0015) ** 2)) * 1.5
            glow = np.exp(-(d_edge / 0.007)) * 0.5
            img[...] += ((core + glow) * fade * intensity)[..., None] * (col * 0.6 + hexc("ffffff") * 0.4)

    add_cyber_ribbon(
        ox=1.20,
        oy=0.60,
        angle=-20,
        waves=[(0.12, 2.2, 0.5), (0.04, 5.4, 1.6)],
        width=0.045,
        colors=[hexc("00f5d4"), hexc("38bdf8"), hexc("c084fc"), hexc("f43f5e")],
        intensity=0.90,
    )

    # 5. Cyber Stardust & Optical Sparkles
    print("--> Sprinkling cyber stardust & light points...")
    rng = np.random.RandomState(1337)
    num_particles = 320
    px = rng.uniform(0.40 * aspect, aspect * 0.98, num_particles)
    py = rng.uniform(0.10, 0.70, num_particles)
    p_rad = rng.uniform(0.0008, 0.0022, num_particles)
    p_bright = rng.uniform(0.35, 1.0, num_particles)
    palette = [hexc("00f5d4"), hexc("38bdf8"), hexc("f43f5e"), hexc("ffffff"), hexc("a855f7")]

    for i in range(num_particles):
        col = palette[i % len(palette)]
        d2 = ((x - px[i]) ** 2 + (y - py[i]) ** 2)
        star = np.exp(-d2 / (p_rad[i] ** 2)) * p_bright[i]
        # Cross flare for brightest stars
        if p_bright[i] > 0.85:
            d_cross = np.exp(-(np.abs(x - px[i]) / 0.0006) ** 2) * np.exp(-(np.abs(y - py[i]) / 0.02) ** 2)
            d_cross += np.exp(-(np.abs(y - py[i]) / 0.0006) ** 2) * np.exp(-(np.abs(x - px[i]) / 0.02) ** 2)
            star += d_cross * 0.4
        img += star[..., None] * col

    # 6. Ergonomics: Desktop Icons Safe Zone & Taskbar Shelf
    print("--> Applying ergonomics: icon zone legibility & taskbar shelf...")
    # Smooth dark falloff on the left where 12 desktop icons live
    icon_zone = 1.0 - 0.35 * np.exp(-(((x - 0.28) / 0.48) ** 2 + ((y - 0.32) / 0.42) ** 2))
    img *= icon_zone[..., None]

    # Taskbar ergonomics (bottom 48px subtle dark shelf so dock and tray are 100% visible)
    taskbar_shelf = smoothstep(0.96, 0.88, y)
    img = img * (0.82 + 0.18 * taskbar_shelf[..., None])

    # Soft subtle vignette for cinematic focus
    r_vig = np.sqrt(((x - aspect / 2.0) / (aspect / 2.0)) ** 2 * 0.7 + ((y - 0.5) / 0.5) ** 2 * 0.7)
    vignette = 1.0 - 0.22 * smoothstep(0.45, 1.35, r_vig)
    img *= vignette[..., None]

    # 7. Film Grain Dither (eliminates banding on 8-bit monitors)
    img = add_dither(img, strength=0.9)

    out_arr = (np.clip(img, 0.0, 1.0) * 255.0).astype(np.uint8)
    return Image.fromarray(out_arr, "RGB")


def deploy_wallpaper(im: Image.Image):
    print("==> Deploying Cyberpunk Aurora Flagship Wallpaper...")

    targets = [
        BUILD_WP,
        USER_WP,
    ]

    for base in targets:
        # 1. Primary DevOS package directory
        devos_pkg = base / "DevOS"
        images_dir = devos_pkg / "contents" / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        # DevOS-Default.png
        default_png = devos_pkg / "DevOS-Default.png"
        im.save(default_png, "PNG", optimize=True)
        print(f"Saved: {default_png} ({default_png.stat().st_size // 1024} KB)")

        # 2560x1440.png for KDE plasma wallpaper engine
        pkg_img = images_dir / "2560x1440.png"
        im.save(pkg_img, "PNG", optimize=True)

        # metadata.json
        meta = {
            "KPlugin": {
                "Id": "DevOS",
                "Name": "DevOS Cyberpunk Aurora",
                "Authors": [{"Name": "DevOS"}],
                "License": "CC-BY-SA-4.0",
            }
        }
        (devos_pkg / "metadata.json").write_text(json.dumps(meta, indent=4) + "\n", encoding="utf-8")

        # Thumbnail screenshot (400x225)
        thumb_path = devos_pkg / "contents" / "screenshot.png"
        thumb = im.resize((THUMB_W, THUMB_H), Image.LANCZOS)
        thumb.save(thumb_path, "PNG", optimize=True)

        # Also save to DevOS-Default folder if present
        devos_default_dir = base / "DevOS-Default"
        if devos_default_dir.exists():
            (devos_default_dir / "contents" / "images").mkdir(parents=True, exist_ok=True)
            im.save(devos_default_dir / "contents" / "images" / "2560x1440.png", "PNG", optimize=True)
            im.save(devos_default_dir / "DevOS-Default.png", "PNG", optimize=True)
            thumb.save(devos_default_dir / "contents" / "screenshot.png", "PNG", optimize=True)

        # Also update DevOS-Slideshow flagship slot
        slideshow_dir = base / "DevOS-Slideshow"
        if slideshow_dir.exists():
            im.save(slideshow_dir / "01_DevOS_Cyberpunk_Aurora.png", "PNG", optimize=True)

    # If live system /usr/share/wallpapers/DevOS exists and is writable, copy there
    sys_devos = Path("/usr/share/wallpapers/DevOS")
    if sys_devos.exists():
        try:
            shutil.copy2(USER_WP / "DevOS" / "DevOS-Default.png", sys_devos / "DevOS-Default.png")
            print("Updated live system /usr/share/wallpapers/DevOS/DevOS-Default.png")
        except PermissionError:
            print("Note: /usr/share/wallpapers/DevOS requires root, will update via pkexec/sudo if needed.")


def main():
    t0 = time.time()
    im = render_cyberpunk_aurora(W, H)
    deploy_wallpaper(im)
    print(f"\n==> Successfully generated and deployed in {time.time() - t0:.1f}s!")


if __name__ == "__main__":
    main()
