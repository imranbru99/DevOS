/* DevOS Modesty filter: local body masks on media pixels.
 * Never apply a blur to HTML containers or use a whole-image fallback. */
(() => {
  'use strict';
  if (window.__devosModestyLoaded) return;
  window.__devosModestyLoaded = true;

  const R = globalThis.ModestyRules;
  const VIDEO_SAMPLE_MS = 750;
  const PIXEL_MAX_SIDE = 384;
  const BG_BATCH_BUDGET_MS = 8;
  const BLUR_CSS = ''; // Regional SVG filters never blur a page container.

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
        if (!el.isConnected) { removeRender(el); tracked.delete(el); videos.delete(el); continue; }
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

  let filterSequence = 0;
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const resize = new ResizeObserver((entries) => {
    for (const entry of entries) {
      const st = info.get(entry.target);
      if (st && st.filterImage) positionMask(entry.target, st);
    }
  });

  function removeRender(el) {
    const st = info.get(el);
    if (!st) return;
    if (st.svg) {
      if (el.style.filter === st.appliedFilter) {
        if (st.originalFilter) el.style.setProperty('filter', st.originalFilter, st.filterPriority);
        else el.style.removeProperty('filter');
      }
      st.svg.remove(); st.svg = null; st.filterImage = null;
      resize.unobserve(el);
    }
    if (st.bgApplied) {
      if (el.style.backgroundImage === st.bgApplied) {
        if (st.originalInlineBG) el.style.setProperty('background-image', st.originalInlineBG, st.bgPriority);
        else el.style.removeProperty('background-image');
      }
      st.bgApplied = null;
    }
  }

  function setBlurred(el, blurred) {
    const st = info.get(el) || {};
    el.setAttribute(attrFor(el), blurred ? 'regional' : 'ok');
    if (blurred && !st.blurred) newlyBlurred++;
    if (!blurred) removeRender(el);
    st.blurred = blurred;
    info.set(el, st); tracked.add(el); reportCount();
  }

  function resetToPending(el) {
    const st = info.get(el);
    if (st) { st.key = null; st.result = null; st.pending = false; st.generation = (st.generation || 0) + 1; }
    setBlurred(el, false);
  }

  function positionMask(el, st) {
    const css = getComputedStyle(el);
    const left = parseFloat(css.borderLeftWidth) + parseFloat(css.paddingLeft);
    const top = parseFloat(css.borderTopWidth) + parseFloat(css.paddingTop);
    const w = el.clientWidth - parseFloat(css.paddingLeft) - parseFloat(css.paddingRight);
    const h = el.clientHeight - parseFloat(css.paddingTop) - parseFloat(css.paddingBottom);
    const fit = R.fitBox(st.result.width, st.result.height, Math.max(1, w), Math.max(1, h), css.objectFit, css.objectPosition);
    for (const [key, value] of Object.entries({ x: fit.x + left, y: fit.y + top, width: fit.w, height: fit.h })) {
      st.filterImage.setAttribute(key, value);
    }
  }

  function svgNode(name, attrs) {
    const node = document.createElementNS(SVG_NS, name);
    for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
    return node;
  }

  async function renderRegions(el, verdict) {
    const st = info.get(el);
    const generation = st.generation = (st.generation || 0) + 1;
    if (attrFor(el) === 'data-dm-bg') {
      removeRender(el);
      st.originalInlineBG = el.style.getPropertyValue('background-image');
      st.bgPriority = el.style.getPropertyPriority('background-image');
      const original = getComputedStyle(el).backgroundImage;
      // Each mask is a separate background layer, below all HTML text.
      if (R.cssLayers(original).length !== 1 || !/^url\(/.test(original)) { setBlurred(el, false); return; }
      el.style.setProperty('background-image', verdict.regions.map((r) => `url("${r.blurLayer}")`).concat(original).join(','), 'important');
      st.bgApplied = el.style.backgroundImage;
      setBlurred(el, true); return;
    }
    const masks = await Promise.all(verdict.regions.map((r) => new Promise((resolve, reject) => {
      const im = new Image(); im.onload = () => resolve(im); im.onerror = reject; im.src = r.mask;
    })));
    if (st.generation !== generation || !settings.enabled || !el.isConnected) return;
    const mask = document.createElement('canvas');
    mask.width = st.result.width; mask.height = st.result.height;
    const ctx = mask.getContext('2d');
    masks.forEach((im) => ctx.drawImage(im, 0, 0, mask.width, mask.height));
    removeRender(el);
    st.originalFilter = el.style.getPropertyValue('filter');
    st.filterPriority = el.style.getPropertyPriority('filter');
    const existing = getComputedStyle(el).filter;
    const id = `devos-body-mask-${++filterSequence}`;
    const svg = svgNode('svg', { width: 0, height: 0, 'aria-hidden': 'true', 'data-dm-internal': '' });
    svg.style.cssText = 'position:absolute;pointer-events:none;overflow:hidden';
    const defs = svgNode('defs');
    const filter = svgNode('filter', { id, x: 0, y: 0, width: 1, height: 1, filterUnits: 'objectBoundingBox', 'color-interpolation-filters': 'sRGB' });
    const image = svgNode('feImage', { href: mask.toDataURL('image/png'), preserveAspectRatio: 'none', result: 'bodyMask' });
    filter.append(image, svgNode('feGaussianBlur', { in: 'SourceGraphic', stdDeviation: 14, result: 'soft' }),
      svgNode('feComposite', { in: 'soft', in2: 'bodyMask', operator: 'in', result: 'softBody' }),
      svgNode('feComposite', { in: 'SourceGraphic', in2: 'bodyMask', operator: 'out', result: 'clearArea' }));
    const merge = svgNode('feMerge'); merge.append(svgNode('feMergeNode', { in: 'clearArea' }), svgNode('feMergeNode', { in: 'softBody' }));
    filter.append(merge); defs.append(filter); svg.append(defs);
    const root = el.getRootNode(); (root.nodeType === 11 ? root : document.documentElement).append(svg);
    st.svg = svg; st.filterImage = image;
    positionMask(el, st); resize.observe(el);
    el.style.setProperty('filter', `${existing === 'none' ? '' : existing + ' '}url("#${id}")`, 'important');
    st.appliedFilter = el.style.filter;
    setBlurred(el, true);
  }

  function applyResult(el, result) {
    const st = info.get(el) || {};
    st.result = result; info.set(el, st);
    const verdict = R.decide(result, settings);
    if (!verdict.blur) { st.generation = (st.generation || 0) + 1; setBlurred(el, false); return; }
    renderRegions(el, verdict).catch(() => setBlurred(el, false));
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
        // Retry transient failures without applying a whole-image blur.
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
    info.set(v, info.get(v) || { blurred: false });
    const restart = () => { resetToPending(v); const st = info.get(v); st.lastSample = 0; sampleVideo(v); };
    v.addEventListener('loadstart', restart);
    v.addEventListener('emptied', restart);
    v.addEventListener('loadeddata', () => sampleVideo(v));
    v.addEventListener('seeked', () => { resetToPending(v); const st = info.get(v); st.lastSample = 0; sampleVideo(v); });
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
    const generation = st.generation || 0;
    const dataUrl = pixelsFrom(v, v.videoWidth, v.videoHeight);  // null if cross-origin without CORS
    detectPixels(dataUrl).then((result) => {
      st.sampling = false;
      if ((st.generation || 0) !== generation) return;
      applyResult(v, result);
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
    const existing = info.get(el);
    if (existing && existing.bgApplied && el.style.backgroundImage === existing.bgApplied) return;
    const bg = getComputedStyle(el).backgroundImage;
    const m = bg && bg !== 'none' ? URL_RE.exec(bg) : null;
    const st = info.get(el);
    if (!m) {
      if (st) { el.removeAttribute('data-dm-bg'); tracked.delete(el); info.delete(el); }
      return;
    }
    const url = m[2];
    if (st && st.key === url) { if (st.result && !st.bgApplied) applyResult(el, st.result); return; }
    const rect = el.getBoundingClientRect();
    if (isSvgUrl(url) || (rect.width < settings.minMediaPx && rect.height < settings.minMediaPx)) return;
    const s = { key: url, blurred: false };
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
    if (el.closest('[data-dm-internal]')) return;
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
          const st = info.get(el);
          if (st && st.bgApplied && (rec.attributeName === 'class' || el.style.backgroundImage !== st.bgApplied)) removeRender(el);
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
    else { document.documentElement.setAttribute('data-dm-off', ''); for (const el of tracked) { const st = info.get(el); if (st) st.generation = (st.generation || 0) + 1; setBlurred(el, false); } }
    for (const ref of shadowStyles) { const s = ref.deref(); if (s) s.disabled = !settings.enabled; }
  }

  function redecideAll() {
    for (const el of tracked) {
      if (!el.isConnected) { tracked.delete(el); continue; }
      const st = info.get(el);
      if (st && st.result) applyResult(el, st.result);
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
