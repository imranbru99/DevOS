/*
 * DevOS Modesty filter - offscreen document running the detector.
 * @vladmandic/face-api (TensorFlow.js inside): tiny face detector + age/gender
 * model, weights loaded from the extension package. Runs only on this PC.
 */
'use strict';

// The tiny face detector is scale sensitive: a face found at 0.9 at one input
// size can drop to 0.3 at another. Run three sizes and merge (lean to blur).
const DETECT_INPUTS = [224, 416, 608];   // multiples of 32
const DETECT_MIN_SCORE = 0.40;           // keep confident faces; rules.js applies the real threshold

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

// Skin across light → deep tones. Old RGB (r>95 && r>g && r>b) missed many
 // real adult women (darker complexions, warm lighting, partial shade).
function isSkinPixel(r, g, b) {
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const lum = 0.299 * r + 0.587 * g + 0.114 * b;
  if (lum < 18 || lum > 250) return false;
  // YCbCr skin cluster (works for a wide range of ethnicities).
  const cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b;
  const cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b;
  if (cb >= 77 && cb <= 140 && cr >= 125 && cr <= 185) return true;
  // Soft RGB fallback for faces under strong warm/cool light.
  if (r > 50 && g > 25 && b > 10 && (max - min) > 8 && r >= g - 8 && r >= b - 8) return true;
  return false;
}

// Check whether a detected face box contains genuine human skin tones.
// Text, banners, hardware devices, and graphics have high contrast but almost 0% skin-tone pixels.
function hasSkinTone(img, b) {
  try {
    const bw = Math.max(1, Math.round(b.width || b.w || 0));
    const bh = Math.max(1, Math.round(b.height || b.h || 0));
    const bx = Math.max(0, Math.round(b.x || 0));
    const by = Math.max(0, Math.round(b.y || 0));
    if (bw < 12 || bh < 12) return false;
    const ratio = bw / bh;
    if (ratio < 0.4 || ratio > 2.4) return false;

    const c = document.createElement('canvas');
    c.width = 32; c.height = 32;
    const ctx = c.getContext('2d');
    ctx.drawImage(img, bx, by, bw, bh, 0, 0, 32, 32);
    const data = ctx.getImageData(0, 0, 32, 32).data;

    let skin = 0;
    let darkPixels = 0;
    let whitePixels = 0;
    const total = 32 * 32;
    for (let i = 0; i < data.length; i += 4) {
      const r = data[i], g = data[i + 1], b = data[i + 2];
      const lum = 0.299 * r + 0.587 * g + 0.114 * b;
      if (lum < 28) darkPixels++;
      if (lum > 245) whitePixels++;
      if (isSkinPixel(r, g, b)) skin++;
    }
    // Real face cannot be >75% pure dark hardware/black plastic or pure white background
    if (darkPixels / total > 0.75 || whitePixels / total > 0.75) return false;
    // Genuine face requires meaningful skin pixel coverage (lowered for darker tones)
    return (skin / total) >= 0.14;
  } catch (e) {
    return false;
  }
}

function hasAnatomicalBody(pose) {
  if (!pose || !pose.keypoints) return false;
  let confidentKeypoints = 0;
  let shoulderCount = 0;
  let hipCount = 0;
  let elbowCount = 0;
  let shoulderY = 0;
  let hipY = 0;

  for (const kp of pose.keypoints) {
    // Slightly lower score so side/cropped adult bodies still count.
    if (kp.score >= 0.28) {
      confidentKeypoints++;
      if (kp.part === 'leftShoulder' || kp.part === 'rightShoulder') {
        shoulderCount++;
        shoulderY += kp.position.y;
      }
      if (kp.part === 'leftHip' || kp.part === 'rightHip') {
        hipCount++;
        hipY += kp.position.y;
      }
      if (kp.part === 'leftElbow' || kp.part === 'rightElbow') elbowCount++;
    }
  }

  // Accept full bodies, torso crops, or hip+shoulder partial figures.
  const torsoOk = shoulderCount > 0 || (hipCount > 0 && elbowCount > 0);
  if (confidentKeypoints < 4 || !torsoOk) return false;

  // Anatomical check: shoulders must be above hips (Y increases downward)
  if (shoulderCount > 0 && hipCount > 0) {
    const avgShoulderY = shoulderY / shoulderCount;
    const avgHipY = hipY / hipCount;
    if (avgShoulderY >= avgHipY) return false;
  }

  return true;
}

function segmentSkinRatio(img, segment) {
  try {
    const w = segment.width, h = segment.height;
    if (w <= 0 || h <= 0) return 0;
    const c = document.createElement('canvas');
    c.width = 48; c.height = 48;
    const ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0, 48, 48);
    const data = ctx.getImageData(0, 0, 48, 48).data;

    let skin = 0;
    let sampled = 0;
    const scaleX = w / 48;
    const scaleY = h / 48;
    for (let cy = 0; cy < 48; cy += 2) {
      for (let cx = 0; cx < 48; cx += 2) {
        const sx = Math.min(w - 1, Math.round(cx * scaleX));
        const sy = Math.min(h - 1, Math.round(cy * scaleY));
        if (segment.data[sy * w + sx]) {
          sampled++;
          const idx = (cy * 48 + cx) * 4;
          const r = data[idx], g = data[idx + 1], b = data[idx + 2];
          if (isSkinPixel(r, g, b)) skin++;
        }
      }
    }
    if (sampled < 5) return 0;
    return skin / sampled;
  } catch (e) {
    return 0.1;
  }
}

function segmentHasSkin(img, segment) {
  // Real adult body / face / limbs: at least a little visible skin.
  return segmentSkinRatio(img, segment) >= 0.04;
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
    // Lower BodyPix gates so real adult bodies (side/crop/partial) still segment.
    const segments = await personModel.segmentMultiPerson(img, { internalResolution: 'medium',
      segmentationThreshold: 0.60, maxDetections: 8, scoreThreshold: 0.40, minKeypointScore: 0.28 });
    const used = new Set();
    const people = segments
      .filter((segment) => {
        const skin = segmentSkinRatio(img, segment);
        if (skin < 0.04) return false;
        // Full / partial anatomical pose, or a skin-heavy torso crop (midriff).
        if (hasAnatomicalBody(segment.pose)) return true;
        if (skin < 0.18) return false;
        const kps = (segment.pose.keypoints || []).filter((k) => k.score >= 0.22);
        return kps.length >= 2;
      })
      .map((segment) => {
        let faceIndex = ModestyRules.matchFace(segment.pose, faces, used);
        // Geometric fallback when nose/eyes are weak but a face sits above the torso.
        if (faceIndex < 0) faceIndex = ModestyRules.matchFaceByTorso(segment.pose, faces, used);
        if (faceIndex >= 0) used.add(faceIndex);
        const skinRatio = +segmentSkinRatio(img, segment).toFixed(3);
        const shoulders = (segment.pose.keypoints || []).filter((k) => /Shoulder$/.test(k.part) && k.score >= 0.20);
        const torsoY = shoulders.length
          ? shoulders.reduce((a, p) => a + p.position.y, 0) / shoulders.length
          : null;
        const mask = document.createElement('canvas');
        mask.width = segment.width; mask.height = segment.height;
        const ctx = mask.getContext('2d');
        const pixels = ctx.createImageData(mask.width, mask.height);
        for (let i = 0; i < segment.data.length; i++) pixels.data[i * 4 + 3] = segment.data[i] ? 255 : 0;
        ctx.putImageData(pixels, 0, 0);
        const layer = document.createElement('canvas'); layer.width = mask.width; layer.height = mask.height;
        const lc = layer.getContext('2d'); lc.filter = 'blur(22px)'; lc.drawImage(img, 0, 0, layer.width, layer.height);
        lc.filter = 'none'; lc.globalCompositeOperation = 'destination-in'; lc.drawImage(mask, 0, 0);
        return { faceIndex, skinRatio, torsoY, mask: mask.toDataURL('image/png'), blurLayer: layer.toDataURL('image/png') };
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
