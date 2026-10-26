# DevOS wallpapers

`make_wallpapers.py` procedurally renders 80 DevOS premium wallpapers
(20 designs, each in four palettes). numpy + Pillow only, fixed seeds, so the
output is reproducible.

`make_ai_era_wallpapers.py` renders the 100 AI-era masterpiece QHD wallpapers
(2560x1440) across 10 flagship themes with dedicated Dark and Light editions:
1. Flagship 3D Fluid Glass Ribbon (Dark Series: AI_001 - AI_010)
2. Flagship Frosted Crystal Infinity Ribbon (Light Series: AI_011 - AI_020)
3. Cyber Sapphire Aurora Wave (Dark Series: AI_021 - AI_030)
4. Cyber Fluid Silk Waves (Light Series: AI_031 - AI_040)
5. Golden Cloudscape & Alpine Mirror Lake (Warm Sunset Series: AI_041 - AI_050)
6. Alpine Lake & Blooming Wildflowers (Daylight / Light Series: AI_051 - AI_060)
7. Cosmic Earth Orbit & Golden City Lights (Night / Space Series: AI_061 - AI_070)
8. Frosted Prism Floral Bloom (Light Series: AI_071 - AI_080)
9. Bioluminescent Neural Flora (Dark Series: AI_081 - AI_090)
10. Futuristic Architectural Pavilion & Desert Dunes (Dusk Series: AI_091 - AI_100)

All 100 wallpapers are processed from photorealistic 8K AI master renders with
unsharp-mask clarity, cinematic color grading, desktop icon safe-zone contrast,
and film-grain dithering for both Dark and Light theme desktop harmony.

Each design is rendered at 2560x1440 or 3840x2160, tone-mapped with photographic
S-curves, ergonomically protected for desktop icon contrast, film-grain dithered, and
saved as KDE Plasma wallpaper packages:

    build/includes.chroot/usr/share/wallpapers/DevOS-<Name>/
        metadata.json
        contents/images/2560x1440.jpg
        contents/screenshot.jpg

    build/includes.chroot/usr/share/wallpapers/DevOS-Slideshow/
        01_...
        ...
        AI_001_Neural_Synapse_Matrix.jpg
        ...
        AI_100_Sonic_Singularity_Dawn.jpg

`preview.jpg` in this folder is a contact sheet for review only; it is not
installed into the image.

## Regenerate AI-Era Wallpapers

Run locally or via Docker:

    python tools/wallpapers/make_ai_era_wallpapers.py

All 100 AI-era wallpapers are generated and synchronized to both the OS build tree
(`build/includes.chroot/usr/share/wallpapers/DevOS-Slideshow/`) and the live host
desktop environment (`~/.local/share/wallpapers/DevOS-Slideshow/`).

## Regenerate Base Wallpapers

No Python is needed on the host; run it in Docker from the repo root:

    MSYS_NO_PATHCONV=1 docker run --rm -v "C:/docker/DevOS:/w" -w /w python:3.12-slim \
      sh -c 'pip -q install numpy pillow && python tools/wallpapers/make_wallpapers.py'

Options:

- `--only AuroraVeil,NebulaDrift` renders just those designs (CamelCase names).
- `--quality 84` lowers JPEG quality if the image size budget gets tight.
- `--no-sheet` skips rebuilding `preview.jpg`.

The script prints each file's size and the mean luminance of the top 15% and
bottom 8% of the image (both must stay below 0.25 so icon labels and the panel
stay readable). A full run takes about 2-3 minutes.
