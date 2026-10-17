/* Rule tests that run inside Chrome (no Node needed): open
 * chrome-extension://<id>/tests.html; the title becomes "PASS n" or "FAIL ...". */
'use strict';
(function () {
  const R = ModestyRules;
  const out = [];
  let failed = 0, passed = 0;
  function eq(name, got, want) {
    const ok = JSON.stringify(got) === JSON.stringify(want);
    ok ? passed++ : failed++;
    out.push((ok ? 'ok   ' : 'FAIL ') + name + (ok ? '' : ' got=' + JSON.stringify(got) + ' want=' + JSON.stringify(want)));
  }
  const S = (m, l) => R.effectiveSettings(m, l);
  const F = (g, p, extra) => Object.assign({ score: 0.9, gender: g, genderProbability: p, w: 80, h: 80 }, extra || {});
  const women = S({}, {});
  const people = S({}, { mode: 'people' });

  eq('defaults', [women.enabled, women.mode, women.femaleThreshold, women.locked], [true, 'women', 0.35, false]);
  eq('female face blurred', R.decide({ ok: true, faces: [F('female', 0.9)] }, women).blur, true);
  eq('confident male not blurred', R.decide({ ok: true, faces: [F('male', 0.95)] }, women).blur, false);
  eq('uncertain male (p=0.6 -> female 0.4) blurred', R.decide({ ok: true, faces: [F('male', 0.6)] }, women).blur, true);
  eq('male p=0.7 (female 0.3) not blurred', R.decide({ ok: true, faces: [F('male', 0.7)] }, women).blur, false);
  eq('mixed group blurred', R.decide({ ok: true, faces: [F('male', 0.99), F('female', 0.7)] }, women).blur, true);
  eq('no face not blurred', R.decide({ ok: true, faces: [] }, women).blur, false);
  eq('weak detection ignored', R.decide({ ok: true, faces: [F('female', 0.9, { score: 0.2 })] }, women).blur, false);
  eq('tiny face blurred in women mode', R.decide({ ok: true, faces: [F('male', 0.99, { w: 12, h: 14 })] }, women).blur, true);
  eq('failed check stays blurred', R.decide({ ok: false, error: 'tainted' }, women).blur, true);
  eq('null result stays blurred', R.decide(null, women).blur, true);
  eq('people mode blurs men', R.decide({ ok: true, faces: [F('male', 0.99)] }, people).blur, true);
  eq('people mode keeps landscape', R.decide({ ok: true, faces: [] }, people).blur, false);
  eq('disabled shows everything', R.decide({ ok: true, faces: [F('female', 0.99)] }, S({}, { enabled: false })).blur, false);

  const locked = S({ locked: true, mode: 'women' }, { enabled: false, mode: 'people', femaleThreshold: 0.9 });
  eq('locked: cannot disable', locked.enabled, true);
  eq('locked: can go stricter', locked.mode, 'people');
  eq('locked: threshold cannot be raised', locked.femaleThreshold, 0.35);
  const locked2 = S({ locked: true, mode: 'people' }, { mode: 'women' });
  eq('locked: cannot go looser', locked2.mode, 'people');
  eq('locked: lower threshold allowed', S({ locked: true }, { femaleThreshold: 0.2 }).femaleThreshold, 0.2);
  eq('unlocked: managed mode is default', S({ mode: 'people' }, {}).mode, 'people');
  eq('unlocked: user overrides', S({ mode: 'people' }, { mode: 'women' }).mode, 'women');
  eq('bad values ignored', S({ mode: 'x', femaleThreshold: 'y' }, { mode: 7 }).mode, 'women');

  eq('icon natural 32x32', R.isIconSized(32, 32, 0, 0, 64), true);
  eq('big image shown small (40px avatar)', R.isIconSized(400, 400, 40, 40, 64), true);
  eq('normal photo', R.isIconSized(400, 300, 400, 300, 64), false);
  eq('not laid out yet', R.isIconSized(400, 300, 0, 0, 64), false);

  document.getElementById('out').textContent = out.join('\n');
  document.title = failed ? 'FAIL ' + failed + '/' + (passed + failed) : 'PASS ' + passed;
})();
