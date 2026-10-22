# DevOS Modesty filter

An opt-in part of Islamic DevOS mode. The default `women` mode blurs **body
regions matched to a face estimated as an adult woman**, rather than blurring
whole images, videos, or HTML containers. The explicit `people` mode masks all
detected people. Models and processing stay on this computer.

## Region selection and readable text

The bundled face detector provides estimated age and gender. BodyPix provides
separate person masks; face/pose matching selects only the corresponding body.
The default threshold is 0.75 female probability and estimated age 18 or older.
Unknown age, weak/small faces, unmatched bodies, and failed checks do not trigger
a blanket blur. Older threshold settings cannot expand matching below 0.65.

Images and video use an SVG filter that merges the unchanged pixels outside the
mask with blurred pixels inside it. A CSS background uses masked image layers
behind its HTML content, preserving text and controls. No ancestor receives
`filter: blur(...)`. Original page filters are restored when disabled.

## Limits

Age, gender, body boundaries, and face-to-body matching are **estimates**, not
verified identity or age. They can be wrong or miss a person. A person without
a visible, confidently matched adult face remains clear in women mode.

Media remains visible while being checked or when detection fails. This is
intentional: there is no whole-image or whole-container fallback. Cross-origin
videos without canvas access cannot be checked. Video masks are sampled rather
than guaranteed for every frame; movement can temporarily misalign a mask.
SVG/canvas content, later animated GIF frames, and multiple CSS backgrounds are
not covered. Text printed inside the selected body pixels (such as a shirt)
can still blur; HTML text and image text outside the mask remain unchanged.

## Enable or refresh an installed filter

```sh
sudo devos-modesty enable --mode women
sudo devos-modesty status
sudo devos-modesty disable
```

Re-enabling repacks version 1.1.0 and refreshes browser policy. Restart or refresh
browser policy to load the new extension. A signing key is created per device in
`/var/lib/devos-modesty/key.pem`, preserved across disable/re-enable. An existing
local legacy key is reused so its extension ID does not change.

Chrome, Chromium, Edge and Brave policies are supported. Incognito and Guest
modes are disabled unless `--keep-incognito` is requested. This covers browsers
that honor these policies; root can always disable the filter. Flatpak browser
policy support is still unverified.

## Checks

```sh
node tests/modesty/rules.test.cjs
python3 -m unittest discover -s tests/unit -p test_modesty.py
```

The rules cover adult/child estimates, uncertainty, mixed groups, body-only
selection, object-fit geometry, and CSS background layers. `tests/modesty/render.html`
is a deterministic browser fixture for body masks and readable HTML text; it uses
mock detector results, not an accuracy benchmark. Model initialization is also
checked separately in Chrome with only local resources.

See `THIRD_PARTY.txt` for the pinned runtimes, model provenance and licenses.
