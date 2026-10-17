# DevOS wallpapers

`make_wallpapers.py` procedurally renders 80 DevOS premium wallpapers
(20 designs, each in four palettes). numpy + Pillow only, fixed seeds, so the
output is reproducible. The desktop shows one and changes to another every
12 hours.

Each design is rendered at 3840x2160 (a few soft designs at 1920x1080 and
upscaled), tone-mapped, vignetted, dithered with light film grain and saved as
a KDE Plasma wallpaper package:

    build/includes.chroot/usr/share/wallpapers/DevOS-<Name>/
        metadata.json
        contents/images/2560x1440.jpg
        contents/screenshot.jpg

`preview.jpg` in this folder is a contact sheet for review only; it is not
installed into the image.

## Regenerate

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
