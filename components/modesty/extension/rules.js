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
    // Require a confident adult-woman estimate before selecting a body mask.
    femaleThreshold: 0.75,
    adultAge: 18,
    // Minimum tiny-face-detector score for something to count as a face.
    faceScore: 0.35,
    // Faces smaller than this (px, in the analysed image) are too small for
    // the gender model to be trusted; in women mode these stay clear.
    uncertainFacePx: 24,
    // Images whose rendered or natural size is below this on both sides are
    // treated as icons and never blurred.
    minMediaPx: 64,
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
  function decide(result, settings) {
    const s = Object.assign({}, DEFAULTS, settings || {});
    if (!s.enabled) return { blur: false, reason: 'disabled', regions: [] };
    if (!result || !result.ok) return { blur: false, reason: 'not-checked', regions: [] };
    const faces = result.faces || [];
    const regions = (result.people || []).filter((person) => {
      if (!person.mask || !person.blurLayer) return false;
      if (s.mode === 'people') return true;
      const face = faces[person.faceIndex];
      return face && Number(face.score) >= s.faceScore &&
        Number.isFinite(face.age) && face.age >= s.adultAge &&
        Math.min(Number(face.w) || 0, Number(face.h) || 0) >= s.uncertainFacePx &&
        femaleProbability(face) >= Math.max(0.65, s.femaleThreshold);
    });
    return { blur: regions.length > 0, reason: regions.length ? (s.mode === 'people' ? 'person' : 'adult-woman') : 'no-target-body', regions };
  }

  function matchFace(pose, faces, used) {
    const anchors = (pose.keypoints || []).filter((k) => /^(nose|leftEye|rightEye)$/.test(k.part) && k.score >= 0.25);
    let best = -1, distance = Infinity;
    faces.forEach((f, index) => {
      if (used && used.has(index)) return;
      for (const anchor of anchors) {
        const p = anchor.position;
        if (p.x < f.x - f.w * 0.25 || p.x > f.x + f.w * 1.25 || p.y < f.y - f.h * 0.25 || p.y > f.y + f.h * 1.25) continue;
        const d = Math.hypot(p.x - f.x - f.w / 2, p.y - f.y - f.h / 2) / Math.max(f.w, f.h, 1);
        if (d < distance) { best = index; distance = d; }
      }
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

  root.ModestyRules = { MODES, DEFAULTS, effectiveSettings, decide, femaleProbability, isIconSized, stricterMode, matchFace, fitBox, cssLayers };
})(typeof globalThis !== 'undefined' ? globalThis : this);
