/*
 * DevOS Modesty filter - settings merge and blur decision rules.
 * Pure functions, no browser APIs: loaded by the content script, the service
 * worker, the popup and tests.html. Exposed as globalThis.ModestyRules.
 */
(function (root) {
  'use strict';

  const MODES = ['women', 'people'];           // ordered from less to more strict
  const DEFAULTS = Object.freeze({
    enabled: true,
    mode: 'women',
    // Adult-woman estimate before selecting a body mask (floor still 0.65).
    femaleThreshold: 0.68,
    adultAge: 18,
    // Minimum tiny-face-detector score for something to count as a face.
    // 0.50 keeps devices out while catching more real faces in photos.
    faceScore: 0.50,
    // Faces smaller than this (px, in the analysed image) are too small for
    // the gender model to be trusted; in women mode these stay clear.
    uncertainFacePx: 20,
    // Images whose rendered or natural size is below this on both sides are
    // treated as icons and never blurred.
    minMediaPx: 64,
    // Body skin share that, with an adult woman face in-frame, selects the mask
    // even when nose/eye anchors failed to match (common on real photo crops).
    bodySkinRatio: 0.12,
    // High visible-skin share on a body mask with NO usable face — midriff,
    // lingerie, and torso crops in image search. Lean to blur for modesty.
    bodySkinOnlyRatio: 0.15,
  });

  function clamp01(x, fallback) {
    const n = Number(x);
    return Number.isFinite(n) ? Math.min(1, Math.max(0, n)) : fallback;
  }

  function stricterMode(a, b) {
    const ia = MODES.indexOf(a), ib = MODES.indexOf(b);
    return MODES[Math.max(ia < 0 ? 0 : ia, ib < 0 ? 0 : ib)];
  }

  /*
   * managed: chrome.storage.managed contents (policy), local: user choices.
   * When managed.locked is true the user can only make the filter stricter:
   * it stays on, the mode can go from "women" to "people" but not back, and
   * the threshold can only go down.
   */
  function effectiveSettings(managed, local) {
    managed = managed || {};
    local = local || {};
    const s = Object.assign({}, DEFAULTS);
    const locked = managed.locked === true;
    if (MODES.includes(managed.mode)) s.mode = managed.mode;
    if (managed.femaleThreshold !== undefined) s.femaleThreshold = clamp01(managed.femaleThreshold, s.femaleThreshold);
    if (typeof managed.enabled === 'boolean') s.enabled = managed.enabled;

    if (locked) {
      s.enabled = true;
      if (MODES.includes(local.mode)) s.mode = stricterMode(s.mode, local.mode);
      if (local.femaleThreshold !== undefined) {
        s.femaleThreshold = Math.min(s.femaleThreshold, clamp01(local.femaleThreshold, s.femaleThreshold));
      }
    } else {
      if (typeof local.enabled === 'boolean') s.enabled = local.enabled;
      if (MODES.includes(local.mode)) s.mode = local.mode;
      if (local.femaleThreshold !== undefined) s.femaleThreshold = clamp01(local.femaleThreshold, s.femaleThreshold);
    }
    s.locked = locked;
    s.managedMode = MODES.includes(managed.mode) ? managed.mode : null;
    return s;
  }

  function femaleProbability(face) {
    const p = clamp01(face.genderProbability, 0.5);
    if (face.gender === 'female') return p;
    if (face.gender === 'male') return 1 - p;
    return 0.5;                                  // unknown -> uncertain
  }

  /*
   * result: {ok: bool, faces: [{score, gender, genderProbability, w, h}], error?}
   * Returns {blur: bool, reason: string}.
   */
  function isAdultWomanFace(face, s) {
    if (!face) return false;
    // A covered head (hijab or hair from behind) is a weaker box. Keep it
    // when it is still a real detection; an open face must clear faceScore.
    const covered = face.headCovered === true;
    const score = Number(face.score);
    if (score < (covered ? Math.min(0.45, s.faceScore) : s.faceScore)) return false;
    const size = Math.min(Number(face.w) || 0, Number(face.h) || 0);
    if (size < s.uncertainFacePx) return false;
    if (face.bearded === true) return false;
    const age = Number(face.age);
    const adult = Number.isFinite(age) && age >= s.adultAge;
    const p = femaleProbability(face);
    if (adult && p >= Math.max(0.65, s.femaleThreshold)) return true;
    // A hijab often makes the gender net say "male". Covered hair and neck,
    // with no beard, is still an adult woman.
    if (adult && face.headCovered === true) return true;
    // On a face under ~48px the age net is not evidence of childhood: the
    // Facebook frame that started this measured an adult woman as age 9.
    // A long dark garment under a female-leaning score is an adult figure.
    // A close-up child has a larger face, so that age reading still wins.
    if (size < 48 && face.clothedAdult === true && p >= 0.52 && Number(face.score) >= 0.55) return true;
    return false;
  }

  function fullImage(result) {
    if (!result || !result.fullBlur) return [];
    return [{ full: true, faceIndex: -1, mask: result.fullBlur, blurLayer: result.fullBlur }];
  }

  function realFace(face, s) {
    return face && Number(face.score) >= s.faceScore &&
      Math.min(Number(face.w) || 0, Number(face.h) || 0) >= s.uncertainFacePx;
  }

  /*
   * Women mode: one girl anywhere in the photo blurs that whole photo.
   * A photo with no girl stays completely clear, including men, scenery,
   * and skin with no female face. People mode blurs the whole photo when
   * any real face is present.
   */
  function decide(result, settings) {
    const s = Object.assign({}, DEFAULTS, settings || {});
    if (!s.enabled) return { blur: false, reason: 'disabled', regions: [] };
    if (!result || !result.ok) return { blur: false, reason: 'not-checked', regions: [] };
    const faces = result.faces || [];
    const girl = faces.some((face) => isAdultWomanFace(face, s));
    if (s.mode === 'people' && faces.some((face) => realFace(face, s))) {
      const regions = fullImage(result);
      return { blur: regions.length > 0, reason: regions.length ? 'person' : 'no-girl', regions };
    }
    if (!girl) return { blur: false, reason: 'no-girl', regions: [] };
    const regions = fullImage(result);
    return { blur: regions.length > 0, reason: regions.length ? 'girl' : 'no-girl', regions };
  }

  function matchFace(pose, faces, used) {
    const anchors = (pose.keypoints || []).filter((k) => /^(nose|leftEye|rightEye)$/.test(k.part) && k.score >= 0.20);
    const shoulders = (pose.keypoints || []).filter((k) => /^(leftShoulder|rightShoulder)$/.test(k.part) && k.score >= 0.20);
    const avgShoulderY = shoulders.length > 0 ? shoulders.reduce((acc, s) => acc + s.position.y, 0) / shoulders.length : null;

    let best = -1, distance = Infinity;
    faces.forEach((f, index) => {
      if (used && used.has(index)) return;
      // If shoulders are detected, human anatomy dictates that the face must be above the shoulder line
      if (avgShoulderY !== null && (f.y + f.h * 0.5) > avgShoulderY + f.h * 0.35) return;
      for (const anchor of anchors) {
        const p = anchor.position;
        if (p.x < f.x - f.w * 0.35 || p.x > f.x + f.w * 1.35 || p.y < f.y - f.h * 0.35 || p.y > f.y + f.h * 1.35) continue;
        const d = Math.hypot(p.x - f.x - f.w / 2, p.y - f.y - f.h / 2) / Math.max(f.w, f.h, 1);
        if (d < distance) { best = index; distance = d; }
      }
    });
    return best;
  }

  // When nose/eyes are missing (common on real cropped photos), match a face
  // that sits above the shoulders and overlaps the torso horizontally.
  function matchFaceByTorso(pose, faces, used) {
    const shoulders = (pose.keypoints || []).filter((k) => /^(leftShoulder|rightShoulder)$/.test(k.part) && k.score >= 0.20);
    const hips = (pose.keypoints || []).filter((k) => /^(leftHip|rightHip)$/.test(k.part) && k.score >= 0.20);
    if (!shoulders.length && !hips.length) return -1;
    const pts = shoulders.length ? shoulders : hips;
    const cx = pts.reduce((a, p) => a + p.position.x, 0) / pts.length;
    const topY = pts.reduce((a, p) => a + p.position.y, 0) / pts.length;
    const spread = Math.max(40, ...pts.map((p) => Math.abs(p.position.x - cx))) * 2.5;

    let best = -1, distance = Infinity;
    faces.forEach((f, index) => {
      if (used && used.has(index)) return;
      const fx = f.x + f.w / 2, fy = f.y + f.h / 2;
      if (fy > topY + f.h * 0.4) return;
      if (Math.abs(fx - cx) > spread + f.w) return;
      const d = Math.hypot(fx - cx, fy - topY) / Math.max(f.w, f.h, 1);
      if (d < distance) { best = index; distance = d; }
    });
    return best;
  }

  function fitBox(sourceW, sourceH, boxW, boxH, fit, position = '50% 50%') {
    let w = boxW, h = boxH;
    if (fit !== 'fill') {
      let scale = fit === 'cover' ? Math.max(boxW / sourceW, boxH / sourceH) : Math.min(boxW / sourceW, boxH / sourceH);
      if (fit === 'none') scale = 1;
      if (fit === 'scale-down') scale = Math.min(1, scale);
      w = sourceW * scale; h = sourceH * scale;
    }
    const parts = position.trim().split(/\s+/);
    const offset = (value, free) => {
      if (value === 'left' || value === 'top') return 0;
      if (value === 'right' || value === 'bottom') return free;
      if (value === 'center' || !value) return free / 2;
      return value.endsWith('%') ? free * parseFloat(value) / 100 : parseFloat(value) || 0;
    };
    return { x: offset(parts[0], boxW - w), y: offset(parts[1] || '50%', boxH - h), w, h };
  }

  function cssLayers(value) {
    const layers = []; let depth = 0, quote = '', start = 0;
    for (let i = 0; i < value.length; i++) {
      const c = value[i];
      if (quote) { if (c === '\\') i++; else if (c === quote) quote = ''; continue; }
      if (c === '"' || c === "'") quote = c;
      else if (c === '(') depth++;
      else if (c === ')') depth--;
      else if (c === ',' && depth === 0) { layers.push(value.slice(start, i).trim()); start = i + 1; }
    }
    layers.push(value.slice(start).trim()); return layers;
  }

  function isIconSized(naturalW, naturalH, renderedW, renderedH, minPx) {
    const m = minPx || DEFAULTS.minMediaPx;
    if (naturalW > 0 && naturalH > 0 && naturalW < m && naturalH < m) return true;
    if (renderedW > 0 && renderedH > 0 && renderedW < m && renderedH < m) return true;
    return false;
  }

  root.ModestyRules = { MODES, DEFAULTS, effectiveSettings, decide, isAdultWomanFace, femaleProbability, isIconSized, stricterMode, matchFace, matchFaceByTorso, fitBox, cssLayers };
})(typeof globalThis !== 'undefined' ? globalThis : this);
