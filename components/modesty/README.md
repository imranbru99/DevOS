# DevOS Modesty filter

Opt-in part of the Islamic DevOS mode. It is a browser extension that blurs
pictures and videos showing women, following the user's religious preference.
A stricter mode blurs pictures of any person. Everything runs on this PC: the
face and gender model is inside the extension, and no picture is uploaded
anywhere.

## Please read: what it can and cannot do

- **AI gender detection is not perfect.** The model (face-api tiny face
  detector + age/gender net) misses some women. Side views, small faces,
  heavy makeup or filters, drawings and low light make this worse. It also
  blurs some men: the threshold is set on purpose to blur when the model is
  unsure (it blurs when P(female) is 0.35 or more, so a man scored "male 60 %"
  is still blurred).
  In the test run (`tests/modesty-chrome/`, 9 public-domain photos) it
  blurred 6 of 7 female portraits and showed both male portraits and the
  landscape. The miss was an older black-and-white photo of Marie Curie,
  which the model rated "male" at 94-99 % at every input size. This set is
  far too small to be a real accuracy measurement.
- **It only sees faces.** It cannot judge bodies, clothing or a person whose
  face is not visible: a woman seen from behind, cropped at the neck, or far
  away in a crowd. Very small faces are blurred in "women" mode because they
  cannot be classified.
- **"people" mode is stricter.** It blurs any picture or video with a detected
  face, whether male or female. It still cannot see people without a visible
  face.
- Pictures stay blurred when they cannot be checked, for example a
  cross-origin video without CORS, a download error, or an image larger than
  25 MB. Small images under 64 px on both sides count as icons and are shown.
- CSS background images are checked a moment after they appear, so one can
  flash briefly. `<img>` and `<video>` are blurred before the first paint.
  `<canvas>`, SVG, `<object>`/`<embed>` and animated GIF frames after the
  first one are not checked.
- Video is checked every 1.5 s while it plays. A frame that is judged unsafe
  keeps the video blurred for at least 3 s, and two safe frames in a row are
  needed to show it again.

## How it is switched on

```
sudo devos-modesty enable [--mode women|people] [--keep-incognito]
sudo devos-modesty status
sudo devos-modesty disable
```

(`devos-modesty` runs `components/modesty/modesty.py`.) `enable`:

1. packs `extension/` into a signed CRX3 (`crx3.py`, key `key.pem`) and writes
   it with an update manifest to `/usr/share/devos/modesty/`,
2. writes `/etc/opt/chrome/policies/managed/devos-modesty.json`. It also
   writes the matching file for Chromium, Edge or Brave when they are
   installed. The file holds `ExtensionSettings` → `force_installed` with
   `update_url: file:///usr/share/devos/modesty/update.xml`, plus the
   extension's managed storage `{"locked": true, "mode": ...}` under
   `3rdparty`,
3. turns off Incognito and Guest windows unless `--keep-incognito` is given,
   because extensions do not run there.

While the filter is locked, the popup has no off switch. The user can only
make it stricter: switch the mode to "people" or lower the threshold.
`disable` removes the policy and the files, and Chrome then uninstalls the
extension.

Root can always run `disable`, so the lock is a commitment device and not
protection against the machine's owner. It also only covers Chromium-based
browsers that read these policies. Flatpak Edge and Brave get a variant that
points at `/run/host/etc/devos/modesty/`. That variant has not been tested.

## Files

- `extension/`: the MV3 extension: content script, service worker,
  offscreen detector, popup, `rules.js` (decision logic) and `tests.html`
  (rule tests that run in the browser).
- `crx3.py`: the CRX3 packer and extension ID.
- `modesty.py`: the enable, disable and status switch.
- `key.pem`: the signing key of this local-only extension. It only fixes the
  extension ID.
- `THIRD_PARTY.txt`: the vendored face-api and TensorFlow.js versions,
  hashes and licences.
- `tools/pack-modesty-extension.py`: builds `dist/devos-modesty.crx` by hand.
- `tests/modesty-chrome/run.sh`: a real Chrome check in a throwaway container.
