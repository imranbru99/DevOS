# DevOS Modesty filter

An opt-in part of Islamic DevOS mode. The default `women` mode blurs the
**whole photo** when a girl is in it. A photo with no girl stays completely
clear, including men, scenery, and pages of text. The blur is only on that
photo, not on the name, buttons, or the rest of the page. The `people` mode
blurs the whole photo when any face is present. Models and processing stay on
this computer.

## Region selection and readable text

BlazeFace finds faces on this PC. The age/gender net runs only on those face
crops. One girl in the photo blurs that entire photo. A covered head with no
beard still counts as a girl when the gender net says male, which is common
with a hijab or hair that hides the face. A face smaller than about 48 pixels
cannot support an age reading, so a long dark garment under a female-leaning
score still counts; a close-up child, whose face is large enough for the age
net, stays clear, and so does the whole photo. The default threshold is 0.68
female probability and estimated age 18 or older. A photo of a man, a group of
men, scenery, or text stays clear. Older threshold settings cannot expand
matching below 0.65.

The blur is a full-photo overlay on the image or video itself. Names, buttons,
and other HTML stay sharp. No ancestor receives `filter: blur(...)`. Original
page filters are restored when disabled.

## Limits

Age and gender are **estimates**, not verified identity or age. They can be
wrong or miss a girl, and then that photo stays clear. A photo is blurred only
after a girl is found in it. Medical diagrams, icons, and drawings stay clear.

Media remains visible while being checked or when detection fails. A
cross-origin video that taints a canvas is checked from a capture of the
on-screen region instead. Video is sampled rather than guaranteed for every
frame. A paused video is checked again until a read succeeds.
SVG/canvas content, later animated GIF frames, and multiple CSS backgrounds are
not covered. Text printed inside the selected body pixels (such as a shirt)
can still blur; HTML text and image text outside the mask remain unchanged.

## Enable or refresh an installed filter

```sh
sudo devos-modesty enable --mode women
sudo devos-modesty status
sudo devos-modesty disable
```

Re-enabling repacks version 1.3.1 and refreshes browser policy. Fully quit and
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
