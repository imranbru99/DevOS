#!/usr/bin/env python3
"""DevOS 100 AI-Era Masterpiece Wallpaper Suite (Dark & Light Editions).

Generates 100 breathtaking, human-attracting OS masterpiece wallpapers
derived from 10 flagship AI-generated 3D optical renders & landscapes:

1.  Flagship 3D Fluid Glass Ribbon (Dark Series: AI_001 - AI_010)
2.  Flagship Frosted Crystal Infinity Ribbon (Light Series: AI_011 - AI_020)
3.  Cyber Sapphire Aurora Wave (Dark Series: AI_021 - AI_030)
4.  Cyber Fluid Silk Waves (Light Series: AI_031 - AI_040)
5.  Golden Cloudscape & Alpine Mirror Lake (Warm Sunset Series: AI_041 - AI_050)
6.  Alpine Lake & Blooming Wildflowers (Daylight / Light Series: AI_051 - AI_060)
7.  Cosmic Earth Orbit & Golden City Lights (Night / Space Series: AI_061 - AI_070)
8.  Frosted Prism Floral Bloom (Light Series: AI_071 - AI_080)
9.  Bioluminescent Neural Flora (Dark Series: AI_081 - AI_090)
10. Futuristic Architectural Pavilion & Desert Dunes (Dusk Series: AI_091 - AI_100)

Deploys to:
- build/includes.chroot/usr/share/wallpapers/DevOS-Slideshow/
- ~/.local/share/wallpapers/DevOS-Slideshow/
"""

import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
MASTER_DIR = ROOT / "tools" / "wallpapers" / "master_sources"
BUILD_SLIDESHOW = ROOT / "build" / "includes.chroot" / "usr" / "share" / "wallpapers" / "DevOS-Slideshow"
USER_SLIDESHOW = Path(os.path.expanduser("~/.local/share/wallpapers/DevOS-Slideshow"))

TARGET_W, TARGET_H = 2560, 1440
F32 = np.float32

# Mapping of 10 master images
MASTER_MAP = {
    1: "devos_flagship_masterpiece_dark_1792973005707.jpg",
    2: "devos_flagship_masterpiece_light_clean_1792973071950.jpg",
    3: "devos_cyber_sapphire_aurora_dark_1792973057403.jpg",
    4: "devos_cyber_fluid_waves_light_1792973112298.jpg",
    5: "devos_golden_cloudscape_sunset_1792973061794.jpg",
    6: "devos_alpine_lake_wildflowers_light_1792973108587.jpg",
    7: "devos_cosmic_earth_orbit_1792973067991.jpg",
    8: "devos_frosted_prism_bloom_light_1792973072171.jpg",
    9: "devos_bioluminescent_neural_flora_dark_1792973079533.jpg",
    10: "devos_futuristic_monolith_dusk_1792973120365.jpg",
}

# The 100 Masterpiece names
WALLPAPERS = [
    # Suite 1: Flagship 3D Fluid Glass Ribbon (Dark Series)
    (1, 1, "AI_001_Flagship_Fluid_Glass_Dark.jpg", "native", 1.05, 1.0, (1.0, 1.0, 1.0), 0.0),
    (1, 2, "AI_002_Flagship_Fluid_Glass_Midnight_Obsidian.jpg", "deep_dark", 1.25, 0.95, (0.92, 0.96, 1.05), -0.05),
    (1, 3, "AI_003_Flagship_Fluid_Glass_Cyber_Neon.jpg", "vibrant", 1.15, 1.25, (0.95, 1.05, 1.15), 0.0),
    (1, 4, "AI_004_Flagship_Fluid_Glass_Warm_Champagne.jpg", "warm_amber", 1.05, 1.1, (1.12, 1.04, 0.92), 0.02),
    (1, 5, "AI_005_Flagship_Fluid_Glass_Nordic_Sapphire.jpg", "cool_blue", 1.1, 1.05, (0.90, 1.02, 1.15), 0.0),
    (1, 6, "AI_006_Flagship_Fluid_Glass_Amethyst_Glow.jpg", "amethyst", 1.1, 1.15, (1.08, 0.92, 1.18), 0.0),
    (1, 7, "AI_007_Flagship_Fluid_Glass_Emerald_Caustic.jpg", "emerald", 1.1, 1.15, (0.90, 1.15, 1.05), 0.0),
    (1, 8, "AI_008_Flagship_Fluid_Glass_Deep_Cinema.jpg", "cinema", 1.2, 1.05, (0.98, 1.0, 1.08), -0.04),
    (1, 9, "AI_009_Flagship_Fluid_Glass_Titanium_Matte.jpg", "matte", 0.98, 0.9, (1.0, 1.0, 1.0), 0.03),
    (1, 10, "AI_010_Flagship_Fluid_Glass_Solar_Amber.jpg", "solar", 1.12, 1.15, (1.15, 1.06, 0.90), 0.0),

    # Suite 2: Flagship Frosted Crystal Infinity Ribbon (Light Series)
    (2, 1, "AI_011_Flagship_Crystal_Ribbon_Light.jpg", "native", 1.05, 1.0, (1.0, 1.0, 1.0), 0.0),
    (2, 2, "AI_012_Flagship_Crystal_Ribbon_Alabaster_Pure.jpg", "high_key", 1.02, 0.95, (1.02, 1.02, 1.04), 0.04),
    (2, 3, "AI_013_Flagship_Crystal_Ribbon_Pastel_Prism.jpg", "vibrant", 1.08, 1.2, (1.02, 1.05, 1.12), 0.0),
    (2, 4, "AI_014_Flagship_Crystal_Ribbon_Warm_Sunlight.jpg", "warm_amber", 1.04, 1.08, (1.08, 1.04, 0.96), 0.02),
    (2, 5, "AI_015_Flagship_Crystal_Ribbon_Glacier_Ice.jpg", "cool_blue", 1.06, 1.05, (0.94, 1.02, 1.1), 0.01),
    (2, 6, "AI_016_Flagship_Crystal_Ribbon_Rose_Quartz.jpg", "rose", 1.05, 1.12, (1.10, 0.96, 1.04), 0.01),
    (2, 7, "AI_017_Flagship_Crystal_Ribbon_Mint_Breeze.jpg", "mint", 1.05, 1.1, (0.95, 1.08, 1.02), 0.01),
    (2, 8, "AI_018_Flagship_Crystal_Ribbon_Studio_Clean.jpg", "studio", 1.04, 0.96, (1.0, 1.0, 1.0), 0.02),
    (2, 9, "AI_019_Flagship_Crystal_Ribbon_Champagne_Luster.jpg", "champagne", 1.06, 1.08, (1.06, 1.03, 0.97), 0.02),
    (2, 10, "AI_020_Flagship_Crystal_Ribbon_Silver_Minimal.jpg", "minimal", 1.0, 0.92, (0.99, 1.0, 1.02), 0.02),

    # Suite 3: Cyber Sapphire Aurora Wave (Dark Series)
    (3, 1, "AI_021_Cyber_Sapphire_Aurora_Dark.jpg", "native", 1.05, 1.0, (1.0, 1.0, 1.0), 0.0),
    (3, 2, "AI_022_Cyber_Sapphire_Aurora_Electric_Cyan.jpg", "cyan_boost", 1.12, 1.25, (0.88, 1.08, 1.18), 0.0),
    (3, 3, "AI_023_Cyber_Sapphire_Aurora_Deep_Space.jpg", "deep_dark", 1.25, 0.95, (0.92, 0.96, 1.08), -0.06),
    (3, 4, "AI_024_Cyber_Sapphire_Aurora_Violet_Pulse.jpg", "amethyst", 1.15, 1.2, (1.08, 0.92, 1.2), 0.0),
    (3, 5, "AI_025_Cyber_Sapphire_Aurora_Emerald_Borealis.jpg", "emerald", 1.12, 1.2, (0.88, 1.18, 1.05), 0.0),
    (3, 6, "AI_026_Cyber_Sapphire_Aurora_Obsidian_Tide.jpg", "obsidian", 1.22, 1.05, (0.96, 1.0, 1.05), -0.04),
    (3, 7, "AI_027_Cyber_Sapphire_Aurora_Laser_Haze.jpg", "haze", 1.08, 1.15, (0.94, 1.05, 1.12), 0.02),
    (3, 8, "AI_028_Cyber_Sapphire_Aurora_Cosmic_Flux.jpg", "flux", 1.18, 1.18, (1.02, 1.02, 1.15), -0.02),
    (3, 9, "AI_029_Cyber_Sapphire_Aurora_Hyper_Neon.jpg", "hyper", 1.16, 1.35, (0.95, 1.1, 1.2), 0.0),
    (3, 10, "AI_030_Cyber_Sapphire_Aurora_Midnight_Flow.jpg", "midnight", 1.2, 1.05, (0.92, 0.98, 1.1), -0.05),

    # Suite 4: Cyber Fluid Silk Waves (Light Series)
    (4, 1, "AI_031_Cyber_Fluid_Waves_Light.jpg", "native", 1.05, 1.0, (1.0, 1.0, 1.0), 0.0),
    (4, 2, "AI_032_Cyber_Fluid_Waves_Pearl_Azure.jpg", "pearl_azure", 1.06, 1.12, (0.96, 1.04, 1.12), 0.02),
    (4, 3, "AI_033_Cyber_Fluid_Waves_Soft_Sky.jpg", "soft_sky", 1.04, 1.06, (0.94, 1.02, 1.1), 0.03),
    (4, 4, "AI_034_Cyber_Fluid_Waves_Pastel_Blush.jpg", "blush", 1.05, 1.1, (1.08, 0.98, 1.04), 0.02),
    (4, 5, "AI_035_Cyber_Fluid_Waves_Opal_Iridescence.jpg", "opal", 1.08, 1.18, (1.04, 1.06, 1.12), 0.01),
    (4, 6, "AI_036_Cyber_Fluid_Waves_Clean_Aero.jpg", "aero", 1.02, 0.98, (0.98, 1.02, 1.06), 0.03),
    (4, 7, "AI_037_Cyber_Fluid_Waves_Morning_Dew.jpg", "dew", 1.05, 1.08, (0.96, 1.05, 1.05), 0.02),
    (4, 8, "AI_038_Cyber_Fluid_Waves_Silken_Silver.jpg", "silver", 1.02, 0.92, (1.0, 1.0, 1.02), 0.03),
    (4, 9, "AI_039_Cyber_Fluid_Waves_Calm_Horizon.jpg", "calm", 1.04, 1.02, (1.02, 1.02, 1.06), 0.02),
    (4, 10, "AI_040_Cyber_Fluid_Waves_Pure_Focus.jpg", "focus", 1.02, 0.95, (1.0, 1.0, 1.0), 0.03),

    # Suite 5: Golden Cloudscape & Alpine Mirror Lake (Warm Sunset Series)
    (5, 1, "AI_041_Golden_Cloudscape_Sunset.jpg", "native", 1.05, 1.0, (1.0, 1.0, 1.0), 0.0),
    (5, 2, "AI_042_Golden_Cloudscape_Alpenglow_Peak.jpg", "alpenglow", 1.1, 1.15, (1.14, 1.02, 0.94), 0.0),
    (5, 3, "AI_043_Golden_Cloudscape_Twilight_Indigo.jpg", "twilight", 1.15, 1.08, (1.02, 0.96, 1.12), -0.04),
    (5, 4, "AI_044_Golden_Cloudscape_Amber_Radiance.jpg", "amber", 1.12, 1.2, (1.16, 1.06, 0.88), 0.0),
    (5, 5, "AI_045_Golden_Cloudscape_Crimson_Dusk.jpg", "crimson", 1.14, 1.18, (1.18, 0.95, 0.98), -0.02),
    (5, 6, "AI_046_Golden_Cloudscape_Mist_Reflection.jpg", "mist", 1.05, 1.05, (1.04, 1.02, 1.02), 0.02),
    (5, 7, "AI_047_Golden_Cloudscape_Velvet_Solitude.jpg", "velvet", 1.18, 1.05, (0.98, 0.98, 1.06), -0.05),
    (5, 8, "AI_048_Golden_Cloudscape_Celestial_Horizon.jpg", "celestial", 1.1, 1.12, (1.06, 1.02, 1.08), 0.0),
    (5, 9, "AI_049_Golden_Cloudscape_Warm_Nostalgia.jpg", "nostalgia", 1.08, 1.15, (1.12, 1.05, 0.92), 0.02),
    (5, 10, "AI_050_Golden_Cloudscape_Deep_Peace.jpg", "peace", 1.06, 1.0, (1.02, 1.01, 1.03), 0.01),

    # Suite 6: Alpine Lake & Blooming Wildflowers (Daylight / Light Series)
    (6, 1, "AI_051_Alpine_Wildflowers_Daylight.jpg", "native", 1.05, 1.0, (1.0, 1.0, 1.0), 0.0),
    (6, 2, "AI_052_Alpine_Wildflowers_Turquoise_Waters.jpg", "turquoise", 1.08, 1.15, (0.92, 1.08, 1.1), 0.01),
    (6, 3, "AI_053_Alpine_Wildflowers_High_Sierra_Sun.jpg", "sunlight", 1.06, 1.12, (1.05, 1.03, 0.96), 0.02),
    (6, 4, "AI_054_Alpine_Wildflowers_Spring_Meadow.jpg", "vibrant", 1.08, 1.25, (1.0, 1.1, 1.02), 0.01),
    (6, 5, "AI_055_Alpine_Wildflowers_Crisp_Granite.jpg", "crisp", 1.1, 1.02, (0.98, 1.01, 1.04), 0.0),
    (6, 6, "AI_056_Alpine_Wildflowers_Vibrant_Nature.jpg", "vivid", 1.08, 1.28, (1.04, 1.08, 1.02), 0.0),
    (6, 7, "AI_057_Alpine_Wildflowers_Clear_Zenith.jpg", "zenith", 1.05, 1.05, (0.96, 1.02, 1.08), 0.02),
    (6, 8, "AI_058_Alpine_Wildflowers_Fresh_Morning.jpg", "morning", 1.04, 1.08, (0.98, 1.04, 1.06), 0.03),
    (6, 9, "AI_059_Alpine_Wildflowers_Mountain_Breeze.jpg", "breeze", 1.06, 1.06, (0.96, 1.02, 1.05), 0.01),
    (6, 10, "AI_060_Alpine_Wildflowers_Pure_Lakeside.jpg", "pure", 1.04, 1.02, (1.0, 1.02, 1.02), 0.02),

    # Suite 7: Cosmic Earth Orbit & Golden City Lights (Night / Space Series)
    (7, 1, "AI_061_Cosmic_Earth_Orbit_Night.jpg", "native", 1.05, 1.0, (1.0, 1.0, 1.0), 0.0),
    (7, 2, "AI_062_Cosmic_Earth_Orbit_Atmosphere_Blue.jpg", "blue_rim", 1.15, 1.18, (0.88, 1.04, 1.22), -0.02),
    (7, 3, "AI_063_Cosmic_Earth_Orbit_Golden_Megacity.jpg", "golden_lights", 1.12, 1.22, (1.15, 1.06, 0.92), -0.02),
    (7, 4, "AI_064_Cosmic_Earth_Orbit_Solar_Sunrise.jpg", "solar_flare", 1.18, 1.2, (1.12, 1.04, 0.98), 0.0),
    (7, 5, "AI_065_Cosmic_Earth_Orbit_Deep_Void.jpg", "deep_void", 1.3, 0.95, (0.94, 0.96, 1.05), -0.08),
    (7, 6, "AI_066_Cosmic_Earth_Orbit_Aurora_Limb.jpg", "aurora_limb", 1.15, 1.22, (0.9, 1.16, 1.1), -0.03),
    (7, 7, "AI_067_Cosmic_Earth_Orbit_Starfield_Glory.jpg", "starfield", 1.14, 1.1, (0.98, 1.0, 1.12), -0.03),
    (7, 8, "AI_068_Cosmic_Earth_Orbit_Ocean_Glitter.jpg", "ocean", 1.16, 1.15, (0.92, 1.06, 1.16), -0.04),
    (7, 9, "AI_069_Cosmic_Earth_Orbit_Planetary_Wonder.jpg", "wonder", 1.12, 1.12, (1.02, 1.02, 1.08), -0.02),
    (7, 10, "AI_070_Cosmic_Earth_Orbit_Infinite_Space.jpg", "infinite", 1.22, 1.02, (0.92, 0.96, 1.08), -0.06),

    # Suite 8: Frosted Prism Floral Bloom (Light Series)
    (8, 1, "AI_071_Frosted_Prism_Bloom_Light.jpg", "native", 1.05, 1.0, (1.0, 1.0, 1.0), 0.0),
    (8, 2, "AI_072_Frosted_Prism_Bloom_Silver_Chrome.jpg", "silver", 1.04, 0.92, (0.98, 1.0, 1.04), 0.02),
    (8, 3, "AI_073_Frosted_Prism_Bloom_Spectral_Pastel.jpg", "spectral", 1.08, 1.2, (1.04, 1.06, 1.12), 0.01),
    (8, 4, "AI_074_Frosted_Prism_Bloom_Pearl_Dew.jpg", "pearl", 1.04, 1.06, (1.02, 1.02, 1.06), 0.02),
    (8, 5, "AI_075_Frosted_Prism_Bloom_Sculpted_Minimal.jpg", "minimal", 1.02, 0.95, (1.0, 1.0, 1.0), 0.03),
    (8, 6, "AI_076_Frosted_Prism_Bloom_Warm_Studio.jpg", "warm_studio", 1.06, 1.1, (1.06, 1.03, 0.96), 0.02),
    (8, 7, "AI_077_Frosted_Prism_Bloom_Ethereal_Glass.jpg", "ethereal", 1.05, 1.08, (0.96, 1.04, 1.08), 0.02),
    (8, 8, "AI_078_Frosted_Prism_Bloom_Clean_Workspace.jpg", "workspace", 1.02, 0.96, (1.0, 1.01, 1.02), 0.03),
    (8, 9, "AI_079_Frosted_Prism_Bloom_Delicate_Petal.jpg", "petal", 1.05, 1.12, (1.08, 0.98, 1.04), 0.02),
    (8, 10, "AI_080_Frosted_Prism_Bloom_Nordic_Luxe.jpg", "nordic", 1.04, 1.02, (0.97, 1.02, 1.06), 0.02),

    # Suite 9: Bioluminescent Neural Flora (Dark Series)
    (9, 1, "AI_081_Bioluminescent_Neural_Flora_Dark.jpg", "native", 1.05, 1.0, (1.0, 1.0, 1.0), 0.0),
    (9, 2, "AI_082_Bioluminescent_Neural_Flora_Crystal_Cyan.jpg", "cyan_glow", 1.15, 1.25, (0.86, 1.12, 1.18), -0.02),
    (9, 3, "AI_083_Bioluminescent_Neural_Flora_Magenta_Orchid.jpg", "magenta", 1.12, 1.24, (1.18, 0.88, 1.14), -0.02),
    (9, 4, "AI_084_Bioluminescent_Neural_Flora_Amber_Spore.jpg", "amber", 1.1, 1.2, (1.18, 1.06, 0.86), -0.01),
    (9, 5, "AI_085_Bioluminescent_Neural_Flora_Deep_Midnight.jpg", "deep_dark", 1.26, 0.95, (0.94, 0.96, 1.06), -0.08),
    (9, 6, "AI_086_Bioluminescent_Neural_Flora_Synaptic_Glow.jpg", "synapse", 1.18, 1.3, (1.02, 1.08, 1.2), -0.02),
    (9, 7, "AI_087_Bioluminescent_Neural_Flora_Macro_Dewdrop.jpg", "macro", 1.12, 1.15, (0.96, 1.06, 1.1), -0.02),
    (9, 8, "AI_088_Bioluminescent_Neural_Flora_Enchanted_Forest.jpg", "enchanted", 1.14, 1.22, (0.92, 1.14, 1.08), -0.03),
    (9, 9, "AI_089_Bioluminescent_Neural_Flora_Ethereal_Sanctuary.jpg", "sanctuary", 1.1, 1.12, (1.04, 1.02, 1.12), -0.02),
    (9, 10, "AI_090_Bioluminescent_Neural_Flora_Organic_AI.jpg", "organic_ai", 1.16, 1.25, (0.9, 1.1, 1.18), -0.03),

    # Suite 10: Futuristic Architectural Pavilion & Desert Dunes (Dusk Series)
    (10, 1, "AI_091_Futuristic_Architectural_Dusk.jpg", "native", 1.05, 1.0, (1.0, 1.0, 1.0), 0.0),
    (10, 2, "AI_092_Futuristic_Architectural_Twilight_Stars.jpg", "twilight", 1.16, 1.12, (1.02, 0.95, 1.15), -0.04),
    (10, 3, "AI_093_Futuristic_Architectural_Warm_Pavilion.jpg", "warm_interior", 1.1, 1.18, (1.14, 1.04, 0.92), 0.0),
    (10, 4, "AI_094_Futuristic_Architectural_Rippled_Sands.jpg", "sands", 1.12, 1.1, (1.12, 1.02, 0.96), -0.01),
    (10, 5, "AI_095_Futuristic_Architectural_Minimalist_Zen.jpg", "zen", 1.04, 0.95, (1.0, 1.0, 1.02), 0.02),
    (10, 6, "AI_096_Futuristic_Architectural_Violet_Horizon.jpg", "violet", 1.14, 1.18, (1.1, 0.94, 1.18), -0.02),
    (10, 7, "AI_097_Futuristic_Architectural_Reflective_Glass.jpg", "reflective", 1.12, 1.1, (0.95, 1.02, 1.12), -0.02),
    (10, 8, "AI_098_Futuristic_Architectural_Contemplative_Silence.jpg", "silence", 1.15, 1.02, (0.96, 0.98, 1.06), -0.04),
    (10, 9, "AI_099_Futuristic_Architectural_Titanium_Sanctuary.jpg", "titanium", 1.08, 1.05, (1.02, 1.02, 1.06), 0.0),
    (10, 10, "AI_100_Futuristic_Architectural_Dawn_Transition.jpg", "dawn", 1.08, 1.12, (1.08, 1.04, 0.98), 0.01),
]


def grade_image(pil_src: Image.Image, contrast: float, saturation: float, tint: tuple, brightness_shift: float, seed: int = 42) -> Image.Image:
    # 1. Resize to target 2560x1440 with Lanczos
    up = pil_src.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)

    # 2. Unsharp Mask for ultra-crisp architectural / glass details
    crisp = up.filter(ImageFilter.UnsharpMask(radius=1.8, percent=120, threshold=2))

    # 3. Saturation adjustment
    if saturation != 1.0:
        enh_sat = ImageEnhance.Color(crisp)
        crisp = enh_sat.enhance(saturation)

    # 4. Color grading in numpy float32
    arr = np.array(crisp, dtype=F32) / 255.0

    # Apply tint
    arr[..., 0] *= tint[0]
    arr[..., 1] *= tint[1]
    arr[..., 2] *= tint[2]

    # Brightness shift
    if brightness_shift != 0.0:
        arr += brightness_shift

    # Contrast S-Curve
    if contrast != 1.0:
        arr = (arr - 0.5) * contrast + 0.5

    # Desktop Ergonomics: Gentle vignette on edges for icon focus
    X = (np.arange(TARGET_W, dtype=F32) / TARGET_H)[None, :]
    Y = (np.arange(TARGET_H, dtype=F32) / TARGET_H)[:, None]
    # Subtle darkening at top-left icon safe zone
    tl_dist = np.sqrt((X - 0.22) ** 2 + (Y - 0.22) ** 2)
    tl_damp = 1.0 - 0.08 * np.exp(-(tl_dist / 0.5) ** 2)
    arr *= tl_damp[..., None]

    # Film-grain dither to prevent 8-bit banding
    rng = np.random.RandomState(seed)
    dith = (rng.uniform(-0.55, 0.55, (TARGET_H, TARGET_W, 1)) + rng.uniform(-0.55, 0.55, (TARGET_H, TARGET_W, 1))).astype(F32) / 255.0
    arr = np.clip(arr + dith, 0.0, 1.0)

    out_arr = (arr * 255.0).astype(np.uint8)
    return Image.fromarray(out_arr, "RGB")


def main():
    BUILD_SLIDESHOW.mkdir(parents=True, exist_ok=True)
    USER_SLIDESHOW.mkdir(parents=True, exist_ok=True)

    print("=" * 75)
    print("DevOS AI-Era Masterpiece Wallpaper Suite (Dark & Light Editions)")
    print(f"Target Resolution: {TARGET_W}x{TARGET_H} (2.5K QHD)")
    print(f"Deploying to:")
    print(f"  1. {BUILD_SLIDESHOW}")
    print(f"  2. {USER_SLIDESHOW}")
    print("=" * 75)

    # Pre-load the 10 master images into memory
    print("--> Loading 10 Flagship Master Source Artworks...")
    master_images = {}
    for idx, fname in MASTER_MAP.items():
        src_path = MASTER_DIR / fname
        if not src_path.exists():
            raise FileNotFoundError(f"Master source image not found: {src_path}")
        master_images[idx] = Image.open(src_path).convert("RGB")
        print(f"    [{idx:02d}/10] Loaded: {fname} ({master_images[idx].size})")

    print("\n--> Generating 100 AI-Era Masterpieces with Photographic Color Grading...")
    t_start = time.time()

    for idx, (master_idx, var_idx, out_name, grade_label, contrast, sat, tint, b_shift) in enumerate(WALLPAPERS, 1):
        t0 = time.time()
        src_im = master_images[master_idx]
        graded = grade_image(src_im, contrast, sat, tint, b_shift, seed=idx * 7)

        # Save to build slideshow directory
        target_build = BUILD_SLIDESHOW / out_name
        graded.save(target_build, "JPEG", quality=94, progressive=True, optimize=True)

        # Save to user live wallpapers directory
        target_user = USER_SLIDESHOW / out_name
        graded.save(target_user, "JPEG", quality=94, progressive=True, optimize=True)

        dur = time.time() - t0
        print(f"[{idx:03d}/100] Master #{master_idx:02d} -> {out_name:<50} ({dur:.2f}s)")

    total_time = time.time() - t_start
    build_count = len(list(BUILD_SLIDESHOW.glob("*.*")))
    user_count = len(list(USER_SLIDESHOW.glob("*.*")))

    print("=" * 75)
    print(f"Successfully generated all 100 Masterpiece Wallpapers in {total_time:.2f}s!")
    print(f"Total wallpapers in build slideshow: {build_count}")
    print(f"Total wallpapers in user slideshow:  {user_count}")
    print("=" * 75)


if __name__ == "__main__":
    main()
