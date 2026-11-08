#!/usr/bin/env python3
"""Package generated originals into multi-size Plasma wallpaper packages."""
import html
import json
from pathlib import Path
import shutil
import struct

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DEST = ROOT / 'build/includes.chroot/usr/share/wallpapers'

# Common desktop + laptop sizes. Portrait flagships may already include phone sizes.
LANDSCAPE_SIZES = (
    (1280, 720), (1280, 800), (1366, 768), (1440, 900), (1680, 1050),
    (1920, 1080), (2560, 1440), (2560, 1600), (3840, 2160),
)


def png_size(path: Path):
    with path.open('rb') as stream:
        header = stream.read(24)
    if header[:8] != b'\x89PNG\r\n\x1a\n' or header[12:16] != b'IHDR':
        raise ValueError(f'Invalid PNG: {path}')
    width, height = struct.unpack('>II', header[16:24])
    if not width or not height:
        raise ValueError(f'Invalid PNG dimensions: {path}')
    return width, height


def main():
    try:
        from PIL import Image  # optional; used only to refresh cover crops
    except ImportError:
        Image = None

    manifest = json.loads((HERE / 'manifest.json').read_text())
    cards = []
    for item in manifest:
        source = ROOT / item['source']
        package = DEST / item['package']
        images = package / 'contents/images'
        images.mkdir(parents=True, exist_ok=True)
        width, height = png_size(source)
        filename = f'{width}x{height}.png'
        target = images / filename
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        legacy = images / 'wallpaper.png'
        shutil.copy2(target, legacy)
        shutil.copy2(target, package / 'contents/screenshot.png')

        if Image is not None:
            master = Image.open(target).convert('RGB')
            for tw, th in LANDSCAPE_SIZES:
                out = images / f'{tw}x{th}.png'
                if out.exists() and out.resolve() == target.resolve():
                    continue
                scale = max(tw / master.width, th / master.height)
                nw, nh = int(master.width * scale), int(master.height * scale)
                resized = master.resize((nw, nh), Image.Resampling.LANCZOS)
                left = max(0, (nw - tw) // 2)
                top = max(0, (nh - th) // 2)
                cropped = resized.crop((left, top, left + tw, top + th))
                cropped.save(out, format='PNG', optimize=True)

        (package / 'metadata.json').write_text(json.dumps({'KPlugin': {
            'Id': item['package'], 'Name': 'DevOS Premium · ' + item['name'],
            'Authors': [{'Name': 'Imran Ahmed', 'Email': 'me@imrandev.bd'}],
            'Website': 'https://imrandev.bd',
            'Description': 'DevOS homepage-ready premium wallpaper with multi-size covers.'
        }}, indent=2) + '\n')
        relative = '../../../build/includes.chroot/usr/share/wallpapers/' + item['package'] + '/contents/images/' + filename
        cards.append(
            f'<a href="{relative}"><img loading="lazy" src="{relative}" alt="{html.escape(item["name"])}">'
            f'<span>{item["id"]} — {html.escape(item["name"])}</span></a>'
        )
        item['width'], item['height'] = width, height

    (HERE / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (HERE / 'gallery.html').write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>DevOS Premium Collection</title><style>'
        'body{margin:0;padding:48px;background:#070910;color:#eff4ff;font:16px system-ui}'
        'h1{font-size:40px;letter-spacing:-.04em;margin-bottom:8px}'
        'p{color:#acbdd5;margin-bottom:36px}'
        '.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}'
        'a{color:inherit;text-decoration:none;background:#0f172a;border:1px solid #243247;'
        'border-radius:16px;overflow:hidden}'
        'img{display:block;width:100%;aspect-ratio:16/9;object-fit:cover}'
        'span{display:block;padding:18px}'
        'a:focus-visible{outline:3px solid #7dd3fc}a:hover{border-color:#38bdf8}'
        '@media(max-width:600px){body{padding:20px}}'
        '</style><h1>DevOS Premium · Home Collection</h1>'
        '<p>20 original wallpapers tuned to DevOS cyan/sapphire branding · '
        'Multi-size packages for phones, laptops and 4K · Click to view the master.</p>'
        '<div class="grid">' + ''.join(cards) + '</div></html>'
    )


if __name__ == '__main__':
    main()
