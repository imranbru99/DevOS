# DevOS Modesty filter

An opt-in part of Islamic DevOS mode. The default `women` mode blurs **body
regions matched to a face estimated as an adult woman**, rather than blurring
whole images, videos, or HTML containers. The explicit `people` mode masks all
detected people. Models and processing stay on this computer.

## Region selection and readable text

MediaPipe Pose Landmarker (lite) and BlazeFace full-range find people and
faces on this PC. The age/gender net runs only on those face crops. A covered
head with no beard still counts as an adult woman when the gender net says
male, which is common with a hijab. A face smaller than about 48 pixels cannot
support an age reading, so a long dark garment under a female-leaning score is
treated as an adult woman; a close-up child, whose face is large enough for
the age net, stays clear. The default threshold is 0.68 female probability and
estimated age 18 or older. Unknown age, weak/small faces, and failed checks do
not trigger a blanket blur. Bodies with substantial visible skin can still be
selected when an adult woman face sits on that body. A man standing beside her
is not selected with her. Older threshold settings cannot expand matching
below 0.65.

Images and video use an SVG filter that merges the unchanged pixels outside the
mask with blurred pixels inside it. A CSS background uses masked image layers
behind its HTML content, preserving text and controls. No ancestor receives
`filter: blur(...)`. Original page filters are restored when disabled.

## Limits

Age, gender, body boundaries, and face-to-body matching are **estimates**, not
verified identity or age. They can be wrong or miss a person. From 1.2.1, women
mode also blurs **high-skin body crops with no face** (midriff / torso image
search). Medical diagrams, icons, and drawings without a person mask stay clear.

Media remains visible while being checked or when detection fails. This is
intentional: there is no whole-image or whole-container fallback. A cross-origin
video that taints a canvas is checked from a capture of the on-screen region
instead. Video masks are sampled rather than guaranteed for every frame;
movement can temporarily misalign a mask. A paused video is checked again until
a read succeeds.
SVG/canvas content, later animated GIF frames, and multiple CSS backgrounds are
not covered. Text printed inside the selected body pixels (such as a shirt)
can still blur; HTML text and image text outside the mask remain unchanged.

## Enable or refresh an installed filter

```sh
sudo devos-modesty enable --mode women
sudo devos-modesty status
sudo devos-modesty disable
```

Re-enabling repacks version 1.3.0 and refreshes browser policy. Fully quit and
reopen Chrome so the new extension loads. A signing key is created per device in
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
