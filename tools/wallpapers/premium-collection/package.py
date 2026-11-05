#!/usr/bin/env python3
"""Package generated originals without resampling or altering the artwork."""
import html
import json
from pathlib import Path
import shutil
import struct

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DEST = ROOT / 'build/includes.chroot/usr/share/wallpapers'


def main():
    manifest = json.loads((HERE / 'manifest.json').read_text())
    cards = []
    for item in manifest:
        source = ROOT / item['source']
        package = DEST / item['package']
        images = package / 'contents/images'
        images.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as stream:
            header = stream.read(24)
        if header[:8] != b'\x89PNG\r\n\x1a\n' or header[12:16] != b'IHDR':
            raise ValueError(f'Invalid PNG: {source}')
        width, height = struct.unpack('>II', header[16:24])
        if not width or not height:
            raise ValueError(f'Invalid PNG dimensions: {source}')
        filename = f'{width}x{height}.png'
        target = images / filename
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        # Keep earlier direct-file selections working while Plasma uses the resolution file.
        legacy = images / 'wallpaper.png'
        if not legacy.exists():
            shutil.copy2(target, legacy)
        shutil.copy2(target, package / 'contents/screenshot.png')
        (package / 'metadata.json').write_text(json.dumps({'KPlugin': {
            'Id': item['package'], 'Name': 'DevOS Premium · ' + item['name'],
            'Authors': [{'Name': 'Imran Ahmed', 'Email': 'me@imrandev.bd'}],
            'Website': 'https://imrandev.bd',
            'Description': 'Original AI-generated desktop artwork for DevOS.'
        }}, indent=2) + '\n')
        relative = '../../../build/includes.chroot/usr/share/wallpapers/' + item['package'] + '/contents/images/' + filename
        cards.append(f'<a href="{relative}"><img loading="lazy" src="{relative}" alt="{html.escape(item["name"])}"><span>{item["id"]} — {html.escape(item["name"])}</span></a>')
    (HERE / 'gallery.html').write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DevOS Premium Collection</title><style>
body{margin:0;padding:48px;background:#0b1020;color:#eff4ff;font:16px system-ui}h1{font-size:40px;letter-spacing:-.04em;margin-bottom:8px}p{color:#acbdd5;margin-bottom:36px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}a{color:inherit;text-decoration:none;background:#172135;border:1px solid #2d3d55;border-radius:16px;overflow:hidden}img{display:block;width:100%;aspect-ratio:16/9;object-fit:cover}span{display:block;padding:18px}a:focus-visible{outline:3px solid #7dd3fc}a:hover{border-color:#7dd3fc}@media(max-width:600px){body{padding:20px}}
</style><h1>A new atmosphere for DevOS.</h1><p>20 original wallpapers · Glass, silk, stone and quiet landscapes · Click to view the original.</p><div class="grid">''' + ''.join(cards) + '</div></html>')


if __name__ == '__main__':
    main()
