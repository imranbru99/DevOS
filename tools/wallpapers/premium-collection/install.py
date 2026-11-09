#!/usr/bin/env python3
"""Install the curated wallpapers for the current user; optionally apply one."""
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
    selection.add_argument('--select', choices=[f'{i:02d}' for i in range(1, 51)], help='Apply a specific collection entry, such as 50 for Apex Bloom')
    selection.add_argument('--apply', choices=['light', 'dark'], help='Apply Pearl Dawn (light) or Cyan Orbit (dark) to all Plasma desktops')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    manifest = json.loads(Path(__file__).with_name('manifest.json').read_text())
    destination = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'wallpapers'
    for item in manifest:
        source = root / 'build/includes.chroot/usr/share/wallpapers' / item['package']
        filename = f"{item['width']}x{item['height']}.png"
        if not (source / 'contents/images' / filename).is_file():
            parser.error(f'Missing artwork: {source}')
    for item in manifest:
        source = root / 'build/includes.chroot/usr/share/wallpapers' / item['package']
        shutil.copytree(source, destination / item['package'], dirs_exist_ok=True)
    print(f'Installed {len(manifest)} wallpapers in {destination}')
    if args.apply or args.select:
        qdbus = shutil.which('qdbus6') or shutil.which('qdbus')
        if not qdbus:
            parser.error('Wallpapers installed. Open Desktop Settings to choose one; qdbus is unavailable.')
        if args.select:
            selected = next(item for item in manifest if item['id'] == args.select)
        else:
            # light = Pearl Dawn (08), dark = Cyan Orbit (01)
            want = '08' if args.apply == 'light' else '01'
            selected = next(item for item in manifest if item['id'] == want)
        # Use the same package URL as Plasma's picker, not a direct-image bypass.
        image = (destination / selected['package']).as_uri() + '/'
        script = '''var screens=desktops(); for(var i=0;i<screens.length;i++) {
var d=screens[i]; d.currentConfigGroup=["Wallpaper",d.wallpaperPlugin,"General"];
var previous=d.readConfig("Image", ""); var plugin=d.wallpaperPlugin;
d.currentConfigGroup=["DevOSPremiumBackup"];
if(!d.readConfig("Saved",false)){d.writeConfig("Image",previous);d.writeConfig("Plugin",plugin);d.writeConfig("Saved",true);}
d.wallpaperPlugin="org.kde.image";d.currentConfigGroup=["Wallpaper","org.kde.image","General"];
d.writeConfig("Image",IMAGE);d.writeConfig("FillMode",2);
}'''.replace('IMAGE', json.dumps(image))
        # A repaired package can already be selected from the failed attempt.
        # Force a URL change so the live backend resolves its new image file.
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
