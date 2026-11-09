#!/usr/bin/env python3
"""Ingest generated DevOS home wallpapers into Plasma packages + manifest."""
from __future__ import annotations

import json
import re
import shutil
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
ASSETS = Path.home() / ".cursor/projects/c-Users-USER-Documents-dev-os/assets"
# Fallback if Agent runs with different home layout
ALT_ASSETS = Path(r"C:/Users/USER/.cursor/projects/c-Users-USER-Documents-dev-os/assets")
DEST = ROOT / "build/includes.chroot/usr/share/wallpapers"
ORIGINALS = HERE / "originals"
LANDSCAPE = (
    (1280, 720), (1280, 800), (1366, 768), (1440, 900), (1680, 1050),
    (1920, 1080), (2560, 1440), (2560, 1600), (3840, 2160),
)


def png_size(path: Path):
    with path.open("rb") as stream:
        header = stream.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError(f"Invalid PNG: {path}")
    return struct.unpack(">II", header[16:24])


def main():
    try:
        from PIL import Image
    except ImportError as exc:
        raise SystemExit("Pillow required: pip install pillow") from exc

    prompts = json.loads((HERE / "prompts-50.json").read_text(encoding="utf-8"))["prompts"]
    assets = ASSETS if ASSETS.is_dir() else ALT_ASSETS
    ORIGINALS.mkdir(parents=True, exist_ok=True)
    DEST.mkdir(parents=True, exist_ok=True)

    manifest = []
    missing = []
    for item in prompts:
        iid = item["id"]
        slug = item["slug"]
        name = item["name"]
        camel = "".join(p.title() for p in slug.split("-"))
        package = f"DevOS-Home50-{iid}-{camel}"
        candidates = sorted(assets.glob(f"devos-home-{iid}-*.jpg")) + sorted(
            assets.glob(f"devos-home-{iid}-*.png")
        )
        if not candidates:
            missing.append(iid)
            continue
        src = candidates[0]
        master_jpg = ORIGINALS / f"devos-home50-{iid}-{slug}.jpg"
        shutil.copy2(src, master_jpg)

        package_dir = DEST / package
        if package_dir.exists():
            shutil.rmtree(package_dir, ignore_errors=True)
        images_dir = package_dir / "contents/images"
        images_dir.mkdir(parents=True, exist_ok=True)
        img = Image.open(src).convert("RGB")

        def save_cover(target: Path, w: int, h: int) -> None:
            scale = max(w / img.width, h / img.height)
            nw, nh = int(img.width * scale), int(img.height * scale)
            r = img.resize((nw, nh), Image.Resampling.LANCZOS)
            l = max(0, (nw - w) // 2)
            t = max(0, (nh - h) // 2)
            cropped = r.crop((l, t, l + w, t + h))
            tmp = target.with_suffix(".tmp.png")
            cropped.save(tmp, format="PNG")
            tmp.replace(target)

        tw, th = 1920, 1080
        master_path = images_dir / "wallpaper.png"
        save_cover(master_path, tw, th)
        save_cover(images_dir / f"{tw}x{th}.png", tw, th)
        save_cover(package_dir / "contents/screenshot.png", tw, th)
        for w, h in LANDSCAPE:
            if (w, h) == (tw, th):
                continue
            save_cover(images_dir / f"{w}x{h}.png", w, h)

        (DEST / package / "metadata.json").write_text(
            json.dumps(
                {
                    "KPlugin": {
                        "Id": package,
                        "Name": f"DevOS Premium · {name}",
                        "Authors": [{"Name": "Imran Ahmed", "Email": "me@imrandev.bd"}],
                        "Website": "https://imrandev.bd",
                        "Description": "DevOS homepage premium wallpaper — cyan/sapphire OS brand.",
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        width, height = png_size(master_path)
        sizes = sorted({p.stem for p in images_dir.glob("*.png")})
        manifest.append(
            {
                "id": iid,
                "name": name,
                "prompt": item["prompt"],
                "package": package,
                "source": str(
                    Path("build/includes.chroot/usr/share/wallpapers")
                    / package
                    / "contents/images/wallpaper.png"
                ).replace("\\", "/"),
                "width": width,
                "height": height,
                "sizes": sizes,
            }
        )
        print(f"OK {iid} {name} -> {package}")

    if missing:
        print("MISSING:", ", ".join(missing))
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    cards = []
    for item in manifest:
        rel = f"../../../{item['source']}"
        cards.append(
            f'<a href="{rel}"><img loading="lazy" src="{rel}" alt="{item["name"]}">'
            f'<span>{item["id"]} — {item["name"]}</span></a>'
        )
    (HERE / "gallery.html").write_text(
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>DevOS Premium 50</title><style>"
        "body{margin:0;padding:48px;background:#070910;color:#eff4ff;font:16px system-ui}"
        "h1{font-size:40px;letter-spacing:-.04em;margin-bottom:8px}"
        "p{color:#acbdd5;margin-bottom:36px}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}"
        "a{color:inherit;text-decoration:none;background:#0f172a;border:1px solid #243247;"
        "border-radius:16px;overflow:hidden}"
        "img{display:block;width:100%;aspect-ratio:16/9;object-fit:cover}"
        "span{display:block;padding:18px}"
        "a:hover{border-color:#38bdf8}"
        "</style><h1>DevOS Premium · 50 Homepage Wallpapers</h1>"
        "<p>Ultra-premium cyan/sapphire collection designed to outshine stock Windows Bloom.</p>"
        f'<div class="grid">{"".join(cards)}</div></html>',
        encoding="utf-8",
    )
    (HERE / "README.md").write_text(
        "# DevOS Premium · 50 Homepage Wallpapers\n\n"
        "Fifty ultra-premium wallpapers for the DevOS homepage and desktop — "
        "cyan/sapphire/obsidian brand language, calm icon-safe left zones, "
        "cinematic lighting meant to feel more premium than stock Windows Bloom.\n\n"
        "Open `gallery.html` to browse.\n\n"
        "## Install on this PC\n\n"
        "```sh\n"
        "python3 tools/wallpapers/premium-collection/install.py\n"
        "python3 tools/wallpapers/premium-collection/install.py --select 50\n"
        "```\n",
        encoding="utf-8",
    )
    print(f"Packaged {len(manifest)} / 50 wallpapers into {DEST}")


if __name__ == "__main__":
    main()
