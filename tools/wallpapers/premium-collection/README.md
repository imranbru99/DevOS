# DevOS Premium · Home Collection

Twenty original wallpapers designed for DevOS itself — cyan/sapphire/obsidian
brand language, calm icon-safe zones, and compositions that crop cleanly on
phones, tablets, laptops, ultrawide and 4K.

These replace the earlier generic sculpture/landscape set. Flagship entries:

| Id | Name | Role |
|---|---|---|
| 01 | Cyan Orbit | Dark default / boot motif |
| 08 | Pearl Dawn | Light-mode pair |
| 20 | Home Bloom | Dashboard homepage hero |

Open `gallery.html` to compare the collection.

## Multi-size packages

Each Plasma package under
`build/includes.chroot/usr/share/wallpapers/DevOS-Premium-*` includes:

- `wallpaper.png` master
- common landscape covers (`1366x768`, `1920x1080`, `2560x1440`, `3840x2160`, …)
- portrait covers on Cyan Orbit, Pearl Dawn and Home Bloom (`720x1280`, `1080x1920`, …)

Plasma picks the closest `WIDTHxHEIGHT.png`. The dashboard homepage switches
between landscape and portrait heroes with CSS (`premium/home-bloom*.jpg`).

## Use on this computer

```sh
python3 tools/wallpapers/premium-collection/install.py
python3 tools/wallpapers/premium-collection/install.py --apply light   # Pearl Dawn
python3 tools/wallpapers/premium-collection/install.py --apply dark    # Cyan Orbit
python3 tools/wallpapers/premium-collection/install.py --select 20     # Home Bloom
```

## Rebuild packaging

```sh
python3 tools/wallpapers/premium-collection/package.py
```

Developer: [Imran Ahmed](https://imrandev.bd) <me@imrandev.bd>.
