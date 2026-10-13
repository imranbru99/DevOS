#!/usr/bin/env python3
"""DevOS premium wallpaper generator.

Deterministic (fixed seeds) procedural renderer using only numpy + Pillow.
Every design is rendered internally at 3840x2160 (a few soft, smooth designs
are rendered at 1920x1080 and upscaled with LANCZOS), tone-mapped, vignetted,
film-grain dithered and written as KDE Plasma wallpaper packages:

    build/includes.chroot/usr/share/wallpapers/DevOS-<CamelName>/
        metadata.json
        contents/images/2560x1440.jpg
        contents/screenshot.jpg            (400x225)

plus a review-only contact sheet at tools/wallpapers/preview.jpg.

Usage:
    python tools/wallpapers/make_wallpapers.py              # all designs
    python tools/wallpapers/make_wallpapers.py --only AuroraVeil,NebulaDrift
    python tools/wallpapers/make_wallpapers.py --quality 84
"""

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "build" / "includes.chroot" / "usr" / "share" / "wallpapers"
PREVIEW = Path(__file__).resolve().parent / "preview.jpg"

RENDER_W, RENDER_H = 3840, 2160
OUT_W, OUT_H = 2560, 1440
THUMB_W, THUMB_H = 400, 225
F32 = np.float32


# --------------------------------------------------------------------------
# colour helpers
# --------------------------------------------------------------------------
def hexc(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)], F32)


C = {k: hexc(v) for k, v in dict(
    bg0="05070d", bg1="0b1020", navy="0f1a3a", deep="070b18", indigo="1e1b4b",
    cyan="22d3ee", sky="38bdf8", violet="818cf8", magenta="a855f7",
    pink="e879f9", teal="2dd4bf", ice="e0f2fe", white="ffffff", blue="3b82f6",
    royal="4f46e5", plum="6d28d9",
).items()}


def grad(t, stops):
    """Map scalar array t -> (..., 3) colour through [(pos, rgb), ...]."""
    t = np.asarray(t, F32)
    pos = [p for p, _ in stops]
    out = np.empty(t.shape + (3,), F32)
    for ch in range(3):
        out[..., ch] = np.interp(t, pos, [c[ch] for _, c in stops])
    return out


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def add(img, field, color, gain=1.0):
    img += np.asarray(field, F32)[..., None] * (np.asarray(color, F32) * F32(gain))


# --------------------------------------------------------------------------
# canvas / image ops
# --------------------------------------------------------------------------
class Canvas:
    def __init__(self, W=RENDER_W, H=RENDER_H):
        self.W, self.H = W, H
        self.A = W / H
        self.px = 1.0 / H
        self.x = ((np.arange(W, dtype=F32) + 0.5) / H)[None, :]
        self.y = ((np.arange(H, dtype=F32) + 0.5) / H)[:, None]

    def zeros(self):
        return np.zeros((self.H, self.W, 3), F32)

    def vgrad(self, top, bottom, mid=None):
        t = self.y[:, 0]
        if mid is None:
            col = grad(t, [(0, top), (1, bottom)])
        else:
            col = grad(t, [(0, top), (mid[0], mid[1]), (1, bottom)])
        return np.ascontiguousarray(np.broadcast_to(col[:, None, :], (self.H, self.W, 3))).astype(F32)


def resize2(a, w, h, resample=Image.BICUBIC):
    return np.asarray(Image.fromarray(np.ascontiguousarray(a, dtype=F32)).resize((w, h), resample), F32)


def resize_any(a, w, h, resample=Image.BICUBIC):
    if a.ndim == 2:
        return resize2(a, w, h, resample)
    return np.stack([resize2(a[..., c], w, h, resample) for c in range(a.shape[2])], -1)


def _box(a, r, axis):
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    p = np.pad(a, pad, mode="edge")
    c = np.cumsum(p, axis=axis, dtype=np.float64)
    n = a.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return ((hi - lo) / (2 * r + 1)).astype(F32)


def blur(a, sigma):
    """Approximate gaussian blur (3x box) with automatic downsampling."""
    if sigma < 0.5:
        return a
    H, W = a.shape[:2]
    f = max(1, int(sigma / 3.0))
    small = resize_any(a, max(2, W // f), max(2, H // f), Image.BOX) if f > 1 else a
    s = sigma / f
    w_ideal = math.sqrt(12.0 * s * s / 3.0 + 1.0)
    r = max(1, int((w_ideal - 1.0) / 2.0 + 0.5))
    for _ in range(3):
        small = _box(_box(small, r, 0), r, 1)
    if f > 1:
        small = resize_any(small, W, H, Image.BICUBIC)
    return small


def bloom(img, cv, sigma, strength, threshold=0.0):
    src = np.maximum(img - threshold, 0) if threshold > 0 else img
    return img + blur(src, sigma * cv.H) * F32(strength)


def noise2(rng, W, H, cells, cells_y=None):
    """Smooth value noise (bicubic-upsampled gaussian grid), ~unit std."""
    cy = cells_y if cells_y else max(1, int(round(cells * H / W)))
    g = rng.standard_normal((cy + 4, cells + 4)).astype(F32)
    fx, fy = W / cells, H / cy
    big = resize2(g, int(round((cells + 4) * fx)), int(round((cy + 4) * fy)))
    ox, oy = int(round(2 * fx)), int(round(2 * fy))
    out = big[oy:oy + H, ox:ox + W]
    return out / F32(0.62)


def fbm(rng, W, H, cells, octaves=5, gain=0.5, lac=2.0):
    total = np.zeros((H, W), F32)
    amp, norm, c = 1.0, 0.0, float(cells)
    for _ in range(octaves):
        total += noise2(rng, W, H, max(1, int(round(c)))) * F32(amp)
        norm += amp * amp
        amp *= gain
        c *= lac
    return total / F32(math.sqrt(norm))


def noise1(rng, n, cells):
    g = rng.standard_normal(cells + 4).astype(F32)
    f = n / cells
    big = resize2(g[None, :], int(round((cells + 4) * f)), 1)[0]
    o = int(round(2 * f))
    return big[o:o + n] / F32(0.62)


def fbm1(rng, n, cells, octaves=4, gain=0.5):
    total = np.zeros(n, F32)
    amp, norm, c = 1.0, 0.0, cells
    for _ in range(octaves):
        total += noise1(rng, n, int(c)) * F32(amp)
        norm += amp * amp
        amp *= gain
        c *= 2
    return total / F32(math.sqrt(norm))


def sample(f, px, py):
    """Bilinear sample of 2-D field f at pixel coordinates (px, py)."""
    h, w = f.shape
    px = np.clip(px, 0, w - 1.001)
    py = np.clip(py, 0, h - 1.001)
    x0 = px.astype(np.int32)
    y0 = py.astype(np.int32)
    fx = (px - x0).astype(F32)
    fy = (py - y0).astype(F32)
    a = f[y0, x0]
    b = f[y0, x0 + 1]
    c = f[y0 + 1, x0]
    d = f[y0 + 1, x0 + 1]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def splat(H, W, xs, ys, vals):
    """Bilinear point splatting. vals: (n,) or (n,3). Returns (H,W,3)."""
    vals = np.asarray(vals, F32)
    if vals.ndim == 1:
        vals = np.repeat(vals[:, None], 3, 1)
    x0 = np.floor(xs).astype(np.int64)
    y0 = np.floor(ys).astype(np.int64)
    fx = (xs - x0).astype(F32)
    fy = (ys - y0).astype(F32)
    out = np.zeros((3, H * W), np.float64)
    for dx, dy, w in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)),
                      (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
        xx, yy = x0 + dx, y0 + dy
        ok = (xx >= 0) & (xx < W) & (yy >= 0) & (yy < H)
        idx = (yy[ok] * W + xx[ok])
        for ch in range(3):
            out[ch] += np.bincount(idx, weights=(w[ok] * vals[ok, ch]), minlength=H * W)
    return np.moveaxis(out.reshape(3, H, W), 0, -1).astype(F32)


def calm(cv, img, strength=0.6, cx=0.42, cy=0.40, rx=0.62, ry=0.38):
    """Darken the centre-left/top-left area where desktop icons live."""
    m = 1.0 - strength * np.exp(-(((cv.x - cx) / rx) ** 2 + ((cv.y - cy) / ry) ** 2))
    img *= m[..., None].astype(F32)
    return img


def stars(cv, img, rng, n, bright=1.0, mask=None, big=6):
    xs = rng.uniform(0, cv.W, n)
    ys = rng.uniform(0, cv.H, n)
    b = np.clip(0.05 + 0.10 * rng.pareto(2.6, n), 0, 1.6) * bright
    if mask is not None:
        b = b * mask(xs / cv.H, ys / cv.H)
    tint = rng.uniform(0, 1, n)
    cols = grad(tint, [(0, C["ice"]), (0.6, C["white"]), (0.8, C["violet"] * 0.6 + 0.4), (1, C["sky"] * 0.6 + 0.4)])
    s = splat(cv.H, cv.W, xs, ys, cols * b[:, None])
    s = blur(s, 0.9 * cv.H / 2160) * 8.0
    img += s
    if big:
        idx = np.argsort(-b)[:big]
        for i in idx:
            d2 = ((cv.x - xs[i] / cv.H) ** 2 + (cv.y - ys[i] / cv.H) ** 2)
            add(img, np.exp(-d2 / (0.004 ** 2)) * 0.25 * b[i] + np.exp(-np.sqrt(d2) / 0.012) * 0.05 * b[i], cols[i])
    return img


def line_glow(img, d, color, core_w, glow_w, core=1.0, glow=0.3, white=0.0, fade=1.0):
    c = np.exp(-(d / core_w) ** 2)
    v = (c * core + np.exp(-d / glow_w) * glow) * fade
    add(img, v, color)
    if white > 0:
        img += (c * c * white * fade)[..., None]


# --------------------------------------------------------------------------
# finishing
# --------------------------------------------------------------------------
def finalize(img, rng, vignette=0.35, exposure=1.0, shoulder=0.72):
    H, W = img.shape[:2]
    cv = Canvas(W, H)
    img = img * F32(exposure)
    r = np.sqrt(((cv.x - cv.A / 2) / (cv.A / 2)) ** 2 * 0.75 + ((cv.y - 0.5) / 0.5) ** 2 * 0.75)
    img *= (1.0 - vignette * smoothstep(0.35, 1.25, r))[..., None]
    img = np.maximum(img, 0)
    k = shoulder
    img = np.where(img > k, k + (1 - k) * (1 - np.exp(-(img - k) / (1 - k))), img).astype(F32)
    out = resize_any(img, OUT_W, OUT_H, Image.LANCZOS)
    # triangular film-grain dither, +-1.5/255
    dith = (rng.uniform(-0.75, 0.75, (OUT_H, OUT_W, 1)) + rng.uniform(-0.75, 0.75, (OUT_H, OUT_W, 1))).astype(F32)
    out = out * 255.0 + dith
    return np.clip(np.round(out), 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------
# designs
# --------------------------------------------------------------------------
def silk(cv, img, *, origin, angle, center, width, wmod, twist, n, colors,
         srange, ramp=0.3, core=0.5, core_w=0.0010, glow=0.035, glow_w=0.005,
         fill=0.09, edge=1.8, white=0.15, gain=1.0):
    ox, oy = origin
    a = math.radians(angle)
    ca, sa = math.cos(a), math.sin(a)
    X = cv.x - ox
    Y = cv.y - oy
    s = X * ca + Y * sa
    t = -X * sa + Y * ca
    c = np.zeros_like(s)
    dc = np.zeros_like(s)
    for amp, fr, ph in center:
        arg = fr * s + ph
        c += amp * np.sin(arg)
        dc += amp * fr * np.cos(arg)
    wa, wf, wp = wmod
    hw = width * (1 + wa * np.sin(wf * s + wp))
    dhw = width * wa * wf * np.cos(wf * s + wp)
    tf, tp = twist
    tw = np.cos(tf * s + tp)
    dtw = -tf * np.sin(tf * s + tp)
    g = hw * tw
    dg = dhw * tw + hw * dtw
    s0, s1 = srange
    fade = (smoothstep(s0, s0 + ramp, s) * smoothstep(s1, s1 - ramp, s)).astype(F32) * F32(gain)
    rel = t - c
    ag = np.abs(g) + 1e-5
    inside = np.clip((ag - np.abs(rel)) / cv.px * 0.5 + 0.5, 0, 1)
    dens = np.clip(width * 0.45 / ag, 0, 2.5)
    o = np.clip(rel / np.where(np.abs(g) < 1e-5, 1e-5, g), -1, 1)
    stops = [(i / (len(colors) - 1), col) for i, col in enumerate(colors)]
    fcol = grad((o + 1) * 0.5, stops)
    fv = (fill * inside * fade * (0.30 + 0.70 * dens / 2.5) * (0.75 + 0.25 * (1 - o * o)))
    img += fv[..., None] * fcol
    del fcol, fv, o, inside
    for i in range(n):
        oi = -1.0 + 2.0 * i / (n - 1)
        yi = c + oi * g
        dy = dc + oi * dg
        d = np.abs(t - yi) / np.sqrt(1 + dy * dy)
        col = grad(np.array((oi + 1) * 0.5), stops)
        k = edge if i in (0, n - 1) else (0.55 + 0.45 * math.sin(i * 2.399) ** 2)
        line_glow(img, d, col, core_w, glow_w, core=core * k, glow=glow * k, white=white * k, fade=fade)
    return img


def d_silk_current(rng):
    cv = Canvas()
    img = cv.vgrad(C["bg0"], C["bg1"])
    add(img, np.exp(-(((cv.x - 1.45) / 0.55) ** 2 + ((cv.y - 0.15) / 0.45) ** 2)), C["navy"], 0.6)
    silk(cv, img, origin=(1.15, 0.72), angle=-26, center=[(0.10, 2.2, 0.3), (0.035, 4.7, 1.1)],
         width=0.085, wmod=(0.35, 1.7, 0.4), twist=(3.1, 0.9), n=22,
         colors=[C["sky"], C["cyan"], C["violet"]], srange=(-0.95, 1.2))
    silk(cv, img, origin=(1.28, 0.60), angle=-33, center=[(0.12, 1.8, 2.0), (0.03, 5.3, 0.2)],
         width=0.06, wmod=(0.3, 2.3, 1.4), twist=(2.4, 2.1), n=16,
         colors=[C["violet"], C["magenta"]], srange=(-0.8, 1.1), fill=0.09, gain=1.0)
    silk(cv, img, origin=(1.05, 0.92), angle=-15, center=[(0.06, 2.6, 1.2), (0.02, 6.1, 0.4)],
         width=0.022, wmod=(0.2, 3.0, 0.0), twist=(4.0, 0.3), n=6,
         colors=[C["cyan"], C["ice"]], srange=(-0.7, 1.0), fill=0.05, gain=0.9)
    img = bloom(img, cv, 0.012, 0.35)
    img = bloom(img, cv, 0.06, 0.25)
    return calm(cv, img, 0.55)


def d_velvet_silk(rng):
    cv = Canvas()
    img = cv.vgrad(hexc("07050f"), hexc("0d0a1f"))
    add(img, np.exp(-(((cv.x - 1.5) / 0.5) ** 2 + ((cv.y - 0.85) / 0.5) ** 2)), C["indigo"], 0.8)
    silk(cv, img, origin=(1.35, 0.55), angle=58, center=[(0.09, 2.0, 0.8), (0.03, 5.0, 2.0)],
         width=0.11, wmod=(0.3, 1.4, 1.0), twist=(2.6, 0.2), n=26,
         colors=[C["magenta"], C["pink"], C["violet"]], srange=(-0.65, 0.75), fill=0.11, core=0.4)
    silk(cv, img, origin=(1.42, 0.62), angle=70, center=[(0.07, 2.7, 2.5), (0.02, 6.3, 0.0)],
         width=0.05, wmod=(0.3, 2.0, 0.0), twist=(3.3, 1.7), n=12,
         colors=[C["violet"], C["royal"] * 0.5 + C["violet"] * 0.5], srange=(-0.6, 0.6), fill=0.07, gain=0.8)
    img = bloom(img, cv, 0.012, 0.35)
    img = bloom(img, cv, 0.07, 0.3)
    return calm(cv, img, 0.5)


def d_glacier_silk(rng):
    cv = Canvas()
    img = cv.vgrad(hexc("04070d"), hexc("081426"))
    add(img, np.exp(-(((cv.x - 1.2) / 0.8) ** 2 + ((cv.y - 0.95) / 0.3) ** 2)), hexc("0c2a40"), 0.45)
    silk(cv, img, origin=(1.05, 0.78), angle=-9, center=[(0.07, 2.4, 0.5), (0.025, 5.5, 2.2), (0.01, 11, 0.3)],
         width=0.10, wmod=(0.45, 1.3, 2.2), twist=(1.9, 1.3), n=44,
         colors=[C["cyan"], C["sky"], C["ice"], C["sky"]], srange=(-0.75, 0.95),
         core=0.32, core_w=0.0008, glow=0.015, fill=0.06, edge=2.2, white=0.12)
    img = bloom(img, cv, 0.01, 0.4)
    img = bloom(img, cv, 0.08, 0.25)
    return calm(cv, img, 0.6)


def d_aurora_veil(rng):
    cv = Canvas()
    W, H = cv.W, cv.H
    img = cv.vgrad(hexc("03050b"), hexc("060b16"), mid=(0.62, hexc("05080f")))
    stars(cv, img, rng, 3200, 0.9, mask=lambda x, y: np.clip(1.1 - y / 0.72, 0, 1))
    xs = cv.x[0]
    for (xc, xw, y0, a1, f1, p1, h, gain, cells) in [
        (1.25, 0.55, 0.50, 0.08, 2.4, 0.4, 0.22, 1.0, 150),
        (1.50, 0.35, 0.36, 0.04, 3.5, 1.2, 0.16, 0.45, 190),
    ]:
        yb = (y0 + a1 * np.sin(f1 * xs + p1) + 0.03 * np.sin(2.7 * f1 * xs + 1.7 * p1) + 0.010 * np.sin(7.3 * f1 * xs))[None, :]
        rn = noise2(rng, W, H, cells, 3) * 0.7 + noise2(rng, W, H, cells * 2, 4) * 0.3
        rays = 0.30 + 0.70 * np.clip(0.5 + 0.5 * rn, 0, 1) ** 2
        env = (np.exp(-((xs - xc) / xw) ** 2) * gain)[None, :]
        above = yb - cv.y
        up = np.maximum(above, 0)
        I = np.where(above > 0, np.exp(-up / h) * (1 + 1.4 * np.exp(-up / 0.012)),
                     2.4 * np.exp(-(above / 0.005) ** 2) + 0.35 * np.exp(above / 0.045))
        I = I * rays * env
        tcol = np.clip(up / (h * 1.5), 0, 1)
        col = grad(tcol, [(0, C["teal"] * 0.5 + C["cyan"] * 0.5), (0.3, C["sky"]), (0.65, C["violet"]), (1, C["magenta"])])
        img += (I * 0.50)[..., None] * col
        del rn, rays, I, col
    img = bloom(img, cv, 0.02, 0.3)
    # distant mountains + lake reflection
    yl = 0.86
    prof = fbm1(rng, W, 5, 5, 0.5)
    ridge = (yl - 0.03 - 0.085 * (0.2 + 0.8 / (1 + np.exp(-1.6 * prof)))
             * (0.5 + 0.5 * np.exp(-((xs - 0.5) / 0.5) ** 2) + 0.6 * np.exp(-((xs - 1.7) / 0.25) ** 2)))[None, :]
    m = np.clip((cv.y - ridge) / cv.px + 0.5, 0, 1)
    img = img * (1 - m[..., None]) + hexc("04070d") * m[..., None]
    add(img, np.exp(-np.abs(cv.y - ridge) / 0.0025) * (1 - m) * np.exp(-((cv.x - 1.25) / 0.6) ** 2), C["cyan"], 0.10)
    r0 = int(yl * H)
    src = np.clip(2 * r0 - np.arange(r0, H), 0, H - 1)
    refl = blur(img[src], 3.0) * 0.5
    depth = np.linspace(1, 0.55, H - r0, dtype=F32)[:, None, None]
    img[r0:] = hexc("03050a") + refl * depth
    img[r0:r0 + 2] += C["cyan"] * 0.03
    img = bloom(img, cv, 0.08, 0.2)
    return calm(cv, img, 0.35)


def rrect_sdf(cv, cx, cy, w, h, r, ang):
    a = math.radians(ang)
    X = cv.x - cx
    Y = cv.y - cy
    u = X * math.cos(a) + Y * math.sin(a)
    v = -X * math.sin(a) + Y * math.cos(a)
    qx = np.abs(u) - w / 2 + r
    qy = np.abs(v) - h / 2 + r
    sdf = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r
    return sdf, u, v


def d_glass_horizon(rng):
    cv = Canvas()
    img = cv.vgrad(C["bg0"], C["bg1"])
    for cx, cy, rx, ry, col, g in [(1.50, 0.30, 0.35, 0.30, C["cyan"], 0.45), (1.12, 0.80, 0.40, 0.25, C["magenta"], 0.33),
                                   (1.65, 0.85, 0.30, 0.30, C["violet"], 0.45), (1.30, 0.55, 0.25, 0.25, C["royal"], 0.4)]:
        add(img, np.exp(-(((cv.x - cx) / rx) ** 2 + ((cv.y - cy) / ry) ** 2)), col, g)
    r = np.hypot(cv.x - 1.36, (cv.y - 0.54))
    line_glow(img, np.abs(r - 0.27), C["sky"], 0.0018, 0.012, core=0.9, glow=0.25, white=0.3)
    line_glow(img, np.abs(r - 0.33), C["violet"], 0.0012, 0.01, core=0.5, glow=0.15)
    img = bloom(img, cv, 0.01, 0.3)
    panels = [(1.20, 0.40, 0.46, 0.30, 0.035, -7), (1.52, 0.68, 0.36, 0.40, 0.045, 5), (1.02, 0.75, 0.30, 0.17, 0.03, -3)]
    for cx, cy, w, h, rr, ang in panels:
        sh, _, _ = rrect_sdf(cv, cx + 0.012, cy + 0.03, w, h, rr, ang)
        img *= (1 - 0.5 * smoothstep(0.05, -0.015, sh))[..., None]
        frosted = blur(img, 0.03 * cv.H)
        sdf, u, v = rrect_sdf(cv, cx, cy, w, h, rr, ang)
        m = np.clip(0.5 - sdf / cv.px, 0, 1)[..., None]
        top = np.clip(0.5 - v / h, 0, 1)
        glass = frosted * 0.9 + hexc("0b1424") * 0.6 + (0.045 * top)[..., None]
        img = img * (1 - m) + glass * m
        dirw = 0.25 + 0.75 * np.clip(-(u / (w / 2)) * 0.45 - (v / (h / 2)) * 0.55, 0, 1)
        rim = np.exp(-(sdf / (1.4 * cv.px)) ** 2)
        img += (rim * dirw * 0.38)[..., None]
        add(img, rim * (1 - dirw) * 0.5, C["violet"], 0.5)
        inner = np.exp(np.minimum(sdf, 0) / 0.008) * m[..., 0] * 0.035
        img += inner[..., None]
    img = bloom(img, cv, 0.05, 0.15)
    return calm(cv, img, 0.55)


def d_chroma_mesh(rng):
    cv = Canvas(1920, 1080)
    wx = fbm(rng, cv.W, cv.H, 2, 3) * 0.16
    wy = fbm(rng, cv.W, cv.H, 2, 3) * 0.16
    X = cv.x + wx
    Y = cv.y + wy
    img = cv.vgrad(C["bg0"], hexc("090b1a"))
    blobs = [(1.55, 0.22, 0.34, C["royal"], 0.55), (1.22, 0.78, 0.30, C["magenta"], 0.60),
             (1.75, 0.78, 0.26, C["cyan"], 0.45), (0.92, 1.02, 0.26, C["violet"], 0.45),
             (1.42, 0.50, 0.18, C["pink"], 0.22), (1.90, 0.40, 0.22, C["sky"], 0.35),
             (0.55, 0.05, 0.40, C["navy"], 0.6)]
    for cx, cy, r, col, g in blobs:
        add(img, np.exp(-((X - cx) ** 2 + (Y - cy) ** 2) / r ** 2), col, g * 1.25)
    # layered silky folds sweeping across the lower right
    for k, (a, b, c, ph, shade) in enumerate([(0.55, 0.42, 0.06, 0.3, 0.80), (0.72, 0.35, 0.05, 1.9, 0.72), (0.88, 0.28, 0.04, 3.1, 0.66)]):
        yk = a - b * (X - 1.0) + c * np.sin(3.1 * X + ph)
        d = Y - yk
        m = smoothstep(-0.003, 0.003, d) * smoothstep(0.35, 0.75, X)
        shadow = np.exp(-np.maximum(d, 0) / 0.06) * m * 0.35
        img *= (1 - (1 - shade) * m - shadow)[..., None]
        add(img, np.exp(-(d / 0.004) ** 2) * smoothstep(0.45, 1.2, X), C["ice"] * 0.6 + C["violet"] * 0.4, 0.10)
        add(img, np.exp(-np.maximum(d, 0) / 0.015) * m, C["violet"], 0.05)
    img = blur(img, 1.0)
    return calm(cv, img, 0.4)


def d_orbit_halo(rng):
    cv = Canvas()
    img = cv.vgrad(C["bg0"], hexc("0a0e1d"))
    cx, cy = 1.30, 0.50
    R0 = 0.10
    rs = np.hypot(cv.x - cx, cv.y - cy)
    add(img, np.exp(-rs / 0.22), C["royal"], 0.25)
    add(img, np.exp(-rs / 0.5), C["navy"], 0.5)
    a = math.radians(-16)
    X = cv.x - cx
    Y = cv.y - cy
    u = X * math.cos(a) + Y * math.sin(a)
    v = -X * math.sin(a) + Y * math.cos(a)
    e = 0.34
    rho = np.sqrt(u * u + (v / e) ** 2)
    gmag = np.sqrt(u * u + v * v / e ** 4) / np.maximum(rho, 1e-4)
    theta = np.arctan2(v / e, u)
    behind = (v < 0) & (rs < R0 * 1.02)
    occl = np.where(behind, 0.0, 1.0).astype(F32)
    rings = [(0.17, C["cyan"], 1.0, 0.0, False), (0.215, C["sky"], 0.6, 1.0, True), (0.28, C["violet"], 0.9, 2.1, False),
             (0.36, C["magenta"], 0.55, 3.0, False), (0.45, C["sky"], 0.45, 4.2, True), (0.57, C["violet"], 0.35, 5.0, False),
             (0.72, C["cyan"], 0.25, 0.6, False)]
    for rr, col, g, th0, dotted in rings:
        d = np.abs(rho - rr) / gmag
        sweep = 0.18 + 0.82 * (0.5 + 0.5 * np.cos(theta - th0)) ** 2.5
        f = sweep * occl * g
        if dotted:
            f = f * (0.5 + 0.5 * np.cos(theta * 90)) ** 6
        line_glow(img, d, col, 0.0011, 0.008, core=0.8, glow=0.12, white=0.2, fade=f)
        sx = cx + (rr * math.cos(th0)) * math.cos(a) - (rr * e * math.sin(th0)) * math.sin(a)
        sy = cy + (rr * math.cos(th0)) * math.sin(a) + (rr * e * math.sin(th0)) * math.cos(a)
        ds = np.hypot(cv.x - sx, cv.y - sy)
        add(img, (np.exp(-(ds / 0.004) ** 2) * 1.2 + np.exp(-ds / 0.02) * 0.15) * g, col * 0.5 + 0.5)
    # central sphere
    inside = np.clip((R0 - rs) / cv.px + 0.5, 0, 1)
    nx = (cv.x - cx) / R0
    ny = (cv.y - cy) / R0
    nz = np.sqrt(np.clip(1 - nx * nx - ny * ny, 0, 1))
    lam = np.clip(-0.55 * nx - 0.45 * ny + 0.7 * nz, 0, 1)
    sphere = grad(lam, [(0, hexc("04060c")), (0.6, hexc("101a3a")), (1, hexc("2a3a80"))])
    rimv = np.exp(-(R0 - np.minimum(rs, R0)) / 0.006) * np.clip(0.4 + 0.6 * (nx * 0.6 + ny * 0.8), 0, 1)
    sphere += rimv[..., None] * C["cyan"] * 0.9
    m = inside[..., None]
    img = img * (1 - m) + sphere * m
    # front part of inner rings over the sphere
    for rr, col, g, th0, dotted in rings[:2]:
        d = np.abs(rho - rr) / gmag
        sweep = 0.18 + 0.82 * (0.5 + 0.5 * np.cos(theta - th0)) ** 2.5
        line_glow(img, d, col, 0.0011, 0.008, core=0.8, glow=0.05, fade=sweep * g * (v > 0) * inside)
    img = bloom(img, cv, 0.012, 0.35)
    img = bloom(img, cv, 0.06, 0.2)
    return calm(cv, img, 0.5)


def gridline(q, fw, lw):
    d = np.abs(np.mod(q + 0.5, 1.0) - 0.5)
    fw = np.maximum(fw, 1e-6)
    cov = np.clip((lw * 0.5 - d) / fw + 0.5, 0, 1) * np.minimum(1.0, lw / fw)
    glow = np.exp(-d / (fw * 4 + lw)) * np.minimum(1.0, (lw / fw)) * 0.3
    return cov + glow


def d_neon_horizon(rng):
    cv = Canvas()
    yh = 0.60
    img = cv.vgrad(hexc("04050b"), hexc("0b0820"))
    add(img, np.exp(-((cv.y - yh) / 0.10) ** 2) * np.exp(-((cv.x - 1.3) / 0.7) ** 2), C["magenta"], 0.22)
    add(img, np.exp(-((cv.y - yh) / 0.035) ** 2), C["violet"], 0.12)
    stars(cv, img, rng, 1200, 0.5, mask=lambda x, y: np.clip(1 - y / 0.5, 0, 1), big=0)
    # sun
    scx, sr = 1.30, 0.21
    rs = np.hypot(cv.x - scx, cv.y - (yh - 0.02))
    disk = np.clip((sr - rs) / cv.px + 0.5, 0, 1) * (cv.y < yh)
    tt = np.clip((cv.y - (yh - 0.02 - sr)) / sr, 0, 1)
    scol = grad(tt, [(0, hexc("f0abfc")), (0.45, C["magenta"]), (1, C["royal"])])
    yy = (yh - 0.02) - cv.y
    gap_w = np.clip((0.11 - yy) / 0.11, 0, 1) * 0.55
    slits = np.clip((np.abs(np.mod(yy * 55, 1.0) - 0.5) * 2 - gap_w) / 0.08, 0, 1)
    slits = np.where(yy > 0.11, 1.0, slits)
    sunv = disk * slits * 0.55
    img += sunv[..., None] * scol
    add(img, np.exp(-np.maximum(rs - sr, 0) / 0.05) * (1 - disk) * (cv.y < yh), C["magenta"], 0.18)
    # mountains
    W = cv.W
    for (base, amp, cells, col, rimc, seedoff) in [(yh - 0.035, 0.07, 5, hexc("0a0a1e"), C["violet"], 0), (yh - 0.012, 0.04, 9, hexc("06061a"), C["cyan"], 1)]:
        prof = fbm1(rng, W, cells, 5, 0.5)
        ridge = (base - amp * (0.15 + 0.6 / (1 + np.exp(-1.6 * prof)) + 0.35 * np.abs(fbm1(rng, W, cells * 4, 3, 0.5))) *(0.4 + 0.6 * np.exp(-((cv.x[0] - 0.7) / 0.6) ** 2) + 0.5 * np.exp(-((cv.x[0] - 1.75) / 0.3) ** 2)))[None, :]
        m = np.clip((cv.y - ridge) / cv.px + 0.5, 0, 1) * (cv.y < yh + 0.002)
        img = img * (1 - m[..., None]) + col * m[..., None]
        add(img, np.exp(-np.abs(cv.y - ridge) / 0.0015) * (cv.y <= ridge + 0.002), rimc, 0.25)
    # ground grid
    r0 = int(math.ceil(yh * cv.H))
    yg = cv.y[r0:] - yh
    z = 0.32 / yg
    xg = cv.x - scx
    xw = xg * z * 2.0
    dz = 0.32 / yg ** 2 * cv.px
    fwx = np.abs(z * 2.0) * cv.px + np.abs(xg * 2.0) * dz
    zw = z * 1.3
    fwz = dz * 1.3
    gl = gridline(xw, fwx, 0.035) + gridline(zw, fwz, 0.035)
    fog = np.exp(-z / 25.0)
    near = smoothstep(1.0, 0.72, cv.y[r0:])
    hz = np.clip(yg / 0.004, 0, 1)
    gv = gl * fog * (0.12 + 0.88 * near) * hz
    gcol = grad(np.clip(np.abs(xg) / 0.9, 0, 1), [(0, C["magenta"]), (0.5, C["violet"]), (1, C["sky"])])
    ground = img[r0:]
    ground[:] = ground * 0.4 + hexc("05040e") * 0.6
    ground += (gv * 0.55)[..., None] * gcol
    refl = np.exp(-((cv.x - scx) / 0.12) ** 2) * np.exp(-yg / 0.06) * 0.12
    ground += refl[..., None] * C["magenta"]
    img = bloom(img, cv, 0.01, 0.4)
    img = bloom(img, cv, 0.06, 0.25)
    return calm(cv, img, 0.5)


def d_nebula_drift(rng):
    cv = Canvas()
    W, H = cv.W, cv.H
    # band along a diagonal on the right
    p0 = np.array([0.85, 1.15])
    p1 = np.array([1.95, -0.05])
    dvec = (p1 - p0) / np.linalg.norm(p1 - p0)
    wn = fbm(rng, W, H, 3, 4) * 0.12
    dist = (cv.x - p0[0]) * (-dvec[1]) + (cv.y - p0[1]) * dvec[0] + wn
    band = np.exp(-(dist / 0.24) ** 2)
    n1 = fbm(rng, W, H, 4, 6, 0.55)
    n2 = fbm(rng, W, H, 5, 6, 0.55)
    n3 = fbm(rng, W, H, 7, 5, 0.6)
    d1 = np.clip(n1 * 0.5 + 0.35, 0, 1.5) ** 2 * band
    d2 = np.clip(n2 * 0.5 + 0.25, 0, 1.5) ** 2 * band
    dust = 1.0 - 0.65 * smoothstep(-0.2, 1.4, n3)
    img = cv.vgrad(hexc("04050b"), hexc("080a18"))
    neb = cv.zeros()
    add(neb, d1, C["magenta"], 0.45)
    add(neb, d1 * np.exp(-(dist / 0.08) ** 2), C["pink"], 0.15)
    add(neb, d2, C["sky"], 0.32)
    add(neb, d2 * np.clip(n1, 0, 1), C["cyan"], 0.2)
    add(neb, band, C["royal"], 0.08)
    neb *= dust[..., None]
    img += neb
    del n1, n2, n3, d1, d2
    stars(cv, img, rng, 6000, 0.8, mask=lambda x, y: 0.6 + 0.8 * np.exp(-(((x - p0[0]) * (-dvec[1]) + (y - p0[1]) * dvec[0]) / 0.3) ** 2), big=7)
    img = bloom(img, cv, 0.03, 0.25)
    return calm(cv, img, 0.45)


def d_liquid_obsidian(rng):
    cv = Canvas(1920, 1080)
    x, y = cv.x, cv.y
    wx = fbm(rng, cv.W, cv.H, 2, 3) * 0.18
    wy = fbm(rng, cv.W, cv.H, 2, 3) * 0.18
    X = x + wx
    Y = y + wy
    h = (np.sin(3.2 * X + 2.2 * np.sin(2.1 * Y + 0.5)) * 0.55 + np.sin(5.3 * Y - 1.7 * X + 1.4 * np.sin(3.3 * X)) * 0.35
         + np.sin(9.1 * X + 6.7 * Y) * 0.06)
    gy, gx = np.gradient(h.astype(F32), cv.px)
    k = 0.22
    nx, ny = -gx * k, -gy * k
    inv = 1 / np.sqrt(nx * nx + ny * ny + 1)
    nx, ny, nz = nx * inv, ny * inv, inv
    rx, ry, rz = 2 * nz * nx, 2 * nz * ny, 2 * nz * nz - 1
    img = cv.zeros() + hexc("05070d")
    add(img, np.exp(-((rx - 0.55) / 0.10) ** 2) * np.exp(-((ry + 0.1) / 0.6) ** 2), C["cyan"], 0.75)
    add(img, np.exp(-((ry + 0.55) / 0.10) ** 2), C["violet"], 0.55)
    add(img, np.exp(-((rx + 0.6) / 0.14) ** 2) * np.exp(-((ry - 0.3) / 0.5) ** 2), C["magenta"], 0.40)
    add(img, (1 - rz) ** 3, C["navy"], 0.5)
    add(img, np.clip(rz, 0, 1) ** 8, hexc("101830"), 0.6)
    mask = 0.10 + 0.90 * smoothstep(0.45, 1.55, x + 0.4 * y)
    img *= mask[..., None]
    return calm(cv, img, 0.5)


def d_lumen_bokeh(rng):
    cv = Canvas()
    img = cv.vgrad(C["bg0"], hexc("0a0d1c"))
    add(img, np.exp(-(((cv.x - 1.35) / 0.6) ** 2 + ((cv.y - 0.6) / 0.4) ** 2)), C["indigo"], 0.6)
    pal = [C["cyan"], C["sky"], C["violet"], C["magenta"], C["pink"], C["ice"]]
    n = 170
    t = rng.uniform(0, 1, n)
    bx = 0.75 + 1.05 * t + rng.normal(0, 0.12, n)
    by = 1.05 - 0.85 * t + 0.12 * np.sin(t * 6) + rng.normal(0, 0.10, n)
    rad = 0.006 + 0.07 * rng.uniform(0, 1, n) ** 2.6
    order = np.argsort(-rad)
    for i in order:
        r = rad[i]
        x0, y0 = bx[i], by[i]
        c0 = max(0, int((x0 - r - 0.01) * cv.H)); c1 = min(cv.W, int((x0 + r + 0.01) * cv.H) + 1)
        r0 = max(0, int((y0 - r - 0.01) * cv.H)); r1 = min(cv.H, int((y0 + r + 0.01) * cv.H) + 1)
        if c1 <= c0 or r1 <= r0:
            continue
        d = np.hypot(cv.x[:, c0:c1] - x0, cv.y[r0:r1] - y0)
        defocus = min(r / 0.076, 1.0)
        soft = 0.02 * r + 0.30 * r * defocus ** 1.5 + 1.2 * cv.px
        disk = np.clip((r - d) / soft + 0.5, 0, 1)
        rim = np.exp(-((d - r * 0.93) / (0.05 * r + cv.px)) ** 2) * 0.35 * (1 - 0.8 * defocus)
        fall = 0.75 + 0.25 * (d / r) ** 2
        alpha = (0.11 + 0.20 * (1 - min(r / 0.076, 1))) * (0.6 + 0.4 * rng.uniform())
        col = pal[rng.integers(len(pal))]
        if col is C["ice"]:
            alpha *= 0.6
        img[r0:r1, c0:c1] += ((disk * fall + rim * disk) * alpha)[..., None] * col
    img = blur(img, 1.2)
    img = bloom(img, cv, 0.03, 0.25)
    return calm(cv, img, 0.55)


def seg_dist(cv, ax, ay, bx, by):
    px, py = cv.x - ax, cv.y - ay
    vx, vy = bx - ax, by - ay
    t = np.clip((px * vx + py * vy) / (vx * vx + vy * vy), 0, 1)
    return np.hypot(px - t * vx, py - t * vy), t


def d_prism_beam(rng):
    cv = Canvas()
    img = cv.vgrad(hexc("04050b"), hexc("090c1a"))
    add(img, np.exp(-(((cv.x - 1.45) / 0.45) ** 2 + ((cv.y - 0.7) / 0.4) ** 2)), C["indigo"], 0.35)
    S = np.array([0.98, -0.10])
    P = np.array([1.30, 0.40])
    base = math.atan2(P[1] - S[1], P[0] - S[0])
    # incoming white beam
    d, t = seg_dist(cv, S[0], S[1], P[0], P[1])
    line_glow(img, d, C["ice"], 0.0014, 0.008, core=0.7, glow=0.10, white=0.35)
    add(img, np.exp(-d / 0.03), C["sky"], 0.05)
    # dispersed fan (refracted towards the lower right)
    rx, ry = cv.x - P[0], cv.y - P[1]
    dist = np.hypot(rx, ry)
    ang = np.arctan2(ry, rx)
    a0, a1 = base - math.radians(36), base - math.radians(2)
    tt = (ang - a0) / (a1 - a0)
    win = smoothstep(-0.03, 0.08, tt) * smoothstep(1.03, 0.92, tt)
    bands = np.zeros_like(tt)
    nb = 9
    for k in range(nb):
        c = (k + 0.5) / nb
        bands += np.exp(-((tt - c) / (0.012 + 0.010 * k / nb)) ** 2) * (0.6 + 0.4 * math.sin(k * 1.7) ** 2)
    att = np.exp(-dist / 0.75) * (1 - np.exp(-dist / 0.015))
    I = (0.18 + 0.82 * bands) * win * att
    col = grad(np.clip(tt, 0, 1), [(0, C["pink"]), (0.22, C["magenta"]), (0.48, C["violet"]), (0.72, C["sky"]), (1, C["cyan"])])
    img += (I * 0.55)[..., None] * col
    img += (win * att * 0.06)[..., None] * col
    # glass plate the beam passes through
    pa = math.degrees(base) + 90
    sdf, u, v = rrect_sdf(cv, P[0], P[1], 0.055, 0.055, 0.004, pa + 45)
    m = np.clip(0.5 - sdf / cv.px, 0, 1)
    img = img * (1 - 0.3 * m[..., None]) + (m * (0.10 + 0.25 * np.clip(-u / 0.04, 0, 1)))[..., None] * (C["violet"] * 0.5 + C["sky"] * 0.5)
    rim = np.exp(-(sdf / (1.3 * cv.px)) ** 2)
    add(img, rim, C["ice"], 0.45)
    add(img, np.exp(-np.maximum(sdf, 0) / 0.01) * (1 - m), C["sky"], 0.12)
    dp = np.hypot(rx, ry)
    add(img, np.exp(-(dp / 0.006) ** 2) * 1.2 + np.exp(-dp / 0.03) * 0.25, C["ice"] * 0.6 + C["sky"] * 0.4)
    # floating dust in the beams
    n = 1400
    xs = rng.uniform(P[0] - 0.1, cv.A, n) * cv.H
    ys = rng.uniform(P[1] - 0.1, 1.0, n) * cv.H
    s = splat(cv.H, cv.W, xs, ys, rng.uniform(0.2, 1.0, n))
    s = blur(s, 1.2) * 6.0
    img += s * (I * 0.9 + 0.02)[..., None]
    img = bloom(img, cv, 0.015, 0.45)
    img = bloom(img, cv, 0.08, 0.3)
    return calm(cv, img, 0.45)


def d_contour_glow(rng):
    cv = Canvas()
    W, H = cv.W, cv.H
    rng.standard_normal(97)
    h = fbm(rng, W, H, 2, 4, 0.42) * 0.45
    h += 1.2 * np.exp(-(((cv.x - 1.42) / 0.36) ** 2 + ((cv.y - 0.62) / 0.24) ** 2))
    h += 0.5 * np.exp(-(((cv.x - 1.05) / 0.25) ** 2 + ((cv.y - 0.95) / 0.2) ** 2))
    N = 26.0
    gy, gx = np.gradient(h, cv.px)
    gm = np.hypot(gx, gy) * N * cv.px + 1e-6
    q = h * N
    d = np.abs(np.mod(q + 0.5, 1.0) - 0.5) / gm  # in px
    lines = np.clip(1.4 - d, 0, 1) * np.minimum(1.0, 0.6 / gm)
    major = (np.mod(np.floor(q + 0.5), 5) == 0)
    hn = np.clip((h + 0.2) / 1.45, 0, 1)
    img = cv.vgrad(C["bg0"], C["bg1"])
    add(img, np.exp(-(((cv.x - 1.35) / 0.5) ** 2 + ((cv.y - 0.55) / 0.4) ** 2)), C["navy"], 0.6)
    col = grad(hn, [(0, hexc("1e3a8a")), (0.4, C["sky"]), (0.7, C["violet"]), (1, C["magenta"])])
    reg = 0.2 + 0.8 * smoothstep(0.5, 1.3, cv.x + 0.3 * cv.y)
    v = 1.6 * lines * (0.38 + 0.62 * major) * reg * (0.45 + 0.55 * hn)
    img += v[..., None] * col
    img = bloom(img, cv, 0.006, 0.6)
    img = bloom(img, cv, 0.05, 0.25)
    return calm(cv, img, 0.5)


def d_lone_arc(rng):
    cv = Canvas()
    img = cv.vgrad(hexc("05070d"), hexc("0a0f1f"))
    cx, cy, R = 1.80, 1.50, 1.08
    r = np.hypot(cv.x - cx, cv.y - cy)
    th = np.arctan2(cv.y - cy, cv.x - cx)
    t = np.clip((th - (-math.pi)) / (math.pi * 0.62), 0, 1)
    col = grad(t, [(0, C["magenta"]), (0.45, C["violet"]), (0.75, C["sky"]), (1, C["cyan"])])
    fade = smoothstep(0.05, 0.45, t) * (0.6 + 0.4 * t)
    d = np.abs(r - R)
    v = (np.exp(-(d / 0.0013) ** 2) * 0.9 + np.exp(-d / 0.012) * 0.10 + np.exp(-d / 0.06) * 0.06) * fade
    img += v[..., None] * col
    img += (np.exp(-(d / 0.0008) ** 2) * 0.35 * fade)[..., None]
    inner = np.exp(-np.maximum(R - r, 0) / 0.14) * (r < R) * fade
    img += (inner * 0.10)[..., None] * col
    d2 = np.abs(r - R * 1.06)
    img += (np.exp(-(d2 / 0.0009) ** 2) * 0.18 * fade * smoothstep(0.3, 0.8, t))[..., None] * C["violet"]
    img = bloom(img, cv, 0.04, 0.2)
    return img


def caustic(u, v, t=0.7, iters=5, inten=0.005):
    TAU = 6.28318
    px = np.mod(u * TAU, TAU) - 250
    py = np.mod(v * TAU, TAU) - 250
    ix, iy = px.copy(), py.copy()
    c = np.ones_like(px)
    for n in range(iters):
        tt = t * (1 - 3.5 / (n + 1))
        nix = px + np.cos(tt - ix) + np.sin(tt + iy)
        niy = py + np.sin(tt - iy) + np.cos(tt + ix)
        ix, iy = nix, niy
        c += 1.0 / np.sqrt((px / (np.sin(ix + tt) / inten)) ** 2 + (py / (np.cos(iy + tt) / inten)) ** 2)
    c /= iters
    c = 1.17 - c ** 1.4
    return np.abs(c) ** 8


def d_abyss_caustics(rng):
    cv = Canvas(1920, 1080)
    yh = 0.30
    img = cv.vgrad(hexc("03070e"), hexc("051424"), mid=(0.45, hexc("061a2c")))
    add(img, np.exp(-(((cv.x - 1.3) / 0.6) ** 2 + ((cv.y - 0.45) / 0.3) ** 2)), hexc("0b3550"), 0.6)
    yg = np.maximum(cv.y - yh, 1e-3)
    z = 0.45 / yg
    u = (cv.x - 1.2) * z * 0.9
    v = z * 0.9
    ca = caustic(u, v)
    cb = caustic(u * 1.03 + 0.21, v * 1.03 + 0.13, t=1.9)
    fall = np.exp(-z / 4.0) * smoothstep(yh, yh + 0.12, cv.y) * smoothstep(1.02, 0.85, cv.y)
    pool = np.exp(-(((cv.x - 1.3) / 0.55) ** 2 + ((cv.y - 0.72) / 0.28) ** 2))
    cm = np.clip(ca * 0.75 + cb * 0.5, 0, 2.5)
    add(img, cm * fall * (0.25 + 0.75 * pool), C["cyan"], 0.75)
    add(img, cm * fall * pool, C["sky"], 0.30)
    # god rays from above-right
    ox, oy = 1.45, -0.45
    ang = np.arctan2(cv.y - oy, cv.x - ox)
    angn = (ang - 0.6) / 1.9
    rays = np.clip(0.5 + 0.5 * fbm1(rng, 4096, 28, 2, 0.5), 0, 1) ** 2
    ridx = np.clip(angn * 4095, 0, 4095).astype(np.int32)
    rr = rays[ridx]
    dist = np.hypot(cv.x - ox, cv.y - oy)
    rv = rr * np.exp(-((dist - 0.95) / 0.45) ** 2) * smoothstep(0.0, 0.25, cv.y) * np.exp(-((cv.x - 1.25) / 0.6) ** 2)
    add(img, blur(rv, 5.0), C["sky"], 0.12)
    img = blur(img, 1.0)
    # marine snow
    n = 900
    xs = rng.uniform(0, cv.W, n)
    ys = rng.uniform(0, cv.H, n)
    b = rng.uniform(0.02, 0.18, n) * np.clip((xs / cv.H - 0.4) / 0.8, 0, 1)
    s = splat(cv.H, cv.W, xs, ys, b)
    img += blur(s, 0.8) * 2.0 * C["ice"]
    img = bloom(img, cv, 0.02, 0.3)
    return calm(cv, img, 0.4)


def d_flux_streams(rng):
    cv = Canvas()
    W, H = cv.W, cv.H
    fw, fh = 480, 270
    ang = fbm(rng, fw, fh, 3, 3, 0.5) * 1.25 - 0.45
    n, steps, step = 6500, 620, 1.1
    sx = rng.uniform(0.25, 1.15, n) * W
    sy = rng.uniform(0.15, 1.05, n) * H
    keep = ((sx / H - 0.35) ** 2 / 0.5 + (sy / H - 0.35) ** 2 / 0.25) > 0.4
    sx, sy = sx[keep], sy[keep]
    n = len(sx)
    tcol = np.clip((sy / H) * 0.85 + (sx / H - 1.0) * 0.25 + rng.uniform(-0.15, 0.15, n), 0, 1)
    pcol = grad(tcol, [(0, C["cyan"]), (0.35, C["sky"]), (0.65, C["violet"]), (1, C["magenta"])])
    w0 = rng.uniform(0.3, 1.0, n) ** 2
    X = np.empty((steps, n), F32)
    Y = np.empty((steps, n), F32)
    x, y = sx.astype(F32), sy.astype(F32)
    for k in range(steps):
        X[k], Y[k] = x, y
        a = sample(ang, x * (fw - 1) / W, y * (fh - 1) / H)
        x = x + step * np.cos(a)
        y = y + step * np.sin(a)
    kk = np.arange(steps, dtype=F32)[:, None]
    life = np.sin(np.pi * (kk + 0.5) / steps) ** 1.5 * w0[None, :]
    vals = (life[..., None] * pcol[None, :, :]).reshape(-1, 3)
    acc = splat(H, W, X.reshape(-1), Y.reshape(-1), vals)
    del X, Y, vals
    acc = blur(acc, 0.7)
    img = cv.vgrad(C["bg0"], C["bg1"])
    img += (1 - np.exp(-acc * 0.9)) * 0.85
    img = bloom(img, cv, 0.008, 0.5)
    img = bloom(img, cv, 0.05, 0.3)
    return calm(cv, img, 0.45)


def d_crystal_facet(rng):
    cv = Canvas()
    W, H = cv.W, cv.H
    sp = 0.10
    nx, ny = int(cv.A / sp) + 3, int(1 / sp) + 3
    gx = (np.arange(nx) - 1) * sp
    gy = (np.arange(ny) - 1) * sp
    PX = gx[None, :] + rng.uniform(-0.38, 0.38, (ny, nx)) * sp + (np.arange(ny)[:, None] % 2) * sp * 0.5
    PY = gy[:, None] + rng.uniform(-0.38, 0.38, (ny, nx)) * sp
    hn = noise2(rng, nx, ny, 3)
    PZ = hn * 0.06 + rng.uniform(-0.02, 0.02, (ny, nx))
    L = np.array([0.55, -0.55, 0.63])
    L /= np.linalg.norm(L)
    im = Image.new("RGB", (W, H))
    dr = ImageDraw.Draw(im)
    edges_im = Image.new("L", (W, H))
    de = ImageDraw.Draw(edges_im)
    glow_im = Image.new("RGB", (W, H))
    dg = ImageDraw.Draw(glow_im)

    def shade(tri):
        p = np.array([[PX[j, i], PY[j, i], PZ[j, i]] for j, i in tri])
        nrm = np.cross(p[1] - p[0], p[2] - p[0])
        nrm /= np.linalg.norm(nrm) + 1e-9
        if nrm[2] < 0:
            nrm = -nrm
        lam = max(0.0, float(nrm @ L))
        spec = max(0.0, float(nrm @ np.array([0.2, -0.3, 0.93]))) ** 40
        cxp, cyp = p[:, 0].mean(), p[:, 1].mean()
        reg = 0.22 + 0.78 * float(smoothstep(0.35, 1.45, cxp + 0.35 * cyp))
        tcol = float(np.clip(cyp * 0.8 + (cxp - 0.8) * 0.3, 0, 1))
        accent = grad(np.array(tcol), [(0, C["sky"]), (0.5, C["violet"]), (1, C["magenta"])])
        base = hexc("070b18") + hexc("16204a") * lam * 0.9 + accent * (lam ** 6) * 0.35 + C["ice"] * spec * 0.25
        return np.clip(base * reg, 0, 1), reg, accent

    tris = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a, b, c_, d = (j, i), (j, i + 1), (j + 1, i), (j + 1, i + 1)
            if rng.uniform() < 0.5:
                tris += [(a, b, d), (a, d, c_)]
            else:
                tris += [(a, b, c_), (b, d, c_)]
    for tri in tris:
        col, reg, accent = shade(tri)
        pts = [(float(PX[j, i] * H), float(PY[j, i] * H)) for j, i in tri]
        dr.polygon(pts, fill=tuple(int(v * 255 + 0.5) for v in col))
        de.line(pts + [pts[0]], fill=int(40 * reg + 10), width=2)
        if rng.uniform() < 0.09 * reg and reg > 0.6:
            k = rng.integers(3)
            seg = [pts[k], pts[(k + 1) % 3]]
            dg.line(seg, fill=tuple(int(v * 255) for v in accent), width=3)
    img = np.asarray(im, F32) / 255.0
    e = np.asarray(edges_im, F32) / 255.0
    img += e[..., None] * (C["sky"] * 0.35 + 0.15)
    gl = np.asarray(glow_im, F32) / 255.0
    img += gl * 0.7 + blur(gl, 0.008 * H) * 1.2 + blur(gl, 0.03 * H) * 0.8
    add(img, np.exp(-(((cv.x - 1.45) / 0.5) ** 2 + ((cv.y - 0.3) / 0.4) ** 2)), C["royal"], 0.10)
    return calm(cv, img, 0.4)


def d_planet_rise(rng):
    cv = Canvas()
    img = cv.vgrad(hexc("03040a"), hexc("0a0f22"))
    cx, cy, R = 0.95, 2.35, 1.85
    stars(cv, img, rng, 3500, 0.75, mask=lambda x, y: np.clip((np.hypot(x - cx, y - cy) - R) / 0.15, 0, 1))
    r = np.hypot(cv.x - cx, cv.y - cy)
    th = np.arctan2(cv.y - cy, cv.x - cx)
    sun_th = math.atan2(-math.sqrt(R * R - 0.3 ** 2), 0.3)
    sx, sy = cx + R * math.cos(sun_th), cy + R * math.sin(sun_th)
    dth = th - sun_th
    w = np.exp(-(dth / 0.16) ** 2) * 1.0 + np.exp(-(dth / 0.45) ** 2) * 0.35 + 0.08
    hgt = r - R
    out = hgt > 0
    atm = np.where(out, np.exp(-hgt / 0.010) * 0.9 + np.exp(-hgt / 0.05) * 0.28 + np.exp(-hgt / 0.18) * 0.08, 0)
    col = grad(np.clip(np.abs(dth) / 0.9, 0, 1), [(0, C["ice"] * 0.5 + C["cyan"] * 0.5), (0.25, C["sky"]), (0.6, C["violet"]), (1, C["magenta"])])
    img += (atm * w)[..., None] * col
    inside = np.clip(-hgt / cv.px + 0.5, 0, 1)
    surf = grad(np.clip(-hgt / 0.35, 0, 1), [(0, hexc("0a1128")), (1, hexc("03050b"))])
    hin = np.minimum(hgt, 0)
    surf += (np.exp(hin / 0.004) * w * 0.8)[..., None] * col
    surf += (np.exp(hin / 0.06) * np.exp(-(dth / 0.25) ** 2) * 0.10)[..., None] * C["sky"]
    img = img * (1 - inside[..., None]) + surf * inside[..., None]
    ds = np.hypot(cv.x - sx, cv.y - sy)
    sun = np.exp(-(ds / 0.006) ** 2) * 2.0 + np.exp(-ds / 0.025) * 0.5 + np.exp(-ds / 0.12) * 0.15
    img += sun[..., None] * (C["ice"] * 0.7 + 0.3)
    streak = np.exp(-np.abs(cv.y - sy) / 0.0025) * np.exp(-np.abs(cv.x - sx) / 0.25) * 0.22
    add(img, streak, C["sky"] * 0.5 + 0.5)
    img = bloom(img, cv, 0.015, 0.3)
    img = bloom(img, cv, 0.08, 0.2)
    return calm(cv, img, 0.4)


def d_halftone_tide(rng):
    cv = Canvas()
    W, H = cv.W, cv.H
    sp = 30.0
    X = np.arange(W, dtype=F32)[None, :]
    Y = np.arange(H, dtype=F32)[:, None]
    row = np.floor(Y / sp)
    off = np.mod(row, 2) * sp * 0.5
    col = np.floor((X - off) / sp)
    ccx = (col + 0.5) * sp + off
    ccy = (row + 0.5) * sp
    ux, uy = ccx / H, ccy / H

    def field(x, y):
        yw = 0.66 + 0.12 * np.sin(2.3 * x + 0.6) + 0.045 * np.sin(5.4 * x + 1.7)
        a = np.exp(-((y - yw) / 0.075) ** 2)
        yw2 = 0.42 + 0.10 * np.sin(1.9 * x + 2.5) + 0.03 * np.sin(6.1 * x)
        b = np.exp(-((y - yw2) / 0.045) ** 2) * 0.55
        return np.clip((a + b) * smoothstep(0.35, 1.25, x) * smoothstep(1.0, 0.86, y), 0, 1)

    F = field(ux, uy)
    rad = sp * 0.42 * np.sqrt(F)
    d = np.hypot(X - ccx, Y - ccy)
    cov = np.clip(rad - d + 0.5, 0, 1) * (rad > 0.6)
    img = cv.vgrad(C["bg0"], C["bg1"])
    soft = blur(field(cv.x, cv.y) * np.ones((H, 1), F32), 0.03 * H)
    add(img, soft, C["royal"], 0.10)
    tc = np.clip((ux - 0.5) / 1.3 + (uy - 0.4) * 0.3, 0, 1)
    dc = grad(tc, [(0, C["sky"]), (0.4, C["cyan"]), (0.7, C["violet"]), (1, C["magenta"])])
    img += (cov * (0.16 + 0.42 * F))[..., None] * dc
    img = bloom(img, cv, 0.006, 0.4)
    img = bloom(img, cv, 0.05, 0.2)
    return calm(cv, img, 0.4)


def d_signal_ridge(rng):
    cv = Canvas()
    W, H = cv.W, cv.H
    base_img = cv.vgrad(hexc("04060c"), hexc("0a0f20"))
    add(base_img, np.exp(-(((cv.x - 1.25) / 0.5) ** 2 + ((cv.y - 0.55) / 0.3) ** 2)), C["indigo"], 0.5)
    img = base_img.copy()
    xs = cv.x[0]
    N = 42
    y0, y1 = 0.38, 0.84
    for i in range(N):
        f = i / (N - 1)
        base = y0 + (y1 - y0) * (f ** 1.15)
        env = np.exp(-((xs - (1.24 + 0.06 * math.sin(i * 0.4))) / (0.26 + 0.08 * f)) ** 2)
        bumps = (0.5 + 0.5 * np.tanh(1.3 * fbm1(rng, W, 9, 3, 0.45) + 0.2)) ** 2
        amp = 0.11 * (0.5 + 0.5 * f)
        yi = base - amp * env * bumps
        dy = np.gradient(yi, cv.px)
        ra = max(0, int((yi.min() - 0.03) * H))
        rb = min(H, int((yi.max() + 0.03) * H) + 1)
        yy = cv.y[ra:rb]
        m = np.clip((yy - yi[None, :]) / cv.px + 0.5, 0, 1)[..., None]
        img[ra:rb] = img[ra:rb] * (1 - m) + base_img[ra:rb] * m
        d = np.abs(yy - yi[None, :]) / np.sqrt(1 + dy[None, :] ** 2)
        col = grad(np.array(f), [(0, C["magenta"]), (0.5, C["violet"]), (1, C["cyan"])])
        lum = ((0.06 + 0.94 * env) * smoothstep(0.30, 0.95, xs) * (0.35 + 0.65 * smoothstep(0.0, 0.25, f))
               * (1 - 0.5 * smoothstep(0.75, 1.0, f)))[None, :]
        line_glow(img[ra:rb], d, col, 0.0010, 0.006, core=0.75, glow=0.08, white=0.12, fade=lum)
    img = bloom(img, cv, 0.01, 0.35)
    img = bloom(img, cv, 0.06, 0.2)
    return calm(cv, img, 0.45)


DESIGNS = [
    ("Silk Current", d_silk_current, 0.35),
    ("Velvet Silk", d_velvet_silk, 0.35),
    ("Glacier Silk", d_glacier_silk, 0.35),
    ("Aurora Veil", d_aurora_veil, 0.30),
    ("Glass Horizon", d_glass_horizon, 0.35),
    ("Chroma Mesh", d_chroma_mesh, 0.40),
    ("Orbit Halo", d_orbit_halo, 0.35),
    ("Neon Horizon", d_neon_horizon, 0.35),
    ("Nebula Drift", d_nebula_drift, 0.35),
    ("Liquid Obsidian", d_liquid_obsidian, 0.40),
    ("Lumen Bokeh", d_lumen_bokeh, 0.35),
    ("Prism Light", d_prism_beam, 0.35),
    ("Contour Glow", d_contour_glow, 0.35),
    ("Lone Arc", d_lone_arc, 0.30),
    ("Abyss Caustics", d_abyss_caustics, 0.40),
    ("Flux Streams", d_flux_streams, 0.35),
    ("Crystal Facet", d_crystal_facet, 0.40),
    ("Planet Rise", d_planet_rise, 0.30),
    ("Halftone Tide", d_halftone_tide, 0.35),
    ("Signal Ridge", d_signal_ridge, 0.35),
]


def camel(name):
    return "".join(w[:1].upper() + w[1:] for w in name.split())


def luminance_bands(arr):
    a = arr.astype(np.float32) / 255.0
    Y = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    h = Y.shape[0]
    return float(Y[: int(h * 0.15)].mean()), float(Y[int(h * 0.92):].mean()), float(Y.mean())


def write_package(name, arr, quality):
    cid = "DevOS-" + camel(name)
    pkg = OUT_DIR / cid
    (pkg / "contents" / "images").mkdir(parents=True, exist_ok=True)
    meta = {"KPlugin": {"Id": cid, "Name": name, "Authors": [{"Name": "DevOS"}], "License": "CC-BY-SA-4.0"}}
    (pkg / "metadata.json").write_bytes((json.dumps(meta, indent=4) + "\n").encode("utf-8"))
    im = Image.fromarray(arr, "RGB")
    jpg = pkg / "contents" / "images" / f"{OUT_W}x{OUT_H}.jpg"
    im.save(jpg, "JPEG", quality=quality, progressive=True, optimize=True)
    shot = pkg / "contents" / "screenshot.jpg"
    im.resize((THUMB_W, THUMB_H), Image.LANCZOS).save(shot, "JPEG", quality=85, progressive=True, optimize=True)
    return jpg, shot


def contact_sheet():
    tw, th, pad, lab = 300, 169, 16, 30
    cols, rows = 5, 4
    Wt = cols * tw + (cols + 1) * pad
    Ht = rows * (th + lab) + (rows + 1) * pad
    sheet = Image.new("RGB", (Wt, Ht), (5, 7, 13))
    dr = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=17)
    except TypeError:
        font = ImageFont.load_default()
    for k, (name, _, _) in enumerate(DESIGNS):
        jpg = OUT_DIR / ("DevOS-" + camel(name)) / "contents" / "images" / f"{OUT_W}x{OUT_H}.jpg"
        if not jpg.exists():
            continue
        r, c = divmod(k, cols)
        x = pad + c * (tw + pad)
        y = pad + r * (th + lab + pad)
        sheet.paste(Image.open(jpg).convert("RGB").resize((tw, th), Image.LANCZOS), (x, y))
        tb = dr.textbbox((0, 0), name, font=font)
        dr.text((x + (tw - (tb[2] - tb[0])) / 2, y + th + 6), name, fill=(203, 213, 225), font=font)
    sheet.save(PREVIEW, "JPEG", quality=88, optimize=True)
    return PREVIEW


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma separated CamelNames")
    ap.add_argument("--quality", type=int, default=88)
    ap.add_argument("--no-sheet", action="store_true")
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    total = 0
    for idx, (name, fn, vig) in enumerate(DESIGNS):
        if only and camel(name) not in only:
            continue
        t0 = time.time()
        rng = np.random.default_rng(2027 + idx * 101)
        img = fn(rng)
        arr = finalize(img, np.random.default_rng(9000 + idx), vignette=vig)
        jpg, shot = write_package(name, arr, args.quality)
        top, bot, mean = luminance_bands(arr)
        size = jpg.stat().st_size + shot.stat().st_size
        total += size
        flag = "" if (top < 0.25 and bot < 0.25 and jpg.stat().st_size <= 700_000) else "  <-- CHECK"
        print(f"{name:16s} {time.time() - t0:6.1f}s  jpg {jpg.stat().st_size / 1024:6.0f} KB  "
              f"lum top {top:.3f} bottom {bot:.3f} mean {mean:.3f}{flag}", flush=True)
    print(f"total (jpg+thumb) {total / 1e6:.2f} MB")
    if not args.no_sheet:
        print("contact sheet:", contact_sheet())


if __name__ == "__main__":
    main()
