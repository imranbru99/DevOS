/*
 * DevOS Modesty filter - offscreen document running the detector.
 * @vladmandic/face-api (TensorFlow.js inside): tiny face detector + age/gender
 * model, weights loaded from the extension package. Runs only on this PC.
 */
'use strict';

// The tiny face detector is scale sensitive: a face found at 0.9 at one input
// size can drop to 0.3 at another. Run three sizes and merge (lean to blur).
const DETECT_INPUTS = [224, 416, 608];   // multiples of 32
const DETECT_MIN_SCORE = 0.25;           // keep weak faces; rules.js applies the real threshold

let readyPromise = null;
let backend = 'none';
let personModel = null;

async function init() {
  const tf = faceapi.tf;
  let ok = false;
  try { ok = await tf.setBackend('webgl'); } catch (e) { ok = false; }
  if (ok) {
    try { await tf.ready(); } catch (e) { ok = false; }
  }
  if (!ok) { await tf.setBackend('cpu'); await tf.ready(); }
  backend = tf.getBackend();
  // Root-relative on purpose: face-api's URI helper collapses the "//" in
  // "chrome-extension://<id>/models" and the fetch then fails.
  const base = '/models';
  await faceapi.nets.tinyFaceDetector.loadFromUri(base);
  await faceapi.nets.ageGenderNet.loadFromUri(base);
  personModel = await globalThis['body-pix'].load({ architecture: 'MobileNetV1', outputStride: 16,
    multiplier: 0.5, quantBytes: 1, modelUrl: '/models/body-pix/model.json' });
}

function ready() {
  if (!readyPromise) readyPromise = init().catch((e) => { readyPromise = null; throw e; });
  return readyPromise;
}

function loadImage(dataUrl) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('image decode failed'));
    img.src = dataUrl;
  });
}

function toFace(f) {
  const b = f.detection.box;
  const pFemale = f.gender === 'female' ? f.genderProbability : 1 - f.genderProbability;
  return { score: f.detection.score, pFemale, age: f.age, x: b.x, y: b.y, w: b.width, h: b.height };
}

function iou(a, b) {
  const x1 = Math.max(a.x, b.x), y1 = Math.max(a.y, b.y);
  const x2 = Math.min(a.x + a.w, b.x + b.w), y2 = Math.min(a.y + a.h, b.y + b.h);
  const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
  return inter / (a.w * a.h + b.w * b.h - inter || 1);
}

// Same face seen at several scales -> one entry with the best detection score
// and the highest female probability among the confident views (score >= 0.5),
// so a disagreement between scales leans to blur but a weak, sloppy box
// around a man's face does not.
function mergeFaces(list) {
  const merged = [];
  for (const f of list.sort((a, b) => b.score - a.score)) {
    const m = merged.find((g) => iou(g, f) > 0.4);
    if (m) { if (f.score >= 0.5) m.pFemale = Math.max(m.pFemale, f.pFemale); m.views++; } else merged.push(Object.assign({ views: 1 }, f));
  }
  return merged.map((f) => ({
    score: +f.score.toFixed(3),
    gender: f.pFemale >= 0.5 ? 'female' : 'male',
    genderProbability: +(f.pFemale >= 0.5 ? f.pFemale : 1 - f.pFemale).toFixed(3),
    age: Math.round(f.age),
    x: Math.round(f.x),
    y: Math.round(f.y),
    w: Math.round(f.w),
    h: Math.round(f.h),
    views: f.views,
  }));
}

// Check whether a detected face box contains genuine human skin tones.
// Text, banners, and graphics have high contrast but almost 0% skin-tone pixels.
function hasSkinTone(img, b) {
  try {
    const bw = Math.max(1, Math.round(b.width || b.w || 0));
    const bh = Math.max(1, Math.round(b.height || b.h || 0));
    const bx = Math.max(0, Math.round(b.x || 0));
    const by = Math.max(0, Math.round(b.y || 0));
    if (bw < 14 || bh < 14) return false;
    const ratio = bw / bh;
    if (ratio < 0.45 || ratio > 2.2) return false;

    const c = document.createElement('canvas');
    c.width = 32; c.height = 32;
    const ctx = c.getContext('2d');
    ctx.drawImage(img, bx, by, bw, bh, 0, 0, 32, 32);
    const data = ctx.getImageData(0, 0, 32, 32).data;

    let skin = 0;
    const total = 32 * 32;
    for (let i = 0; i < data.length; i += 4) {
      const r = data[i], g = data[i + 1], b = data[i + 2];
      // Cross-ethnicity RGB skin tone detection
      if (r > 95 && g > 40 && b > 20 && Math.max(r, g, b) - Math.min(r, g, b) > 15 && Math.abs(r - g) > 15 && r > g && r > b) {
        skin++;
      }
    }
    return (skin / total) >= 0.12;
  } catch (e) {
    return true; // Fallback to allowing if canvas read fails
  }
}

function hasAnatomicalBody(pose) {
  if (!pose || !pose.keypoints) return false;
  let confidentKeypoints = 0;
  let hasTorso = false;
  for (const kp of pose.keypoints) {
    if (kp.score >= 0.25) {
      confidentKeypoints++;
      if (kp.part === 'leftShoulder' || kp.part === 'rightShoulder' || kp.part === 'leftHip' || kp.part === 'rightHip') {
        hasTorso = true;
      }
    }
  }
  return confidentKeypoints >= 3 && hasTorso;
}

let queue = Promise.resolve();
function detect(dataUrl) {
  const job = queue.then(async () => {
    await ready();
    const img = await loadImage(dataUrl);
    const found = [];
    for (const inputSize of DETECT_INPUTS) {
      const opts = new faceapi.TinyFaceDetectorOptions({ inputSize, scoreThreshold: DETECT_MIN_SCORE });
      for (const f of await faceapi.detectAllFaces(img, opts).withAgeAndGender()) {
        if (hasSkinTone(img, f.detection.box)) {
          found.push(toFace(f));
        }
      }
    }
    const faces = mergeFaces(found);
    const segments = await personModel.segmentMultiPerson(img, { internalResolution: 'medium',
      segmentationThreshold: 0.7, maxDetections: 8, scoreThreshold: 0.4, minKeypointScore: 0.25 });
    const used = new Set();
    const people = segments
      .filter((segment) => hasAnatomicalBody(segment.pose))
      .map((segment) => {
        const faceIndex = ModestyRules.matchFace(segment.pose, faces, used);
        if (faceIndex >= 0) used.add(faceIndex);
        const mask = document.createElement('canvas');
        mask.width = segment.width; mask.height = segment.height;
        const ctx = mask.getContext('2d');
        const pixels = ctx.createImageData(mask.width, mask.height);
        for (let i = 0; i < segment.data.length; i++) pixels.data[i * 4 + 3] = segment.data[i] ? 255 : 0;
        ctx.putImageData(pixels, 0, 0);
        const layer = document.createElement('canvas'); layer.width = mask.width; layer.height = mask.height;
        const lc = layer.getContext('2d'); lc.filter = 'blur(14px)'; lc.drawImage(img, 0, 0, layer.width, layer.height);
        lc.filter = 'none'; lc.globalCompositeOperation = 'destination-in'; lc.drawImage(mask, 0, 0);
        return { faceIndex, mask: mask.toDataURL('image/png'), blurLayer: layer.toDataURL('image/png') };
      });
    return { ok: true, backend, width: img.naturalWidth, height: img.naturalHeight, faces, people };
  });
  queue = job.catch(() => {});
  return job;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || msg.target !== 'offscreen') return false;
  if (msg.type === 'detect') {
    detect(msg.dataUrl).then(sendResponse, (e) => sendResponse({ ok: false, error: String(e && e.message || e) }));
    return true;
  }
  if (msg.type === 'ping') { ready().then(() => sendResponse({ ok: true, backend }), (e) => sendResponse({ ok: false, error: String(e) })); return true; }
  return false;
});

ready().catch(() => {});
