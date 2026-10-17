/*
 * DevOS Modesty filter - service worker.
 * - fetches images with the extension's host permission (no canvas tainting,
 *   no CORS), shrinks them and hands them to the offscreen document where the
 *   face/gender model runs. Nothing is sent anywhere except back to the page's
 *   own content script; the only network request is the re-fetch of the image
 *   from the server the page already loaded it from.
 * - keeps the per-tab "blurred" counter and badge.
 */
'use strict';
importScripts('rules.js');

const MAX_SIDE = 512;              // analysed image size (longest side, px)
const MAX_FETCH_BYTES = 25 << 20;  // ignore huge downloads (stay blurred)
const MAX_PARALLEL_FETCHES = 4;
const CACHE_LIMIT = 800;

const resultCache = new Map();     // url -> Promise<result>
const tabFrames = new Map();       // tabId -> Map(frameId -> count)

// ---------------------------------------------------------------- settings
async function readManaged() {
  try { return await chrome.storage.managed.get(null); } catch (e) { return {}; }
}
async function readLocal() {
  const got = await chrome.storage.local.get(['settings', 'totalBlurred']);
  return { settings: got.settings || {}, totalBlurred: got.totalBlurred || 0 };
}
async function currentSettings() {
  const [managed, local] = await Promise.all([readManaged(), readLocal()]);
  return { managed, local: local.settings, effective: ModestyRules.effectiveSettings(managed, local.settings), totalBlurred: local.totalBlurred };
}

// ---------------------------------------------------------------- offscreen
let creating = null;
async function ensureOffscreen() {
  const url = chrome.runtime.getURL('offscreen.html');
  if (chrome.runtime.getContexts) {
    const ctx = await chrome.runtime.getContexts({ contextTypes: ['OFFSCREEN_DOCUMENT'], documentUrls: [url] });
    if (ctx.length) return;
  }
  if (!creating) {
    creating = chrome.offscreen.createDocument({
      url: 'offscreen.html',
      reasons: ['WORKERS'],
      justification: 'Runs the local face/gender model (TensorFlow.js) that decides which images to blur.',
    }).catch((e) => { if (!String(e).includes('single offscreen')) throw e; })
      .finally(() => { creating = null; });
  }
  await creating;
}

async function detectInOffscreen(dataUrl) {
  await ensureOffscreen();
  // The offscreen page needs a moment to parse the 1.3 MB detector bundle
  // before its message listener exists; keep trying for ~20 s.
  for (let attempt = 0; attempt < 40; attempt++) {
    try {
      const res = await chrome.runtime.sendMessage({ target: 'offscreen', type: 'detect', dataUrl });
      if (res) return res;
    } catch (e) { /* receiver not ready yet */ }
    await new Promise((r) => setTimeout(r, 500));
    if (attempt === 10) await ensureOffscreen();
  }
  return { ok: false, error: 'detector unavailable' };
}

// ---------------------------------------------------------------- fetch + shrink
let activeFetches = 0;
const fetchWaiters = [];
async function withFetchSlot(fn) {
  if (activeFetches >= MAX_PARALLEL_FETCHES) await new Promise((r) => fetchWaiters.push(r));
  activeFetches++;
  try { return await fn(); } finally {
    activeFetches--;
    const next = fetchWaiters.shift();
    if (next) next();
  }
}

function bytesToBase64(bytes) {
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

async function blobToSmallDataUrl(blob) {
  const bmp = await createImageBitmap(blob);
  const srcW = bmp.width, srcH = bmp.height;
  const scale = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height));
  const w = Math.max(1, Math.round(bmp.width * scale)), h = Math.max(1, Math.round(bmp.height * scale));
  const canvas = new OffscreenCanvas(w, h);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#fff';                    // transparent PNGs -> white, not black
  ctx.fillRect(0, 0, w, h);
  ctx.drawImage(bmp, 0, 0, w, h);
  bmp.close();
  const out = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.9 });
  return { dataUrl: 'data:image/jpeg;base64,' + bytesToBase64(new Uint8Array(await out.arrayBuffer())), width: srcW, height: srcH };
}

async function fetchImage(url) {
  let resp = await fetch(url, { credentials: 'omit', cache: 'force-cache' });
  if (!resp.ok) resp = await fetch(url, { credentials: 'include', cache: 'force-cache' });
  if (!resp.ok) throw new Error('HTTP ' + resp.status);
  const blob = await resp.blob();
  if (blob.size > MAX_FETCH_BYTES) throw new Error('image too large');
  return blob;
}

function detectUrl(url) {
  if (resultCache.has(url)) return resultCache.get(url);
  const p = withFetchSlot(async () => {
    try {
      const blob = await fetchImage(url);
      const small = await blobToSmallDataUrl(blob);
      const res = await detectInOffscreen(small.dataUrl);
      if (!res.ok) resultCache.delete(url);   // retry later instead of caching a failure
      return res;
    } catch (e) {
      resultCache.delete(url);
      return { ok: false, error: String(e && e.message || e) };
    }
  });
  resultCache.set(url, p);
  if (resultCache.size > CACHE_LIMIT) resultCache.delete(resultCache.keys().next().value);
  return p;
}

// ---------------------------------------------------------------- counters
function updateBadge(tabId) {
  const frames = tabFrames.get(tabId);
  let n = 0;
  if (frames) for (const c of frames.values()) n += c;
  chrome.action.setBadgeBackgroundColor({ tabId, color: '#3a5a40' }).catch(() => {});
  chrome.action.setBadgeText({ tabId, text: n ? String(n > 999 ? '999+' : n) : '' }).catch(() => {});
  return n;
}
function tabCount(tabId) {
  const frames = tabFrames.get(tabId);
  let n = 0;
  if (frames) for (const c of frames.values()) n += c;
  return n;
}

chrome.tabs.onRemoved.addListener((tabId) => tabFrames.delete(tabId));
chrome.tabs.onUpdated.addListener((tabId, info) => {
  if (info.status === 'loading') { tabFrames.delete(tabId); updateBadge(tabId); }
});

// ---------------------------------------------------------------- messages
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || msg.target === 'offscreen') return false;
  switch (msg.type) {
    case 'detect-url':
      detectUrl(msg.url).then(sendResponse);
      return true;
    case 'detect-pixels':
      detectInOffscreen(msg.dataUrl).then(sendResponse, (e) => sendResponse({ ok: false, error: String(e) }));
      return true;
    case 'get-settings':
      currentSettings().then((s) => sendResponse(s.effective));
      return true;
    case 'count': {
      const tabId = sender.tab && sender.tab.id;
      if (tabId === undefined || tabId < 0) return false;
      if (!tabFrames.has(tabId)) tabFrames.set(tabId, new Map());
      tabFrames.get(tabId).set(sender.frameId || 0, Math.max(0, msg.count | 0));
      updateBadge(tabId);
      if (msg.newly > 0) {
        chrome.storage.local.get('totalBlurred').then((g) =>
          chrome.storage.local.set({ totalBlurred: (g.totalBlurred || 0) + (msg.newly | 0) }));
      }
      return false;
    }
    case 'popup-state':
      currentSettings().then((s) => sendResponse({
        effective: s.effective, managed: s.managed, local: s.local,
        total: s.totalBlurred, tab: msg.tabId !== undefined ? tabCount(msg.tabId) : 0,
      }));
      return true;
    case 'popup-set': {
      // effectiveSettings() enforces the lock, so a locked filter cannot be
      // loosened even if this message is forged.
      readLocal().then(({ settings }) => {
        const next = Object.assign({}, settings);
        if (typeof msg.enabled === 'boolean') next.enabled = msg.enabled;
        if (ModestyRules.MODES.includes(msg.mode)) next.mode = msg.mode;
        return chrome.storage.local.set({ settings: next });
      }).then(() => currentSettings()).then((s) => sendResponse(s.effective));
      return true;
    }
    default:
      return false;
  }
});

// Start the model early so the first image on a page is not slowed down.
chrome.runtime.onStartup.addListener(() => { ensureOffscreen().catch(() => {}); });
chrome.runtime.onInstalled.addListener(() => { ensureOffscreen().catch(() => {}); });
