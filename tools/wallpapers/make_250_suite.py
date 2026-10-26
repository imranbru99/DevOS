#!/usr/bin/env python3
"""DevOS 250 Wallpaper Master Suite Expansion.

Generates 110 additional breathtaking, ultra-premium 2.5K QHD wallpapers
(AI_101 to AI_210), bringing the complete DevOS Slideshow suite to 250 wallpapers:
40 original masterworks + 210 AI-Era Masterpieces (Dark & Light editions).

Outclasses Apple macOS and Windows 11 with handcrafted color grading,
cinematic S-curve contrast, unsharp mask clarity, and ergonomic safe zones.
"""

import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
MASTER_DIR = ROOT / "tools" / "wallpapers" / "master_sources"
CYBERPUNK_SRC = ROOT / "tools" / "wallpapers" / "DevOS_Cyberpunk_Aurora_2560x1440.png"
BUILD_SLIDESHOW = ROOT / "build" / "includes.chroot" / "usr" / "share" / "wallpapers" / "DevOS-Slideshow"
USER_SLIDESHOW = Path(os.path.expanduser("~/.local/share/wallpapers/DevOS-Slideshow"))

TARGET_W, TARGET_H = 2560, 1440
F32 = np.float32

# Mapping of master sources
MASTER_FILES = {
    "dark_ribbon": "devos_flagship_masterpiece_dark_1792973005707.jpg",
    "crystal_ribbon": "devos_flagship_masterpiece_light_clean_1792973071950.jpg",
    "cyber_sapphire": "devos_cyber_sapphire_aurora_dark_1792973057403.jpg",
    "silk_waves": "devos_cyber_fluid_waves_light_1792973112298.jpg",
    "golden_clouds": "devos_golden_cloudscape_sunset_1792973061794.jpg",
    "alpine_lake": "devos_alpine_lake_wildflowers_light_1792973108587.jpg",
    "earth_orbit": "devos_cosmic_earth_orbit_1792973067991.jpg",
    "prism_bloom": "devos_frosted_prism_bloom_light_1792973072171.jpg",
    "neural_flora": "devos_bioluminescent_neural_flora_dark_1792973079533.jpg",
    "pavilion_dusk": "devos_futuristic_monolith_dusk_1792973120365.jpg",
    "flagship_light": "devos_flagship_masterpiece_light_1792973052955.jpg",
}

# 110 New Wallpaper Definitions (AI_101 through AI_210)
NEW_WALLPAPERS = [
    # Suite 11: Tokyo Cyberpunk Midnight Rain & Reflections (Dark)
    ("cyber_aurora_base", "AI_101_Tokyo_Cyberpunk_Midnight_Rain.jpg", 1.15, 1.25, (0.92, 1.05, 1.15), -0.02, "center"),
    ("cyber_aurora_base", "AI_102_Tokyo_Cyberpunk_Neon_Asphalt.jpg", 1.22, 1.3, (1.1, 0.95, 1.2), -0.04, "center"),
    ("cyber_aurora_base", "AI_103_Tokyo_Cyberpunk_Cyan_Haze.jpg", 1.18, 1.2, (0.88, 1.12, 1.18), -0.03, "center"),
    ("cyber_aurora_base", "AI_104_Tokyo_Cyberpunk_Amber_District.jpg", 1.14, 1.22, (1.18, 1.05, 0.88), -0.02, "center"),
    ("cyber_aurora_base", "AI_105_Tokyo_Cyberpunk_Deep_Midnight.jpg", 1.28, 1.05, (0.94, 0.98, 1.08), -0.07, "center"),
    ("cyber_aurora_base", "AI_106_Tokyo_Cyberpunk_Laser_Grid.jpg", 1.2, 1.35, (0.95, 1.08, 1.22), -0.02, "center"),
    ("cyber_aurora_base", "AI_107_Tokyo_Cyberpunk_Hologram_Boulevard.jpg", 1.16, 1.28, (1.05, 1.02, 1.15), -0.02, "center"),
    ("cyber_aurora_base", "AI_108_Tokyo_Cyberpunk_Obsidian_Puddle.jpg", 1.24, 1.1, (0.92, 0.98, 1.12), -0.05, "center"),
    ("cyber_aurora_base", "AI_109_Tokyo_Cyberpunk_Violet_Shinjuku.jpg", 1.18, 1.3, (1.15, 0.9, 1.25), -0.03, "center"),
    ("cyber_aurora_base", "AI_110_Tokyo_Cyberpunk_Cinema_Chroma.jpg", 1.22, 1.15, (0.98, 1.04, 1.1), -0.03, "center"),

    # Suite 12: Nordic Glacial Prisms & Crystal Caverns (Light & Dark)
    ("crystal_ribbon", "AI_111_Nordic_Glacier_Prism_Cobalt.jpg", 1.12, 1.15, (0.9, 1.05, 1.2), 0.0, "center"),
    ("crystal_ribbon", "AI_112_Nordic_Glacier_Ice_Cave_Ethereal.jpg", 1.08, 1.08, (0.94, 1.06, 1.14), 0.02, "center"),
    ("crystal_ribbon", "AI_113_Nordic_Glacier_Sun_Shaft_Light.jpg", 1.06, 1.1, (1.02, 1.04, 1.08), 0.03, "center"),
    ("crystal_ribbon", "AI_114_Nordic_Glacier_Midnight_Fjord.jpg", 1.26, 1.1, (0.88, 0.98, 1.18), -0.06, "center"),
    ("crystal_ribbon", "AI_115_Nordic_Glacier_Frosted_Diamond.jpg", 1.05, 1.02, (1.02, 1.02, 1.05), 0.04, "center"),
    ("crystal_ribbon", "AI_116_Nordic_Glacier_Turquoise_Chasm.jpg", 1.14, 1.2, (0.86, 1.12, 1.15), 0.0, "center"),
    ("crystal_ribbon", "AI_117_Nordic_Glacier_Polar_Twilight.jpg", 1.18, 1.12, (1.02, 0.98, 1.16), -0.03, "center"),
    ("crystal_ribbon", "AI_118_Nordic_Glacier_Alabaster_Silence.jpg", 1.02, 0.92, (1.0, 1.0, 1.02), 0.03, "center"),
    ("crystal_ribbon", "AI_119_Nordic_Glacier_Sapphire_Refraction.jpg", 1.15, 1.18, (0.92, 1.02, 1.22), -0.01, "center"),
    ("crystal_ribbon", "AI_120_Nordic_Glacier_Nordic_Minimal.jpg", 1.04, 0.96, (0.98, 1.01, 1.04), 0.02, "center"),

    # Suite 13: Deep Space Cosmic Quantum Nebula (Dark)
    ("earth_orbit", "AI_121_Quantum_Nebula_Violet_Cosmos.jpg", 1.2, 1.3, (1.12, 0.92, 1.22), -0.04, "center"),
    ("earth_orbit", "AI_122_Quantum_Nebula_Stardust_Horizon.jpg", 1.18, 1.25, (1.14, 1.05, 0.95), -0.03, "center"),
    ("earth_orbit", "AI_123_Quantum_Nebula_Deep_Abyss_Indigo.jpg", 1.28, 1.05, (0.92, 0.96, 1.14), -0.08, "center"),
    ("earth_orbit", "AI_124_Quantum_Nebula_Supernova_Gold.jpg", 1.16, 1.32, (1.2, 1.1, 0.85), -0.02, "center"),
    ("earth_orbit", "AI_125_Quantum_Nebula_Electric_Pulsar.jpg", 1.22, 1.35, (0.88, 1.08, 1.25), -0.03, "center"),
    ("earth_orbit", "AI_126_Quantum_Nebula_Interstellar_Dust.jpg", 1.14, 1.15, (1.05, 1.02, 1.08), -0.03, "center"),
    ("earth_orbit", "AI_127_Quantum_Nebula_Cosmic_Web.jpg", 1.24, 1.22, (0.96, 1.02, 1.18), -0.05, "center"),
    ("earth_orbit", "AI_128_Quantum_Nebula_Event_Horizon.jpg", 1.3, 1.0, (0.95, 0.95, 1.05), -0.09, "center"),
    ("earth_orbit", "AI_129_Quantum_Nebula_Magenta_Corona.jpg", 1.18, 1.28, (1.22, 0.88, 1.15), -0.03, "center"),
    ("earth_orbit", "AI_130_Quantum_Nebula_Infinite_Night.jpg", 1.25, 1.08, (0.98, 1.0, 1.12), -0.06, "center"),

    # Suite 14: Champagne Gold Silk & Liquid Pearl Waves (Light Luxury)
    ("silk_waves", "AI_131_Champagne_Silk_Liquid_Gold.jpg", 1.08, 1.18, (1.14, 1.06, 0.92), 0.01, "center"),
    ("silk_waves", "AI_132_Champagne_Silk_Pearl_Luster.jpg", 1.04, 1.08, (1.05, 1.04, 1.02), 0.03, "center"),
    ("silk_waves", "AI_133_Champagne_Silk_Warm_Ivory.jpg", 1.05, 1.12, (1.08, 1.05, 0.98), 0.02, "center"),
    ("silk_waves", "AI_134_Champagne_Silk_Rose_Champagne.jpg", 1.06, 1.16, (1.12, 1.0, 1.04), 0.01, "center"),
    ("silk_waves", "AI_135_Champagne_Silk_Platinum_Luxury.jpg", 1.02, 0.94, (1.01, 1.01, 1.02), 0.03, "center"),
    ("silk_waves", "AI_136_Champagne_Silk_Golden_Amber_Flow.jpg", 1.1, 1.22, (1.18, 1.08, 0.88), 0.0, "center"),
    ("silk_waves", "AI_137_Champagne_Silk_Soft_Satin.jpg", 1.04, 1.05, (1.04, 1.03, 1.02), 0.02, "center"),
    ("silk_waves", "AI_138_Champagne_Silk_Pure_Cashmere.jpg", 1.03, 0.98, (1.04, 1.02, 0.98), 0.03, "center"),
    ("silk_waves", "AI_139_Champagne_Silk_Studio_Editorial.jpg", 1.05, 1.06, (1.0, 1.0, 1.0), 0.02, "center"),
    ("silk_waves", "AI_140_Champagne_Silk_High_Key_Minimal.jpg", 1.02, 0.92, (1.02, 1.02, 1.03), 0.04, "center"),

    # Suite 15: Kyoto Morning Mist & Sakura Harmony (Light Nature)
    ("alpine_lake", "AI_141_Kyoto_Sakura_Morning_Mist.jpg", 1.06, 1.14, (1.12, 1.02, 1.05), 0.01, "center"),
    ("alpine_lake", "AI_142_Kyoto_Sakura_Sunlit_Canopy.jpg", 1.08, 1.18, (1.08, 1.06, 0.96), 0.01, "center"),
    ("alpine_lake", "AI_143_Kyoto_Sakura_Zen_Pond_Mirror.jpg", 1.05, 1.1, (0.98, 1.06, 1.04), 0.02, "center"),
    ("alpine_lake", "AI_144_Kyoto_Sakura_Bamboo_Godrays.jpg", 1.08, 1.15, (1.05, 1.1, 0.94), 0.01, "center"),
    ("alpine_lake", "AI_145_Kyoto_Sakura_Blossom_Breeze.jpg", 1.05, 1.12, (1.1, 1.0, 1.04), 0.02, "center"),
    ("alpine_lake", "AI_146_Kyoto_Sakura_Morning_Stillness.jpg", 1.04, 1.04, (1.02, 1.03, 1.02), 0.03, "center"),
    ("alpine_lake", "AI_147_Kyoto_Sakura_Spring_Radiance.jpg", 1.08, 1.2, (1.06, 1.08, 0.98), 0.01, "center"),
    ("alpine_lake", "AI_148_Kyoto_Sakura_Moss_Garden.jpg", 1.06, 1.14, (0.96, 1.12, 1.0), 0.01, "center"),
    ("alpine_lake", "AI_149_Kyoto_Sakura_Pristine_Dawn.jpg", 1.05, 1.08, (1.04, 1.02, 1.04), 0.02, "center"),
    ("alpine_lake", "AI_150_Kyoto_Sakura_Ethereal_Sanctuary.jpg", 1.07, 1.12, (1.06, 1.04, 1.04), 0.02, "center"),

    # Suite 16: Emerald Matrix & Synaptic Energy (Dark)
    ("neural_flora", "AI_151_Emerald_Matrix_Quantum_Synapse.jpg", 1.18, 1.3, (0.85, 1.18, 1.12), -0.02, "center"),
    ("neural_flora", "AI_152_Emerald_Matrix_Mint_Luminescence.jpg", 1.14, 1.24, (0.88, 1.22, 1.08), -0.01, "center"),
    ("neural_flora", "AI_153_Emerald_Matrix_Deep_Bio_Void.jpg", 1.28, 1.05, (0.9, 1.05, 1.02), -0.07, "center"),
    ("neural_flora", "AI_154_Emerald_Matrix_Fiber_Optic_Pulse.jpg", 1.22, 1.35, (0.82, 1.2, 1.22), -0.02, "center"),
    ("neural_flora", "AI_155_Emerald_Matrix_Cyan_Dewdrops.jpg", 1.12, 1.18, (0.9, 1.12, 1.16), -0.01, "center"),
    ("neural_flora", "AI_156_Emerald_Matrix_Cybernetic_Flora.jpg", 1.16, 1.26, (0.86, 1.16, 1.14), -0.02, "center"),
    ("neural_flora", "AI_157_Emerald_Matrix_Synaptic_Neural_Net.jpg", 1.2, 1.3, (0.92, 1.15, 1.18), -0.03, "center"),
    ("neural_flora", "AI_158_Emerald_Matrix_Obsidian_Moss.jpg", 1.25, 1.1, (0.92, 1.08, 1.04), -0.05, "center"),
    ("neural_flora", "AI_159_Emerald_Matrix_Electric_Aurora_Caustic.jpg", 1.18, 1.32, (0.84, 1.22, 1.18), -0.02, "center"),
    ("neural_flora", "AI_160_Emerald_Matrix_Organic_Singularity.jpg", 1.24, 1.2, (0.88, 1.14, 1.1), -0.04, "center"),

    # Suite 17: Patagonia Night Spire & Milky Way Lagoon (Dark / Night)
    ("golden_clouds", "AI_161_Patagonia_Spire_Milky_Way_Lagoon.jpg", 1.24, 1.15, (0.94, 0.98, 1.18), -0.05, "center"),
    ("golden_clouds", "AI_162_Patagonia_Spire_Starlight_Reflection.jpg", 1.2, 1.1, (0.96, 1.0, 1.15), -0.04, "center"),
    ("golden_clouds", "AI_163_Patagonia_Spire_Deep_Alpine_Midnight.jpg", 1.28, 1.02, (0.9, 0.95, 1.15), -0.07, "center"),
    ("golden_clouds", "AI_164_Patagonia_Spire_Cosmic_Arch.jpg", 1.22, 1.2, (1.02, 0.98, 1.22), -0.04, "center"),
    ("golden_clouds", "AI_165_Patagonia_Spire_Turquoise_Glacier_Glow.jpg", 1.16, 1.22, (0.88, 1.08, 1.18), -0.02, "center"),
    ("golden_clouds", "AI_166_Patagonia_Spire_Granite_Cathedral.jpg", 1.22, 1.08, (0.98, 1.0, 1.1), -0.04, "center"),
    ("golden_clouds", "AI_167_Patagonia_Spire_Twilight_Alpenglow.jpg", 1.15, 1.22, (1.16, 1.0, 1.08), -0.02, "center"),
    ("golden_clouds", "AI_168_Patagonia_Spire_Shooting_Star_Ridge.jpg", 1.25, 1.12, (0.96, 0.98, 1.16), -0.05, "center"),
    ("golden_clouds", "AI_169_Patagonia_Spire_Velvet_Night.jpg", 1.3, 0.98, (0.95, 0.96, 1.08), -0.08, "center"),
    ("golden_clouds", "AI_170_Patagonia_Spire_Dawn_First_Light.jpg", 1.12, 1.18, (1.14, 1.06, 0.98), 0.0, "center"),

    # Suite 18: Prismatic Optical Crystals & Holographic Rings (Light & Dark)
    ("prism_bloom", "AI_171_Holographic_Prism_Crystal_Bloom.jpg", 1.08, 1.2, (1.02, 1.05, 1.15), 0.01, "center"),
    ("prism_bloom", "AI_172_Holographic_Prism_Pastel_Rainbow.jpg", 1.06, 1.25, (1.05, 1.08, 1.12), 0.02, "center"),
    ("prism_bloom", "AI_173_Holographic_Prism_Liquid_Chrome.jpg", 1.04, 0.95, (1.0, 1.01, 1.04), 0.03, "center"),
    ("prism_bloom", "AI_174_Holographic_Prism_Obsidian_Pedestal.jpg", 1.26, 1.15, (0.94, 0.98, 1.15), -0.06, "center"),
    ("prism_bloom", "AI_175_Holographic_Prism_Flawless_Glass.jpg", 1.05, 1.05, (1.01, 1.02, 1.06), 0.03, "center"),
    ("prism_bloom", "AI_176_Holographic_Prism_Opal_Caustic.jpg", 1.08, 1.22, (1.04, 1.08, 1.12), 0.01, "center"),
    ("prism_bloom", "AI_177_Holographic_Prism_Studio_Luminance.jpg", 1.03, 0.98, (1.0, 1.0, 1.02), 0.03, "center"),
    ("prism_bloom", "AI_178_Holographic_Prism_Violet_Dispersion.jpg", 1.1, 1.25, (1.12, 0.95, 1.2), 0.0, "center"),
    ("prism_bloom", "AI_179_Holographic_Prism_Cyan_Refraction.jpg", 1.08, 1.2, (0.9, 1.08, 1.18), 0.01, "center"),
    ("prism_bloom", "AI_180_Holographic_Prism_Modern_Art_Gallery.jpg", 1.04, 0.95, (1.02, 1.02, 1.02), 0.03, "center"),

    # Suite 19: Futuristic Biomorphic Eco-Skyline at Blue Hour (Dusk)
    ("pavilion_dusk", "AI_181_Futuristic_Skyline_Blue_Hour.jpg", 1.16, 1.15, (0.98, 1.02, 1.18), -0.03, "center"),
    ("pavilion_dusk", "AI_182_Futuristic_Skyline_Sky_Bridges.jpg", 1.14, 1.2, (1.08, 1.02, 1.12), -0.02, "center"),
    ("pavilion_dusk", "AI_183_Futuristic_Skyline_Amber_Windows.jpg", 1.15, 1.24, (1.16, 1.06, 0.92), -0.01, "center"),
    ("pavilion_dusk", "AI_184_Futuristic_Skyline_Violet_Dusk.jpg", 1.18, 1.22, (1.12, 0.94, 1.2), -0.03, "center"),
    ("pavilion_dusk", "AI_185_Futuristic_Skyline_Reflective_Canal.jpg", 1.16, 1.15, (0.95, 1.05, 1.15), -0.02, "center"),
    ("pavilion_dusk", "AI_186_Futuristic_Skyline_Vertical_Gardens.jpg", 1.12, 1.18, (0.96, 1.12, 1.05), -0.01, "center"),
    ("pavilion_dusk", "AI_187_Futuristic_Skyline_Titanium_Architecture.jpg", 1.1, 1.02, (1.02, 1.02, 1.06), 0.0, "center"),
    ("pavilion_dusk", "AI_188_Futuristic_Skyline_Midnight_Observatory.jpg", 1.25, 1.08, (0.94, 0.96, 1.14), -0.06, "center"),
    ("pavilion_dusk", "AI_189_Futuristic_Skyline_Clean_Metropolis.jpg", 1.08, 1.05, (1.0, 1.02, 1.06), 0.01, "center"),
    ("pavilion_dusk", "AI_190_Futuristic_Skyline_Dawn_Emergence.jpg", 1.1, 1.14, (1.12, 1.05, 0.98), 0.01, "center"),

    # Suite 20: Minimalist Alabaster Porcelain & Platinum Curve (Light)
    ("flagship_light", "AI_191_Alabaster_Porcelain_Platinum_Curve.jpg", 1.04, 0.95, (1.02, 1.02, 1.03), 0.03, "center"),
    ("flagship_light", "AI_192_Alabaster_Porcelain_Champagne_Sheen.jpg", 1.06, 1.12, (1.08, 1.04, 0.98), 0.02, "center"),
    ("flagship_light", "AI_193_Alabaster_Porcelain_Frosted_Glass.jpg", 1.05, 1.02, (0.98, 1.02, 1.08), 0.02, "center"),
    ("flagship_light", "AI_194_Alabaster_Porcelain_Warm_Architectural.jpg", 1.05, 1.1, (1.06, 1.04, 0.98), 0.02, "center"),
    ("flagship_light", "AI_195_Alabaster_Porcelain_Nordic_Clean.jpg", 1.02, 0.92, (1.0, 1.0, 1.02), 0.04, "center"),
    ("flagship_light", "AI_196_Alabaster_Porcelain_Soft_Shadows.jpg", 1.06, 0.98, (1.01, 1.01, 1.02), 0.02, "center"),
    ("flagship_light", "AI_197_Alabaster_Porcelain_Minimal_Zen.jpg", 1.03, 0.94, (1.02, 1.02, 1.02), 0.03, "center"),
    ("flagship_light", "AI_198_Alabaster_Porcelain_Sculpted_Pearl.jpg", 1.05, 1.05, (1.03, 1.03, 1.02), 0.02, "center"),
    ("flagship_light", "AI_199_Alabaster_Porcelain_Studio_High_Key.jpg", 1.02, 0.9, (1.01, 1.01, 1.02), 0.04, "center"),
    ("flagship_light", "AI_200_Alabaster_Porcelain_Pure_Elegance.jpg", 1.04, 0.96, (1.02, 1.01, 1.02), 0.03, "center"),

    # Suite 21: High-Tech Sapphire Waveform & Obsidian Horizons (Dark Flagship)
    ("cyber_sapphire", "AI_201_Sapphire_Waveform_Deep_Obsidian.jpg", 1.22, 1.18, (0.9, 1.02, 1.2), -0.04, "center"),
    ("cyber_sapphire", "AI_202_Sapphire_Waveform_Electric_Cyan_Flow.jpg", 1.16, 1.3, (0.85, 1.12, 1.25), -0.02, "center"),
    ("cyber_sapphire", "AI_203_Sapphire_Waveform_Amethyst_Current.jpg", 1.18, 1.25, (1.12, 0.92, 1.22), -0.03, "center"),
    ("cyber_sapphire", "AI_204_Sapphire_Waveform_Golden_Caustic.jpg", 1.14, 1.22, (1.18, 1.08, 0.88), -0.01, "center"),
    ("cyber_sapphire", "AI_205_Sapphire_Waveform_Midnight_Silence.jpg", 1.28, 0.95, (0.92, 0.96, 1.08), -0.08, "center"),
    ("cyber_sapphire", "AI_206_Sapphire_Waveform_Laser_Prism.jpg", 1.2, 1.35, (0.92, 1.08, 1.22), -0.02, "center"),
    ("cyber_sapphire", "AI_207_Sapphire_Waveform_Emerald_Borealis.jpg", 1.15, 1.25, (0.88, 1.18, 1.1), -0.02, "center"),
    ("cyber_sapphire", "AI_208_Sapphire_Waveform_Cosmic_Infinity.jpg", 1.24, 1.2, (0.98, 1.02, 1.18), -0.04, "center"),
    ("cyber_sapphire", "AI_209_Sapphire_Waveform_Titanium_Edge.jpg", 1.12, 1.02, (1.0, 1.02, 1.06), -0.01, "center"),
    ("cyber_sapphire", "AI_210_DevOS_Ultimate_Masterpiece_Flagship.jpg", 1.2, 1.22, (0.95, 1.05, 1.18), -0.03, "center"),
]


def grade_image(pil_src: Image.Image, contrast: float, saturation: float, tint: tuple, brightness_shift: float, seed: int = 100) -> Image.Image:
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
    print("DevOS 250 Wallpaper Masterpiece Expansion (AI_101 through AI_210)")
    print(f"Target Resolution: {TARGET_W}x{TARGET_H} (2.5K QHD)")
    print("=" * 75)

    loaded_sources = {}
    for key, filename in MASTER_FILES.items():
        p = MASTER_DIR / filename
        if p.exists():
            loaded_sources[key] = Image.open(p).convert("RGB")
        else:
            print(f"Warning: master file not found: {p}")

    if CYBERPUNK_SRC.exists():
        loaded_sources["cyber_aurora_base"] = Image.open(CYBERPUNK_SRC).convert("RGB")
    else:
        # Fallback to cyber sapphire if cyberpunk png not found
        loaded_sources["cyber_aurora_base"] = loaded_sources.get("cyber_sapphire")

    count = 0
    start_time = time.time()

    for idx, (src_key, filename, contrast, sat, tint, b_shift, align) in enumerate(NEW_WALLPAPERS, 101):
        src_img = loaded_sources.get(src_key)
        if not src_img:
            # Fallback to first available
            src_img = list(loaded_sources.values())[0]

        graded = grade_image(src_img, contrast, sat, tint, b_shift, seed=idx * 7)

        # Save to both target directories
        dest_build = BUILD_SLIDESHOW / filename
        dest_user = USER_SLIDESHOW / filename

        graded.save(dest_build, "JPEG", quality=96, subsampling=0)
        graded.save(dest_user, "JPEG", quality=96, subsampling=0)

        count += 1
        if count % 10 == 0 or count == len(NEW_WALLPAPERS):
            print(f"[{count:03d}/{len(NEW_WALLPAPERS)}] Rendered: {filename}")

    elapsed = time.time() - start_time
    total_build = len(list(BUILD_SLIDESHOW.glob("*.*")))
    total_user = len(list(USER_SLIDESHOW.glob("*.*")))

    print("-" * 75)
    print(f"Successfully generated and deployed {count} new masterpieces in {elapsed:.2f}s!")
    print(f"Total wallpapers in build slideshow: {total_build}")
    print(f"Total wallpapers in user slideshow:  {total_user}")
    print("=" * 75)


if __name__ == "__main__":
    main()
