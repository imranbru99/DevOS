/* DevOS Modesty filter: if a photo contains a girl, blur that whole photo.
 * Photos with no girl stay clear. The blur stays on the photo itself. */
(() => {
  'use strict';
  if (window.__devosModestyLoaded) return;
  window.__devosModestyLoaded = true;

  const R = globalThis.ModestyRules;
  const VIDEO_SAMPLE_MS = 750;
  const PIXEL_MAX_SIDE = 640;
  const BG_BATCH_BUDGET_MS = 8;
  const BLUR_CSS = 'img[data-dm-girl="1"],video[data-dm-girl="1"]{filter:blur(18px) !important}';

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
  const XLINK_NS = 'http://www.w3.org/1999/xlink';
  const TECH_DEVICE_REGEX = /\b(?:router|modem|switch|access[\s_-]?point|onu|gpon|epon|adapter|ethernet|wi-fi|wifi|gigabit|mbps|antenna|motherboard|gpu|cpu|ram|ssd|hard[\s_-]?drive|hdd|processor|laptop|desktop|monitor|display|keyboard|mouse|printer|scanner|webcam|casing|chassis|gadget|circuit|pcb)\b/i;

  function isHardwareOrTechContext(img) {
    try {
      const src = img.currentSrc || img.src || '';
      const alt = img.alt || '';
      const title = img.title || '';
      if (TECH_DEVICE_REGEX.test(alt) || TECH_DEVICE_REGEX.test(title) || TECH_DEVICE_REGEX.test(src)) return true;
      const docTitle = document.title || '';
      const url = location.href || '';
      if (TECH_DEVICE_REGEX.test(docTitle) || TECH_DEVICE_REGEX.test(url)) {
        if (img.closest('.product, .gallery, .item, #product, [class*="product"], [class*="gallery"], [class*="image"]')) return true;
      }
    } catch (e) {}
    return false;
  }

  const resize = new ResizeObserver((entries) => {
    for (const entry of entries) {
      const st = info.get(entry.target);
      if (st && st.filterImage) positionMask(entry.target, st);
    }
  });

  function removeRender(el) {
    const st = info.get(el);
    if (!st) return;
    if (st.overlay) {
      st.overlay.remove();
      st.overlay = null;
      resize.unobserve(el);
    }
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
    if (el.tagName === 'IMG' || el.tagName === 'VIDEO') {
      if (blurred) el.setAttribute('data-dm-girl', '1');
      else el.removeAttribute('data-dm-girl');
    }
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

  function getVisibleBox(el) {
    if (!el || !el.isConnected) return null;
    const css = window.getComputedStyle(el);
    if (css.display === 'none' || css.visibility === 'hidden' || css.visibility === 'collapse' || parseFloat(css.opacity) === 0) {
      return null;
    }
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return null;

    const vw = window.innerWidth || document.documentElement.clientWidth || 1000;
    const vh = window.innerHeight || document.documentElement.clientHeight || 1000;

    let left = Math.max(0, r.left);
    let top = Math.max(0, r.top);
    let right = Math.min(vw, r.right);
    let bottom = Math.min(vh, r.bottom);

    if (right <= left || bottom <= top) return null;

    let parent = el.parentElement;
    while (parent && parent !== document.documentElement && parent !== document.body) {
      const ps = window.getComputedStyle(parent);
      if (ps.display === 'none' || ps.visibility === 'hidden' || parseFloat(ps.opacity) === 0) {
        return null;
      }
      const overflow = (ps.overflow || '') + (ps.overflowX || '') + (ps.overflowY || '');
      if (/(hidden|scroll|auto|clip)/.test(overflow)) {
        const pr = parent.getBoundingClientRect();
        left = Math.max(left, pr.left);
        top = Math.max(top, pr.top);
        right = Math.min(right, pr.right);
        bottom = Math.min(bottom, pr.bottom);
        if (right <= left || bottom <= top) return null;
      }
      parent = parent.parentElement;
    }

    return { r, visible: { left, top, right, bottom } };
  }

  let repositionTimer = null;
  function startRepositionLoop() {
    if (repositionTimer) return;
    repositionTimer = setInterval(() => {
      let hasOverlays = false;
      for (const el of tracked) {
        if (!el.isConnected) {
          removeRender(el);
          tracked.delete(el);
          videos.delete(el);
          continue;
        }
        const st = info.get(el);
        if (st && st.overlay) {
          hasOverlays = true;
          positionMask(el, st);
        }
      }
      if (!hasOverlays) {
        clearInterval(repositionTimer);
        repositionTimer = null;
      }
    }, 250);
  }

  function positionMask(el, st) {
    if (!st) return;
    if (st.overlay) {
      const ov = st.overlay;
      if (!el.isConnected) {
        ov.style.display = 'none';
        return;
      }
      const box = getVisibleBox(el);
      if (!box) {
        ov.style.display = 'none';
        return;
      }
      const { r, visible } = box;
      ov.style.position = 'fixed';
      ov.style.left = `${r.left}px`;
      ov.style.top = `${r.top}px`;
      ov.style.width = `${Math.max(1, r.width)}px`;
      ov.style.height = `${Math.max(1, r.height)}px`;

      const elStyle = window.getComputedStyle(el);
      if (elStyle.borderRadius && elStyle.borderRadius !== '0px') {
        ov.style.borderRadius = elStyle.borderRadius;
      }
      // A screen capture is already the pixels on screen, including letterbox
      // bars. Stretching that bitmap with the video's object-fit would slide
      // the blur off her body.
      if (st.result && st.result.presented) {
        ov.style.objectFit = 'fill';
        ov.style.objectPosition = 'center';
      } else {
        if (elStyle.objectFit) ov.style.objectFit = elStyle.objectFit;
        if (elStyle.objectPosition) ov.style.objectPosition = elStyle.objectPosition;
      }

      const insetTop = Math.max(0, Math.round(visible.top - r.top));
      const insetRight = Math.max(0, Math.round(r.right - visible.right));
      const insetBottom = Math.max(0, Math.round(r.bottom - visible.bottom));
      const insetLeft = Math.max(0, Math.round(visible.left - r.left));
      if (insetTop > 0 || insetRight > 0 || insetBottom > 0 || insetLeft > 0) {
        ov.style.clipPath = `inset(${insetTop}px ${insetRight}px ${insetBottom}px ${insetLeft}px)`;
      } else {
        ov.style.clipPath = 'none';
      }
      ov.style.display = 'block';
      return;
    }
    if (!st.filterImage) return;
    const css = getComputedStyle(el);
    const left = (parseFloat(css.borderLeftWidth) || 0) + (parseFloat(css.paddingLeft) || 0);
    const top = (parseFloat(css.borderTopWidth) || 0) + (parseFloat(css.paddingTop) || 0);
    const w = el.clientWidth - (parseFloat(css.paddingLeft) || 0) - (parseFloat(css.paddingRight) || 0);
    const h = el.clientHeight - (parseFloat(css.paddingTop) || 0) - (parseFloat(css.paddingBottom) || 0);
    if (w <= 0 || h <= 0 || el.clientWidth <= 0 || el.clientHeight <= 0) return;
    const fit = R.fitBox(st.result.width, st.result.height, w, h, css.objectFit, css.objectPosition);
    // In primitiveUnits="objectBoundingBox", coordinates are fractions in [0, 1]
    const normX = Math.max(0, Math.min(1, (fit.x + left) / el.clientWidth));
    const normY = Math.max(0, Math.min(1, (fit.y + top) / el.clientHeight));
    const normW = Math.max(0, Math.min(1, fit.w / el.clientWidth));
    const normH = Math.max(0, Math.min(1, fit.h / el.clientHeight));
    st.filterImage.setAttribute('x', normX);
    st.filterImage.setAttribute('y', normY);
    st.filterImage.setAttribute('width', normW);
    st.filterImage.setAttribute('height', normH);
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
    // Prefer painted overlays (blurLayer). Google Images often ignores SVG
    // filters on <img>, so overlays are what the user actually sees.
    const layers = await Promise.all(verdict.regions.map((r) => new Promise((resolve, reject) => {
      const im = new Image(); im.onload = () => resolve(im); im.onerror = reject; im.src = r.blurLayer || r.mask;
    })));
    if (st.generation !== generation || !settings.enabled || !el.isConnected) return;
    removeRender(el);

    const sheet = document.createElement('canvas');
    sheet.width = st.result.width;
    sheet.height = st.result.height;
    const sctx = sheet.getContext('2d');
    layers.forEach((im) => sctx.drawImage(im, 0, 0, sheet.width, sheet.height));

    const overlay = document.createElement('img');
    overlay.src = sheet.toDataURL('image/png');
    overlay.alt = '';
    overlay.setAttribute('data-dm-internal', '');
    overlay.setAttribute('aria-hidden', 'true');
    overlay.draggable = false;
    const computed = window.getComputedStyle(el);
    overlay.style.cssText = [
      'position:fixed',
      'margin:0',
      'padding:0',
      'border:0',
      'pointer-events:none',
      'z-index:2147483646',
      `object-fit:${computed.objectFit || 'fill'}`,
      `object-position:${computed.objectPosition || 'center'}`,
      `border-radius:${computed.borderRadius || '0px'}`,
      'image-rendering:auto',
    ].join(';');
    document.documentElement.appendChild(overlay);
    st.overlay = overlay;
    positionMask(el, st);
    resize.observe(el);
    startRepositionLoop();
    setBlurred(el, true);
  }

  function applyResult(el, result) {
    const st = info.get(el) || {};
    st.result = result; info.set(el, st);
    if (!result || !result.ok) {
      st.generation = (st.generation || 0) + 1;
      setBlurred(el, false);
      return;
    }
    // Devices and hardware must not be blurred by noise; require high confidence genuine face
    if (st.isTechDevice) {
      const confidentFace = (result.faces || []).some((f) => Number(f.score) >= 0.70 && Number(f.genderProbability) >= 0.80);
      if (!confidentFace) {
        st.generation = (st.generation || 0) + 1;
        setBlurred(el, false);
        return;
      }
    }
    const verdict = R.decide(result, settings);
    if (!verdict.blur) { st.generation = (st.generation || 0) + 1; setBlurred(el, false); return; }
    // Blur the photo element immediately. The overlay is extra; a failed
    // overlay must not put the girl back in view.
    if (el.tagName === 'IMG' || el.tagName === 'VIDEO') el.setAttribute('data-dm-girl', '1');
    renderRegions(el, verdict).catch(() => {});
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
  const nearViewportObserver = typeof IntersectionObserver !== 'undefined' ? new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        nearViewportObserver.unobserve(entry.target);
        doProcessImg(entry.target);
      }
    }
  }, { rootMargin: '600px 0px 600px 0px' }) : null;

  function isNearViewport(el) {
    try {
      const r = el.getBoundingClientRect();
      const vh = window.innerHeight || 800;
      const vw = window.innerWidth || 1200;
      return r.bottom >= -600 && r.top <= vh + 600 && r.right >= -600 && r.left <= vw + 600;
    } catch (e) {
      return true;
    }
  }

  function processImg(img) {
    if (!settings.enabled) return;
    if (isNearViewport(img) || !nearViewportObserver) {
      doProcessImg(img);
    } else {
      nearViewportObserver.observe(img);
    }
  }

  function doProcessImg(img) {
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
    st.isTechDevice = isHardwareOrTechContext(img);
    st.pending = true;
    let p;
    if (/^(data|blob):/i.test(key)) {
      const shot = pixelsFrom(img, img.naturalWidth, img.naturalHeight);
      p = shot
        ? detectPixels(shot)
        : captureElement(img).then((cap) => detectPixels(cap).then((result) => {
          if (result && cap) result.presented = true;
          return result;
        }));
    } else {
      p = detectUrl(key);
    }
    p.then(async (result) => {
      st.pending = false;
      if (st.key !== key) return;                       // src changed meanwhile
      let safe = result && typeof result === 'object' ? result : { ok: false, error: 'no response' };
      // A blocked photo URL still shows on screen. Read those pixels once.
      const startup = !safe.ok && (safe.error === 'detector unavailable' || safe.error === 'no response');
      if (!safe.ok && !startup && safe.error !== 'tainted' && !st.captured) {
        st.captured = true;
        const cap = await captureElement(img);
        if (st.key !== key) return;
        if (cap) {
          const again = await detectPixels(cap);
          if (again && again.ok) { again.presented = true; safe = again; }
        }
      }
      if (st.key !== key) return;
      applyResult(img, safe);
      // The face model can take a while to start. Keep this photo in the
      // queue until a real check finishes, instead of leaving it sharp.
      const transient = !safe.ok && safe.error !== 'tainted';
      if (transient && (st.retries || 0) < 12) {
        st.retries = (st.retries || 0) + 1;
        const wait = Math.min(20000, 1500 * st.retries);
        setTimeout(() => { if (st.key === key) { st.result = null; st.captured = false; processImg(img); } }, wait);
      }
    }).catch(() => {
      st.pending = false;
      if (st.key !== key || (st.retries || 0) >= 12) return;
      st.retries = (st.retries || 0) + 1;
      setTimeout(() => { if (st.key === key) { st.result = null; processImg(img); } }, 2000);
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

  function topGeometry(el) {
    const r = el.getBoundingClientRect();
    let x = r.left, y = r.top, view = window;
    try {
      while (view.frameElement) {
        const fr = view.frameElement.getBoundingClientRect();
        x += fr.left;
        y += fr.top;
        view = view.parent;
      }
    } catch (e) {
      return null;
    }
    return {
      x, y, w: r.width, h: r.height,
      viewportW: view.innerWidth || r.width,
      viewportH: view.innerHeight || r.height,
    };
  }

  async function captureElement(el) {
    const rect = topGeometry(el);
    if (!rect || rect.w < 8 || rect.h < 8) return null;
    const hidden = [];
    document.querySelectorAll('[data-dm-internal]').forEach((node) => {
      hidden.push([node, node.style.visibility]);
      node.style.visibility = 'hidden';
    });
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    let res = null;
    try {
      res = await send({ type: 'capture-region', rect });
    } finally {
      for (const [node, visibility] of hidden) node.style.visibility = visibility;
    }
    return res && res.dataUrl ? res.dataUrl : null;
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
    const job = dataUrl
      ? detectPixels(dataUrl).then((result) => result)
      : captureElement(v).then((shot) => detectPixels(shot).then((result) => {
        if (result && shot) result.presented = true;
        return result;
      }));
    job.then((result) => {
      st.sampling = false;
      if (v.paused) st.pauseTries = (st.pauseTries || 0) + 1;
      if ((st.generation || 0) !== generation) return;
      applyResult(v, result);
    });
  }

  setInterval(() => {
    if (!settings.enabled || document.hidden) return;
    for (const v of videos) {
      if (!v.isConnected) { videos.delete(v); continue; }
      if (v.ended || v.readyState < 2) continue;
      const st = info.get(v);
      // A paused Facebook video is what the user is looking at. Keep trying
      // until a check succeeds, including the screen-capture fallback.
      if (v.paused && st && st.result && st.result.ok && (st.blurred || (st.pauseTries || 0) >= 4)) continue;
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
        for (const node of rec.removedNodes) {
          if (node.nodeType === 1) {
            if (tracked.has(node)) { removeRender(node); tracked.delete(node); videos.delete(node); }
            if (node.querySelectorAll) {
              const nested = node.querySelectorAll('[data-dm], [data-dm-bg], video, img');
              for (const n of nested) {
                if (tracked.has(n)) { removeRender(n); tracked.delete(n); videos.delete(n); }
              }
            }
          }
        }
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
          if (st && st.blurred && (el.tagName === 'IMG' || el.tagName === 'VIDEO')) el.setAttribute('data-dm-girl', '1');
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

  // Google Images / lazy grids often swap src after first paint — rescan on
  // scroll so newly revealed thumbnails are checked without a full reload.
  let scrollScanTimer = null;
  function scheduleScrollScan() {
    if (!settings.enabled || scrollScanTimer) return;
    scrollScanTimer = setTimeout(() => {
      scrollScanTimer = null;
      if (!settings.enabled) return;
      document.querySelectorAll('img').forEach((img) => {
        if (!img.complete || !img.naturalWidth) return;
        const st = info.get(img);
        const key = img.currentSrc || img.src || '';
        if (!st || st.key !== key || (!st.result && !st.pending)) processImg(img);
      });
    }, 400);
  }
  window.addEventListener('scroll', scheduleScrollScan, { passive: true, capture: true });
  // Keep painted body overlays locked to their images while the page scrolls.
  window.addEventListener('scroll', () => {
    for (const el of tracked) {
      const st = info.get(el);
      if (st && st.overlay) positionMask(el, st);
    }
  }, { passive: true, capture: true });

  // ------------------------------------------------------------ start
  observer.observe(document.documentElement || document, OBSERVE_OPTS);
  loadSettings().then(() => {
    if (!settings.enabled) return;
    scanTree(document.documentElement);
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => scanTree(document.documentElement), { once: true });
    }
    // Second pass after Google Images finishes hydrating thumbnails.
    setTimeout(() => { if (settings.enabled) scanTree(document.documentElement); }, 1500);
    setTimeout(() => { if (settings.enabled) scanTree(document.documentElement); }, 4000);
  });
})();
