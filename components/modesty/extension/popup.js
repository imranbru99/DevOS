'use strict';
const $ = (id) => document.getElementById(id);
let tabId;

function render(state) {
  if (!state || !state.effective) return;
  const s = state.effective;
  $('lock').hidden = !s.locked;
  $('enabledRow').hidden = s.locked;           // no off switch while locked
  $('enabled').checked = !!s.enabled;
  if (s.mode) $('mode').value = s.mode;
  // While locked, modes looser than the one set by DevOS are not offered.
  for (const opt of $('mode').options) {
    opt.disabled = !!(s.locked && s.managedMode &&
      ModestyRules.MODES.indexOf(opt.value) < ModestyRules.MODES.indexOf(s.managedMode));
  }
  $('mode').disabled = !s.enabled;
  if (state.tab !== undefined) $('tabCount').textContent = state.tab;
  if (state.total !== undefined) $('total').textContent = state.total;
}

async function refresh() {
  try {
    const res = await chrome.runtime.sendMessage({ type: 'popup-state', tabId });
    if (res && res.effective) {
      render(res);
    }
  } catch (e) {
    // Service worker may be starting or message channel closed
    console.warn('Modesty popup refresh:', e);
  }
}

// Immediate optimistic toggle + storage update
$('enabled').addEventListener('change', async (e) => {
  const isChecked = e.target.checked;
  $('mode').disabled = !isChecked;
  try {
    const res = await chrome.runtime.sendMessage({ type: 'popup-set', enabled: isChecked });
    if (res && res.effective) {
      render(res);
    } else {
      await refresh();
    }
  } catch (err) {
    console.warn('Modesty popup-set enabled error:', err);
    await refresh();
  }
});

$('mode').addEventListener('change', async (e) => {
  const modeVal = e.target.value;
  try {
    const res = await chrome.runtime.sendMessage({ type: 'popup-set', mode: modeVal });
    if (res && res.effective) {
      render(res);
    } else {
      await refresh();
    }
  } catch (err) {
    console.warn('Modesty popup-set mode error:', err);
    await refresh();
  }
});

// Run refresh immediately so the popup never renders in an uninitialized state
refresh();

// Also query current active tab to get page-specific blur count
chrome.tabs.query({ active: true, currentWindow: true }).then((tabs) => {
  if (tabs && tabs[0]) {
    tabId = tabs[0].id;
    refresh();
  }
}).catch(() => {});
