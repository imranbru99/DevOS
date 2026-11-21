/*
 * DevOS Modesty filter — on-device detector.
 * MediaPipe Pose Landmarker (lite) + BlazeFace full-range find people and
 * faces. face-api's age/gender net runs only on those face crops. A single
 * tiny-face pass is the fallback if MediaPipe cannot start. Nothing is fetched
 * at runtime.
 */
const POSE_INDEX = {
  nose: 0, leftEye: 2, rightEye: 5, leftEar: 7, rightEar: 8,
  leftShoulder: 11, rightShoulder: 12, leftElbow: 13, rightElbow: 14,
  leftWrist: 15, rightWrist: 16, leftHip: 23, rightHip: 24,
  leftKnee: 25, rightKnee: 26, leftAnkle: 27, rightAnkle: 28,
};

let readyPromise = null;
let backend = 'none';
let useTinyFace = false;
let faceReady = false;
let poseReady = false;
let callSeq = 0;

async function initAgeGender() {
  const tf = faceapi.tf;
  let ok = false;
  try {
    if (tf.env) {
      try { tf.env().set('WEBGL_PACK', true); } catch (e) {}
    }
    ok = await tf.setBackend('webgl');
  } catch (e) { ok = false; }
  if (ok) {
    try { await tf.ready(); } catch (e) { ok = false; }
  }
  if (!ok) { await tf.setBackend('cpu'); await tf.ready(); }
  backend = tf.getBackend();
  await faceapi.nets.ageGenderNet.loadFromUri('/models');
}

// Face and pose each need their own wasm instance. Loading both in this
// document deadlocks the second graph, so they live in separate iframes.
function visionFrame(task) {
  return document.getElementById(task === 'pose' ? 'dm-pose' : 'dm-face');
}

function callVision(task, type, extra, ms) {
  const frame = visionFrame(task);
  const win = frame && frame.contentWindow;
  if (!win) return Promise.resolve({ ok: false, error: 'no frame' });
  const id = ++callSeq;
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      window.removeEventListener('message', onMsg);
      resolve({ ok: false, error: task + ' timeout' });
    }, ms);
    function onMsg(ev) {
      const msg = ev.data;
      if (!msg || msg.task !== task || msg.id !== id) return;
      clearTimeout(timer);
      window.removeEventListener('message', onMsg);
      resolve(msg);
    }
    window.addEventListener('message', onMsg);
    win.postMessage(Object.assign({ task, type, id }, extra || {}), '*');
  });
}

async function pingVision(task) {
  const deadline = Date.now() + 40000;
  while (Date.now() < deadline) {
    const res = await callVision(task, 'ping', {}, 2000);
    if (res && res.type === 'ready') return res;
    await new Promise((r) => setTimeout(r, 250));
  }
  return { ok: false, error: task + ' unavailable' };
}

async function init() {
  await initAgeGender();
  const [face, pose] = await Promise.all([pingVision('face'), pingVision('pose')]);
  faceReady = !!(face && face.ok);
  poseReady = !!(pose && pose.ok);
  if (!faceReady) {
    await faceapi.nets.tinyFaceDetector.loadFromUri('/models');
    useTinyFace = true;
    backend = poseReady ? 'pose+tiny-face' : 'tiny-face';
  } else {
    backend = poseReady ? 'mediapipe' : 'blazeface';
  }
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

function ycbcrSkin(r, g, b) {
  const lum = 0.299 * r + 0.587 * g + 0.114 * b;
  if (lum < 18 || lum > 245) return false;
  const cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b;
  const cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b;
  return cb >= 77 && cb <= 140 && cr >= 133 && cr <= 173;
}

function isSkinPixel(r, g, b) {
  if (ycbcrSkin(r, g, b)) return true;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const lum = 0.299 * r + 0.587 * g + 0.114 * b;
  if (lum < 18 || lum > 250) return false;
  return r > 50 && g > 25 && b > 10 && (max - min) > 8 && r >= g - 8 && r >= b - 8;
}

function lumOf(r, g, b) { return 0.299 * r + 0.587 * g + 0.114 * b; }

let scratch = null;
function pixelsOf(img) {
  const w = img.naturalWidth || img.width;
  const h = img.naturalHeight || img.height;
  if (!scratch) scratch = document.createElement('canvas');
  scratch.width = w;
  scratch.height = h;
  const ctx = scratch.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(img, 0, 0, w, h);
  return { ctx, w, h, data: ctx.getImageData(0, 0, w, h).data };
}

function sampleRegion(data, w, h, x, y, rw, rh) {
  const x0 = Math.max(0, Math.floor(x));
  const y0 = Math.max(0, Math.floor(y));
  const x1 = Math.min(w, Math.ceil(x + rw));
  const y1 = Math.min(h, Math.ceil(y + rh));
  let n = 0, skin = 0, lum = 0, dark = 0;
  for (let py = y0; py < y1; py += 2) {
    for (let px = x0; px < x1; px += 2) {
      const i = (py * w + px) * 4;
      const r = data[i], g = data[i + 1], b = data[i + 2];
      const L = lumOf(r, g, b);
      n++;
      lum += L;
      if (ycbcrSkin(r, g, b)) skin++;
      else if (L < 52) dark++;
    }
  }
  if (!n) return null;
  return { n, skin: skin / n, lum: lum / n, dark: dark / n };
}

function describeAppearance(data, w, h, face) {
  const fw = Math.max(8, face.w), fh = Math.max(8, face.h);
  const sideL = sampleRegion(data, w, h, face.x - fw * 0.95, face.y + fh * 0.1, fw * 0.7, fh * 0.75);
  const sideR = sampleRegion(data, w, h, face.x + fw * 1.25, face.y + fh * 0.1, fw * 0.7, fh * 0.75);
  const neck = sampleRegion(data, w, h, face.x + fw * 0.2, face.y + fh * 1.05, fw * 0.6, fh * 0.6);
  const sides = [sideL, sideR].filter(Boolean);
  const sideSkin = sides.length ? sides.reduce((a, s) => a + s.skin, 0) / sides.length : 1;
  const neckSkin = neck ? neck.skin : 1;
  const headCovered = sideSkin < 0.35 && neckSkin < 0.45;

  const cheekL = sampleRegion(data, w, h, face.x + fw * 0.08, face.y + fh * 0.35, fw * 0.28, fh * 0.28);
  const cheekR = sampleRegion(data, w, h, face.x + fw * 0.64, face.y + fh * 0.35, fw * 0.28, fh * 0.28);
  const chin = sampleRegion(data, w, h, face.x + fw * 0.28, face.y + fh * 0.72, fw * 0.44, fh * 0.28);
  const cheeks = [cheekL, cheekR].filter(Boolean);
  const cheekSkin = cheeks.length ? cheeks.reduce((a, s) => a + s.skin, 0) / cheeks.length : 0;
  const cheekLum = cheeks.length ? cheeks.reduce((a, s) => a + s.lum, 0) / cheeks.length : 0;
  const bearded = !!(chin && cheekSkin > 0.22 && chin.skin < 0.55 && chin.lum + 12 < cheekLum);

  const below = face.y + fh * 1.2;
  const columnH = fh * 4.2;
  const room = h - below;
  let clothedAdult = false;
  if (room >= fh * 3) {
    const column = sampleRegion(data, w, h, face.x + fw / 2 - fw * 1.1, below, fw * 2.2, Math.min(columnH, room));
    clothedAdult = !!(column && column.n >= 40 && column.dark >= 0.42);
  }
  return { headCovered, bearded, clothedAdult };
}

function clipBox(box, w, h) {
  let width = box.width;
  let height = box.height;
  let x = box.originX;
  let y = box.originY;
  if (width <= 2 && height <= 2) {
    x *= w; y *= h; width *= w; height *= h;
  }
  x = Math.max(0, x); y = Math.max(0, y);
  width = Math.min(w - x, width); height = Math.min(h - y, height);
  if (width < 8 || height < 8) return null;
  return { x, y, w: width, h: height };
}

function iou(a, b) {
  const x1 = Math.max(a.x, b.x), y1 = Math.max(a.y, b.y);
  const x2 = Math.min(a.x + a.w, b.x + b.w), y2 = Math.min(a.y + a.h, b.y + b.h);
  const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
  return inter / (a.w * a.h + b.w * b.h - inter || 1);
}

function dedupeFaces(list) {
  const kept = [];
  for (const face of list.sort((a, b) => b.score - a.score)) {
    if (kept.some((g) => iou(g, face) > 0.3)) continue;
    kept.push(face);
  }
  return kept;
}

async function ageGenderOf(img, face) {
  const canvas = document.createElement('canvas');
  canvas.width = 160;
  canvas.height = 160;
  const ctx = canvas.getContext('2d');
  const pad = 0.25;
  const sx = Math.max(0, face.x - face.w * pad);
  const sy = Math.max(0, face.y - face.h * pad);
  const sw = face.w * (1 + pad * 2);
  const sh = face.h * (1 + pad * 2);
  ctx.drawImage(img, sx, sy, sw, sh, 0, 0, 160, 160);
  try {
    const pred = await faceapi.predictAgeAndGender(canvas);
    return {
      age: Math.round(pred.age),
      gender: pred.gender,
      genderProbability: pred.genderProbability,
    };
  } catch (e) {
    return { age: NaN, gender: 'unknown', genderProbability: 0.5 };
  }
}

function rectFromFace(face, w, h) {
  const bw = Math.max(face.w * 3.6, 48);
  const bh = Math.max(face.h * 8.5, 120);
  let x = face.x + face.w / 2 - bw / 2;
  let y = face.y - face.h * 0.9;
  x = Math.max(0, Math.min(w - 8, x));
  y = Math.max(0, Math.min(h - 8, y));
  return { x, y, w: Math.min(bw, w - x), h: Math.min(bh, h - y) };
}

function paintEllipse(ctx, rect) {
  ctx.beginPath();
  ctx.ellipse(rect.x + rect.w / 2, rect.y + rect.h / 2, rect.w / 2, rect.h / 2, 0, 0, Math.PI * 2);
  ctx.fill();
}

function maskBounds(maskCanvas) {
  const ctx = maskCanvas.getContext('2d', { willReadFrequently: true });
  const { data, width, height } = ctx.getImageData(0, 0, maskCanvas.width, maskCanvas.height);
  let minX = width, minY = height, maxX = 0, maxY = 0, n = 0, skin = 0;
  const src = scratch && scratch.width === width ? scratch.getContext('2d', { willReadFrequently: true }).getImageData(0, 0, width, height).data : null;
  for (let y = 0; y < height; y += 2) {
    for (let x = 0; x < width; x += 2) {
      const i = (y * width + x) * 4;
      if (data[i + 3] < 128) continue;
      n++;
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
      if (src && isSkinPixel(src[i], src[i + 1], src[i + 2])) skin++;
    }
  }
  if (!n) return null;
  return {
    cx: (minX + maxX) / 2,
    bw: Math.max(8, maxX - minX),
    torsoY: minY + (maxY - minY) * 0.35,
    skinRatio: skin / n,
  };
}

function finishPerson(img, maskCanvas, faceIndex, bounds) {
  const layer = document.createElement('canvas');
  layer.width = maskCanvas.width;
  layer.height = maskCanvas.height;
  const lc = layer.getContext('2d');
  lc.filter = 'blur(22px)';
  lc.drawImage(img, 0, 0, layer.width, layer.height);
  lc.filter = 'none';
  lc.globalCompositeOperation = 'destination-in';
  lc.drawImage(maskCanvas, 0, 0);
  const url = layer.toDataURL('image/png');
  return {
    faceIndex,
    skinRatio: +bounds.skinRatio.toFixed(3),
    torsoY: bounds.torsoY,
    cx: bounds.cx,
    bw: bounds.bw,
    mask: url,
    blurLayer: url,
  };
}

function keypointsOf(landmarks, w, h) {
  return Object.entries(POSE_INDEX).map(([part, index]) => {
    const p = landmarks[index];
    if (!p) return null;
    const score = p.v != null ? Number(p.v) : (p.visibility == null ? 0.5 : Number(p.visibility));
    return { part, score, position: { x: p.x * w, y: p.y * h } };
  }).filter(Boolean);
}

function paintPose(ctx, landmarks, w, h, maskImage) {
  ctx.fillStyle = '#fff';
  if (maskImage && maskImage.width) {
    ctx.drawImage(maskImage, 0, 0, w, h);
    return;
  }
  const pts = keypointsOf(landmarks, w, h).filter((k) => k.score >= 0.25);
  if (pts.length < 4) return;
  ctx.beginPath();
  pts.forEach((k, i) => (i ? ctx.lineTo(k.position.x, k.position.y) : ctx.moveTo(k.position.x, k.position.y)));
  ctx.closePath();
  ctx.fill();
}

function loadUrl(url) {
  return new Promise((resolve) => {
    if (!url) { resolve(null); return; }
    const el = new Image();
    el.onload = () => resolve(el);
    el.onerror = () => resolve(null);
    el.src = url;
  });
}

async function facesFromTiny(img, frame) {
  const opts = new faceapi.TinyFaceDetectorOptions({ inputSize: 416, scoreThreshold: 0.4 });
  const found = await faceapi.detectAllFaces(img, opts).withAgeAndGender();
  const faces = [];
  for (const f of found) {
    const b = f.detection.box;
    const box = { x: b.x, y: b.y, w: b.width, h: b.height, score: f.detection.score };
    const look = describeAppearance(frame.data, frame.w, frame.h, box);
    const pFemale = f.gender === 'female' ? f.genderProbability : 1 - f.genderProbability;
    faces.push({
      score: +box.score.toFixed(3),
      gender: pFemale >= 0.5 ? 'female' : 'male',
      genderProbability: +(pFemale >= 0.5 ? pFemale : 1 - pFemale).toFixed(3),
      age: Math.round(f.age),
      x: Math.round(box.x), y: Math.round(box.y), w: Math.round(box.w), h: Math.round(box.h),
      headCovered: look.headCovered,
      bearded: look.bearded,
      clothedAdult: look.clothedAdult,
    });
  }
  return faces;
}

async function detectWithPose(img, dataUrl) {
  const frame = pixelsOf(img);
  const facePromise = faceReady ? callVision('face', 'detect', { dataUrl }, 8000) : Promise.resolve({ ok: false });
  const posePromise = poseReady ? callVision('pose', 'detect', { dataUrl }, 8000) : Promise.resolve({ ok: false });
  const faceMsg = await facePromise;
  const rawFaces = [];
  if (faceMsg && faceMsg.ok) {
    for (const det of faceMsg.faces || []) {
      const box = clipBox(det.box || {}, frame.w, frame.h);
      if (!box || det.score < 0.4) continue;
      rawFaces.push(Object.assign({ score: det.score }, box));
    }
  }
  const boxes = dedupeFaces(rawFaces);
  let faces = [];
  for (const box of boxes) {
    const look = describeAppearance(frame.data, frame.w, frame.h, box);
    const gender = await ageGenderOf(img, box);
    faces.push({
      score: +box.score.toFixed(3),
      gender: gender.gender,
      genderProbability: +(Number(gender.genderProbability) || 0).toFixed(3),
      age: gender.age,
      x: Math.round(box.x), y: Math.round(box.y), w: Math.round(box.w), h: Math.round(box.h),
      headCovered: look.headCovered,
      bearded: look.bearded,
      clothedAdult: look.clothedAdult,
    });
  }
  if (!faces.length && useTinyFace) faces = await facesFromTiny(img, frame);

  const poseMsg = await posePromise;
  const people = [];
  const used = new Set();
  const poses = (poseMsg && poseMsg.ok && poseMsg.poses) || [];
  const maskImages = await Promise.all(poses.map((p) => loadUrl(p.mask)));
  poses.forEach((entry, index) => {
    const landmarks = entry.landmarks || [];
    const keypoints = keypointsOf(landmarks, frame.w, frame.h);
    const pose = { keypoints };
    const canvas = document.createElement('canvas');
    canvas.width = frame.w;
    canvas.height = frame.h;
    const ctx = canvas.getContext('2d');
    paintPose(ctx, landmarks, frame.w, frame.h, maskImages[index]);
    const bounds = maskBounds(canvas);
    if (!bounds) return;
    let faceIndex = ModestyRules.matchFace(pose, faces, used);
    if (faceIndex < 0) faceIndex = ModestyRules.matchFaceByTorso(pose, faces, used);
    if (faceIndex >= 0) used.add(faceIndex);
    people.push(finishPerson(img, canvas, faceIndex, bounds));
  });
  faces.forEach((face, index) => {
    if (used.has(index)) return;
    const rect = rectFromFace(face, frame.w, frame.h);
    const canvas = document.createElement('canvas');
    canvas.width = frame.w;
    canvas.height = frame.h;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    paintEllipse(ctx, rect);
    const bounds = maskBounds(canvas);
    if (!bounds) return;
    people.push(finishPerson(img, canvas, index, bounds));
  });
  return { ok: true, backend, width: frame.w, height: frame.h, faces, people };
}

async function detectWithTinyFace(img) {
  const frame = pixelsOf(img);
  const opts = new faceapi.TinyFaceDetectorOptions({ inputSize: 416, scoreThreshold: 0.4 });
  const found = await faceapi.detectAllFaces(img, opts).withAgeAndGender();
  const faces = [];
  for (const f of found) {
    const b = f.detection.box;
    const box = { x: b.x, y: b.y, w: b.width, h: b.height, score: f.detection.score };
    const look = describeAppearance(frame.data, frame.w, frame.h, box);
    const pFemale = f.gender === 'female' ? f.genderProbability : 1 - f.genderProbability;
    faces.push({
      score: +box.score.toFixed(3),
      gender: pFemale >= 0.5 ? 'female' : 'male',
      genderProbability: +(pFemale >= 0.5 ? pFemale : 1 - pFemale).toFixed(3),
      age: Math.round(f.age),
      x: Math.round(box.x), y: Math.round(box.y), w: Math.round(box.w), h: Math.round(box.h),
      headCovered: look.headCovered,
      bearded: look.bearded,
      clothedAdult: look.clothedAdult,
    });
  }
  const people = faces.map((face, index) => {
    const rect = rectFromFace(face, frame.w, frame.h);
    const canvas = document.createElement('canvas');
    canvas.width = frame.w;
    canvas.height = frame.h;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    paintEllipse(ctx, rect);
    const bounds = maskBounds(canvas) || { skinRatio: 0, torsoY: rect.y, cx: rect.x + rect.w / 2, bw: rect.w };
    return finishPerson(img, canvas, index, bounds);
  });
  return { ok: true, backend, width: frame.w, height: frame.h, faces, people };
}

let queue = Promise.resolve();
function detect(dataUrl) {
  const job = queue.then(async () => {
    await ready();
    const img = await loadImage(dataUrl);
    if (!faceReady && !poseReady) return detectWithTinyFace(img);
    return detectWithPose(img, dataUrl);
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
  if (msg.type === 'ping') {
    ready().then(() => sendResponse({ ok: true, backend }), (e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
  return false;
});

ready().catch(() => {});
