# DevOS Premium Collection

Twenty individually generated original wallpapers, created with the built-in
image generation tool. These are wallpaper assets, not screenshots of implemented
OS interfaces. The collection combines glass and satin sculptures with quiet
landscape photography styles; each artwork has its own description in `manifest.json` and its exact generation
prompt in `prompts.json`.
No design is produced by recoloring another entry.

Open `gallery.html` to compare the collection and click an image for the original.
Original images are retained at the dimensions returned by the generator; they
are not upscaled or advertised as native 4K. Plasma scales them to the display.

## Use on this computer

From the repository root:

```sh
python3 tools/wallpapers/premium-collection/install.py
```

Then right-click the desktop, open wallpaper settings and choose a **DevOS Premium**
entry. To install and immediately select a flagship on all Plasma desktops:

```sh
python3 tools/wallpapers/premium-collection/install.py --apply light
# Or use Sapphire Bloom:
python3 tools/wallpapers/premium-collection/install.py --apply dark
```

The installer copies only this collection into the current user's wallpaper
folder. It does not replace the panel, remove shortcuts or restart Plasma. When
applying a wallpaper, it stores the original image/plugin in each desktop's
`DevOSPremiumBackup` configuration group. Existing wallpaper files stay intact.

## Build integration

Each artwork is a separate package under
`build/includes.chroot/usr/share/wallpapers/DevOS-Premium-*` with its own metadata,
original PNG and preview. These packages ship with the next built image. The
DevOS light-mode switcher prefers Pearl Fold when available, falls back to the
legacy Daylight image on older installations, and preserves other manually
selected premium designs.

`package.py` copies the manifest's sources into Plasma packages without modifying
image content. For repeatable packaging, the completed manifest references the
repository copies rather than the image generator's private output folder.

Developer: [Imran Ahmed](https://imrandev.bd) <me@imrandev.bd>.


## Plasma picker compatibility

Plasma resolves package images using a `WIDTHxHEIGHT` filename. Every package
therefore includes `contents/images/1672x941.png`. The old `wallpaper.png` path is
retained for existing direct-image selections. Image bytes are unchanged.

The installer selects package URLs, matching the desktop picker, rather than
bypassing resolution lookup with a direct file. Select any entry by number:

```sh
python3 tools/wallpapers/premium-collection/install.py --select 16
```

This installs the corrected collection and selects Solar Veil. If wallpaper
settings were open during repair, close and reopen that window to refresh its
cached model. A Plasma restart or logout is not required by the installer.

Resolver reference: [KDE packagefinder.cpp](https://github.com/KDE/plasma-workspace/blob/master/wallpapers/image/plugin/finder/packagefinder.cpp).
