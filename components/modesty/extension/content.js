/*
 * DevOS Modesty filter - content script (runs in every frame at document_start).
 *
 * content.css already blurs every <img> and <video> that does not carry
 * data-dm="ok", so nothing is shown before it has been checked. This script
 * asks the extension's detector about each media element and sets
 * data-dm="ok" only on the ones it clears. Elements with a CSS background
 * image get data-dm-bg="pending" -> "ok" | "blur".
 */
(() => {
  'use strict';
  if (window.__devosModestyLoaded) return;
  window.__devosModestyLoaded = true;

  const R = globalThis.ModestyRules;
  const VIDEO_SAMPLE_MS = 1500;
  const VIDEO_HOLD_MS = 3000;          // keep a video blurred this long after an unsafe frame
  const VIDEO_SAFE_STREAK = 2;         // consecutive safe frames needed to un-blur a playing video
  const PIXEL_MAX_SIDE = 384;
  const BG_BATCH_BUDGET_MS = 8;
  const BLUR_CSS = `
    img:not([data-dm="ok"]), video:not([data-dm="ok"]),
    [data-dm-bg="pending"], [data-dm-bg="blur"] { filter: blur(28px) !important; }`;

  let settings = R.effectiveSettings({}, {});
  const results = new Map();           // media key (URL) -> Promise<result>
  const info = new WeakMap();          // element -> per-element state
  const tracked = new Set();           // elements with a decision (for re-deciding on settings change)
  const videos = new Set();
  const shadowStyles = [];
  let newlyBlurred = 0;
  let alive = true;

  // ------------------------------------------------------------ messaging
  function send(msg) {
    if (!alive) return Promise.resolve(null);
    try {
      return chrome.runtime.sendMessage(msg).catch((e) => {
        if (String(e).includes('context invalidated')) alive = false;
        return null;
      });
    } catch (e) {
      alive = false;                    // extension reloaded/removed; stay blurred
      return Promise.resolve(null);
    }
  }

  let countTimer = null;
  function reportCount() {
    if (countTimer) return;
    countTimer = setTimeout(() => {
      countTimer = null;
      let count = 0;
      for (const el of tracked) {
        if (!el.isConnected) { tracked.delete(el); videos.delete(el); continue; }
        const st = info.get(el);
        if (st && st.blurred) count++;
      }
      const newly = newlyBlurred;
      newlyBlurred = 0;
      send({ type: 'count', count, newly });
    }, 500);
  }

  // ------------------------------------------------------------ state marks
  function attrFor(el) { return (el.tagName === 'IMG' || el.tagName === 'VIDEO') ? 'data-dm' : 'data-dm-bg'; }

  function setBlurred(el, blurred) {
    const st = info.get(el) || {};
    const attr = attrFor(el);
    if (blurred) {
      if (attr === 'data-dm') el.removeAttribute('data-dm'); else el.setAttribute('data-dm-bg', 'blur');
      if (!st.blurred) newlyBlurred++;
    } else {
      el.setAttribute(attr, 'ok');
    }
    st.blurred = blurred;
    info.set(el, st);
    tracked.add(el);
    reportCount();
  }

  function resetToPending(el) {
    const st = info.get(el);
    if (st) { st.key = null; st.result = null; st.safeStreak = 0; }
    if (attrFor(el) === 'data-dm') el.removeAttribute('data-dm');
    else el.setAttribute('data-dm-bg', 'pending');
  }

  function applyResult(el, result) {
    const st = info.get(el) || {};
    st.result = result;
    info.set(el, st);
    setBlurred(el, R.decide(result, settings).blur);
  }

  // ------------------------------------------------------------ detection
  function pixelsFrom(source, w, h) {
    // Returns a small JPEG data URL, or null if the canvas is tainted.
    const scale = Math.min(1, PIXEL_MAX_SIDE / Math.max(w, h));
    const c = document.createElement('canvas');
    c.width = Math.max(1, Math.round(w * scale));
    c.height = Math.max(1, Math.round(h * scale));
    const ctx = c.getContext('2d');
    ctx.drawImage(source, 0, 0, c.width, c.height);
    try { return c.toDataURL('image/jpeg', 0.85); } catch (e) { return null; }
  }

  function detectUrl(url) {
    if (!results.has(url)) {
      const p = send({ type: 'detect-url', url }).then((r) => r || { ok: false, error: 'no response' });
      results.set(url, p);
      p.then((r) => { if (!r.ok) results.delete(url); });
    }
    return results.get(url);
  }

  function detectPixels(dataUrl) {
    if (!dataUrl) return Promise.resolve({ ok: false, error: 'tainted' });
    return send({ type: 'detect-pixels', dataUrl }).then((r) => r || { ok: false, error: 'no response' });
  }

  function isSvgUrl(u) { return /^data:image\/svg/i.test(u) || /\.svg(\?|#|$)/i.test(u); }

  // ------------------------------------------------------------ <img>
  function processImg(img) {
    if (!settings.enabled) return;
    const key = img.currentSrc || img.src || '';
    const st = info.get(img) || {};
    info.set(img, st);
    if (st.key === key && (st.result || st.pending)) return;
    st.key = key;
    st.result = null;
    if (!key) return;                                   // nothing to show yet; stays blurred
    if (!img.complete) return;                          // the capture-phase load listener comes back
    if (img.naturalWidth === 0) { setBlurred(img, false); return; } // broken image, nothing to see
    const rect = img.getBoundingClientRect();
    if (isSvgUrl(key) || R.isIconSized(img.naturalWidth, img.naturalHeight, rect.width, rect.height, settings.minMediaPx)) {
      st.result = { ok: true, faces: [], skipped: true };
      setBlurred(img, false);
      return;
    }
    st.pending = true;
    let p;
    if (/^(data|blob):/i.test(key)) {
      const cacheKey = key.length > 2048 ? null : key;
      p = cacheKey && results.has(cacheKey) ? results.get(cacheKey)
        : detectPixels(pixelsFrom(img, img.naturalWidth, img.naturalHeight));
      if (cacheKey) results.set(cacheKey, p);
    } else {
      p = detectUrl(key);
    }
    p.then((result) => {
      st.pending = false;
      if (st.key !== key) return;                       // src changed meanwhile
      applyResult(img, result);
      if (!result.ok && result.error !== 'tainted' && (st.retries || 0) < 2) {
        // Transient failure (detector still starting, network hiccup): it stays
        // blurred meanwhile, try again a bit later.
        st.retries = (st.retries || 0) + 1;
        setTimeout(() => { if (st.key === key) { st.result = null; processImg(img); } }, 5000 * st.retries);
      }
    });
  }

  // ------------------------------------------------------------ <video>
  function trackVideo(v) {
    if (videos.has(v)) return;
    videos.add(v);
    tracked.add(v);
    info.set(v, info.get(v) || { safeStreak: 0, holdUntil: 0, blurred: true });
    const restart = () => { resetToPending(v); const st = info.get(v); st.holdUntil = 0; sampleVideo(v); };
    v.addEventListener('loadstart', restart);
    v.addEventListener('emptied', restart);
    v.addEventListener('loadeddata', () => sampleVideo(v));
    v.addEventListener('seeked', () => sampleVideo(v));
    v.addEventListener('play', () => sampleVideo(v));
    if (v.readyState >= 2) sampleVideo(v);
    else checkPoster(v);
  }

  function checkPoster(v) {
    // Before any frame is available the poster image is what the user sees.
    if (!v.poster || v.readyState >= 2) return;
    detectUrl(v.poster).then((result) => {
      if (v.readyState >= 2) return;
      applyResult(v, result);
    });
  }

  function sampleVideo(v) {
    if (!settings.enabled || !v.isConnected) return;
    const st = info.get(v);
    if (!st || st.sampling || v.readyState < 2 || !v.videoWidth) return;
    const now = performance.now();
    if (st.lastSample && now - st.lastSample < 400) return;
    st.lastSample = now;
    st.sampling = true;
    const dataUrl = pixelsFrom(v, v.videoWidth, v.videoHeight);  // null if cross-origin without CORS
    detectPixels(dataUrl).then((result) => {
      st.sampling = false;
      st.result = result;
      const verdict = R.decide(result, settings);
      const t = performance.now();
      if (verdict.blur) {
        st.safeStreak = 0;
        st.holdUntil = t + VIDEO_HOLD_MS;
        setBlurred(v, true);
      } else {
        st.safeStreak = (st.safeStreak || 0) + 1;
        if (t >= (st.holdUntil || 0) && (st.safeStreak >= VIDEO_SAFE_STREAK || v.paused)) setBlurred(v, false);
      }
    });
  }

  setInterval(() => {
    if (!settings.enabled || document.hidden) return;
    for (const v of videos) {
      if (!v.isConnected) { videos.delete(v); continue; }
      if (v.paused || v.ended || v.readyState < 2) continue;
      const r = v.getBoundingClientRect();
      if (r.bottom < 0 || r.right < 0 || r.top > innerHeight || r.left > innerWidth) continue;
      sampleVideo(v);
    }
  }, VIDEO_SAMPLE_MS);

  // ------------------------------------------------------------ CSS background images
  const bgQueue = new Set();
  let bgScheduled = false;
  const URL_RE = /url\(\s*(['"]?)(.*?)\1\s*\)/i;

  function queueBg(el) {
    if (el.nodeType !== 1 || el.tagName === 'IMG' || el.tagName === 'VIDEO' || el.tagName === 'SCRIPT' || el.tagName === 'STYLE') return;
    bgQueue.add(el);
    if (!bgScheduled) {
      bgScheduled = true;
      (window.requestIdleCallback || ((f) => setTimeout(() => f({ timeRemaining: () => BG_BATCH_BUDGET_MS }), 16)))(runBgQueue);
    }
  }

  function runBgQueue(deadline) {
    bgScheduled = false;
    const start = performance.now();
    for (const el of bgQueue) {
      bgQueue.delete(el);
      if (el.isConnected) checkBg(el);
      if (performance.now() - start > BG_BATCH_BUDGET_MS && deadline.timeRemaining() < 1) break;
    }
    if (bgQueue.size && !bgScheduled) {
      bgScheduled = true;
      (window.requestIdleCallback || ((f) => setTimeout(() => f({ timeRemaining: () => BG_BATCH_BUDGET_MS }), 16)))(runBgQueue);
    }
  }

  function checkBg(el) {
    const bg = getComputedStyle(el).backgroundImage;
    const m = bg && bg !== 'none' ? URL_RE.exec(bg) : null;
    const st = info.get(el);
    if (!m) {
      if (st) { el.removeAttribute('data-dm-bg'); tracked.delete(el); info.delete(el); }
      return;
    }
    const url = m[2];
    if (st && st.key === url) return;
    const rect = el.getBoundingClientRect();
    if (isSvgUrl(url) || (rect.width < settings.minMediaPx && rect.height < settings.minMediaPx)) return;
    const s = { key: url, blurred: true };
    info.set(el, s);
    el.setAttribute('data-dm-bg', 'pending');
    const p = /^(data|blob):/i.test(url) ? detectBgPixels(url) : detectUrl(url);
    p.then((result) => { if (s.key === url && info.get(el) === s) applyResult(el, result); });
  }

  function detectBgPixels(url) {
    return new Promise((resolve) => {
      const im = new Image();
      im.onload = () => resolve(detectPixels(pixelsFrom(im, im.naturalWidth, im.naturalHeight)));
      im.onerror = () => resolve({ ok: false, error: 'decode' });
      im.src = url;
    });
  }

  // ------------------------------------------------------------ scanning
  function scanElement(el) {
    if (el.tagName === 'IMG') processImg(el);
    else if (el.tagName === 'VIDEO') trackVideo(el);
    else queueBg(el);
    const sr = el.shadowRoot || (chrome.dom && chrome.dom.openOrClosedShadowRoot && safeShadow(el));
    if (sr) adoptShadowRoot(sr);
  }

  function safeShadow(el) { try { return chrome.dom.openOrClosedShadowRoot(el); } catch (e) { return null; } }

  function scanTree(root) {
    if (root.nodeType === 1) scanElement(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    let n = walker.nextNode();
    while (n) { scanElement(n); n = walker.nextNode(); }
  }

  const adoptedRoots = new WeakSet();
  function adoptShadowRoot(sr) {
    if (adoptedRoots.has(sr)) return;
    adoptedRoots.add(sr);
    const style = document.createElement('style');
    style.textContent = BLUR_CSS;
    style.disabled = !settings.enabled;
    sr.prepend(style);
    shadowStyles.push(new WeakRef(style));
    observer.observe(sr, OBSERVE_OPTS);
    scanTree(sr);
  }

  const OBSERVE_OPTS = { childList: true, subtree: true, attributes: true,
    attributeFilter: ['src', 'srcset', 'style', 'class', 'poster'] };

  const observer = new MutationObserver((records) => {
    if (!settings.enabled) return;
    for (const rec of records) {
      if (rec.type === 'childList') {
        for (const node of rec.addedNodes) if (node.nodeType === 1) scanTree(node);
      } else if (rec.type === 'attributes') {
        const el = rec.target;
        if (el.tagName === 'IMG' && (rec.attributeName === 'src' || rec.attributeName === 'srcset')) {
          // Re-blur at once (this runs before the next paint), then check the new picture.
          resetToPending(el);
          processImg(el);
        } else if (el.tagName === 'VIDEO' && rec.attributeName === 'poster') {
          checkPoster(el);
        } else if (rec.attributeName === 'style' || rec.attributeName === 'class') {
          queueBg(el);
        }
      }
    }
  });

  // Images finish loading (lazy loading, srcset switches) -> check them.
  document.addEventListener('load', (e) => {
    const t = e.target;
    if (t && t.tagName === 'IMG') {
      const st = info.get(t);
      if (st && st.key !== (t.currentSrc || t.src)) resetToPending(t);
      processImg(t);
    }
  }, true);
  document.addEventListener('error', (e) => {
    const t = e.target;
    if (t && t.tagName === 'IMG' && t.naturalWidth === 0) setBlurred(t, false);
  }, true);

  // ------------------------------------------------------------ settings
  function applyEnabled() {
    if (settings.enabled) document.documentElement.removeAttribute('data-dm-off');
    else document.documentElement.setAttribute('data-dm-off', '');
    for (const ref of shadowStyles) { const s = ref.deref(); if (s) s.disabled = !settings.enabled; }
  }

  function redecideAll() {
    for (const el of tracked) {
      if (!el.isConnected) { tracked.delete(el); continue; }
      const st = info.get(el);
      if (st && st.result) setBlurred(el, R.decide(st.result, settings).blur);
    }
  }

  async function loadSettings() {
    const s = await send({ type: 'get-settings' });
    if (s) settings = s;
    applyEnabled();
  }

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'managed' || (area === 'local' && changes.settings)) {
      const wasEnabled = settings.enabled;
      loadSettings().then(() => {
        if (settings.enabled && !wasEnabled) scanTree(document.documentElement);
        else redecideAll();
      });
    }
  });

  // ------------------------------------------------------------ start
  observer.observe(document.documentElement || document, OBSERVE_OPTS);
  loadSettings().then(() => {
    if (!settings.enabled) return;
    scanTree(document.documentElement);
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => scanTree(document.documentElement), { once: true });
    }
  });
})();
