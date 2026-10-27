#!/usr/bin/env python3
"""Generates premium, ultra-modern Antigravity KDE Studio icon suite.

Crafts a dark-glassmorphism obsidian squircle, glowing neon cyan/sapphire rim,
isolated Antigravity dimensional emblem, and a glowing KDE Plasma spark badge.
Exports pixel-perfect icons across all hicolor resolutions and scalable SVG.
"""

import math
import os
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

ROOT = Path(__file__).resolve().parents[1]
USER_ICONS = Path.home() / ".local/share/icons/hicolor"
CHROOT_ICONS = ROOT / "build/includes.chroot/usr/share/icons/hicolor"


def create_master_icon(size: int = 1024) -> Image.Image:
    # 1. Base canvas with alpha
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    
    # 2. Outer Soft Ambient Drop Shadow
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow)
    margin = int(size * 0.08)
    corner_r = int(size * 0.22)
    s_box = [margin, margin + int(size * 0.03), size - margin, size - margin + int(size * 0.03)]
    s_draw.rounded_rectangle(s_box, radius=corner_r, fill=(0, 0, 0, 180))
    shadow = shadow.filter(ImageFilter.GaussianBlur(int(size * 0.045)))
    canvas = Image.alpha_composite(canvas, shadow)

    # 3. Squircle Base with Deep Midnight Obsidian Gradient
    squircle = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sq_box = [margin, margin, size - margin, size - margin]
    
    # Render vertical luxury gradient
    for y in range(margin, size - margin):
        t = (y - margin) / (size - 2 * margin)
        # Deep cosmic midnight: #060914 (top) -> #0f172a (mid) -> #080d1a (bottom)
        if t < 0.5:
            factor = t / 0.5
            r = int(6 * (1 - factor) + 15 * factor)
            g = int(9 * (1 - factor) + 23 * factor)
            b = int(20 * (1 - factor) + 42 * factor)
        else:
            factor = (t - 0.5) / 0.5
            r = int(15 * (1 - factor) + 8 * factor)
            g = int(23 * (1 - factor) + 13 * factor)
            b = int(42 * (1 - factor) + 26 * factor)
        
        row_mask = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        r_draw = ImageDraw.Draw(row_mask)
        r_draw.line([(margin, y), (size - margin, y)], fill=(r, g, b, 255))
        squircle = Image.alpha_composite(squircle, row_mask)
    
    # Apply rounded squircle mask
    sq_mask = Image.new("L", (size, size), 0)
    m_draw = ImageDraw.Draw(sq_mask)
    m_draw.rounded_rectangle(sq_box, radius=corner_r, fill=255)
    
    base_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    base_layer.paste(squircle, (0, 0), sq_mask)

    # 4. Neon Edge Rim (Cyan -> Indigo -> Violet glow)
    rim = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rim_draw = ImageDraw.Draw(rim)
    rim_width = max(2, int(size * 0.012))
    rim_draw.rounded_rectangle(sq_box, radius=corner_r, outline=(56, 189, 248, 220), width=rim_width)
    
    # Top specular glass edge
    spec = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    spec_draw = ImageDraw.Draw(spec)
    spec_box = [margin + 4, margin + 2, size - margin - 4, margin + int(size * 0.12)]
    spec_draw.rounded_rectangle(spec_box, radius=corner_r, fill=(255, 255, 255, 30))
    spec = spec.filter(ImageFilter.GaussianBlur(int(size * 0.015)))
    
    base_layer = Image.alpha_composite(base_layer, rim)
    base_layer = Image.alpha_composite(base_layer, spec)
    
    # 5. Radial Glow in Center (Atmospheric Bloom)
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(glow)
    gc_x, gc_y = size // 2, size // 2
    gr = int(size * 0.28)
    g_draw.ellipse([gc_x - gr, gc_y - gr, gc_x + gr, gc_y + gr], fill=(14, 165, 233, 90))
    glow = glow.filter(ImageFilter.GaussianBlur(int(size * 0.08)))
    base_layer = Image.alpha_composite(base_layer, glow)

    # 6. Extract & Place the Antigravity Loop
    orig_path = Path.home() / ".local/share/icons/hicolor/512x512/apps/antigravity.png"
    if orig_path.exists():
        orig = Image.open(orig_path).convert("RGBA")
        arr = np.array(orig)
        r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]
        color_std = np.std(arr[:, :, :3], axis=2)
        # Isolate the colorful ribbon from the white squircle
        is_ribbon = (a > 80) & ((color_std > 12) | (r < 230) | (g < 230) | (b < 230))
        
        # Soften mask edges with smooth alpha
        alpha_channel = np.zeros_like(a)
        alpha_channel[is_ribbon] = a[is_ribbon]
        
        ribbon_arr = np.copy(arr)
        ribbon_arr[:, :, 3] = alpha_channel
        ribbon_img = Image.fromarray(ribbon_arr)
        
        # Crop tight to ribbon
        y_idx, x_idx = np.where(is_ribbon)
        if len(x_idx) > 0:
            tight = ribbon_img.crop((x_idx.min() - 4, y_idx.min() - 4, x_idx.max() + 4, y_idx.max() + 4))
            
            # Upscale with high quality Lanczos to fit nicely inside base
            target_w = int(size * 0.58)
            ratio = target_w / tight.width
            target_h = int(tight.height * ratio)
            tight_res = tight.resize((target_w, target_h), Image.Resampling.LANCZOS)
            
            # Drop shadow behind the ribbon
            r_shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            rx = (size - target_w) // 2
            ry = (size - target_h) // 2 - int(size * 0.02)
            r_shadow.paste(Image.new("RGBA", tight_res.size, (0, 0, 0, 160)), (rx, ry + int(size * 0.02)), tight_res)
            r_shadow = r_shadow.filter(ImageFilter.GaussianBlur(int(size * 0.025)))
            
            base_layer = Image.alpha_composite(base_layer, r_shadow)
            base_layer.paste(tight_res, (rx, ry), tight_res)

    # 7. Add Luxury KDE Plasma Spark Gemstone Badge (Bottom-Right)
    badge_size = int(size * 0.36)
    badge = Image.new("RGBA", (badge_size, badge_size), (0, 0, 0, 0))
    b_draw = ImageDraw.Draw(badge)
    
    # Outer dark coin with cyan glow border
    b_margin = int(badge_size * 0.06)
    b_r = badge_size // 2 - b_margin
    b_cx, b_cy = badge_size // 2, badge_size // 2
    
    # Shadow
    b_draw.ellipse([b_cx - b_r, b_cy - b_r + int(badge_size*0.04), b_cx + b_r, b_cy + b_r + int(badge_size*0.04)], fill=(0, 0, 0, 160))
    # Outer cyan neon ring
    b_draw.ellipse([b_cx - b_r, b_cy - b_r, b_cx + b_r, b_cy + b_r], fill=(14, 165, 233, 255))
    # Deep midnight sapphire center
    b_draw.ellipse([b_cx - b_r + int(badge_size*0.04), b_cy - b_r + int(badge_size*0.04),
                    b_cx + b_r - int(badge_size*0.04), b_cy + b_r - int(badge_size*0.04)], fill=(10, 15, 30, 255))
    
    # Inner glowing radial core
    core_r = int(b_r * 0.6)
    b_draw.ellipse([b_cx - core_r, b_cy - core_r, b_cx + core_r, b_cy + core_r], fill=(2, 132, 199, 140))
    
    # Draw Stylized KDE Plasma 'K' / Spark Emblem
    # Central stem
    k_x = b_cx - int(badge_size * 0.12)
    k_top = b_cy - int(badge_size * 0.24)
    k_bot = b_cy + int(badge_size * 0.24)
    stem_w = max(3, int(badge_size * 0.09))
    b_draw.rounded_rectangle([k_x, k_top, k_x + stem_w, k_bot], radius=stem_w//2, fill=(248, 250, 252, 255))
    
    # Diagonal arms
    arm_w = max(3, int(badge_size * 0.08))
    # Upper arm
    b_draw.line([(k_x + stem_w - 2, b_cy - int(badge_size * 0.02)), (b_cx + int(badge_size * 0.22), k_top + 2)], fill=(56, 189, 248, 255), width=arm_w)
    # Lower arm
    b_draw.line([(k_x + stem_w - 2, b_cy + int(badge_size * 0.02)), (b_cx + int(badge_size * 0.22), k_bot - 2)], fill=(56, 189, 248, 255), width=arm_w)
    
    # Spark dots
    dot_r = max(2, int(badge_size * 0.035))
    b_draw.ellipse([b_cx + int(badge_size * 0.20) - dot_r, k_top - dot_r, b_cx + int(badge_size * 0.20) + dot_r, k_top + dot_r], fill=(255, 255, 255, 255))
    b_draw.ellipse([b_cx + int(badge_size * 0.20) - dot_r, k_bot - dot_r, b_cx + int(badge_size * 0.20) + dot_r, k_bot + dot_r], fill=(255, 255, 255, 255))
    
    # Composite badge onto bottom-right of base
    badge_pos_x = size - margin - badge_size + int(size * 0.05)
    badge_pos_y = size - margin - badge_size + int(size * 0.05)
    base_layer.paste(badge, (badge_pos_x, badge_pos_y), badge)

    canvas = Image.alpha_composite(canvas, base_layer)
    return canvas


def generate_svg() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="100%" height="100%">
  <defs>
    <!-- Background Gradients -->
    <linearGradient id="obsidianBg" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#0a0f1d"/>
      <stop offset="50%" stop-color="#111827"/>
      <stop offset="100%" stop-color="#080c18"/>
    </linearGradient>
    <linearGradient id="neonRim" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#38bdf8"/>
      <stop offset="50%" stop-color="#6366f1"/>
      <stop offset="100%" stop-color="#a855f7"/>
    </linearGradient>
    <linearGradient id="kdeCyan" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#00f2fe"/>
      <stop offset="100%" stop-color="#4facfe"/>
    </linearGradient>
    <radialGradient id="centerGlow" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#0284c7" stop-opacity="0.45"/>
      <stop offset="100%" stop-color="#0284c7" stop-opacity="0"/>
    </radialGradient>
    <filter id="softGlow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="16" result="blur"/>
      <feComposite in="SourceGraphic" in2="blur" operator="over"/>
    </filter>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="16" stdDeviation="20" flood-color="#000000" flood-opacity="0.6"/>
    </filter>
  </defs>

  <!-- Base Squircle with Shadow -->
  <rect x="44" y="44" width="424" height="424" rx="100" fill="url(#obsidianBg)" filter="url(#shadow)" stroke="url(#neonRim)" stroke-width="4.5"/>

  <!-- Specular Top Reflection -->
  <path d="M 64 64 Q 256 95 448 64" fill="none" stroke="#ffffff" stroke-opacity="0.2" stroke-width="2.5" stroke-linecap="round"/>

  <!-- Atmospheric Core Glow -->
  <circle cx="256" cy="250" r="160" fill="url(#centerGlow)"/>

  <!-- Antigravity Infinity Ribbon (Stylized Vectors) -->
  <g filter="url(#softGlow)">
    <!-- Left Loop Arch -->
    <path d="M 180 340 C 130 300 120 200 190 150 C 250 110 300 180 340 250" fill="none" stroke="#38bdf8" stroke-width="32" stroke-linecap="round"/>
    <!-- Right Loop Arch -->
    <path d="M 340 250 C 380 310 370 380 310 390 C 250 400 200 320 180 250" fill="none" stroke="#8b5cf6" stroke-width="32" stroke-linecap="round"/>
    <!-- Apex Fusion -->
    <path d="M 190 150 C 240 120 280 150 330 200" fill="none" stroke="#f43f5e" stroke-width="30" stroke-linecap="round"/>
    <!-- Amber Accent -->
    <path d="M 170 310 C 160 250 200 200 260 170" fill="none" stroke="#eab308" stroke-width="26" stroke-linecap="round"/>
  </g>

  <!-- KDE Plasma Emblem Badge (Bottom Right) -->
  <g transform="translate(320, 320)">
    <circle cx="70" cy="70" r="66" fill="#070b19" stroke="url(#kdeCyan)" stroke-width="4"/>
    <circle cx="70" cy="70" r="44" fill="#0284c7" fill-opacity="0.35"/>
    <!-- KDE 'K' Motif -->
    <rect x="52" y="38" width="10" height="64" rx="5" fill="#f8fafc"/>
    <line x1="62" y1="70" x2="88" y2="44" stroke="#38bdf8" stroke-width="9" stroke-linecap="round"/>
    <line x1="62" y1="70" x2="88" y2="96" stroke="#38bdf8" stroke-width="9" stroke-linecap="round"/>
    <circle cx="88" cy="44" r="4" fill="#ffffff"/>
    <circle cx="88" cy="96" r="4" fill="#ffffff"/>
  </g>
</svg>
"""


def main():
    print("==> Generating Master High-Resolution Icon...")
    master = create_master_icon(1024)
    
    resolutions = [16, 22, 24, 32, 48, 64, 128, 256, 512]
    
    for res in resolutions:
        size_str = f"{res}x{res}"
        resized = master.resize((res, res), Image.Resampling.LANCZOS)
        
        # Unsharp mask for smaller icons to ensure razor sharpness
        if res <= 48:
            resized = resized.filter(ImageFilter.UnsharpMask(radius=1.2, percent=140, threshold=2))
        elif res <= 128:
            resized = resized.filter(ImageFilter.UnsharpMask(radius=1.0, percent=110, threshold=2))
        
        # Save to user icons
        u_dir = USER_ICONS / size_str / "apps"
        u_dir.mkdir(parents=True, exist_ok=True)
        resized.save(u_dir / "antigravity-kde.png", "PNG")

        # Save to build chroot icons
        c_dir = CHROOT_ICONS / size_str / "apps"
        c_dir.mkdir(parents=True, exist_ok=True)
        resized.save(c_dir / "antigravity-kde.png", "PNG")
        
        print(f"  [+] Generated {size_str}/apps/antigravity-kde.png")

    # Save Scalable SVG
    svg_content = generate_svg()
    (USER_ICONS / "scalable/apps").mkdir(parents=True, exist_ok=True)
    with open(USER_ICONS / "scalable/apps/antigravity-kde.svg", "w", encoding="utf-8") as f:
        f.write(svg_content)
        
    (CHROOT_ICONS / "scalable/apps").mkdir(parents=True, exist_ok=True)
    with open(CHROOT_ICONS / "scalable/apps/antigravity-kde.svg", "w", encoding="utf-8") as f:
        f.write(svg_content)
        
    print("  [+] Generated scalable/apps/antigravity-kde.svg")
    print("==> All icons successfully rendered and installed!")


if __name__ == "__main__":
    main()
