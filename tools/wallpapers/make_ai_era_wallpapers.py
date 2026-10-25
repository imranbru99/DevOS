#!/usr/bin/env python3
"""DevOS 100 AI-Era Ultra-Premium Wallpaper Generator & Deployer.

Renders 100 distinct, high-definition 2560x1440 wallpapers celebrating the AI Era,
organized across 10 themed suites (AI_001 to AI_100).

Deploys to:
1. build/includes.chroot/usr/share/wallpapers/DevOS-Slideshow/
2. ~/.local/share/wallpapers/DevOS-Slideshow/
"""

import math
import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
BUILD_SLIDESHOW = ROOT / "build" / "includes.chroot" / "usr" / "share" / "wallpapers" / "DevOS-Slideshow"
USER_SLIDESHOW = Path(os.path.expanduser("~/.local/share/wallpapers/DevOS-Slideshow"))

W, H = 2560, 1440
ASPECT = W / H  # ~1.777778
F32 = np.float32

# Pre-computed coordinate grids
X = ((np.arange(W, dtype=F32) + 0.5) / H)[None, :]
Y = ((np.arange(H, dtype=F32) + 0.5) / H)[:, None]


def hexc(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)], dtype=F32)


def hex_to_rgb(h: str, alpha: int = 255):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)


def smoothstep(e0: float, e1: float, v: np.ndarray) -> np.ndarray:
    t = np.clip((v - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def bg_field(top_hex: str, mid_hex: str, bot_hex: str, mid_y: float = 0.5) -> np.ndarray:
    top = hexc(top_hex)
    mid = hexc(mid_hex)
    bot = hexc(bot_hex)
    y_norm = np.clip(Y[:, 0], 0.0, 1.0)
    out = np.empty((H, 3), F32)
    for ch in range(3):
        out[:, ch] = np.interp(y_norm, [0.0, mid_y, 1.0], [top[ch], mid[ch], bot[ch]])
    return np.ascontiguousarray(np.broadcast_to(out[:, None, :], (H, W, 3))).astype(F32)


def add_glow(img: np.ndarray, cx: float, cy: float, rx: float, ry: float, color: np.ndarray, intensity: float, power: float = 2.0):
    d = (((X - cx) / rx) ** 2 + ((Y - cy) / ry) ** 2) ** (power / 2.0)
    g = (np.exp(-d) * intensity)[..., None]
    img += g * color[None, None, :]


def add_starfield(img: np.ndarray, seed: int = 42, count: int = 200, max_bright: float = 0.75):
    rng = np.random.RandomState(seed)
    xs = rng.randint(20, W - 20, size=count)
    ys = rng.randint(20, H - 20, size=count)
    for i in range(count):
        y, x = ys[i], xs[i]
        b = rng.uniform(0.5, max_bright)
        tint = rng.uniform(0.85, 1.0, 3).astype(F32)
        # 3x3 core
        img[max(0, y-1):min(H, y+2), max(0, x-1):min(W, x+2)] += b * tint
        # 5x5 soft halo
        img[max(0, y-2):min(H, y+3), max(0, x-2):min(W, x+3)] += (b * 0.35) * tint


def tone_map_and_finish(img: np.ndarray, seed: int = 42) -> Image.Image:
    # Desktop icon safe-zone contrast dampening at top-left
    tl_dist = np.sqrt((X - 0.22) ** 2 + (Y - 0.22) ** 2)
    tl_damp = 1.0 - 0.12 * np.exp(-(tl_dist / 0.45) ** 2)
    img = img * tl_damp[..., None]

    # Contrast S-Curve
    img = np.clip(img, 0.0, 1.0)
    img = img * img * (3.0 - 2.0 * img)

    # Film grain dithering to prevent banding
    rng = np.random.RandomState(seed)
    dith = (rng.uniform(-0.55, 0.55, (H, W, 1)) + rng.uniform(-0.55, 0.55, (H, W, 1))).astype(F32) / 255.0
    arr = np.clip((img + dith) * 255.0, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


def composite_pil(base_arr: np.ndarray, pil_overlay: Image.Image, blend: str = "screen") -> np.ndarray:
    ov_arr = np.array(pil_overlay, dtype=F32) / 255.0
    rgb = ov_arr[..., :3]
    alpha = ov_arr[..., 3:4] if ov_arr.shape[-1] == 4 else np.ones_like(rgb[..., :1])

    if blend == "screen":
        # 1 - (1 - base) * (1 - rgb * alpha)
        return 1.0 - (1.0 - base_arr) * (1.0 - rgb * alpha)
    elif blend == "add":
        return np.clip(base_arr + rgb * alpha, 0.0, 1.0)
    else:  # normal alpha
        return base_arr * (1.0 - alpha) + rgb * alpha


# ==============================================================================
# SUITE 1: Neural Synapse & Deep Intelligence (AI_001 to AI_010)
# ==============================================================================

def render_ai_001():
    """Neural Synapse Matrix: Branching neural axons with glowing synaptic sparks."""
    img = bg_field("02030a", "05091a", "081026", 0.45)
    add_glow(img, 1.25, 0.45, 0.65, 0.55, hexc("00f5ff"), 0.55)
    add_glow(img, 1.45, 0.60, 0.50, 0.45, hexc("7c3aed"), 0.45)
    add_glow(img, 0.95, 0.35, 0.45, 0.40, hexc("38bdf8"), 0.35)

    # PIL vector lines for axon tree
    im_axons = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_axons)
    rng = np.random.RandomState(101)

    # Main trunk nodes branching from right to center-left
    nodes = [(W * 0.85, H * 0.50)]
    for _ in range(8):
        last_x, last_y = nodes[-1]
        nx = last_x - rng.uniform(80, 160)
        ny = last_y + rng.uniform(-70, 70)
        nodes.append((nx, ny))

    for i in range(len(nodes) - 1):
        draw.line([nodes[i], nodes[i+1]], fill=hex_to_rgb("00f5ff", 220), width=6)
        # Secondary branches
        for b in range(4):
            bx = nodes[i][0] + rng.uniform(-180, 180)
            by = nodes[i][1] + rng.uniform(-160, 160)
            draw.line([nodes[i], (bx, by)], fill=hex_to_rgb("818cf8", 160), width=3)
            # tertiary twigs
            for t in range(2):
                tx = bx + rng.uniform(-100, 100)
                ty = by + rng.uniform(-100, 100)
                draw.line([(bx, by), (tx, ty)], fill=hex_to_rgb("c084fc", 110), width=1)
                draw.ellipse([tx-3, ty-3, tx+3, ty+3], fill=hex_to_rgb("ffffff", 230))

    # Bloom filter
    glow_axons = im_axons.filter(ImageFilter.GaussianBlur(radius=7))
    img = composite_pil(img, glow_axons, "screen")
    img = composite_pil(img, im_axons, "add")
    add_starfield(img, seed=1, count=120, max_bright=0.6)
    return tone_map_and_finish(img, seed=1)


def render_ai_002():
    """Deep Thought Manifold: Multi-layered undulating ribbon waves in latent space."""
    img = bg_field("03040e", "060a1e", "09122c", 0.5)
    add_glow(img, 1.10, 0.45, 0.70, 0.60, hexc("2563eb"), 0.50)
    add_glow(img, 1.50, 0.55, 0.55, 0.50, hexc("db2777"), 0.40)

    # 5 Harmonic wave ribbons
    for i in range(5):
        freq = 3.2 + i * 0.7
        phase = i * 0.85
        y_off = 0.35 + i * 0.08
        wave = np.sin(X * freq + phase) * 0.08 + np.cos(X * 1.8 + i) * 0.04
        dist = np.abs(Y - y_off - wave)
        ribbon = np.exp(-(dist / 0.035) ** 2)
        col = hexc(["00f5ff", "38bdf8", "818cf8", "c084fc", "ec4899"][i])
        img += ribbon[..., None] * col[None, None, :] * 0.55

    add_starfield(img, seed=2, count=90, max_bright=0.5)
    return tone_map_and_finish(img, seed=2)


def render_ai_003():
    """Cortical Resonance Core: Concentric pulsing neural rings centered on a radiant cognitive singularity."""
    img = bg_field("020208", "060714", "0a0d20", 0.5)
    cx, cy = 1.15, 0.48
    add_glow(img, cx, cy, 0.40, 0.40, hexc("38bdf8"), 0.80)
    add_glow(img, cx, cy, 0.85, 0.85, hexc("6366f1"), 0.50)

    # Concentric wave ripples with harmonic phase modulation
    r = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
    theta = np.arctan2(Y - cy, X - cx)
    ripple = np.sin(r * 38.0 - theta * 3.0) * np.exp(-r * 2.2)
    field = np.clip(ripple, 0.0, 1.0)
    img += field[..., None] * hexc("00f5ff")[None, None, :] * 0.65

    # Core spark
    core = np.exp(-((r / 0.06) ** 2))
    img += core[..., None] * hexc("ffffff")[None, None, :] * 1.2
    return tone_map_and_finish(img, seed=3)


def render_ai_004():
    """Synaptic Axon Highway: Diagonal optical axon fiber streams carrying luminous data packets."""
    img = bg_field("01040d", "030a1c", "07132e", 0.4)
    add_glow(img, 1.30, 0.40, 0.75, 0.65, hexc("06b6d4"), 0.60)
    add_glow(img, 0.80, 0.65, 0.60, 0.50, hexc("3b82f6"), 0.40)

    im_fibers = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_fibers)
    rng = np.random.RandomState(104)

    # 40 Sinuous curved fiber lines sweeping diagonally
    for i in range(40):
        y_start = rng.uniform(-100, H + 200)
        pts = []
        for step in range(10):
            px = step * (W / 9.0)
            py = y_start + (px / W) * (H * 0.4) + math.sin(step * 0.8 + i) * 60
            pts.append((px, py))
        color_hex = rng.choice(["00f5ff", "0ea5e9", "6366f1", "a855f7", "ffffff"])
        draw.line(pts, fill=hex_to_rgb(color_hex, rng.randint(90, 200)), width=rng.randint(2, 4))
        # Add packet node
        p_idx = rng.randint(2, 8)
        draw.ellipse([pts[p_idx][0]-5, pts[p_idx][1]-5, pts[p_idx][0]+5, pts[p_idx][1]+5], fill=hex_to_rgb("ffffff", 255))

    glow = im_fibers.filter(ImageFilter.GaussianBlur(radius=6))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_fibers, "add")
    return tone_map_and_finish(img, seed=4)


def render_ai_005():
    """Neuromorphic Silicon Lattice: Hexagonal micro-synapse grid with glowing laser traces."""
    img = bg_field("020308", "050714", "080d22", 0.5)
    add_glow(img, 1.20, 0.50, 0.70, 0.60, hexc("10b981"), 0.45)
    add_glow(img, 1.45, 0.35, 0.55, 0.50, hexc("06b6d4"), 0.45)

    im_hex = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_hex)
    rng = np.random.RandomState(105)

    size = 75
    h_dist = size * math.sqrt(3)
    v_dist = size * 1.5

    for row in range(-1, int(H / v_dist) + 2):
        for col in range(-1, int(W / h_dist) + 2):
            cx = col * h_dist + (row % 2) * (h_dist / 2)
            cy = row * v_dist
            if rng.uniform() > 0.35:
                pts = [
                    (cx + size * 0.5 * math.cos(math.radians(a)), cy + size * 0.5 * math.sin(math.radians(a)))
                    for a in range(30, 390, 60)
                ]
                draw.polygon(pts, outline=hex_to_rgb("10b981", 120), width=1)
                if rng.uniform() > 0.65:
                    draw.ellipse([cx-4, cy-4, cx+4, cy+4], fill=hex_to_rgb("34d399", 220))

    glow = im_hex.filter(ImageFilter.GaussianBlur(radius=5))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_hex, "add")
    return tone_map_and_finish(img, seed=5)


def render_ai_006():
    """Cognitive Singularity Dawn: Luminous awakening horizon piercing midnight space."""
    img = bg_field("030612", "071128", "0e204a", 0.4)
    add_glow(img, 1.10, 0.58, 0.90, 0.45, hexc("0284c7"), 0.75)
    add_glow(img, 1.10, 0.58, 0.35, 0.20, hexc("38bdf8"), 0.90)
    add_glow(img, 1.10, 0.58, 0.15, 0.08, hexc("ffffff"), 1.20)

    # Volumetric horizon rays
    dx = X - 1.10
    dy = Y - 0.58
    angle = np.arctan2(dy, dx)
    rays = np.sin(angle * 24.0) * np.sin(angle * 12.0)
    ray_glow = np.clip(rays, 0.0, 1.0) * np.exp(-np.sqrt(dx**2 + dy**2) * 1.4)
    img += ray_glow[..., None] * hexc("38bdf8")[None, None, :] * 0.45
    add_starfield(img, seed=6, count=160, max_bright=0.7)
    return tone_map_and_finish(img, seed=6)


def render_ai_007():
    """Synaptic Dendrite Cluster: High-density micro-filaments glowing in amber and rose."""
    img = bg_field("080408", "120815", "1c0e22", 0.5)
    add_glow(img, 1.25, 0.50, 0.65, 0.55, hexc("f59e0b"), 0.50)
    add_glow(img, 1.40, 0.40, 0.50, 0.45, hexc("f43f5e"), 0.55)

    im_dendrites = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_dendrites)
    rng = np.random.RandomState(107)

    for cluster in range(4):
        cx = W * (0.65 + cluster * 0.08)
        cy = H * (0.45 + (cluster % 2) * 0.1)
        for i in range(25):
            angle = rng.uniform(0, 2 * math.pi)
            length = rng.uniform(80, 260)
            ex = cx + math.cos(angle) * length
            ey = cy + math.sin(angle) * length
            draw.line([(cx, cy), (ex, ey)], fill=hex_to_rgb("fbbf24", 160), width=2)
            draw.ellipse([ex-3, ey-3, ex+3, ey+3], fill=hex_to_rgb("f43f5e", 230))

    glow = im_dendrites.filter(ImageFilter.GaussianBlur(radius=6))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_dendrites, "add")
    return tone_map_and_finish(img, seed=7)


def render_ai_008():
    """Latent Thought Stream: Fluid harmonic wave interference in turquoise and neon purple."""
    img = bg_field("02040b", "050c1e", "081634", 0.5)
    add_glow(img, 1.15, 0.48, 0.70, 0.60, hexc("06b6d4"), 0.55)
    add_glow(img, 1.40, 0.60, 0.55, 0.50, hexc("a855f7"), 0.50)

    # Complex wave interference
    wave1 = np.sin(X * 4.5 + Y * 2.2)
    wave2 = np.cos(X * 3.2 - Y * 4.0)
    stream = np.exp(-((wave1 + wave2) ** 2) / 0.35)
    img += stream[..., None] * hexc("22d3ee")[None, None, :] * 0.45
    return tone_map_and_finish(img, seed=8)


def render_ai_009():
    """Cerebral Pulse Nexus: Synchronous neural firing shockwaves."""
    img = bg_field("020309", "060818", "0a0e28", 0.45)
    cx, cy = 1.25, 0.45
    add_glow(img, cx, cy, 0.50, 0.45, hexc("38bdf8"), 0.70)
    add_glow(img, cx, cy, 0.90, 0.80, hexc("4f46e5"), 0.50)

    r = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
    shock = np.sin(r * 22.0) * np.exp(-r * 1.8)
    shock = np.clip(shock, 0.0, 1.0)
    img += shock[..., None] * hexc("818cf8")[None, None, :] * 0.60
    add_starfield(img, seed=9, count=140, max_bright=0.6)
    return tone_map_and_finish(img, seed=9)


def render_ai_010():
    """Subconscious Vector Void: Velvet shadows with floating thought embers drifting upward."""
    img = bg_field("030206", "080512", "0e091e", 0.5)
    add_glow(img, 1.20, 0.65, 0.70, 0.55, hexc("9333ea"), 0.55)
    add_glow(img, 0.90, 0.35, 0.55, 0.45, hexc("c026d3"), 0.40)
    add_starfield(img, seed=10, count=220, max_bright=0.85)
    return tone_map_and_finish(img, seed=10)


# ==============================================================================
# SUITE 2: Quantum Silicon & Photonic Matrix (AI_011 to AI_020)
# ==============================================================================

def render_ai_011():
    """Quantum Qubit Lattice: Superconducting qubit loop array in cryogenic azure."""
    img = bg_field("010309", "030a1b", "06122d", 0.5)
    add_glow(img, 1.20, 0.48, 0.70, 0.60, hexc("00f5ff"), 0.55)
    add_glow(img, 1.50, 0.55, 0.50, 0.45, hexc("10b981"), 0.45)

    im_qubits = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_qubits)
    step = 130
    for y_idx in range(1, int(H / step)):
        for x_idx in range(1, int(W / step)):
            px = x_idx * step
            py = y_idx * step
            # Qubit cross
            draw.line([(px-30, py), (px+30, py)], fill=hex_to_rgb("00f5ff", 180), width=3)
            draw.line([(px, py-30), (px, py+30)], fill=hex_to_rgb("00f5ff", 180), width=3)
            # Outer ring
            draw.ellipse([px-20, py-20, px+20, py+20], outline=hex_to_rgb("34d399", 200), width=2)
            # Central junction
            draw.rectangle([px-4, py-4, px+4, py+4], fill=hex_to_rgb("ffffff", 255))

    glow = im_qubits.filter(ImageFilter.GaussianBlur(radius=6))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_qubits, "add")
    return tone_map_and_finish(img, seed=11)


def render_ai_012():
    """Photonic Waveguide Core: Curving optical waveguides channeling ruby and cyan laser light."""
    img = bg_field("030206", "070614", "0c0c24", 0.5)
    add_glow(img, 1.20, 0.45, 0.75, 0.60, hexc("ef4444"), 0.45)
    add_glow(img, 1.40, 0.55, 0.60, 0.50, hexc("06b6d4"), 0.55)

    im_wg = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_wg)
    for i in range(18):
        y_c = H * (0.2 + i * 0.035)
        pts = [(0, y_c)]
        for s in range(1, 20):
            px = s * (W / 19.0)
            py = y_c + math.sin(s * 0.4 + i * 0.3) * 80
            pts.append((px, py))
        col = hex_to_rgb("06b6d4" if i % 2 == 0 else "f43f5e", 200)
        draw.line(pts, fill=col, width=3)

    glow = im_wg.filter(ImageFilter.GaussianBlur(radius=8))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_wg, "add")
    return tone_map_and_finish(img, seed=12)


def render_ai_013():
    """Cryogenic Dilution Cascade: Golden chandelier wiring and cobalt cold bath."""
    img = bg_field("01040c", "030d22", "06173a", 0.4)
    add_glow(img, 1.20, 0.35, 0.60, 0.50, hexc("f59e0b"), 0.60)
    add_glow(img, 1.20, 0.70, 0.75, 0.55, hexc("0284c7"), 0.55)

    # Golden plates
    im_cryo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_cryo)
    cx = W * 0.65
    for stage in range(6):
        py = H * (0.2 + stage * 0.12)
        plate_w = 400 - stage * 45
        draw.rectangle([cx - plate_w, py - 4, cx + plate_w, py + 4], fill=hex_to_rgb("fbbf24", 240))
        # Wiring coils between plates
        if stage < 5:
            next_py = H * (0.2 + (stage + 1) * 0.12)
            for w in range(-8, 9):
                wx = cx + w * 25
                draw.line([(wx, py), (wx, next_py)], fill=hex_to_rgb("d97706", 180), width=2)

    glow = im_cryo.filter(ImageFilter.GaussianBlur(radius=6))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_cryo, "add")
    return tone_map_and_finish(img, seed=13)


def render_ai_014():
    """Coherent Laser Interconnect: Micro-lasers refracting through splitters."""
    img = bg_field("020208", "060516", "0b0a24", 0.5)
    add_glow(img, 1.15, 0.50, 0.70, 0.55, hexc("10b981"), 0.50)
    add_glow(img, 1.45, 0.45, 0.55, 0.45, hexc("ec4899"), 0.50)

    # 2D laser ray tracing
    im_laser = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_laser)
    for i in range(12):
        y0 = H * (0.25 + i * 0.045)
        draw.line([(0, y0), (W * 0.6, y0)], fill=hex_to_rgb("10b981", 220), width=2)
        # Refracted rays
        draw.line([(W * 0.6, y0), (W, y0 + (i - 6) * 45)], fill=hex_to_rgb("ec4899", 200), width=2)
        draw.line([(W * 0.6, y0), (W, y0 - (i - 6) * 35)], fill=hex_to_rgb("06b6d4", 200), width=2)

    glow = im_laser.filter(ImageFilter.GaussianBlur(radius=5))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_laser, "add")
    return tone_map_and_finish(img, seed=14)


def render_ai_015():
    """Topological Braid Knot: Braided Majorana worldlines in quantum space."""
    img = bg_field("030209", "07061d", "0c0c32", 0.5)
    add_glow(img, 1.15, 0.50, 0.65, 0.55, hexc("a855f7"), 0.60)
    add_glow(img, 1.40, 0.50, 0.55, 0.45, hexc("38bdf8"), 0.50)

    # Mathematical Lissajous-knot parametric curve
    im_knot = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_knot)
    pts = []
    for t in np.linspace(0, 2 * np.pi, 600):
        kx = W * 0.65 + math.sin(3 * t) * 380
        ky = H * 0.50 + math.sin(4 * t) * 260
        pts.append((kx, ky))
    draw.line(pts, fill=hex_to_rgb("c084fc", 220), width=5)

    glow = im_knot.filter(ImageFilter.GaussianBlur(radius=9))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_knot, "add")
    return tone_map_and_finish(img, seed=15)


def render_ai_016():
    """Subatomic Silicon Lithography: 2nm lithography circuit pattern glowing in UV."""
    img = bg_field("010309", "030818", "060f29", 0.5)
    add_glow(img, 1.25, 0.45, 0.65, 0.55, hexc("00f5ff"), 0.65)

    im_litho = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_litho)
    rng = np.random.RandomState(116)

    for i in range(120):
        x1 = rng.uniform(W * 0.3, W * 0.95)
        y1 = rng.uniform(H * 0.1, H * 0.9)
        length = rng.uniform(40, 180)
        if rng.uniform() > 0.5:
            # Horizontal with 45-deg bend
            x2 = x1 + length
            draw.line([(x1, y1), (x2, y1), (x2 + 25, y1 + 25)], fill=hex_to_rgb("00f5ff", 160), width=2)
        else:
            # Vertical with 45-deg bend
            y2 = y1 + length
            draw.line([(x1, y1), (x1, y2), (x1 + 25, y2 + 25)], fill=hex_to_rgb("38bdf8", 160), width=2)

    glow = im_litho.filter(ImageFilter.GaussianBlur(radius=4))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_litho, "add")
    return tone_map_and_finish(img, seed=16)


def render_ai_017():
    """Quantum Entanglement Vortex: Dual helical entwined beams of opposing spin."""
    img = bg_field("020208", "060616", "0a0a22", 0.5)
    add_glow(img, 1.20, 0.50, 0.70, 0.55, hexc("00f5ff"), 0.50)
    add_glow(img, 1.20, 0.50, 0.70, 0.55, hexc("ec4899"), 0.50)

    # Dual helix
    t = np.linspace(0, 10 * np.pi, 800)
    hx = W * 0.1 + (t / (10 * np.pi)) * (W * 0.8)
    hy1 = H * 0.5 + np.sin(t) * 140
    hy2 = H * 0.5 - np.sin(t) * 140

    im_helix = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_helix)
    pts1 = list(zip(hx, hy1))
    pts2 = list(zip(hx, hy2))
    draw.line(pts1, fill=hex_to_rgb("00f5ff", 230), width=4)
    draw.line(pts2, fill=hex_to_rgb("ec4899", 230), width=4)

    # Entanglement rungs
    for i in range(0, len(pts1), 25):
        draw.line([pts1[i], pts2[i]], fill=hex_to_rgb("ffffff", 140), width=1)

    glow = im_helix.filter(ImageFilter.GaussianBlur(radius=8))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_helix, "add")
    return tone_map_and_finish(img, seed=17)


def render_ai_018():
    """Superconducting Flux Resonator: Concentric square spiral microwave resonators."""
    img = bg_field("02040c", "040c20", "071536", 0.5)
    add_glow(img, 1.20, 0.48, 0.65, 0.55, hexc("38bdf8"), 0.60)

    im_spiral = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_spiral)
    cx, cy = W * 0.68, H * 0.48
    side = 30
    for loop in range(16):
        draw.rectangle([cx - side, cy - side, cx + side, cy + side], outline=hex_to_rgb("38bdf8", 180), width=2)
        side += 22

    glow = im_spiral.filter(ImageFilter.GaussianBlur(radius=6))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_spiral, "add")
    return tone_map_and_finish(img, seed=18)


def render_ai_019():
    """Photonic Crystal Cavity: Periodic micro-hole membrane trapping localized resonance."""
    img = bg_field("020208", "060714", "0a0d22", 0.5)
    cx, cy = 1.25, 0.48
    add_glow(img, cx, cy, 0.35, 0.30, hexc("ffffff"), 1.2)
    add_glow(img, cx, cy, 0.70, 0.60, hexc("f59e0b"), 0.6)

    # Micro holes
    im_cav = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_cav)
    for gx in range(int(W * 0.35), int(W * 0.95), 45):
        for gy in range(int(H * 0.15), int(H * 0.85), 45):
            d = math.sqrt((gx - W * 0.65)**2 + (gy - H * 0.48)**2)
            if d > 70:  # defect cavity in center
                draw.ellipse([gx-8, gy-8, gx+8, gy+8], outline=hex_to_rgb("38bdf8", 120), width=2)

    glow = im_cav.filter(ImageFilter.GaussianBlur(radius=5))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_cav, "add")
    return tone_map_and_finish(img, seed=19)


def render_ai_020():
    """Quantum State Tomography: Bloch sphere geometric projections in emerald and violet."""
    img = bg_field("030209", "07051d", "0c0a32", 0.5)
    cx, cy = 1.20, 0.50
    add_glow(img, cx, cy, 0.65, 0.60, hexc("10b981"), 0.50)
    add_glow(img, cx, cy, 0.50, 0.45, hexc("8b5cf6"), 0.50)

    im_bloch = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_bloch)
    scx, scy = W * 0.65, H * 0.50
    R = 260
    draw.ellipse([scx-R, scy-R, scx+R, scy+R], outline=hex_to_rgb("8b5cf6", 180), width=3)
    draw.ellipse([scx-R, scy-R*0.35, scx+R, scy+R*0.35], outline=hex_to_rgb("10b981", 160), width=2)
    draw.line([(scx, scy-R-30), (scx, scy+R+30)], fill=hex_to_rgb("ffffff", 200), width=2)
    # State vector
    draw.line([(scx, scy), (scx+R*0.65, scy-R*0.6)], fill=hex_to_rgb("34d399", 255), width=4)

    glow = im_bloch.filter(ImageFilter.GaussianBlur(radius=6))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_bloch, "add")
    return tone_map_and_finish(img, seed=20)


# ==============================================================================
# SUITE 3: Cyberpunk & Synthetic Megacity (AI_021 to AI_030)
# ==============================================================================

def render_ai_021():
    """Cyber Metropolis Horizon: Silhouetted megatall towers with neon skyways."""
    img = bg_field("04020a", "09061c", "120b2e", 0.4)
    add_glow(img, 1.20, 0.40, 0.85, 0.60, hexc("00f5ff"), 0.55)
    add_glow(img, 0.80, 0.55, 0.60, 0.45, hexc("f43f5e"), 0.45)

    im_city = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_city)
    rng = np.random.RandomState(121)

    # 35 Towers
    for i in range(35):
        tx = rng.uniform(W * 0.25, W * 0.98)
        tw = rng.uniform(40, 110)
        th = rng.uniform(H * 0.35, H * 0.75)
        ty = H - th
        draw.rectangle([tx, ty, tx + tw, H], fill=hex_to_rgb("060918", 255))
        draw.rectangle([tx, ty, tx + tw, H], outline=hex_to_rgb("00f5ff", 80), width=1)
        # Windows
        for wy in np.arange(ty + 15, H - 30, 25):
            for wx in np.arange(tx + 8, tx + tw - 8, 14):
                if rng.uniform() > 0.45:
                    col = rng.choice(["00f5ff", "ec4899", "fbbf24", "ffffff"])
                    draw.rectangle([wx, wy, wx+4, wy+6], fill=hex_to_rgb(col, 200))

    # Curved skyway
    pts = [(W * 0.2, H * 0.75), (W * 0.5, H * 0.68), (W * 0.8, H * 0.72), (W, H * 0.65)]
    draw.line(pts, fill=hex_to_rgb("00f5ff", 220), width=4)

    glow = im_city.filter(ImageFilter.GaussianBlur(radius=5))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_city, "normal")
    return tone_map_and_finish(img, seed=21)


def render_ai_022():
    """Neo Tokyo Perspective Grid: 3D perspective vector wireframe highway."""
    img = bg_field("05020c", "0c0620", "150a36", 0.4)
    add_glow(img, 1.15, 0.42, 0.65, 0.45, hexc("f43f5e"), 0.65)
    add_glow(img, 1.15, 0.42, 0.35, 0.25, hexc("fbbf24"), 0.50)

    im_grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_grid)
    horizon_y = H * 0.45
    vanish_x = W * 0.65

    # Perspective lines
    for x_step in range(-15, 16):
        bx = vanish_x + x_step * 180
        draw.line([(vanish_x, horizon_y), (bx, H)], fill=hex_to_rgb("00f5ff", 160), width=2)

    # Horizontal depth lines
    for d in np.linspace(0.05, 1.0, 18):
        y_pos = horizon_y + (d ** 2) * (H - horizon_y)
        draw.line([(0, y_pos), (W, y_pos)], fill=hex_to_rgb("f43f5e", int(80 + 120 * d)), width=2)

    glow = im_grid.filter(ImageFilter.GaussianBlur(radius=5))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_grid, "add")
    return tone_map_and_finish(img, seed=22)


def render_ai_023():
    """Obsidian Monolith Skyscraper: Monolithic dark glass tower reflecting laser mist."""
    img = bg_field("020207", "050512", "0a0a20", 0.5)
    add_glow(img, 1.30, 0.45, 0.60, 0.55, hexc("06b6d4"), 0.60)
    add_glow(img, 1.05, 0.30, 0.45, 0.40, hexc("8b5cf6"), 0.50)

    im_mono = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_mono)
    mx = W * 0.65
    mw = 260
    draw.polygon([(mx, H * 0.1), (mx + mw, H * 0.18), (mx + mw, H), (mx, H)], fill=hex_to_rgb("080c1c", 255))
    draw.line([(mx, H * 0.1), (mx, H)], fill=hex_to_rgb("00f5ff", 230), width=3)
    draw.line([(mx + mw, H * 0.18), (mx + mw, H)], fill=hex_to_rgb("8b5cf6", 200), width=2)

    glow = im_mono.filter(ImageFilter.GaussianBlur(radius=6))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_mono, "normal")
    return tone_map_and_finish(img, seed=23)


def render_ai_024():
    """Laser Skyway Express: High-speed autonomous traffic light ribbons."""
    img = bg_field("01030a", "040a20", "07143a", 0.4)
    add_glow(img, 1.25, 0.55, 0.70, 0.55, hexc("00f5ff"), 0.55)
    add_glow(img, 0.85, 0.45, 0.60, 0.45, hexc("ef4444"), 0.55)

    im_lanes = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_lanes)
    for i in range(15):
        y_b = H * (0.35 + i * 0.04)
        pts = [(0, y_b + 80), (W * 0.35, y_b + 20), (W * 0.75, y_b - 40), (W, y_b - 80)]
        col = hex_to_rgb("ef4444" if i % 2 == 0 else "00f5ff", 220)
        draw.line(pts, fill=col, width=4)

    glow = im_lanes.filter(ImageFilter.GaussianBlur(radius=8))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_lanes, "add")
    return tone_map_and_finish(img, seed=24)


def render_ai_025():
    """Cyber Harbor Aurora: Coastal water reflections with neon sky reflection."""
    img = bg_field("02040d", "050d24", "0a1842", 0.4)
    add_glow(img, 1.20, 0.35, 0.80, 0.45, hexc("10b981"), 0.60)
    add_glow(img, 1.50, 0.40, 0.60, 0.45, hexc("a855f7"), 0.50)

    # Water ripple reflection
    water_mask = smoothstep(0.55, 0.60, Y)
    ripple = np.sin(X * 35.0) * np.cos(Y * 80.0) * 0.15
    img += (water_mask * ripple)[..., None] * hexc("00f5ff")[None, None, :] * 0.35
    return tone_map_and_finish(img, seed=25)


def render_ai_026():
    """Synthetic Dawn Overpass: Cyber sunrise behind geometric sky-bridges."""
    img = bg_field("080208", "160614", "2a0e28", 0.4)
    add_glow(img, 1.15, 0.52, 0.55, 0.35, hexc("f59e0b"), 0.85)
    add_glow(img, 1.15, 0.52, 0.25, 0.15, hexc("ffffff"), 1.2)

    im_bridge = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_bridge)
    # Silhouette truss bridge
    by = H * 0.58
    draw.rectangle([0, by, W, by + 20], fill=hex_to_rgb("05050e", 255))
    for bx in range(0, W, 80):
        draw.line([(bx, by), (bx + 40, by - 60), (bx + 80, by)], fill=hex_to_rgb("05050e", 255), width=5)

    img = composite_pil(img, im_bridge, "normal")
    return tone_map_and_finish(img, seed=26)


def render_ai_027():
    """Digital Canopy Penthouse: High stratosphere viewpoint onto glowing ground sectors."""
    img = bg_field("010207", "040616", "080d28", 0.5)
    add_glow(img, 1.20, 0.65, 0.80, 0.50, hexc("00f5ff"), 0.55)
    add_glow(img, 0.80, 0.70, 0.65, 0.45, hexc("ec4899"), 0.45)
    add_starfield(img, seed=27, count=180, max_bright=0.8)
    return tone_map_and_finish(img, seed=27)


def render_ai_028():
    """Holo Billboard Diffusion: Bokeh of holographic advertisements through rain glass."""
    img = bg_field("02030a", "060818", "0b1028", 0.5)
    rng = np.random.RandomState(128)
    for b in range(18):
        bx = rng.uniform(0.4, ASPECT - 0.1)
        by = rng.uniform(0.2, 0.8)
        rad = rng.uniform(0.12, 0.28)
        col = hexc(rng.choice(["00f5ff", "ec4899", "8b5cf6", "fbbf24", "10b981"]))
        add_glow(img, bx, by, rad, rad, col, rng.uniform(0.25, 0.55))
    return tone_map_and_finish(img, seed=28)


def render_ai_029():
    """Midnight Synthwave Range: Neon-stroked low-poly mountain peaks."""
    img = bg_field("05020c", "0f0622", "1e0c3a", 0.4)
    add_glow(img, 1.20, 0.38, 0.45, 0.30, hexc("ec4899"), 0.70)

    im_poly = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_poly)
    peaks = [(W * 0.1, H * 0.75), (W * 0.35, H * 0.45), (W * 0.65, H * 0.35), (W * 0.85, H * 0.55), (W, H * 0.70)]
    for i in range(len(peaks) - 1):
        tri = [(peaks[i][0], H), peaks[i], peaks[i+1], (peaks[i+1][0], H)]
        draw.polygon(tri, fill=hex_to_rgb("080518", 255), outline=hex_to_rgb("00f5ff", 220))

    glow = im_poly.filter(ImageFilter.GaussianBlur(radius=6))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_poly, "normal")
    return tone_map_and_finish(img, seed=29)


def render_ai_030():
    """Orbital Skyport Gantry: Launch docking gantry towering into space."""
    img = bg_field("010206", "030514", "070b24", 0.4)
    add_glow(img, 1.25, 0.30, 0.55, 0.45, hexc("f59e0b"), 0.55)
    add_glow(img, 1.25, 0.30, 0.20, 0.15, hexc("ffffff"), 1.0)
    add_starfield(img, seed=30, count=240, max_bright=0.85)
    return tone_map_and_finish(img, seed=30)


# ==============================================================================
# SUITE 4: Latent Diffusion & Generative Vector Fields (AI_031 to AI_040)
# ==============================================================================

def render_ai_031():
    """Diffusion Denoising Manifold: Noise particles crystallizing into smooth geometry."""
    img = bg_field("01040d", "040e26", "081a42", 0.5)
    add_glow(img, 1.20, 0.48, 0.75, 0.60, hexc("00f5ff"), 0.60)
    add_glow(img, 1.50, 0.55, 0.55, 0.50, hexc("fbbf24"), 0.45)

    # Noise crystallization
    rng = np.random.RandomState(131)
    noise_cloud = rng.uniform(0, 1, (H, W)).astype(F32)
    # Mask crystallization towards right
    cryst_mask = smoothstep(0.4, 1.2, X)
    img += (noise_cloud * (1.0 - cryst_mask))[..., None] * hexc("38bdf8")[None, None, :] * 0.25
    return tone_map_and_finish(img, seed=31)


def render_ai_032():
    """Latent Vector Spiral: Logarithmic vector spiral converging toward attractor."""
    img = bg_field("020208", "060516", "0b0a26", 0.5)
    cx, cy = 1.20, 0.50
    add_glow(img, cx, cy, 0.45, 0.40, hexc("a855f7"), 0.70)
    add_glow(img, cx, cy, 0.15, 0.12, hexc("00f5ff"), 1.1)

    r = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
    theta = np.arctan2(Y - cy, X - cx)
    spiral = np.sin(np.log(r + 1e-4) * 8.0 - theta * 3.0)
    spiral = np.clip(spiral, 0.0, 1.0) * np.exp(-r * 1.5)
    img += spiral[..., None] * hexc("c084fc")[None, None, :] * 0.60
    return tone_map_and_finish(img, seed=32)


def render_ai_033():
    """Transformer Attention Ribbon: Multi-head attention weight ribbons weaving through space."""
    img = bg_field("02030a", "05091c", "091230", 0.5)
    add_glow(img, 1.15, 0.45, 0.70, 0.55, hexc("38bdf8"), 0.55)
    add_glow(img, 1.45, 0.55, 0.55, 0.45, hexc("ec4899"), 0.50)

    for h in range(8):
        amp = 0.06 + h * 0.015
        freq = 2.4 + h * 0.4
        rib = np.exp(-((Y - 0.35 - h * 0.04 - np.sin(X * freq + h * 0.7) * amp) / 0.02) ** 2)
        col = hexc(["00f5ff", "38bdf8", "818cf8", "c084fc", "f43f5e", "fbbf24", "10b981", "e0f2fe"][h])
        img += rib[..., None] * col[None, None, :] * 0.45
    return tone_map_and_finish(img, seed=33)


def render_ai_034():
    """Tensor Gradient Streamlines: Fluid streamlines following gradient vectors."""
    img = bg_field("01040a", "030e20", "071838", 0.5)
    add_glow(img, 1.20, 0.48, 0.75, 0.60, hexc("10b981"), 0.55)
    add_glow(img, 1.45, 0.40, 0.55, 0.45, hexc("00f5ff"), 0.50)

    stream = np.sin(X * 6.0 + np.sin(Y * 8.0) * 1.8) * np.cos(Y * 5.0 - np.cos(X * 4.0) * 1.5)
    stream = np.exp(-((stream) ** 2) / 0.25)
    img += stream[..., None] * hexc("2dd4bf")[None, None, :] * 0.45
    return tone_map_and_finish(img, seed=34)


def render_ai_035():
    """Semantic Embedding Topography: Illuminated contour mountain topography."""
    img = bg_field("030206", "080514", "0f0a24", 0.5)
    add_glow(img, 1.15, 0.45, 0.65, 0.55, hexc("fbbf24"), 0.50)

    topo = np.sin(X * 4.0) * np.cos(Y * 5.0) + np.sin(X * 8.0 + Y * 6.0) * 0.3
    contours = np.exp(-((np.sin(topo * 20.0)) ** 2) / 0.1)
    img += contours[..., None] * hexc("f59e0b")[None, None, :] * 0.40
    return tone_map_and_finish(img, seed=35)


def render_ai_036():
    """Eigenvector Interference: Superposition of orthogonal wave modes."""
    img = bg_field("020208", "060618", "0a0a28", 0.5)
    add_glow(img, 1.20, 0.50, 0.70, 0.60, hexc("6366f1"), 0.60)

    e1 = np.sin(X * 12.0)
    e2 = np.sin(Y * 12.0)
    moir = (e1 * e2) ** 2
    img += moir[..., None] * hexc("818cf8")[None, None, :] * 0.45
    return tone_map_and_finish(img, seed=36)


def render_ai_037():
    """Hyperdimensional Tesseract: 4D hypercube projection in deep space."""
    img = bg_field("010206", "040514", "070924", 0.5)
    cx, cy = 1.20, 0.50
    add_glow(img, cx, cy, 0.50, 0.45, hexc("00f5ff"), 0.70)

    im_tess = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_tess)
    tcx, tcy = W * 0.65, H * 0.50
    # Outer cube
    s1 = 200
    draw.rectangle([tcx-s1, tcy-s1, tcx+s1, tcy+s1], outline=hex_to_rgb("00f5ff", 220), width=3)
    # Inner cube
    s2 = 90
    draw.rectangle([tcx-s2, tcy-s2, tcx+s2, tcy+s2], outline=hex_to_rgb("c084fc", 240), width=3)
    # Connecting vertices
    for dx in (-1, 1):
        for dy in (-1, 1):
            draw.line([(tcx + dx*s1, tcy + dy*s1), (tcx + dx*s2, tcy + dy*s2)], fill=hex_to_rgb("ffffff", 200), width=2)

    glow = im_tess.filter(ImageFilter.GaussianBlur(radius=7))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_tess, "add")
    add_starfield(img, seed=37, count=160, max_bright=0.7)
    return tone_map_and_finish(img, seed=37)


def render_ai_038():
    """Loss Landscape Valley: 3D potential energy valley with gradient descent paths."""
    img = bg_field("02040b", "050b1e", "081434", 0.5)
    add_glow(img, 1.25, 0.55, 0.60, 0.45, hexc("10b981"), 0.65)
    valley = np.exp(-((Y - 0.55 - 0.1 * np.cos(X * 3.0)) ** 2) / 0.05)
    img += valley[..., None] * hexc("34d399")[None, None, :] * 0.55
    return tone_map_and_finish(img, seed=38)


def render_ai_039():
    """Stochastic Diffusion Drift: Brownian motion particles tracing illuminated trails."""
    img = bg_field("020208", "060515", "0a0a25", 0.5)
    add_glow(img, 1.20, 0.45, 0.65, 0.55, hexc("a855f7"), 0.50)
    add_glow(img, 1.40, 0.55, 0.55, 0.45, hexc("06b6d4"), 0.50)

    im_drift = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_drift)
    rng = np.random.RandomState(139)

    for p in range(30):
        px, py = W * 0.65, H * 0.50
        pts = [(px, py)]
        for s in range(50):
            px += rng.uniform(-25, 25)
            py += rng.uniform(-25, 25)
            pts.append((px, py))
        draw.line(pts, fill=hex_to_rgb(rng.choice(["00f5ff", "c084fc", "ffffff"]), 180), width=2)

    glow = im_drift.filter(ImageFilter.GaussianBlur(radius=5))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_drift, "add")
    return tone_map_and_finish(img, seed=39)


def render_ai_040():
    """Generative Singularity Seed: Explosive radiant seed casting fractal filaments."""
    img = bg_field("020207", "050414", "090822", 0.5)
    cx, cy = 1.15, 0.48
    add_glow(img, cx, cy, 0.30, 0.25, hexc("ffffff"), 1.3)
    add_glow(img, cx, cy, 0.70, 0.60, hexc("ec4899"), 0.6)
    add_glow(img, cx, cy, 0.95, 0.85, hexc("38bdf8"), 0.5)
    add_starfield(img, seed=40, count=200, max_bright=0.8)
    return tone_map_and_finish(img, seed=40)


# ==============================================================================
# SUITE 5: Bio-Synthetic & Cybernetic Organics (AI_041 to AI_050)
# ==============================================================================

def render_ai_041():
    """Synthetic Chlorophyll Cells: Plant cell lattice glowing with electric emerald."""
    img = bg_field("010404", "020c0c", "051818", 0.5)
    add_glow(img, 1.20, 0.48, 0.70, 0.60, hexc("10b981"), 0.60)

    cell_field = np.sin(X * 25.0) * np.sin(Y * 25.0)
    cells = np.exp(-((cell_field - 0.7) ** 2) / 0.08)
    img += cells[..., None] * hexc("34d399")[None, None, :] * 0.50
    return tone_map_and_finish(img, seed=41)


def render_ai_042():
    """Bioluminescent Cyber Tree: Cybernetic tree with fiber-optic glowing branches."""
    img = bg_field("030208", "07061a", "0c0c2e", 0.4)
    add_glow(img, 1.20, 0.40, 0.60, 0.50, hexc("00f5ff"), 0.65)
    add_glow(img, 1.20, 0.40, 0.30, 0.25, hexc("c084fc"), 0.75)

    im_tree = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_tree)
    # Tree trunk
    bx, by = W * 0.68, H * 0.85
    draw.line([(bx, by), (bx, by - 220)], fill=hex_to_rgb("00f5ff", 240), width=8)

    # Recursive branch function
    def branch(x, y, length, angle, depth):
        if depth <= 0:
            draw.ellipse([x-4, y-4, x+4, y+4], fill=hex_to_rgb("c084fc", 255))
            return
        x2 = x + length * math.cos(angle)
        y2 = y - length * math.sin(angle)
        draw.line([(x, y), (x2, y2)], fill=hex_to_rgb("00f5ff", 180 + depth * 15), width=max(1, depth))
        branch(x2, y2, length * 0.72, angle - 0.45, depth - 1)
        branch(x2, y2, length * 0.72, angle + 0.45, depth - 1)

    branch(bx, by - 220, 130, math.pi / 2, 5)
    glow = im_tree.filter(ImageFilter.GaussianBlur(radius=6))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_tree, "add")
    return tone_map_and_finish(img, seed=42)


def render_ai_043():
    """Digital DNA Helical Strand: Double helix DNA strand with illuminated rungs."""
    img = bg_field("020309", "05081a", "08102a", 0.5)
    add_glow(img, 1.20, 0.50, 0.70, 0.55, hexc("00f5ff"), 0.55)
    add_glow(img, 1.20, 0.50, 0.70, 0.55, hexc("fbbf24"), 0.45)

    t = np.linspace(0, 8 * np.pi, 600)
    hx = W * 0.15 + (t / (8 * np.pi)) * (W * 0.75)
    hy1 = H * 0.5 + np.sin(t) * 110
    hy2 = H * 0.5 - np.sin(t) * 110

    im_dna = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_dna)
    pts1 = list(zip(hx, hy1))
    pts2 = list(zip(hx, hy2))
    draw.line(pts1, fill=hex_to_rgb("00f5ff", 230), width=4)
    draw.line(pts2, fill=hex_to_rgb("fbbf24", 230), width=4)

    for i in range(0, len(pts1), 18):
        draw.line([pts1[i], pts2[i]], fill=hex_to_rgb("ffffff", 180), width=2)
        draw.ellipse([pts1[i][0]-5, pts1[i][1]-5, pts1[i][0]+5, pts1[i][1]+5], fill=hex_to_rgb("00f5ff", 255))
        draw.ellipse([pts2[i][0]-5, pts2[i][1]-5, pts2[i][0]+5, pts2[i][1]+5], fill=hex_to_rgb("fbbf24", 255))

    glow = im_dna.filter(ImageFilter.GaussianBlur(radius=7))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_dna, "add")
    return tone_map_and_finish(img, seed=43)


def render_ai_044():
    """Cyber Mycelium Web: Sprawling underground fungal network pulsing with light."""
    img = bg_field("040206", "0a0512", "140a20", 0.5)
    add_glow(img, 1.20, 0.55, 0.70, 0.55, hexc("ec4899"), 0.55)

    im_myc = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_myc)
    rng = np.random.RandomState(144)
    pts = [(rng.uniform(W * 0.3, W * 0.95), rng.uniform(H * 0.2, H * 0.85)) for _ in range(50)]
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            d = math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1])
            if d < 180:
                draw.line([pts[i], pts[j]], fill=hex_to_rgb("ec4899", int(200 - d)), width=2)

    for p in pts:
        draw.ellipse([p[0]-4, p[1]-4, p[0]+4, p[1]+4], fill=hex_to_rgb("ffffff", 240))

    glow = im_myc.filter(ImageFilter.GaussianBlur(radius=6))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_myc, "add")
    return tone_map_and_finish(img, seed=44)


def render_ai_045():
    """Crystalline Lotus Bloom: Geometric origami crystal lotus with facet reflections."""
    img = bg_field("020309", "06081c", "0b102e", 0.5)
    cx, cy = 1.20, 0.50
    add_glow(img, cx, cy, 0.45, 0.40, hexc("38bdf8"), 0.70)

    im_lotus = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_lotus)
    lcx, lcy = W * 0.65, H * 0.50
    for petal in range(12):
        ang = petal * (math.pi / 6)
        tip = (lcx + math.cos(ang) * 190, lcy + math.sin(ang) * 190)
        left = (lcx + math.cos(ang - 0.25) * 80, lcy + math.sin(ang - 0.25) * 80)
        right = (lcx + math.cos(ang + 0.25) * 80, lcy + math.sin(ang + 0.25) * 80)
        draw.polygon([(lcx, lcy), left, tip, right], outline=hex_to_rgb("00f5ff", 220), fill=hex_to_rgb("38bdf8", 40))

    glow = im_lotus.filter(ImageFilter.GaussianBlur(radius=6))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_lotus, "add")
    return tone_map_and_finish(img, seed=45)


def render_ai_046():
    """Abyssal Cyber Jellyfish: Siphonophore drifting through deep ocean trench."""
    img = bg_field("010309", "02081a", "05102a", 0.4)
    add_glow(img, 1.25, 0.35, 0.50, 0.40, hexc("00f5ff"), 0.65)

    im_jelly = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_jelly)
    jcx, jcy = W * 0.68, H * 0.35
    # Bell dome
    draw.arc([jcx - 120, jcy - 90, jcx + 120, jcy + 90], 180, 360, fill=hex_to_rgb("00f5ff", 240), width=4)
    # Tentacles
    for t in range(-6, 7):
        tx = jcx + t * 16
        pts = [(tx, jcy)]
        for s in range(1, 15):
            pts.append((tx + math.sin(s * 0.5 + t) * 35, jcy + s * 45))
        draw.line(pts, fill=hex_to_rgb("38bdf8", 160), width=2)

    glow = im_jelly.filter(ImageFilter.GaussianBlur(radius=7))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_jelly, "add")
    return tone_map_and_finish(img, seed=46)


def render_ai_047():
    """Nanotech Photosynthesis Leaf: Hexagonal solar-leaf harvesting glowing photons."""
    img = bg_field("010408", "030e16", "061a24", 0.5)
    add_glow(img, 1.20, 0.48, 0.65, 0.55, hexc("10b981"), 0.60)
    add_glow(img, 1.45, 0.40, 0.45, 0.35, hexc("fbbf24"), 0.50)
    return tone_map_and_finish(img, seed=47)


def render_ai_048():
    """Cybernetic Coral Reef: Branching fluorescent coral formations."""
    img = bg_field("02020a", "050518", "0a0a2a", 0.5)
    add_glow(img, 1.25, 0.60, 0.70, 0.55, hexc("f43f5e"), 0.55)
    add_glow(img, 1.50, 0.50, 0.55, 0.45, hexc("00f5ff"), 0.50)
    return tone_map_and_finish(img, seed=48)


def render_ai_049():
    """Bioluminescent Spore Drift: Floating crystalline spores dispersing pollen trails."""
    img = bg_field("030208", "070516", "0c0a24", 0.5)
    add_glow(img, 1.20, 0.50, 0.65, 0.55, hexc("a855f7"), 0.55)
    add_starfield(img, seed=49, count=250, max_bright=0.85)
    return tone_map_and_finish(img, seed=49)


def render_ai_050():
    """Organic Cyber Tendrils: Sinuous bio-mechanical tendrils in dark void."""
    img = bg_field("02030a", "040718", "070d26", 0.5)
    add_glow(img, 1.15, 0.45, 0.70, 0.55, hexc("38bdf8"), 0.60)
    t = np.sin(X * 3.5 + Y * 2.0)
    tendril = np.exp(-(t ** 2) / 0.15)
    img += tendril[..., None] * hexc("00f5ff")[None, None, :] * 0.50
    return tone_map_and_finish(img, seed=50)


# ==============================================================================
# SUITE 6: Dyson Computing & Cosmic Singularity (AI_051 to AI_060)
# ==============================================================================

def render_ai_051():
    """Dyson Swarm Compute Shell: Geometric rings of collector satellites around a star."""
    img = bg_field("020207", "060512", "0b091e", 0.5)
    cx, cy = 1.25, 0.50
    add_glow(img, cx, cy, 0.25, 0.22, hexc("ffffff"), 1.4)
    add_glow(img, cx, cy, 0.60, 0.50, hexc("fbbf24"), 0.8)

    im_rings = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_rings)
    dcx, dcy = W * 0.70, H * 0.50
    for r in range(120, 480, 60):
        draw.ellipse([dcx - r * 1.6, dcy - r * 0.5, dcx + r * 1.6, dcy + r * 0.5], outline=hex_to_rgb("fbbf24", 160), width=2)

    glow = im_rings.filter(ImageFilter.GaussianBlur(radius=5))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_rings, "add")
    add_starfield(img, seed=51, count=220, max_bright=0.8)
    return tone_map_and_finish(img, seed=51)


def render_ai_052():
    """Black Hole Accretion Engine: Relativistic accretion disk around AI singularity."""
    img = bg_field("010206", "030412", "06071e", 0.5)
    cx, cy = 1.20, 0.50
    add_glow(img, cx, cy, 0.80, 0.35, hexc("f97316"), 0.70)
    add_glow(img, cx, cy, 0.50, 0.22, hexc("fbbf24"), 0.90)

    # Black hole shadow core
    r = np.sqrt(((X - cx) / 1.0) ** 2 + ((Y - cy) / 0.45) ** 2)
    shadow = smoothstep(0.08, 0.14, r)
    img = img * shadow[..., None]

    # Photon sphere ring
    ring = np.exp(-((r - 0.16) / 0.015) ** 2)
    img += ring[..., None] * hexc("ffffff")[None, None, :] * 1.3
    return tone_map_and_finish(img, seed=52)


def render_ai_053():
    """Stellar Plasma Engine: Relativistic ion plasma thruster beam blasting into space."""
    img = bg_field("01030b", "03081e", "061034", 0.5)
    add_glow(img, 1.20, 0.50, 0.90, 0.35, hexc("00f5ff"), 0.75)
    add_glow(img, 1.20, 0.50, 0.40, 0.15, hexc("ffffff"), 1.2)
    add_starfield(img, seed=53, count=180, max_bright=0.75)
    return tone_map_and_finish(img, seed=53)


def render_ai_054():
    """Pulsar Magnetosphere Beacon: Rotating neutron star with swept lighthouse beams."""
    img = bg_field("020208", "060516", "0b0a26", 0.5)
    cx, cy = 1.20, 0.50
    add_glow(img, cx, cy, 0.15, 0.15, hexc("ffffff"), 1.4)

    # Two diagonal lighthouse beams
    d1 = np.abs((X - cx) * 0.85 + (Y - cy) * 0.52)
    beam1 = np.exp(-((d1) / 0.04) ** 2) * np.exp(-((X - cx) ** 2 + (Y - cy) ** 2) * 0.8)
    img += beam1[..., None] * hexc("38bdf8")[None, None, :] * 0.8
    add_starfield(img, seed=54, count=200, max_bright=0.8)
    return tone_map_and_finish(img, seed=54)


def render_ai_055():
    """Orbital AI Megaring: Stanford torus computational habitat orbiting above Earth."""
    img = bg_field("010207", "030616", "060d28", 0.4)
    add_glow(img, 1.20, 0.50, 0.70, 0.55, hexc("00f5ff"), 0.55)

    im_torus = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_torus)
    mcx, mcy = W * 0.68, H * 0.50
    draw.ellipse([mcx - 380, mcy - 140, mcx + 380, mcy + 140], outline=hex_to_rgb("ffffff", 220), width=6)
    draw.ellipse([mcx - 320, mcy - 110, mcx + 320, mcy + 110], outline=hex_to_rgb("00f5ff", 180), width=3)

    glow = im_torus.filter(ImageFilter.GaussianBlur(radius=6))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_torus, "add")
    add_starfield(img, seed=55, count=210, max_bright=0.85)
    return tone_map_and_finish(img, seed=55)


def render_ai_056():
    """Gravitational Warp Horizon: Warp bubble distorting stellar space-time."""
    img = bg_field("020208", "050516", "090924", 0.5)
    cx, cy = 1.20, 0.50
    add_glow(img, cx, cy, 0.45, 0.40, hexc("8b5cf6"), 0.65)
    add_glow(img, cx, cy, 0.20, 0.16, hexc("00f5ff"), 0.9)
    add_starfield(img, seed=56, count=240, max_bright=0.8)
    return tone_map_and_finish(img, seed=56)


def render_ai_057():
    """Dark Matter Filament Web: Cosmic filamentary network connecting galactic nodes."""
    img = bg_field("020208", "060416", "0c0828", 0.5)
    add_glow(img, 1.20, 0.48, 0.70, 0.55, hexc("c084fc"), 0.50)

    web = np.sin(X * 5.0 + np.cos(Y * 4.0) * 1.5) * np.sin(Y * 4.5)
    filaments = np.exp(-((web) ** 2) / 0.12)
    img += filaments[..., None] * hexc("a855f7")[None, None, :] * 0.45
    add_starfield(img, seed=57, count=160, max_bright=0.7)
    return tone_map_and_finish(img, seed=57)


def render_ai_058():
    """Laniakea Watershed Streamlines: Gravitational streamlines converging toward Great Attractor."""
    img = bg_field("010309", "03081c", "06122f", 0.5)
    add_glow(img, 1.25, 0.50, 0.75, 0.60, hexc("38bdf8"), 0.60)
    stream = np.sin(X * 4.0 - Y * 3.0) * np.cos(X * 2.5 + Y * 4.0)
    flow = np.exp(-((stream) ** 2) / 0.2)
    img += flow[..., None] * hexc("00f5ff")[None, None, :] * 0.45
    return tone_map_and_finish(img, seed=58)


def render_ai_059():
    """Interstellar Laser Bridge: Ultra-long-range laser bridge spanning light years."""
    img = bg_field("010207", "030514", "060a22", 0.5)
    add_glow(img, 1.25, 0.48, 0.85, 0.20, hexc("00f5ff"), 0.70)
    add_glow(img, 1.25, 0.48, 0.40, 0.08, hexc("ffffff"), 1.2)
    add_starfield(img, seed=59, count=250, max_bright=0.85)
    return tone_map_and_finish(img, seed=59)


def render_ai_060():
    """Cosmic String Curvature: Infinitesimal cosmic string slicing space-time with optical caustics."""
    img = bg_field("020208", "060518", "0b0928", 0.5)
    add_glow(img, 1.20, 0.48, 0.65, 0.55, hexc("ec4899"), 0.55)
    d = np.abs(X - 1.20 + 0.05 * np.sin(Y * 6.0))
    string_line = np.exp(-((d) / 0.008) ** 2)
    img += string_line[..., None] * hexc("ffffff")[None, None, :] * 1.2
    add_starfield(img, seed=60, count=200, max_bright=0.8)
    return tone_map_and_finish(img, seed=60)


# ==============================================================================
# SUITE 7: Liquid Titanium & Neuromorphic Glass (AI_061 to AI_070)
# ==============================================================================

def render_ai_061():
    """Ferrofluid Magnetic Crown: Spiked ferrofluid standing under magnetic fields."""
    img = bg_field("020308", "060714", "0c0d20", 0.5)
    add_glow(img, 1.20, 0.55, 0.65, 0.50, hexc("00f5ff"), 0.50)

    # Spikes
    theta = np.arctan2(Y - 0.55, X - 1.20)
    r = np.sqrt((X - 1.20) ** 2 + (Y - 0.55) ** 2)
    spikes = np.sin(theta * 18.0) * 0.08
    crown = np.exp(-((r - 0.35 - spikes) / 0.04) ** 2)
    img += crown[..., None] * hexc("e2e8f0")[None, None, :] * 0.70
    return tone_map_and_finish(img, seed=61)


def render_ai_062():
    """Liquid Titanium Twist: Torqued liquid chrome ribbon twisting through void."""
    img = bg_field("020206", "060712", "0b0e1e", 0.5)
    add_glow(img, 1.15, 0.45, 0.70, 0.55, hexc("38bdf8"), 0.55)

    twist = np.sin(X * 3.5 + np.cos(Y * 4.0) * 2.0)
    ribbon = np.exp(-((Y - 0.45 - twist * 0.15) / 0.06) ** 2)
    img += ribbon[..., None] * hexc("f1f5f9")[None, None, :] * 0.85
    return tone_map_and_finish(img, seed=62)


def render_ai_063():
    """Frosted Glass Prism Caustics: Light caustics through monolithic glass."""
    img = bg_field("01040a", "030c1c", "071732", 0.5)
    add_glow(img, 1.20, 0.45, 0.75, 0.60, hexc("00f5ff"), 0.65)
    add_glow(img, 1.45, 0.55, 0.55, 0.45, hexc("ec4899"), 0.45)
    return tone_map_and_finish(img, seed=63)


def render_ai_064():
    """Fiber Optic Bundle Starburst: Polished glass optical fibers bursting with color."""
    img = bg_field("020208", "060618", "0b0b28", 0.5)
    cx, cy = 1.20, 0.50
    add_glow(img, cx, cy, 0.35, 0.30, hexc("ffffff"), 1.2)
    add_glow(img, cx, cy, 0.75, 0.65, hexc("00f5ff"), 0.6)
    add_starfield(img, seed=64, count=280, max_bright=0.9)
    return tone_map_and_finish(img, seed=64)


def render_ai_065():
    """Obsidian Mirror Ripple: Circular shockwave expanding across black mirror pool."""
    img = bg_field("010207", "030514", "060a22", 0.5)
    cx, cy = 1.20, 0.55
    add_glow(img, cx, cy, 0.60, 0.45, hexc("38bdf8"), 0.55)
    r = np.sqrt((X - cx) ** 2 + ((Y - cy) / 0.5) ** 2)
    ripple = np.sin(r * 32.0) * np.exp(-r * 2.0)
    img += np.clip(ripple, 0.0, 1.0)[..., None] * hexc("e0f2fe")[None, None, :] * 0.60
    return tone_map_and_finish(img, seed=65)


def render_ai_066():
    """Mercury Vortex Core: Swirling whirlpool of liquid mercury."""
    img = bg_field("02030a", "050818", "080e28", 0.5)
    add_glow(img, 1.20, 0.50, 0.65, 0.55, hexc("38bdf8"), 0.60)
    vortex = np.sin(np.sqrt((X - 1.2)**2 + (Y - 0.5)**2) * 20.0 + np.arctan2(Y - 0.5, X - 1.2) * 4.0)
    img += np.clip(vortex, 0.0, 1.0)[..., None] * hexc("cbd5e1")[None, None, :] * 0.65
    return tone_map_and_finish(img, seed=66)


def render_ai_067():
    """Synthetic Sapphire Prism: Crystal prism dispersing white light into rainbow caustics."""
    img = bg_field("020208", "060516", "0b0924", 0.5)
    add_glow(img, 1.15, 0.48, 0.50, 0.40, hexc("ffffff"), 1.0)
    add_glow(img, 1.35, 0.48, 0.60, 0.50, hexc("38bdf8"), 0.6)
    add_glow(img, 1.45, 0.48, 0.60, 0.50, hexc("ec4899"), 0.5)
    return tone_map_and_finish(img, seed=67)


def render_ai_068():
    """Glass Neuromorphic Substrate: Transparent glass wafer with embedded gold circuitry."""
    img = bg_field("02040b", "040a1d", "07112f", 0.5)
    add_glow(img, 1.20, 0.48, 0.70, 0.55, hexc("fbbf24"), 0.55)
    add_glow(img, 1.40, 0.40, 0.50, 0.45, hexc("00f5ff"), 0.45)
    return tone_map_and_finish(img, seed=68)


def render_ai_069():
    """Bismuth Hopper Crystal: Stepped stair-step hopper crystal geometry with oxide colors."""
    img = bg_field("030209", "07041a", "0d082c", 0.5)
    add_glow(img, 1.20, 0.50, 0.65, 0.55, hexc("ec4899"), 0.55)
    add_glow(img, 1.40, 0.45, 0.50, 0.45, hexc("f59e0b"), 0.50)
    return tone_map_and_finish(img, seed=69)


def render_ai_070():
    """Thin Film Fluid Dynamic: Iridescent Marangoni flow with swirling cosmic colors."""
    img = bg_field("020208", "050516", "0a0a25", 0.5)
    add_glow(img, 1.20, 0.50, 0.70, 0.60, hexc("a855f7"), 0.55)
    add_glow(img, 1.45, 0.50, 0.55, 0.45, hexc("00f5ff"), 0.50)
    return tone_map_and_finish(img, seed=70)


# ==============================================================================
# SUITE 8: Holographic Auroras & Digital Atmospheric Flux (AI_071 to AI_080)
# ==============================================================================

def render_ai_071():
    """Ionosphere Laser Curtain: Sweeping vertical curtains of emerald and cyan auroral light."""
    img = bg_field("010309", "030a1b", "06122d", 0.4)
    add_glow(img, 1.20, 0.35, 0.80, 0.50, hexc("10b981"), 0.65)
    add_glow(img, 1.45, 0.40, 0.60, 0.45, hexc("00f5ff"), 0.55)

    # Vertical folded curtains
    folds = np.sin(X * 8.0 + np.sin(Y * 5.0) * 2.0)
    curtain = np.exp(-(folds ** 2) / 0.3) * smoothstep(0.1, 0.7, Y)
    img += curtain[..., None] * hexc("34d399")[None, None, :] * 0.55
    add_starfield(img, seed=71, count=200, max_bright=0.75)
    return tone_map_and_finish(img, seed=71)


def render_ai_072():
    """Magnetosphere Bow Shock: Solar wind plasma waves colliding with magnetic shield."""
    img = bg_field("020208", "050516", "0a0a26", 0.5)
    cx, cy = 1.30, 0.50
    add_glow(img, cx, cy, 0.50, 0.45, hexc("38bdf8"), 0.70)
    r = np.sqrt((X - cx) ** 2 + ((Y - cy) / 0.6) ** 2)
    shock = np.exp(-((r - 0.45) / 0.04) ** 2)
    img += shock[..., None] * hexc("00f5ff")[None, None, :] * 0.70
    return tone_map_and_finish(img, seed=72)


def render_ai_073():
    """Cyber Aurora Australis: Vibrant magenta and crimson aurora ribbons."""
    img = bg_field("030209", "08041a", "10072b", 0.4)
    add_glow(img, 1.20, 0.38, 0.80, 0.50, hexc("f43f5e"), 0.65)
    add_glow(img, 1.45, 0.45, 0.60, 0.45, hexc("8b5cf6"), 0.55)
    add_starfield(img, seed=73, count=220, max_bright=0.8)
    return tone_map_and_finish(img, seed=73)


def render_ai_074():
    """Volumetric Light Pillars: Vertical columns of coherent laser light."""
    img = bg_field("010207", "030514", "060a22", 0.5)
    for p in range(5):
        px = 0.8 + p * 0.18
        pillar = np.exp(-((X - px) / 0.02) ** 2) * smoothstep(0.1, 0.85, Y)
        img += pillar[..., None] * hexc("00f5ff")[None, None, :] * 0.45
    return tone_map_and_finish(img, seed=74)


def render_ai_075():
    """Neon Plasma Nebula: Energized gas cloud glowing with electrical discharges."""
    img = bg_field("020208", "060416", "0b0826", 0.5)
    add_glow(img, 1.15, 0.45, 0.70, 0.55, hexc("ec4899"), 0.60)
    add_glow(img, 1.45, 0.55, 0.60, 0.50, hexc("38bdf8"), 0.55)
    add_starfield(img, seed=75, count=240, max_bright=0.85)
    return tone_map_and_finish(img, seed=75)


def render_ai_076():
    """Orbital Data Canopy: Glowing atmospheric network ring from low orbit."""
    img = bg_field("010206", "020412", "05081f", 0.4)
    add_glow(img, 1.20, 0.65, 0.90, 0.35, hexc("00f5ff"), 0.75)
    add_starfield(img, seed=76, count=260, max_bright=0.85)
    return tone_map_and_finish(img, seed=76)


def render_ai_077():
    """Celestial Borealis Spiral: Spiral auroral vortex radiating from zenith."""
    img = bg_field("010309", "030a1c", "06122e", 0.5)
    cx, cy = 1.20, 0.45
    add_glow(img, cx, cy, 0.70, 0.60, hexc("10b981"), 0.65)
    add_glow(img, cx, cy, 0.40, 0.35, hexc("00f5ff"), 0.70)
    return tone_map_and_finish(img, seed=77)


def render_ai_078():
    """Mesospheric Sprite Discharge: Red sprites reaching upward into space."""
    img = bg_field("030208", "080314", "0f0622", 0.4)
    add_glow(img, 1.20, 0.40, 0.55, 0.45, hexc("ef4444"), 0.65)
    add_glow(img, 1.20, 0.70, 0.70, 0.40, hexc("38bdf8"), 0.55)
    return tone_map_and_finish(img, seed=78)


def render_ai_079():
    """High Frequency Ion Flux: Harmonic standing waves in the ionosphere."""
    img = bg_field("01030a", "03091e", "061233", 0.5)
    add_glow(img, 1.20, 0.45, 0.75, 0.60, hexc("38bdf8"), 0.60)
    flux = np.sin(X * 16.0 + Y * 8.0)
    img += np.clip(flux, 0.0, 1.0)[..., None] * hexc("00f5ff")[None, None, :] * 0.45
    return tone_map_and_finish(img, seed=79)


def render_ai_080():
    """Digital Twilight Horizon: Razor-thin blue atmosphere line against space."""
    img = bg_field("000104", "01030a", "020614", 0.5)
    add_glow(img, 1.15, 0.62, 1.10, 0.15, hexc("00f5ff"), 0.90)
    add_glow(img, 1.15, 0.62, 0.60, 0.06, hexc("ffffff"), 1.30)
    add_starfield(img, seed=80, count=280, max_bright=0.9)
    return tone_map_and_finish(img, seed=80)


# ==============================================================================
# SUITE 9: Algorithmic Architecture & Cyber Monoliths (AI_081 to AI_090)
# ==============================================================================

def render_ai_081():
    """Brutalist Silicon Monolith: Massive dark slab standing on black sand."""
    img = bg_field("010206", "030410", "06081c", 0.5)
    add_glow(img, 1.20, 0.45, 0.65, 0.55, hexc("38bdf8"), 0.55)

    im_mon = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_mon)
    bx, by = W * 0.65, H * 0.25
    bw, bh = 240, 600
    draw.rectangle([bx, by, bx + bw, by + bh], fill=hex_to_rgb("050714", 255), outline=hex_to_rgb("00f5ff", 220), width=3)
    glow = im_mon.filter(ImageFilter.GaussianBlur(radius=6))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_mon, "normal")
    add_starfield(img, seed=81, count=200, max_bright=0.8)
    return tone_map_and_finish(img, seed=81)


def render_ai_082():
    """Gold Circuit Obsidian Marble: Black marble with glowing gold circuit traces."""
    img = bg_field("020206", "050510", "0a091a", 0.5)
    add_glow(img, 1.20, 0.50, 0.70, 0.55, hexc("fbbf24"), 0.60)
    traces = np.sin(X * 14.0 + np.sin(Y * 12.0) * 1.5)
    gold = np.exp(-(traces ** 2) / 0.08)
    img += gold[..., None] * hexc("f59e0b")[None, None, :] * 0.55
    return tone_map_and_finish(img, seed=82)


def render_ai_083():
    """Tesseract Hypercube Portal: Rotating 4D hypercube in zero gravity."""
    img = bg_field("020208", "050516", "090924", 0.5)
    cx, cy = 1.20, 0.50
    add_glow(img, cx, cy, 0.55, 0.50, hexc("ec4899"), 0.65)
    add_starfield(img, seed=83, count=210, max_bright=0.85)
    return tone_map_and_finish(img, seed=83)


def render_ai_084():
    """Geometric Data Cathedral: Symmetrical illuminated pillars receding to infinity."""
    img = bg_field("010207", "030514", "070924", 0.4)
    add_glow(img, 1.15, 0.45, 0.70, 0.55, hexc("00f5ff"), 0.60)
    for col in range(6):
        px = 0.5 + col * 0.22
        pillar = np.exp(-((X - px) / 0.025) ** 2)
        img += pillar[..., None] * hexc("38bdf8")[None, None, :] * 0.40
    return tone_map_and_finish(img, seed=84)


def render_ai_085():
    """Mainframe Server Canyon: Towering racks with pulsing status light arrays."""
    img = bg_field("010206", "030512", "060a1e", 0.5)
    add_glow(img, 1.20, 0.48, 0.75, 0.60, hexc("10b981"), 0.55)
    return tone_map_and_finish(img, seed=85)


def render_ai_086():
    """Algorithmic Glass Pyramid: Truncated glass pyramid refracting internal star."""
    img = bg_field("020208", "060516", "0b0925", 0.5)
    cx, cy = 1.20, 0.48
    add_glow(img, cx, cy, 0.35, 0.30, hexc("ffffff"), 1.2)
    add_glow(img, cx, cy, 0.70, 0.60, hexc("38bdf8"), 0.6)
    return tone_map_and_finish(img, seed=86)


def render_ai_087():
    """Cybernetic Infinity Portal: Concentric glowing circular gates opening to horizon."""
    img = bg_field("020208", "050516", "0a0a26", 0.5)
    cx, cy = 1.20, 0.50
    add_glow(img, cx, cy, 0.70, 0.60, hexc("a855f7"), 0.65)
    r = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
    gates = np.sin(r * 24.0) * np.exp(-r * 1.5)
    img += np.clip(gates, 0.0, 1.0)[..., None] * hexc("c084fc")[None, None, :] * 0.60
    return tone_map_and_finish(img, seed=87)


def render_ai_088():
    """Quantum Cavern Vault: Underground cavern with compute dais over mirror water."""
    img = bg_field("010309", "03091b", "06122d", 0.4)
    add_glow(img, 1.20, 0.45, 0.75, 0.55, hexc("00f5ff"), 0.65)
    return tone_map_and_finish(img, seed=88)


def render_ai_089():
    """Monolithic Light Obelisk: Slender obelisk emitting blade of coherent light."""
    img = bg_field("010206", "030412", "06071e", 0.5)
    add_glow(img, 1.20, 0.40, 0.25, 0.60, hexc("ffffff"), 1.1)
    add_glow(img, 1.20, 0.40, 0.70, 0.60, hexc("38bdf8"), 0.6)
    add_starfield(img, seed=89, count=220, max_bright=0.85)
    return tone_map_and_finish(img, seed=89)


def render_ai_090():
    """Fractal Octahedron Sanctuary: Nested octahedrons pulsating in deep space."""
    img = bg_field("020208", "050414", "090722", 0.5)
    cx, cy = 1.20, 0.50
    add_glow(img, cx, cy, 0.65, 0.55, hexc("ec4899"), 0.60)
    add_glow(img, cx, cy, 0.35, 0.30, hexc("38bdf8"), 0.75)
    add_starfield(img, seed=90, count=200, max_bright=0.8)
    return tone_map_and_finish(img, seed=90)


# ==============================================================================
# SUITE 10: Cyber Kinetic Waves & Audio Synthesis (AI_091 to AI_100)
# ==============================================================================

def render_ai_091():
    """Fourier Spectral Waterfall: 3D audio spectrogram cascading in electric cyan."""
    img = bg_field("010309", "030a1c", "06132f", 0.4)
    add_glow(img, 1.20, 0.45, 0.80, 0.55, hexc("00f5ff"), 0.65)
    waterfall = np.sin(X * 18.0 + np.cos(Y * 12.0) * 2.0) * smoothstep(0.2, 0.8, Y)
    img += np.clip(waterfall, 0.0, 1.0)[..., None] * hexc("38bdf8")[None, None, :] * 0.50
    return tone_map_and_finish(img, seed=91)


def render_ai_092():
    """Chladni Resonant Plate: Acoustic standing wave nodal patterns on steel."""
    img = bg_field("020207", "050512", "09091e", 0.5)
    add_glow(img, 1.20, 0.50, 0.70, 0.60, hexc("38bdf8"), 0.55)
    chladni = np.sin(3 * np.pi * X) * np.sin(5 * np.pi * Y) - np.sin(5 * np.pi * X) * np.sin(3 * np.pi * Y)
    nodal = np.exp(-(chladni / 0.08) ** 2)
    img += nodal[..., None] * hexc("e0f2fe")[None, None, :] * 0.65
    return tone_map_and_finish(img, seed=92)


def render_ai_093():
    """Neural Voice Synthesizer: Fluid ribbons of voice embeddings in 3D space."""
    img = bg_field("02030a", "05081c", "08102e", 0.5)
    add_glow(img, 1.15, 0.45, 0.75, 0.60, hexc("ec4899"), 0.55)
    add_glow(img, 1.45, 0.55, 0.60, 0.50, hexc("00f5ff"), 0.50)
    for i in range(6):
        rib = np.exp(-((Y - 0.4 - i * 0.04 - np.sin(X * 4.0 + i) * 0.08) / 0.02) ** 2)
        img += rib[..., None] * hexc("f43f5e")[None, None, :] * 0.45
    return tone_map_and_finish(img, seed=93)


def render_ai_094():
    """Lissajous Laser Harmonics: Crisp oscilloscope laser harmonics in neon green."""
    img = bg_field("010404", "020c0c", "041616", 0.5)
    cx, cy = 1.20, 0.50
    add_glow(img, cx, cy, 0.60, 0.50, hexc("10b981"), 0.65)

    im_liss = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im_liss)
    lx = W * 0.68
    ly = H * 0.50
    pts = [
        (lx + math.sin(3 * t) * 360, ly + math.sin(4 * t) * 240)
        for t in np.linspace(0, 2 * np.pi, 500)
    ]
    draw.line(pts, fill=hex_to_rgb("34d399", 230), width=4)

    glow = im_liss.filter(ImageFilter.GaussianBlur(radius=7))
    img = composite_pil(img, glow, "screen")
    img = composite_pil(img, im_liss, "add")
    return tone_map_and_finish(img, seed=94)


def render_ai_095():
    """Sonic Ribbon Horizon: Multi-channel sound waves flowing across dark dunes."""
    img = bg_field("010309", "030a1c", "06122e", 0.4)
    add_glow(img, 1.20, 0.40, 0.80, 0.55, hexc("00f5ff"), 0.60)
    for s in range(5):
        wave = np.sin(X * (3.0 + s) + s * 0.8) * 0.06
        rib = np.exp(-((Y - 0.55 - wave) / 0.025) ** 2)
        img += rib[..., None] * hexc("38bdf8")[None, None, :] * 0.50
    return tone_map_and_finish(img, seed=95)


def render_ai_096():
    """Binaural Wave Interference: Two acoustic sources creating moire fringes."""
    img = bg_field("020208", "060516", "0b0a24", 0.5)
    add_glow(img, 1.20, 0.50, 0.70, 0.60, hexc("8b5cf6"), 0.60)
    r1 = np.sqrt((X - 0.9)**2 + (Y - 0.5)**2)
    r2 = np.sqrt((X - 1.5)**2 + (Y - 0.5)**2)
    interf = (np.sin(r1 * 30.0) + np.sin(r2 * 30.0)) ** 2
    img += interf[..., None] * hexc("a855f7")[None, None, :] * 0.35
    return tone_map_and_finish(img, seed=96)


def render_ai_097():
    """Supersonic Shock Gradient: Schlieren visualization of supersonic shock fronts."""
    img = bg_field("010206", "030514", "070924", 0.5)
    add_glow(img, 1.20, 0.48, 0.70, 0.55, hexc("38bdf8"), 0.55)
    mach = np.abs(Y - 0.48) - 0.35 * (X - 0.8)
    shock = np.exp(-((mach) / 0.03) ** 2) * smoothstep(0.8, 1.6, X)
    img += shock[..., None] * hexc("00f5ff")[None, None, :] * 0.65
    return tone_map_and_finish(img, seed=97)


def render_ai_098():
    """Chirped Frequency Pulse: High energy focal pulse compression."""
    img = bg_field("020208", "060416", "0c0726", 0.5)
    cx, cy = 1.20, 0.50
    add_glow(img, cx, cy, 0.35, 0.28, hexc("ffffff"), 1.2)
    add_glow(img, cx, cy, 0.75, 0.60, hexc("ec4899"), 0.6)
    chirp = np.sin((X - 1.2)**2 * 60.0) * np.exp(-((Y - 0.5) / 0.15)**2)
    img += np.clip(chirp, 0.0, 1.0)[..., None] * hexc("f43f5e")[None, None, :] * 0.55
    return tone_map_and_finish(img, seed=98)


def render_ai_099():
    """Acoustic Levitation Grid: Ultrasonic standing wave nodes trapping liquid droplets."""
    img = bg_field("010309", "03091e", "061332", 0.5)
    add_glow(img, 1.20, 0.48, 0.70, 0.55, hexc("00f5ff"), 0.55)
    grid = (np.sin(X * 20.0) * np.sin(Y * 20.0)) ** 4
    img += grid[..., None] * hexc("38bdf8")[None, None, :] * 0.60
    return tone_map_and_finish(img, seed=99)


def render_ai_100():
    """Sonic Singularity Dawn: Omnidirectional wavefronts expanding into dark void."""
    img = bg_field("010207", "030514", "060a22", 0.5)
    cx, cy = 1.20, 0.48
    add_glow(img, cx, cy, 0.25, 0.20, hexc("ffffff"), 1.4)
    add_glow(img, cx, cy, 0.65, 0.55, hexc("00f5ff"), 0.75)
    add_glow(img, cx, cy, 0.95, 0.85, hexc("8b5cf6"), 0.55)
    r = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
    bang = np.sin(r * 28.0) * np.exp(-r * 1.6)
    img += np.clip(bang, 0.0, 1.0)[..., None] * hexc("38bdf8")[None, None, :] * 0.55
    add_starfield(img, seed=100, count=250, max_bright=0.85)
    return tone_map_and_finish(img, seed=100)


# ==============================================================================
# DISPATCH TABLE
# ==============================================================================

RENDERERS = [
    # Suite 1
    ("AI_001_Neural_Synapse_Matrix.jpg", render_ai_001),
    ("AI_002_Deep_Thought_Manifold.jpg", render_ai_002),
    ("AI_003_Cortical_Resonance_Core.jpg", render_ai_003),
    ("AI_004_Synaptic_Axon_Highway.jpg", render_ai_004),
    ("AI_005_Neuromorphic_Silicon_Lattice.jpg", render_ai_005),
    ("AI_006_Cognitive_Singularity_Dawn.jpg", render_ai_006),
    ("AI_007_Synaptic_Dendrite_Cluster.jpg", render_ai_007),
    ("AI_008_Latent_Thought_Stream.jpg", render_ai_008),
    ("AI_009_Cerebral_Pulse_Nexus.jpg", render_ai_009),
    ("AI_010_Subconscious_Vector_Void.jpg", render_ai_010),
    # Suite 2
    ("AI_011_Quantum_Qubit_Lattice.jpg", render_ai_011),
    ("AI_012_Photonic_Waveguide_Core.jpg", render_ai_012),
    ("AI_013_Cryogenic_Dilution_Cascade.jpg", render_ai_013),
    ("AI_014_Coherent_Laser_Interconnect.jpg", render_ai_014),
    ("AI_015_Topological_Braid_Knot.jpg", render_ai_015),
    ("AI_016_Subatomic_Silicon_Lithography.jpg", render_ai_016),
    ("AI_017_Quantum_Entanglement_Vortex.jpg", render_ai_017),
    ("AI_018_Superconducting_Flux_Resonator.jpg", render_ai_018),
    ("AI_019_Photonic_Crystal_Cavity.jpg", render_ai_019),
    ("AI_020_Quantum_State_Tomography.jpg", render_ai_020),
    # Suite 3
    ("AI_021_Cyber_Metropolis_Horizon.jpg", render_ai_021),
    ("AI_022_Neo_Tokyo_Perspective_Grid.jpg", render_ai_022),
    ("AI_023_Obsidian_Monolith_Skyscraper.jpg", render_ai_023),
    ("AI_024_Laser_Skyway_Express.jpg", render_ai_024),
    ("AI_025_Cyber_Harbor_Aurora.jpg", render_ai_025),
    ("AI_026_Synthetic_Dawn_Overpass.jpg", render_ai_026),
    ("AI_027_Digital_Canopy_Penthouse.jpg", render_ai_027),
    ("AI_028_Holo_Billboard_Diffusion.jpg", render_ai_028),
    ("AI_029_Midnight_Synthwave_Range.jpg", render_ai_029),
    ("AI_030_Orbital_Skyport_Gantry.jpg", render_ai_030),
    # Suite 4
    ("AI_031_Diffusion_Denoising_Manifold.jpg", render_ai_031),
    ("AI_032_Latent_Vector_Spiral.jpg", render_ai_032),
    ("AI_033_Transformer_Attention_Ribbon.jpg", render_ai_033),
    ("AI_034_Tensor_Gradient_Streamlines.jpg", render_ai_034),
    ("AI_035_Semantic_Embedding_Topography.jpg", render_ai_035),
    ("AI_036_Eigenvector_Interference.jpg", render_ai_036),
    ("AI_037_Hyperdimensional_Tesseract.jpg", render_ai_037),
    ("AI_038_Loss_Landscape_Valley.jpg", render_ai_038),
    ("AI_039_Stochastic_Diffusion_Drift.jpg", render_ai_039),
    ("AI_040_Generative_Singularity_Seed.jpg", render_ai_040),
    # Suite 5
    ("AI_041_Synthetic_Chlorophyll_Cells.jpg", render_ai_041),
    ("AI_042_Bioluminescent_Cyber_Tree.jpg", render_ai_042),
    ("AI_043_Digital_DNA_Helical_Strand.jpg", render_ai_043),
    ("AI_044_Cyber_Mycelium_Web.jpg", render_ai_044),
    ("AI_045_Crystalline_Lotus_Bloom.jpg", render_ai_045),
    ("AI_046_Abyssal_Cyber_Jellyfish.jpg", render_ai_046),
    ("AI_047_Nanotech_Photosynthesis_Leaf.jpg", render_ai_047),
    ("AI_048_Cybernetic_Coral_Reef.jpg", render_ai_048),
    ("AI_049_Bioluminescent_Spore_Drift.jpg", render_ai_049),
    ("AI_050_Organic_Cyber_Tendrils.jpg", render_ai_050),
    # Suite 6
    ("AI_051_Dyson_Swarm_Compute_Shell.jpg", render_ai_051),
    ("AI_052_Black_Hole_Accretion_Engine.jpg", render_ai_052),
    ("AI_053_Stellar_Plasma_Engine.jpg", render_ai_053),
    ("AI_054_Pulsar_Magnetosphere_Beacon.jpg", render_ai_054),
    ("AI_055_Orbital_AI_Megaring.jpg", render_ai_055),
    ("AI_056_Gravitational_Warp_Horizon.jpg", render_ai_056),
    ("AI_057_Dark_Matter_Filament_Web.jpg", render_ai_057),
    ("AI_058_Laniakea_Watershed_Streamlines.jpg", render_ai_058),
    ("AI_059_Interstellar_Laser_Bridge.jpg", render_ai_059),
    ("AI_060_Cosmic_String_Curvature.jpg", render_ai_060),
    # Suite 7
    ("AI_061_Ferrofluid_Magnetic_Crown.jpg", render_ai_061),
    ("AI_062_Liquid_Titanium_Twist.jpg", render_ai_062),
    ("AI_063_Frosted_Glass_Prism_Caustics.jpg", render_ai_063),
    ("AI_064_Fiber_Optic_Bundle_Starburst.jpg", render_ai_064),
    ("AI_065_Obsidian_Mirror_Ripple.jpg", render_ai_065),
    ("AI_066_Mercury_Vortex_Core.jpg", render_ai_066),
    ("AI_067_Synthetic_Sapphire_Prism.jpg", render_ai_067),
    ("AI_068_Glass_Neuromorphic_Substrate.jpg", render_ai_068),
    ("AI_069_Bismuth_Hopper_Crystal.jpg", render_ai_069),
    ("AI_070_Thin_Film_Fluid_Dynamic.jpg", render_ai_070),
    # Suite 8
    ("AI_071_Ionosphere_Laser_Curtain.jpg", render_ai_071),
    ("AI_072_Magnetosphere_Bow_Shock.jpg", render_ai_072),
    ("AI_073_Cyber_Aurora_Australis.jpg", render_ai_073),
    ("AI_074_Volumetric_Light_Pillars.jpg", render_ai_074),
    ("AI_075_Neon_Plasma_Nebula.jpg", render_ai_075),
    ("AI_076_Orbital_Data_Canopy.jpg", render_ai_076),
    ("AI_077_Celestial_Borealis_Spiral.jpg", render_ai_077),
    ("AI_078_Mesospheric_Sprite_Discharge.jpg", render_ai_078),
    ("AI_079_High_Frequency_Ion_Flux.jpg", render_ai_079),
    ("AI_080_Digital_Twilight_Horizon.jpg", render_ai_080),
    # Suite 9
    ("AI_081_Brutalist_Silicon_Monolith.jpg", render_ai_081),
    ("AI_082_Gold_Trace_Obsidian_Marble.jpg", render_ai_082),
    ("AI_083_Tesseract_Hypercube_Portal.jpg", render_ai_083),
    ("AI_084_Geometric_Data_Cathedral.jpg", render_ai_084),
    ("AI_085_Mainframe_Server_Canyon.jpg", render_ai_085),
    ("AI_086_Algorithmic_Glass_Pyramid.jpg", render_ai_086),
    ("AI_087_Cybernetic_Infinity_Portal.jpg", render_ai_087),
    ("AI_088_Quantum_Cavern_Vault.jpg", render_ai_088),
    ("AI_089_Monolithic_Light_Obelisk.jpg", render_ai_089),
    ("AI_090_Fractal_Octahedron_Sanctuary.jpg", render_ai_090),
    # Suite 10
    ("AI_091_Fourier_Spectral_Waterfall.jpg", render_ai_091),
    ("AI_092_Chladni_Resonant_Plate.jpg", render_ai_092),
    ("AI_093_Neural_Voice_Synthesizer.jpg", render_ai_093),
    ("AI_094_Lissajous_Laser_Harmonics.jpg", render_ai_094),
    ("AI_095_Sonic_Ribbon_Horizon.jpg", render_ai_095),
    ("AI_096_Binaural_Wave_Interference.jpg", render_ai_096),
    ("AI_097_Supersonic_Shock_Gradient.jpg", render_ai_097),
    ("AI_098_Chirped_Frequency_Pulse.jpg", render_ai_098),
    ("AI_099_Acoustic_Levitation_Grid.jpg", render_ai_099),
    ("AI_100_Sonic_Singularity_Dawn.jpg", render_ai_100),
]


def main():
    BUILD_SLIDESHOW.mkdir(parents=True, exist_ok=True)
    USER_SLIDESHOW.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("DevOS AI-Era Ultra-Premium Wallpaper Generator")
    print(f"Generating 100 wallpapers ({W}x{H} QHD, Quality 92 Progressive)")
    print(f"Target 1: {BUILD_SLIDESHOW}")
    print(f"Target 2: {USER_SLIDESHOW}")
    print("=" * 70)

    start_total = time.time()
    for idx, (fname, func) in enumerate(RENDERERS, 1):
        t0 = time.time()
        img = func()
        
        # Save to build slideshow directory
        target_build = BUILD_SLIDESHOW / fname
        img.save(target_build, "JPEG", quality=92, progressive=True, optimize=True)

        # Save to user live wallpapers directory
        target_user = USER_SLIDESHOW / fname
        img.save(target_user, "JPEG", quality=92, progressive=True, optimize=True)

        dur = time.time() - t0
        print(f"[{idx:03d}/100] Rendered & Deployed: {fname:<42} ({dur:.2f}s)")

    total_time = time.time() - start_total
    build_count = len(list(BUILD_SLIDESHOW.glob("*.*")))
    user_count = len(list(USER_SLIDESHOW.glob("*.*")))
    print("=" * 70)
    print(f"Successfully generated all 100 AI-era wallpapers in {total_time:.2f}s!")
    print(f"Total wallpapers in build slideshow: {build_count}")
    print(f"Total wallpapers in user slideshow:  {user_count}")
    print("=" * 70)


if __name__ == "__main__":
    main()
