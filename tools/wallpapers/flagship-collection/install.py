#!/usr/bin/env python3
"""Install DevOS Flagship wallpapers for the current user; optionally apply one.

Additive install — does not remove legacy Home50/Premium packages.
Uses Plasma package URLs (same as the picker), with a reversible backup key.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        '--select',
        help='Apply a flagship id from manifest.json (e.g. home50-01 or master-alpine)',
    )
    selection.add_argument(
        '--apply',
        choices=['light', 'dark'],
        help='Apply Pearl Dawn (light) or Cyan Orbit (dark)',
    )
    args = parser.parse_args()

    here = Path(__file__).resolve().parent
    root = here.parents[2]
    manifest = json.loads((here / 'manifest.json').read_text())
    items = manifest['items'] if isinstance(manifest, dict) else manifest
    destination = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'wallpapers'

    for item in items:
        source = root / 'build/includes.chroot/usr/share/wallpapers' / item['package']
        if not (source / 'contents/images/wallpaper.png').is_file():
            parser.error(f'Missing artwork: {source}')
        shutil.copytree(source, destination / item['package'], dirs_exist_ok=True)

    print(f"Installed {len(items)} flagship wallpapers in {destination}")

    if not (args.apply or args.select):
        return

    qdbus = shutil.which('qdbus6') or shutil.which('qdbus')
    if not qdbus:
        parser.error('Wallpapers installed. Open Desktop Settings to choose one; qdbus is unavailable.')

    if args.select:
        selected = next((item for item in items if item['id'] == args.select), None)
        if not selected:
            parser.error(f'Unknown id {args.select}')
    else:
        want = 'home50-08' if args.apply == 'light' else 'home50-01'
        selected = next(item for item in items if item['id'] == want)

    image = (destination / selected['package']).as_uri() + '/'
    script = '''var screens=desktops(); for(var i=0;i<screens.length;i++) {
var d=screens[i]; d.currentConfigGroup=["Wallpaper",d.wallpaperPlugin,"General"];
var previous=d.readConfig("Image", ""); var plugin=d.wallpaperPlugin;
d.currentConfigGroup=["DevOSFlagshipBackup"];
if(!d.readConfig("Saved",false)){d.writeConfig("Image",previous);d.writeConfig("Plugin",plugin);d.writeConfig("Saved",true);}
d.wallpaperPlugin="org.kde.image";d.currentConfigGroup=["Wallpaper","org.kde.image","General"];
d.writeConfig("Image",IMAGE);d.writeConfig("FillMode",2);
}'''.replace('IMAGE', json.dumps(image))

    direct = (destination / selected['package'] / 'contents/images' /
              f"{selected['width']}x{selected['height']}.png").as_uri()
    refresh = '''var screens=desktops(); for(var i=0;i<screens.length;i++) {
var d=screens[i]; d.currentConfigGroup=["Wallpaper",d.wallpaperPlugin,"General"];
if(d.readConfig("Image", "")===PACKAGE){d.writeConfig("Image",DIRECT);}
}'''.replace('PACKAGE', json.dumps(image)).replace('DIRECT', json.dumps(direct))

    command = [qdbus, 'org.kde.plasmashell', '/PlasmaShell', 'org.kde.PlasmaShell.evaluateScript']
    subprocess.run(command + [refresh], check=True)
    time.sleep(0.3)
    subprocess.run(command + [script], check=True)
    print('Applied ' + selected['name'])


if __name__ == '__main__':
    main()
