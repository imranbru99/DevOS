#!/usr/bin/env python3
"""DevOS Premium Wallpaper & Slideshow Generator.

Generates:
1. Ultra-premium Flagship Luxury Default Wallpaper (DevOS-Default).
2. 5 Brand-new Vibrant Luxury Wallpapers:
   - DevOS-CelestialBloom
   - DevOS-SolarDawn
   - DevOS-EmeraldAurora
   - DevOS-LiquidTitanium
   - DevOS-NeonCyberpulse
3. Curated 32+ Wallpaper Slideshow Suite in DevOS-Slideshow/.
4. Synchronizes packages to:
   - build/includes.chroot/usr/share/wallpapers/
   - ~/.local/share/wallpapers/ (live host)
"""

import json
import math
import os
import shutil
import time
from pathlib import Path

import numpy as np
from PIL import Image

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
    dith = (rng.uniform(-0.7, 0.7, (H, W, 1)) + rng.uniform(-0.7, 0.7, (H, W, 1))).astype(F32) * (strength / 255.0)
    return np.clip(img + dith, 0.0, 1.0)


# ==============================================================================
# 1. Flagship Luxury Default Wallpaper
# ==============================================================================
def render_flagship_default() -> Image.Image:
    x = ((np.arange(W, dtype=F32) + 0.5) / H)[None, :]
    y = ((np.arange(H, dtype=F32) + 0.5) / H)[:, None]
    A = W / H

    bg_top = hexc("050814")
    bg_mid = hexc("0a142c")
    bg_bot = hexc("0e1d40")

    t_bg = y[:, 0] / 1.0
    bg_col = np.empty((H, 3), F32)
    for ch in range(3):
        bg_col[:, ch] = np.interp(t_bg, [0.0, 0.45, 1.0], [bg_top[ch], bg_mid[ch], bg_bot[ch]])
    img = np.ascontiguousarray(np.broadcast_to(bg_col[:, None, :], (H, W, 3))).astype(F32)

    def add_glow(img, cx, cy, rx, ry, color, strength):
        d2 = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
        img += (np.exp(-d2) * strength)[..., None] * color[None, None, :]

    add_glow(img, 1.30, 0.48, 0.75, 0.65, hexc("1d4ed8"), 0.65)
    add_glow(img, 1.55, 0.65, 0.55, 0.55, hexc("7c3aed"), 0.50)
    add_glow(img, 1.15, 0.35, 0.50, 0.45, hexc("06b6d4"), 0.45)
    add_glow(img, 1.70, 0.28, 0.45, 0.40, hexc("db2777"), 0.30)
    add_glow(img, 0.90, 0.70, 0.60, 0.50, hexc("0284c7"), 0.35)

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

        d = t - c
        u = d / np.maximum(np.abs(g), 0.001)

        inside = np.abs(u) <= 1.0
        s0, s1 = srange
        ramp = 0.25
        long_fade = smoothstep(s0, s0 + ramp, s) * smoothstep(s1, s1 - ramp, s)

        N_u = u
        N_s = -dc - dg * u
        N_z = np.sqrt(np.maximum(0.01, 1.0 - u * u * 0.8))
        norm = np.sqrt(N_u * N_u + N_s * N_s + N_z * N_z)
        N_u /= norm
        N_s /= norm
        N_z /= norm

        L_u, L_s, L_z = 0.4, -0.6, 0.7
        L_norm = math.sqrt(L_u * L_u + L_s * L_s + L_z * L_z)
        L_u, L_s, L_z = L_u / L_norm, L_s / L_norm, L_z / L_norm

        diffuse = np.maximum(0.0, N_u * L_u + N_s * L_s + N_z * L_z)
        spec = np.maximum(0.0, N_z) ** 14.0
        fresnel = (1.0 - N_z) ** 2.5

        t_col = np.clip((u + 1.0) * 0.5, 0.0, 1.0)
        col_stops = [(i / (len(colors) - 1), c) for i, c in enumerate(colors)]
        base_col = grad(t_col, col_stops)

        lit_col = base_col * (0.35 + 0.65 * diffuse[..., None]) + spec[..., None] * 0.45 * hexc("ffffff") + fresnel[..., None] * 0.35 * colors[-1]

        alpha = inside.astype(F32) * long_fade * fill_gain
        img += lit_col * alpha[..., None]

        edge_dist = np.abs(np.abs(d) - np.abs(g))
        edge_glow = np.exp(-(edge_dist / 0.006) ** 2) * edge_gain * long_fade
        img += edge_glow[..., None] * (0.6 * colors[-1] + 0.4 * hexc("ffffff"))

    add_ribbon(img, origin=(1.45, 0.58), angle=32,
               waves=[(0.14, 1.8, 0.4), (0.04, 4.2, 1.2)],
               width=0.20, twist_freq=1.5,
               colors=[hexc("0f2b5c"), hexc("1e40af"), hexc("3b82f6"), hexc("60a5fa")],
               srange=(-0.95, 1.05), fill_gain=0.92, edge_gain=1.1)

    add_ribbon(img, origin=(1.32, 0.46), angle=-22,
               waves=[(0.11, 2.1, 0.9), (0.03, 5.0, 0.3)],
               width=0.14, twist_freq=2.2,
               colors=[hexc("1e1b4b"), hexc("4338ca"), hexc("6366f1"), hexc("a5b4fc")],
               srange=(-0.85, 0.95), fill_gain=0.88, edge_gain=1.2)

    add_ribbon(img, origin=(1.25, 0.52), angle=12,
               waves=[(0.10, 2.4, 1.5), (0.03, 5.8, 1.8)],
               width=0.08, twist_freq=2.8,
               colors=[hexc("0284c7"), hexc("06b6d4"), hexc("38bdf8"), hexc("bae6fd")],
               srange=(-0.80, 0.85), fill_gain=0.82, edge_gain=1.3)

    add_ribbon(img, origin=(1.18, 0.72), angle=-16,
               waves=[(0.08, 2.5, 1.0), (0.02, 6.2, 0.8)],
               width=0.045, twist_freq=3.8,
               colors=[hexc("00f2fe"), hexc("e0f2fe"), hexc("ffffff")],
               srange=(-0.70, 0.90), fill_gain=0.75, edge_gain=1.5)

    add_ribbon(img, origin=(1.50, 0.40), angle=48,
               waves=[(0.07, 2.8, 2.0), (0.02, 6.0, 0.0)],
               width=0.075, twist_freq=3.2,
               colors=[hexc("2563eb"), hexc("60a5fa"), hexc("c084fc")],
               srange=(-0.65, 0.75), fill_gain=0.75, edge_gain=0.9)

    icon_mask = 1.0 - 0.35 * np.exp(-(((x - 0.35) / 0.55) ** 2 + ((y - 0.28) / 0.38) ** 2))
    img *= icon_mask[..., None]

    taskbar_shelf = smoothstep(0.96, 0.88, y / 1.0)
    img = img * (0.84 + 0.16 * taskbar_shelf[..., None])

    r_vig = np.sqrt(((x - A / 2.0) / (A / 2.0)) ** 2 * 0.7 + ((y - 0.5) / 0.5) ** 2 * 0.7)
    vignette = 1.0 - 0.25 * smoothstep(0.40, 1.30, r_vig)
    img *= vignette[..., None]

    img = add_dither(img)
    return Image.fromarray((img * 255.0).astype(np.uint8), "RGB")


# ==============================================================================
# 2. Celestial Bloom Wallpaper (Vibrant Organic Fluid Bloom)
# ==============================================================================
def render_celestial_bloom() -> Image.Image:
    x = ((np.arange(W, dtype=F32) + 0.5) / H)[None, :]
    y = ((np.arange(H, dtype=F32) + 0.5) / H)[:, None]
    A = W / H

    bg = grad(y[:, 0], [(0.0, hexc("030612")), (0.5, hexc("070e24")), (1.0, hexc("0b1536"))])
    img = np.ascontiguousarray(np.broadcast_to(bg[:, None, :], (H, W, 3))).astype(F32)

    cx, cy = 1.15, 0.52

    # Radial ambient energy
    d2 = ((x - cx) / 0.7) ** 2 + ((y - cy) / 0.6) ** 2
    img += (np.exp(-d2) * 0.8)[..., None] * hexc("0284c7")

    # Layered petals
    petals = [
        (0.0, 0.38, 0.18, [hexc("0f172a"), hexc("1d4ed8"), hexc("38bdf8")]),
        (0.5, 0.42, 0.20, [hexc("1e1b4b"), hexc("4f46e5"), hexc("818cf8")]),
        (1.1, 0.35, 0.16, [hexc("0369a1"), hexc("06b6d4"), hexc("67e8f9")]),
        (1.7, 0.40, 0.19, [hexc("312e81"), hexc("6366f1"), hexc("a5b4fc")]),
        (2.3, 0.36, 0.17, [hexc("0c4a6e"), hexc("0284c7"), hexc("38bdf8")]),
        (2.9, 0.44, 0.22, [hexc("2e1065"), hexc("7c3aed"), hexc("c084fc")]),
        (3.6, 0.39, 0.18, [hexc("0284c7"), hexc("38bdf8"), hexc("e0f2fe")]),
        (4.2, 0.43, 0.20, [hexc("1e3a8a"), hexc("2563eb"), hexc("93c5fd")]),
        (4.9, 0.37, 0.17, [hexc("4338ca"), hexc("6366f1"), hexc("c4b5fd")]),
        (5.5, 0.41, 0.19, [hexc("0f766e"), hexc("14b8a6"), hexc("5eead4")]),
    ]

    for angle, length, width, colors in petals:
        ca, sa = math.cos(angle), math.sin(angle)
        dx = x - cx
        dy = y - cy
        p_len = dx * ca + dy * sa
        p_wid = -dx * sa + dy * ca

        shape = smoothstep(0.0, 0.08, p_len) * smoothstep(length, length * 0.6, p_len)
        p_ratio = np.clip(p_len / length, 0.0, 1.0)
        hw = width * (1.0 - p_ratio ** 1.5) * (1.0 + 0.3 * np.sin(p_len * 20.0))
        dist = np.abs(p_wid) / np.maximum(0.001, hw)

        mask = smoothstep(1.0, 0.4, dist) * shape
        edge = np.exp(-(np.abs(dist - 0.9) / 0.08) ** 2) * shape

        t_col = np.clip(p_len / length, 0.0, 1.0)
        col = grad(t_col, [(i / (len(colors) - 1), c) for i, c in enumerate(colors)])

        img += col * mask[..., None] * 0.85
        img += (edge[..., None] * 0.7) * (0.5 * colors[-1] + 0.5 * hexc("ffffff"))

    # Luminous center
    d_center = np.sqrt(((x - cx) / 0.12) ** 2 + ((y - cy) / 0.12) ** 2)
    img += (np.exp(-d_center * 3.0) * 1.2)[..., None] * hexc("e0f2fe")
    img += (np.exp(-d_center * 1.2) * 0.6)[..., None] * hexc("00f2fe")

    img = add_dither(img)
    return Image.fromarray((img * 255.0).astype(np.uint8), "RGB")


# ==============================================================================
# 3. Solar Dawn Wallpaper (Vibrant Sunrise Horizon)
# ==============================================================================
def render_solar_dawn() -> Image.Image:
    x = ((np.arange(W, dtype=F32) + 0.5) / H)[None, :]
    y = ((np.arange(H, dtype=F32) + 0.5) / H)[:, None]
    A = W / H

    bg = grad(y[:, 0], [
        (0.0, hexc("050512")),
        (0.35, hexc("0c0e2a")),
        (0.55, hexc("1e1b4b")),
        (0.70, hexc("831843")),
        (0.82, hexc("ea580c")),
        (0.92, hexc("fbbf24")),
        (1.0, hexc("1c1917")),
    ])
    img = np.ascontiguousarray(np.broadcast_to(bg[:, None, :], (H, W, 3))).astype(F32)

    sun_x, sun_y = 1.05, 0.72

    # Sunburst bloom
    d_sun = np.sqrt(((x - sun_x) / 0.45) ** 2 + ((y - sun_y) / 0.25) ** 2)
    img += (np.exp(-d_sun * 2.2) * 1.3)[..., None] * hexc("fef08a")
    img += (np.exp(-d_sun * 0.8) * 0.7)[..., None] * hexc("f97316")

    # Light rays radiating upwards
    angle = np.arctan2(y - sun_y, x - sun_x)
    rays = (np.sin(angle * 14.0) * 0.5 + 0.5) ** 2.0
    ray_falloff = smoothstep(0.75, 0.1, d_sun) * smoothstep(0.85, 0.4, y)
    img += (rays * ray_falloff * 0.35)[..., None] * hexc("fed7aa")

    # Sleek dark terrain silhouettes
    t1 = 0.78 + 0.04 * np.sin(3.5 * x) + 0.015 * np.sin(8.0 * x)
    terrain1 = smoothstep(t1 - 0.005, t1 + 0.005, y)
    img = img * (1.0 - 0.75 * terrain1)[..., None] + terrain1[..., None] * hexc("09090b") * 0.25

    t2 = 0.86 + 0.03 * np.cos(4.2 * x + 1.0)
    terrain2 = smoothstep(t2 - 0.004, t2 + 0.004, y)
    img = img * (1.0 - 0.85 * terrain2)[..., None] + terrain2[..., None] * hexc("030712") * 0.15

    # Specular rim on terrain
    rim1 = np.exp(-((y - t1) / 0.004) ** 2) * 0.85
    img += rim1[..., None] * hexc("fde047")

    img = add_dither(img)
    return Image.fromarray((img * 255.0).astype(np.uint8), "RGB")


# ==============================================================================
# 4. Emerald Aurora Wallpaper (Dancing Northern Lights over Starfield)
# ==============================================================================
def render_emerald_aurora() -> Image.Image:
    x = ((np.arange(W, dtype=F32) + 0.5) / H)[None, :]
    y = ((np.arange(H, dtype=F32) + 0.5) / H)[:, None]
    A = W / H

    bg = grad(y[:, 0], [(0.0, hexc("020608")), (0.45, hexc("041316")), (1.0, hexc("02080a"))])
    img = np.ascontiguousarray(np.broadcast_to(bg[:, None, :], (H, W, 3))).astype(F32)

    # Fast vectorized stars
    rng = np.random.RandomState(1337)
    px = rng.randint(0, W, 450)
    py = rng.randint(0, int(H * 0.72), 450)
    pb = rng.uniform(0.4, 1.0, 450).astype(F32)
    for sx, sy, sb in zip(px, py, pb):
        img[sy, sx] = np.clip(img[sy, sx] + sb * hexc("f0fdf4"), 0.0, 1.0)
        if 0 < sy < H - 1 and 0 < sx < W - 1:
            img[sy - 1:sy + 2, sx - 1:sx + 2] += (sb * 0.25) * hexc("a7f3d0")

    # Aurora ribbons
    curtains = [
        (0.38, 0.08, [hexc("022c22"), hexc("059669"), hexc("10b981"), hexc("34d399")]),
        (0.48, 0.12, [hexc("064e3b"), hexc("10b981"), hexc("2dd4bf"), hexc("67e8f9")]),
        (0.58, 0.09, [hexc("042f2e"), hexc("0d9488"), hexc("14b8a6"), hexc("a7f3d0")]),
        (0.32, 0.06, [hexc("1e1b4b"), hexc("7c3aed"), hexc("06b6d4"), hexc("6ee7b7")]),
    ]

    for cy, h_amp, colors in curtains:
        c_curve = cy + h_amp * np.sin(2.2 * x + 0.8) + 0.03 * np.sin(5.5 * x + 1.2)
        dy = y - c_curve
        curtain_h = 0.28 + 0.05 * np.cos(3.0 * x)
        inside = (dy >= -0.02) & (dy <= curtain_h)
        v_flow = (dy + 0.02) / curtain_h

        rays = (np.sin(x * 65.0 + dy * 12.0) * 0.35 + 0.65) * (np.sin(x * 22.0) * 0.3 + 0.7)
        fade = smoothstep(0.0, 0.15, v_flow) * smoothstep(1.0, 0.5, v_flow) * inside.astype(F32)

        t_col = np.clip(v_flow, 0.0, 1.0)
        col = grad(t_col, [(i / (len(colors) - 1), c) for i, c in enumerate(colors)])

        img += (col * (fade * rays)[..., None]) * 1.15
        edge = np.exp(-((dy - 0.01) / 0.008) ** 2) * (np.sin(x * 3.0) * 0.2 + 0.8)
        img += (edge[..., None] * 0.6) * (0.6 * colors[-1] + 0.4 * hexc("ffffff"))

    # Mountain silhouette
    m_curve = 0.84 + 0.06 * np.sin(2.4 * x + 1.0) + 0.02 * np.cos(6.2 * x)
    mountains = smoothstep(m_curve - 0.003, m_curve + 0.003, y)
    img = img * (1.0 - 0.92 * mountains)[..., None] + mountains[..., None] * hexc("010406")

    img = add_dither(img)
    return Image.fromarray((img * 255.0).astype(np.uint8), "RGB")


# ==============================================================================
# 5. Liquid Titanium Wallpaper (Ultra-Modern Chrome / Platinum Luxury Waves)
# ==============================================================================
def render_liquid_titanium() -> Image.Image:
    x = ((np.arange(W, dtype=F32) + 0.5) / H)[None, :]
    y = ((np.arange(H, dtype=F32) + 0.5) / H)[:, None]
    A = W / H

    bg = grad(y[:, 0], [(0.0, hexc("0a0b0e")), (0.5, hexc("12141a")), (1.0, hexc("181a22"))])
    img = np.ascontiguousarray(np.broadcast_to(bg[:, None, :], (H, W, 3))).astype(F32)

    waves = [
        (0.42, 0.18, 1.8, 0.5, [hexc("1e293b"), hexc("64748b"), hexc("cbd5e1"), hexc("ffffff")]),
        (0.55, 0.14, 2.4, 1.8, [hexc("0f172a"), hexc("334155"), hexc("94a3b8"), hexc("e2e8f0")]),
        (0.68, 0.16, 2.1, 3.2, [hexc("1e1b4b"), hexc("475569"), hexc("cbd5e1"), hexc("f8fafc")]),
        (0.30, 0.12, 1.5, 4.0, [hexc("0f2942"), hexc("38bdf8"), hexc("93c5fd"), hexc("ffffff")]),
    ]

    for cy, amp, freq, phase, colors in waves:
        wave_y = cy + amp * np.sin(freq * x + phase) + 0.03 * np.cos(3.5 * freq * x)
        d = y - wave_y
        thick = 0.15 + 0.04 * np.sin(2.0 * x)
        inside = np.abs(d) <= thick
        u = d / thick

        N_y = u
        N_x = -amp * freq * np.cos(freq * x + phase)
        N_z = np.sqrt(np.maximum(0.02, 1.0 - u * u))
        norm = np.sqrt(N_x * N_x + N_y * N_y + N_z * N_z)
        N_x = N_x / norm
        N_y = N_y / norm
        N_z = N_z / norm

        # Studio environment reflections
        ref_spec = np.maximum(0.0, N_z) ** 18.0
        ref_fres = (1.0 - N_z) ** 2.8

        t_col = np.clip((u + 1.0) * 0.5, 0.0, 1.0)
        col = grad(t_col, [(i / (len(colors) - 1), c) for i, c in enumerate(colors)])

        lit = col * (0.4 + 0.6 * N_z[..., None]) + ref_spec[..., None] * 0.65 * hexc("ffffff") + ref_fres[..., None] * 0.45 * hexc("38bdf8")
        mask = inside.astype(F32) * smoothstep(1.0, 0.7, np.abs(u))
        img += lit * mask[..., None] * 0.85

        crest = np.exp(-(d / 0.005) ** 2) * 0.95
        img += crest[..., None] * (0.8 * hexc("ffffff") + 0.2 * hexc("67e8f9"))

    img = add_dither(img)
    return Image.fromarray((img * 255.0).astype(np.uint8), "RGB")


# ==============================================================================
# 6. Neon Cyberpulse Wallpaper (Synthwave Perspective Grid & Laser Horizon)
# ==============================================================================
def render_neon_cyberpulse() -> Image.Image:
    x = ((np.arange(W, dtype=F32) + 0.5) / H)[None, :]
    y = ((np.arange(H, dtype=F32) + 0.5) / H)[:, None]
    A = W / H

    bg = grad(y[:, 0], [(0.0, hexc("050014")), (0.55, hexc("12002b")), (0.65, hexc("240046")), (1.0, hexc("050014"))])
    img = np.ascontiguousarray(np.broadcast_to(bg[:, None, :], (H, W, 3))).astype(F32)

    horizon_y = 0.58

    # Sun at horizon
    d_sun = np.sqrt(((x - A / 2.0) / 0.35) ** 2 + ((y - horizon_y) / 0.35) ** 2)
    sun_mask = d_sun <= 1.0
    sun_stripes = np.sin((y - horizon_y) * 80.0) >= -0.2
    sun_col = grad((y[:, 0] - (horizon_y - 0.35)) / 0.35, [(0.0, hexc("fbbf24")), (0.5, hexc("f43f5e")), (1.0, hexc("9333ea"))])
    sun_img = np.broadcast_to(sun_col[:, None, :], (H, W, 3))
    img += (sun_mask & sun_stripes)[..., None] * sun_img * 0.95
    img += (np.exp(-d_sun * 1.5) * 0.65)[..., None] * hexc("f43f5e")

    # Perspective Grid below horizon
    grid_mask = y > horizon_y
    z_proj = 1.0 / np.maximum(0.001, y - horizon_y)
    x_proj = (x - A / 2.0) * z_proj

    h_lines = np.abs(np.sin(z_proj * 1.2)) ** 24.0
    v_lines = np.abs(np.sin(x_proj * 2.5)) ** 24.0
    grid_lines = np.maximum(h_lines, v_lines) * grid_mask.astype(F32)
    grid_fade = smoothstep(0.0, 0.15, y - horizon_y) * smoothstep(1.0, 0.7, y)

    img += (grid_lines * grid_fade * 0.85)[..., None] * hexc("06b6d4")
    img += (grid_lines * grid_fade * 0.45)[..., None] * hexc("f43f5e")

    # Glowing horizon laser line
    h_laser = np.exp(-((y - horizon_y) / 0.004) ** 2) * 1.4
    img += h_laser[..., None] * (0.6 * hexc("00f2fe") + 0.4 * hexc("ffffff"))

    img = add_dither(img)
    return Image.fromarray((img * 255.0).astype(np.uint8), "RGB")


# ==============================================================================
# Helper to write standard KDE package
# ==============================================================================
def write_kde_package(target_dir: Path, package_id: str, display_name: str, im: Image.Image):
    pkg = target_dir / package_id
    img_dir = pkg / "contents" / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "KPlugin": {
            "Id": package_id,
            "Name": display_name,
            "Authors": [{"Name": "DevOS"}],
            "License": "CC-BY-SA-4.0"
        }
    }
    (pkg / "metadata.json").write_text(json.dumps(meta, indent=4) + "\n", encoding="utf-8")

    # 2560x1440 image (PNG & JPG for universal KDE support)
    im.save(img_dir / "2560x1440.png", "PNG", optimize=True)
    im.save(img_dir / "2560x1440.jpg", "JPEG", quality=90, progressive=True, optimize=True)

    # 400x225 screenshot thumbnail
    thumb = im.resize((THUMB_W, THUMB_H), Image.LANCZOS)
    thumb.save(pkg / "contents" / "screenshot.png", "PNG", optimize=True)
    thumb.save(pkg / "contents" / "screenshot.jpg", "JPEG", quality=88, progressive=True, optimize=True)


def main():
    print("=" * 70)
    print(" DevOS Ultra-Premium Wallpaper & Slideshow Suite Generator")
    print("=" * 70)

    BUILD_WP.mkdir(parents=True, exist_ok=True)
    USER_WP.mkdir(parents=True, exist_ok=True)

    # 1. Render all 6 flagship / vibrant luxury wallpapers
    wallpapers = [
        ("DevOS-Default", "DevOS Flagship", render_flagship_default),
        ("DevOS-CelestialBloom", "Celestial Bloom", render_celestial_bloom),
        ("DevOS-SolarDawn", "Solar Dawn", render_solar_dawn),
        ("DevOS-EmeraldAurora", "Emerald Aurora", render_emerald_aurora),
        ("DevOS-LiquidTitanium", "Liquid Titanium", render_liquid_titanium),
        ("DevOS-NeonCyberpulse", "Neon Cyberpulse", render_neon_cyberpulse),
    ]

    rendered_images = {}
    for pkg_id, name, render_fn in wallpapers:
        t0 = time.time()
        print(f"--> Rendering [{pkg_id}] ({name})...", end="", flush=True)
        im = render_fn()
        rendered_images[pkg_id] = (name, im)
        print(f" Done ({time.time() - t0:.1f}s)")

        # Save to build/includes.chroot/
        write_kde_package(BUILD_WP, pkg_id, name, im)
        # Save to ~/.local/share/wallpapers/ (live session)
        write_kde_package(USER_WP, pkg_id, name, im)

        # For DevOS-Default, also write package named 'DevOS' (for backward compat)
        if pkg_id == "DevOS-Default":
            write_kde_package(BUILD_WP, "DevOS", "DevOS Flagship", im)
            write_kde_package(USER_WP, "DevOS", "DevOS Flagship", im)

            # Write direct single-file DevOS-Default.png
            devos_dir_build = BUILD_WP / "DevOS"
            devos_dir_build.mkdir(parents=True, exist_ok=True)
            im.save(devos_dir_build / "DevOS-Default.png", "PNG", optimize=True)

            devos_dir_user = USER_WP / "DevOS"
            devos_dir_user.mkdir(parents=True, exist_ok=True)
            im.save(devos_dir_user / "DevOS-Default.png", "PNG", optimize=True)

    # 2. Build the Slideshow Suite directory (DevOS-Slideshow) with 32+ wallpapers
    slideshow_build = BUILD_WP / "DevOS-Slideshow"
    slideshow_build.mkdir(parents=True, exist_ok=True)
    slideshow_user = USER_WP / "DevOS-Slideshow"
    slideshow_user.mkdir(parents=True, exist_ok=True)

    print("\n--> Building Slideshow Suite (32+ ultra-premium images)...")

    # Add the 6 newly created flagship wallpapers
    new_slides = [
        ("01_DevOS_Flagship.png", rendered_images["DevOS-Default"][1]),
        ("02_Celestial_Bloom.jpg", rendered_images["DevOS-CelestialBloom"][1]),
        ("03_Solar_Dawn.jpg", rendered_images["DevOS-SolarDawn"][1]),
        ("04_Emerald_Aurora.jpg", rendered_images["DevOS-EmeraldAurora"][1]),
        ("05_Liquid_Titanium.jpg", rendered_images["DevOS-LiquidTitanium"][1]),
        ("06_Neon_Cyberpulse.jpg", rendered_images["DevOS-NeonCyberpulse"][1]),
    ]

    for fname, im in new_slides:
        if fname.endswith(".png"):
            im.save(slideshow_build / fname, "PNG", optimize=True)
            im.save(slideshow_user / fname, "PNG", optimize=True)
        else:
            im.save(slideshow_build / fname, "JPEG", quality=90, progressive=True, optimize=True)
            im.save(slideshow_user / fname, "JPEG", quality=90, progressive=True, optimize=True)

    # Collect existing 26 top designs from the procedural suite
    existing_curated = [
        ("07_Silk_Current.jpg", "DevOS-SilkCurrent"),
        ("08_Glacier_Silk.jpg", "DevOS-GlacierSilk"),
        ("09_Velvet_Silk.jpg", "DevOS-VelvetSilk"),
        ("10_Aurora_Veil.jpg", "DevOS-AuroraVeil"),
        ("11_Aurora_Veil_Rose.jpg", "DevOS-AuroraVeilRose"),
        ("12_Glass_Horizon.jpg", "DevOS-GlassHorizon"),
        ("13_Glass_Horizon_Ember.jpg", "DevOS-GlassHorizonEmber"),
        ("14_Chroma_Mesh.jpg", "DevOS-ChromaMesh"),
        ("15_Neon_Horizon.jpg", "DevOS-NeonHorizon"),
        ("16_Nebula_Drift.jpg", "DevOS-NebulaDrift"),
        ("17_Nebula_Drift_Rose.jpg", "DevOS-NebulaDriftRose"),
        ("18_Liquid_Obsidian.jpg", "DevOS-LiquidObsidian"),
        ("19_Lumen_Bokeh.jpg", "DevOS-LumenBokeh"),
        ("20_Prism_Light.jpg", "DevOS-PrismLight"),
        ("21_Contour_Glow.jpg", "DevOS-ContourGlow"),
        ("22_Contour_Glow_Ember.jpg", "DevOS-ContourGlowEmber"),
        ("23_Abyss_Caustics.jpg", "DevOS-AbyssCaustics"),
        ("24_Flux_Streams.jpg", "DevOS-FluxStreams"),
        ("25_Flux_Streams_Tide.jpg", "DevOS-FluxStreamsTide"),
        ("26_Crystal_Facet.jpg", "DevOS-CrystalFacet"),
        ("27_Crystal_Facet_Rose.jpg", "DevOS-CrystalFacetRose"),
        ("28_Planet_Rise.jpg", "DevOS-PlanetRise"),
        ("29_Halftone_Tide.jpg", "DevOS-HalftoneTide"),
        ("30_Signal_Ridge.jpg", "DevOS-SignalRidge"),
        ("31_Signal_Ridge_Ember.jpg", "DevOS-SignalRidgeEmber"),
        ("32_Orbit_Halo.jpg", "DevOS-OrbitHalo"),
    ]

    for fname, pkg_name in existing_curated:
        src = BUILD_WP / pkg_name / "contents" / "images" / "2560x1440.jpg"
        if not src.exists():
            src = Path(f"/usr/share/wallpapers/{pkg_name}/contents/images/2560x1440.jpg")
        if src.exists():
            shutil.copyfile(src, slideshow_build / fname)
            shutil.copyfile(src, slideshow_user / fname)
            print(f"   [+] Slideshow: {fname} from {pkg_name}")

    total_slides = len(list(slideshow_user.glob("*")))
    print(f"==> Total wallpapers in Slideshow collection: {total_slides}")

    # Create KDE Package metadata for DevOS-Slideshow so it also shows up nicely
    write_kde_package(BUILD_WP, "DevOS-Slideshow", "DevOS Slideshow Collection", rendered_images["DevOS-Default"][1])
    write_kde_package(USER_WP, "DevOS-Slideshow", "DevOS Slideshow Collection", rendered_images["DevOS-Default"][1])

    print("\n==> Wallpapers successfully generated and deployed to both live user and build paths!")


if __name__ == "__main__":
    main()
