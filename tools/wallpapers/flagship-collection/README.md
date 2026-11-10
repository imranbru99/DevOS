# DevOS Flagship Wallpaper Collection

Additive redesign of the DevOS wallpaper library: cyan `#38bdf8` on graphite, subject-aware masters, Plasma packages that sit **beside** legacy Home50/Premium sets (originals preserved).

## Quick paths

| Artifact | Path |
|----------|------|
| Creative direction | `docs/CREATIVE_DIRECTION.md` |
| Audit inventory | `docs/inventory-audit.json` |
| QA / session report | `docs/FLAGSHIP_REPORT.md` |
| Progress / resume | `progress-manifest.json`, `progress-summary.json`, `remaining-ids.json` |
| Redesigned masters | `redesigned/masters/` |
| Lazy thumbs | `redesigned/thumbs/` |
| Reversible mapping | `mapping.json` |
| Ship manifest | `manifest.json` |
| Gallery | `gallery.html` |
| Package script | `scripts/package-flagship.ps1` |
| User install | `install.py` |
| Plasma packages | `build/includes.chroot/usr/share/wallpapers/DevOS-Flagship-*` |

## Install (Linux / DevOS)

```sh
python3 tools/wallpapers/flagship-collection/install.py
python3 tools/wallpapers/flagship-collection/install.py --apply dark   # Cyan Orbit
python3 tools/wallpapers/flagship-collection/install.py --apply light  # Pearl Dawn
python3 tools/wallpapers/flagship-collection/install.py --select home50-50
```

## Re-package after new masters (Windows host)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/wallpapers/flagship-collection/scripts/package-flagship.ps1
```

## Honesty notes

- GenerateImage masters in this session are **1280×720**. Plasma `3840x2160.png` files are **covers/upscales for picker compatibility**, not native 4K detail.
- Full library redesign is **batch-incomplete**; see `remaining-ids.json`.
