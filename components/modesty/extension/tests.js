/* Pure rule/geometry regression tests, runnable in a browser or Node. */
'use strict';
(function () {
  const R = ModestyRules, out = []; let failed = 0, passed = 0;
  function eq(name, got, want) {
    const ok = JSON.stringify(got) === JSON.stringify(want); ok ? passed++ : failed++;
    out.push((ok ? 'ok ' : 'FAIL ') + name + (ok ? '' : ` got=${JSON.stringify(got)} want=${JSON.stringify(want)}`));
  }
  const S = (m, l) => R.effectiveSettings(m, l);
  const F = (gender, p, extra) => Object.assign({ score: .95, gender, genderProbability: p, age: 30, x: 10, y: 10, w: 80, h: 80 }, extra || {});
  const P = (faceIndex, extra) => Object.assign({ faceIndex, mask: 'mask', blurLayer: 'layer' }, extra || {});
  const D = (faces, people) => ({ ok: true, width: 300, height: 400, fullBlur: 'full', faces, people: people || [] });
  const women = S({}, {}), people = S({}, { mode: 'people' });
  eq('default adult women threshold', women.femaleThreshold, .68);
  eq('adult woman body selected', R.decide(D([F('female', .95)]), women).blur, true);
  eq('male body stays clear', R.decide(D([F('male', .95)]), women).blur, false);
  eq('uncertain classification stays clear', R.decide(D([F('male', .6)]), women).blur, false);
  eq('child stays clear', R.decide(D([F('female', .95, { age: 17 })]), women).blur, false);
  eq('missing age stays clear', R.decide(D([F('female', .95, { age: undefined })]), women).blur, false);
  eq('adult boundary', R.decide(D([F('female', .95, { age: 18 })]), women).blur, true);
  eq('weak face ignored', R.decide(D([F('female', .99, { score: .2 })]), women).blur, false);
  eq('small uncertain face ignored', R.decide(D([F('female', .99, { w: 12 })]), women).blur, false);
  eq('a girl face blurs the whole image', R.decide(D([F('female', .99)]), women).regions.map((r) => r.full), [true]);
  eq('a girl face without a blur layer is not invented', R.decide({ ok: true, faces: [F('female', .99)] }, women).blur, false);
  eq('unmatched body stays clear in women mode', R.decide(D([], [P(-1)]), women).blur, false);
  eq('low-skin unmatched body stays clear', R.decide(D([], [P(-1, { skinRatio: .08 })]), women).blur, false);
  eq('skin with no girl stays clear',
    R.decide(D([], [P(-1, { skinRatio: .25 })]), women).blur, false);
  eq('skin crop without a girl stays clear',
    R.decide(D([], [P(-1, { skinRatio: .16 })]), women).blur, false);
  eq('a photo that contains a girl blurs as a whole',
    R.decide(D([F('female', .95, { y: 20 })], [P(-1, { skinRatio: .25, torsoY: 160 })]), women).regions[0].full, true);
  eq('people mode does not blur a photo with no face', R.decide(D([], [P(-1)]), people).blur, false);
  eq('failed detection leaves text readable', R.decide({ ok: false }, women).blur, false);
  eq('missing detection has no whole-image fallback', R.decide(null, women).regions, []);
  const group = D([F('male', .99), F('female', .95), F('female', .99, { age: 12 })]);
  eq('a photo with a girl blurs once, as the whole image', R.decide(group, women).regions.length, 1);
  eq('a man-only photo stays clear', R.decide(D([F('male', .99)]), women).blur, false);
  eq('people mode blurs the whole photo when any face is real', R.decide(group, people).regions.length, 1);
  eq('disabled has no masks', R.decide(group, S({}, { enabled: false })).regions, []);
  const locked = S({ locked: true }, { enabled: false, mode: 'people', femaleThreshold: .9 });
  eq('lock stays enabled', locked.enabled, true);
  eq('lock can select people', locked.mode, 'people');
  eq('lock cannot raise threshold', locked.femaleThreshold, .68);
  eq('torso fallback matches face above shoulders', R.matchFaceByTorso({
    keypoints: [
      { part: 'leftShoulder', score: .9, position: { x: 100, y: 120 } },
      { part: 'rightShoulder', score: .9, position: { x: 160, y: 120 } },
    ],
  }, [F('female', .99, { x: 110, y: 20, w: 40, h: 50 })]), 0);
  eq('lock cannot weaken people mode', S({ locked: true, mode: 'people' }, { mode: 'women' }).mode, 'people');
  eq('old broad threshold cannot select uncertain men', R.decide(D([F('male', .6)]), S({ femaleThreshold: .35 }, {})).blur, false);
  eq('no body in text image', R.decide(D([], []), women).regions, []);
  const faces = [F('male', .99), F('female', .99, { x: 150 })];
  const pose = { keypoints: [{ part: 'nose', score: .9, position: { x: 190, y: 50 } }] };
  eq('pose matches its own face', R.matchFace(pose, faces), 1);
  eq('already assigned face is not reused', R.matchFace(pose, faces, new Set([1])), -1);
  eq('body with no face anchors stays unmatched', R.matchFace({ keypoints: [] }, faces), -1);
  eq('covered adult counted even if the model says male',
    R.decide(D([F('male', .8, { headCovered: true, bearded: false })]), women).blur, true);
  eq('covered child stays clear',
    R.decide(D([F('female', .9, { age: 14, headCovered: true })]), women).blur, false);
  eq('bearded covered man stays clear',
    R.decide(D([F('male', .9, { headCovered: true, bearded: true })]), women).blur, false);
  eq('tiny face misread as a child is selected when the garment is long and dark',
    R.decide(D([F('female', .56, { age: 9, w: 25, h: 25, score: .75, clothedAdult: true, x: 120, y: 170 })],
      [P(0, { skinRatio: .05, cx: 130, bw: 90 })]), women).blur, true);
  eq('close-up child stays clear even with a clothing flag',
    R.decide(D([F('female', .95, { age: 12, w: 80, h: 80, clothedAdult: true })]), women).blur, false);
  eq('a photo with a girl and a man blurs the whole image',
    R.decide(D([
      F('female', .56, { age: 9, w: 25, h: 25, score: .75, clothedAdult: true, x: 100, y: 40 }),
      F('male', .9, { x: 220, y: 40, w: 30, h: 30 }),
    ]), women).regions.map((p) => p.full), [true]);
  eq('contain placement', R.fitBox(400, 200, 300, 300, 'contain'), { x: 0, y: 75, w: 300, h: 150 });
  eq('cover crop placement', R.fitBox(400, 200, 300, 300, 'cover'), { x: -150, y: 0, w: 600, h: 300 });
  eq('object position placement', R.fitBox(400, 200, 300, 300, 'cover', '0% 50%'), { x: 0, y: 0, w: 600, h: 300 });
  eq('fill placement', R.fitBox(400, 200, 300, 300, 'fill'), { x: 0, y: 0, w: 300, h: 300 });
  eq('data URL comma is not a second background', R.cssLayers('url("data:image/png;base64,abc")').length, 1);
  eq('gradient and photo are separate layers', R.cssLayers('linear-gradient(red,blue), url("a.png")').length, 2);
  eq('icon skipped', R.isIconSized(32, 32, 0, 0), true);
  eq('normal photo not skipped', R.isIconSized(400, 300, 400, 300), false);
  document.getElementById('out').textContent = out.join('\n');
  document.title = failed ? `FAIL ${failed}/${passed + failed}` : `PASS ${passed}`;
})();
