'use strict';
const $ = (id) => document.getElementById(id);
let tabId;

function render(state) {
  const s = state.effective;
  $('lock').hidden = !s.locked;
  $('enabledRow').hidden = s.locked;           // no off switch while locked
  $('enabled').checked = s.enabled;
  $('mode').value = s.mode;
  // While locked, modes looser than the one set by DevOS are not offered.
  for (const opt of $('mode').options) {
    opt.disabled = s.locked && s.managedMode &&
      ModestyRules.MODES.indexOf(opt.value) < ModestyRules.MODES.indexOf(s.managedMode);
  }
  $('mode').disabled = !s.enabled;
  if (state.tab !== undefined) $('tabCount').textContent = state.tab;
  if (state.total !== undefined) $('total').textContent = state.total;
}

async function refresh() {
  render(await chrome.runtime.sendMessage({ type: 'popup-state', tabId }));
}

$('enabled').addEventListener('change', async (e) => {
  await chrome.runtime.sendMessage({ type: 'popup-set', enabled: e.target.checked });
  refresh();
});
$('mode').addEventListener('change', async (e) => {
  await chrome.runtime.sendMessage({ type: 'popup-set', mode: e.target.value });
  refresh();
});

chrome.tabs.query({ active: true, currentWindow: true }).then((tabs) => {
  tabId = tabs[0] && tabs[0].id;
  refresh();
});
