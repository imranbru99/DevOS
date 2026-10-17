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
    // Blur when P(female) >= this. Below 0.5 on purpose: when the model is
    // unsure (P around 0.4-0.6) the picture stays blurred.
    femaleThreshold: 0.35,
    // Minimum tiny-face-detector score for something to count as a face.
    faceScore: 0.35,
    // Faces smaller than this (px, in the analysed image) are too small for
    // the gender model to be trusted; in "women" mode they are blurred.
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
    if (!s.enabled) return { blur: false, reason: 'disabled' };
    if (!result || !result.ok) return { blur: true, reason: 'not-checked' };
    const faces = (result.faces || []).filter((f) => (Number(f.score) || 0) >= s.faceScore);
    if (!faces.length) return { blur: false, reason: 'no-face' };
    if (s.mode === 'people') return { blur: true, reason: 'person' };
    for (const f of faces) {
      if (femaleProbability(f) >= s.femaleThreshold) return { blur: true, reason: 'female' };
      if (Math.min(Number(f.w) || 0, Number(f.h) || 0) < s.uncertainFacePx) return { blur: true, reason: 'face-too-small' };
    }
    return { blur: false, reason: 'male-only' };
  }

  function isIconSized(naturalW, naturalH, renderedW, renderedH, minPx) {
    const m = minPx || DEFAULTS.minMediaPx;
    if (naturalW > 0 && naturalH > 0 && naturalW < m && naturalH < m) return true;
    if (renderedW > 0 && renderedH > 0 && renderedW < m && renderedH < m) return true;
    return false;
  }

  root.ModestyRules = { MODES, DEFAULTS, effectiveSettings, decide, femaleProbability, isIconSized, stricterMode };
})(typeof globalThis !== 'undefined' ? globalThis : this);
