'use strict';
const $ = (id) => document.getElementById(id);
let tabId;
let lastState = null;

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

function monthKey(d = new Date()) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function formatMonthKey(key) {
  const m = /^(\d{4})-(\d{2})$/.exec(key || '');
  if (!m) return key || '—';
  const idx = Math.max(0, Math.min(11, parseInt(m[2], 10) - 1));
  return `${MONTH_NAMES[idx]} ${m[1]}`;
}

function showView(which) {
  $('viewMain').hidden = which !== 'main';
  $('viewSettings').hidden = which !== 'settings';
}

function renderMonthList(monthly) {
  const list = $('monthList');
  list.innerHTML = '';
  const entries = Object.entries(monthly || {}).sort((a, b) => b[0].localeCompare(a[0]));
  if (!entries.length) {
    const li = document.createElement('li');
    li.className = 'empty';
    li.textContent = 'No blurs recorded yet';
    list.appendChild(li);
    return;
  }
  for (const [key, count] of entries.slice(0, 12)) {
    const li = document.createElement('li');
    li.innerHTML = `<span>${formatMonthKey(key)}</span><strong>${count}</strong>`;
    list.appendChild(li);
  }
}

function render(state) {
  if (!state || !state.effective) return;
  lastState = state;
  const s = state.effective;
  $('lock').hidden = !s.locked;
  $('enabledRow').hidden = s.locked;
  $('enabled').checked = !!s.enabled;
  if (s.mode) $('mode').value = s.mode;
  for (const opt of $('mode').options) {
    opt.disabled = !!(s.locked && s.managedMode &&
      ModestyRules.MODES.indexOf(opt.value) < ModestyRules.MODES.indexOf(s.managedMode));
  }
  $('mode').disabled = !s.enabled;

  const key = monthKey();
  const monthly = state.monthly || {};
  $('monthCount').textContent = String(monthly[key] || 0);
  $('monthLabel').textContent = `blurred in ${formatMonthKey(key)}`;
  if (state.tab !== undefined) $('tabCount').textContent = state.tab;
  if (state.total !== undefined) $('total').textContent = state.total;
  renderMonthList(monthly);
}

async function refresh() {
  try {
    const res = await chrome.runtime.sendMessage({ type: 'popup-state', tabId });
    if (res && res.effective) render(res);
  } catch (e) {
    console.warn('Modesty popup refresh:', e);
  }
}

$('openSettings').addEventListener('click', () => {
  showView('settings');
  refresh();
});
$('backMain').addEventListener('click', () => showView('main'));

$('enabled').addEventListener('change', async (e) => {
  const isChecked = e.target.checked;
  $('mode').disabled = !isChecked;
  try {
    const res = await chrome.runtime.sendMessage({ type: 'popup-set', enabled: isChecked });
    if (res && res.effective) {
      render(Object.assign({}, lastState || {}, { effective: res }));
    } else {
      await refresh();
    }
  } catch (err) {
    console.warn('Modesty popup-set enabled error:', err);
    await refresh();
  }
});

$('mode').addEventListener('change', async (e) => {
  try {
    const res = await chrome.runtime.sendMessage({ type: 'popup-set', mode: e.target.value });
    if (res && res.effective) {
      render(Object.assign({}, lastState || {}, { effective: res }));
    } else {
      await refresh();
    }
  } catch (err) {
    console.warn('Modesty popup-set mode error:', err);
    await refresh();
  }
});

showView('main');
refresh();
chrome.tabs.query({ active: true, currentWindow: true }).then((tabs) => {
  if (tabs && tabs[0]) {
    tabId = tabs[0].id;
    refresh();
  }
}).catch(() => {});
