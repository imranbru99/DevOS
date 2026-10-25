# DevOS wallpapers

`make_wallpapers.py` procedurally renders 80 DevOS premium wallpapers
(20 designs, each in four palettes). numpy + Pillow only, fixed seeds, so the
output is reproducible.

`make_ai_era_wallpapers.py` procedurally renders 100 AI-era ultra-premium QHD
wallpapers (2560x1440) across 10 futuristic themes (Neural Synapses, Quantum Silicon,
Cyberpunk Megacities, Latent Diffusion, Bio-Synthetic Organics, Dyson Computing, Liquid
Titanium, Holographic Auroras, Algorithmic Architecture, and Audio Synthesis). All 100
are deployed to the `DevOS-Slideshow` suite for dynamic KDE Plasma desktop cycling.

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
