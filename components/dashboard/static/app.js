/**
 * DevOS Dashboard
 * PIN keypad, password strength, real telemetry, storage doctor and launchpad.
 * Everything shown comes from the local API; unknown values show as "—".
 */

let currentPin = '';
const MAX_PIN_LEN = 6;

const TAB_IDS = ['overview', 'security', 'subsystems', 'storage', 'firstboot'];

document.addEventListener('DOMContentLoaded', () => {
  initNavigation();
  initClock();
  fetchSystemMetrics();
  fetchServices();
  setInterval(fetchSystemMetrics, 4000);
  setInterval(fetchServices, 15000);
  openTabFromHash();
  window.addEventListener('hashchange', openTabFromHash);
});

// devos-dashboard opens straight into a tab with #storage, #security, ...
function openTabFromHash() {
  const tab = (location.hash || '').replace('#', '');
  if (TAB_IDS.includes(tab)) switchTab(tab);
}

function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function setBar(id, percent) {
  const el = document.getElementById(id);
  if (el) el.style.width = `${percent == null ? 0 : Math.max(0, Math.min(100, percent))}%`;
}

function pct(value) {
  return value == null ? '—' : `${value}%`;
}

// Navigation & Tab Switching
function initNavigation() {
  const buttons = document.querySelectorAll('.nav-btn');
  buttons.forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.getAttribute('data-tab');
      switchTab(tab);
    });
  });
}

function switchTab(tabId) {
  document.querySelectorAll('.nav-btn').forEach(b => {
    b.classList.toggle('active', b.getAttribute('data-tab') === tabId);
  });
  document.querySelectorAll('.tab-pane').forEach(p => {
    p.classList.toggle('active', p.id === `tab-${tabId}`);
  });
  if (tabId === 'storage') {
    fetchStorageDevices();
  }
}

// Live Clock
function initClock() {
  const clockEl = document.getElementById('live-clock');
  function update() {
    const now = new Date();
    clockEl.textContent = now.toLocaleTimeString();
  }
  update();
  setInterval(update, 1000);
}

// System Telemetry Fetch
async function fetchSystemMetrics() {
  try {
    const res = await fetch('/api/system/status');
    if (!res.ok) return;
    const data = await res.json();

    // Live USB or installed PC: shows/hides installer-only controls.
    document.body.classList.toggle('is-live', !!data.live);
    document.body.classList.toggle('is-installed', !data.live);
    setText('system-status-text', data.badge || data.os_name || 'DevOS');
    setText('foot-os', data.pretty_name || data.os_name || 'DevOS');

    // CPU
    if (data.cpu_model) setText('cpu-model', data.cpu_model);
    const cores = data.cpu_cores ? `${data.cpu_cores} threads` : '';
    setText('cpu-core-count', [cores, data.architecture].filter(Boolean).join(' • ') || '—');
    setText('cpu-percent', pct(data.cpu_percent));
    setBar('cpu-progress', data.cpu_percent);

    // AI tier
    setText('ai-tier-badge', data.tier || 'Not detected');

    // Memory & zRAM
    const mem = data.memory || {};
    if (mem.total_mb != null) {
      setText('ram-usage-text', `${(mem.used_mb / 1024).toFixed(1)} GB / ${(mem.total_mb / 1024).toFixed(1)} GB`);
    } else {
      setText('ram-usage-text', '—');
    }
    setText('ram-percent', pct(mem.percent));
    setBar('ram-progress', mem.percent);
    if (mem.zram_active) {
      const bits = [mem.zram_algorithm, mem.zram_ratio ? `${mem.zram_ratio}x` : ''].filter(Boolean);
      setText('zram-badge', `zRAM on${bits.length ? ` (${bits.join(', ')})` : ''}`);
    } else {
      setText('zram-badge', 'zRAM off');
    }

    // Root filesystem
    const disk = data.disk || {};
    if (disk.total_gb != null) {
      setText('disk-usage-text', `${disk.used_gb} GB / ${disk.total_gb} GB`);
    } else {
      setText('disk-usage-text', '—');
    }
    setText('disk-percent', pct(disk.percent));
    setBar('disk-progress', disk.percent);
    const fs = data.root_fs ? (data.root_fs === 'btrfs' ? 'Btrfs' : data.root_fs) : '';
    setText('root-fs-label', fs ? `System Root (${fs})` : 'System Root');
    setText('fs-badge', fs ? `${fs}${data.snapper ? ' + Snapper' : ''}` : '—');

    // Footer
    setText('foot-host', data.hostname || '');
    setText('foot-desktop', data.desktop || '');
    let boot = data.boot_mode === 'uefi' ? 'UEFI' : (data.boot_mode === 'bios' ? 'Legacy BIOS' : '');
    if (data.boot_mode === 'uefi' && data.secure_boot != null) {
      boot += data.secure_boot ? ' • Secure Boot on' : ' • Secure Boot off';
    }
    setText('foot-boot', boot);
    setText('foot-sep', data.desktop && boot ? '•' : '');
  } catch (err) {
    console.debug('Dashboard API not reachable', err);
  }
}

async function fetchServices() {
  try {
    const res = await fetch('/api/services/status');
    if (!res.ok) return;
    const svc = (await res.json()).services || {};
    const show = (id, running, onText, offText) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.textContent = running ? onText : offText;
      el.classList.toggle('active', !!running);
    };
    if (svc.devserver) show('svc-devserver', svc.devserver.running, 'Web server running', 'Web server stopped');
    if (svc.ai_core) show('svc-ai', svc.ai_core.running, 'Local AI running', 'Local AI not running');
  } catch (err) {
    console.debug('Services API not reachable', err);
  }
}

// PIN Keypad Management
function pressPin(digit) {
  if (currentPin.length < MAX_PIN_LEN) {
    currentPin += digit;
    updatePinDots();
  }
}

function backspacePin() {
  if (currentPin.length > 0) {
    currentPin = currentPin.slice(0, -1);
    updatePinDots();
  }
}

function clearPin() {
  currentPin = '';
  updatePinDots();
}

function updatePinDots() {
  for (let i = 1; i <= MAX_PIN_LEN; i++) {
    const dot = document.getElementById(`dot-${i}`);
    if (dot) {
      dot.classList.toggle('filled', i <= currentPin.length);
    }
  }
}

async function submitPin() {
  const fb = document.getElementById('pin-feedback');
  if (currentPin.length < 4) {
    showFeedback(fb, 'PIN must be at least 4 digits.', 'error');
    return;
  }

  showFeedback(fb, 'Saving & configuring fast PIN...', 'success');
  try {
    const res = await fetch('/api/setup/pin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin: currentPin })
    });
    const result = await res.json();
    if (result.success) {
      showFeedback(fb, '✓ PIN activated! You can now use this PIN for fast unlock.', 'success');
      clearPin();
    } else {
      showFeedback(fb, result.error || 'Failed to save PIN.', 'error');
    }
  } catch (e) {
    showFeedback(fb, 'Could not reach DevOS Dashboard. The PIN was not saved.', 'error');
  }
}

// Password Strength Analyzer
function evalPasswordStrength() {
  const pw = document.getElementById('new-pw').value;
  const conf = document.getElementById('confirm-pw').value;

  const hasLen = pw.length >= 8;
  const hasUpper = /[A-Z]/.test(pw);
  const hasNum = /[0-9!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(pw);
  const isMatch = pw.length > 0 && pw === conf;

  document.getElementById('chk-len').classList.toggle('valid', hasLen);
  document.getElementById('chk-upper').classList.toggle('valid', hasUpper);
  document.getElementById('chk-num').classList.toggle('valid', hasNum);
  document.getElementById('chk-match').classList.toggle('valid', isMatch);

  // Strength score
  let score = 0;
  if (pw.length >= 6) score += 25;
  if (hasLen) score += 25;
  if (hasUpper) score += 25;
  if (hasNum) score += 25;

  const fill = document.getElementById('strength-fill');
  const text = document.getElementById('strength-text');

  fill.style.width = `${score}%`;

  if (score === 0) {
    text.textContent = 'Empty';
    fill.style.backgroundColor = 'transparent';
  } else if (score <= 50) {
    text.textContent = 'Weak';
    text.style.color = '#f43f5e';
    fill.style.backgroundColor = '#f43f5e';
  } else if (score <= 75) {
    text.textContent = 'Moderate';
    text.style.color = '#f59e0b';
    fill.style.backgroundColor = '#f59e0b';
  } else {
    text.textContent = 'Ultra Strong';
    text.style.color = '#10b981';
    fill.style.backgroundColor = '#10b981';
  }
}

function togglePasswordVisibility(fieldId) {
  const input = document.getElementById(fieldId);
  if (input) {
    input.type = input.type === 'password' ? 'text' : 'password';
  }
}

async function submitPassword() {
  const pw = document.getElementById('new-pw').value;
  const conf = document.getElementById('confirm-pw').value;
  const fb = document.getElementById('pw-feedback');

  if (pw.length < 4) {
    showFeedback(fb, 'Password must be at least 4 characters.', 'error');
    return;
  }
  if (pw !== conf) {
    showFeedback(fb, 'Passwords do not match.', 'error');
    return;
  }

  showFeedback(fb, 'Updating account password & syncing PAM...', 'success');
  try {
    const res = await fetch('/api/setup/password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pw })
    });
    const result = await res.json();
    if (result.success) {
      showFeedback(fb, `✓ ${result.message}`, 'success');
      document.getElementById('new-pw').value = '';
      document.getElementById('confirm-pw').value = '';
      evalPasswordStrength();
    } else {
      showFeedback(fb, result.error || 'Failed to update password.', 'error');
    }
  } catch (e) {
    showFeedback(fb, 'Could not reach DevOS Dashboard. The password was not changed.', 'error');
  }
}

// First Boot Wizard Completion
async function completeFirstBoot() {
  const lang = document.getElementById('wz-lang').value;
  const kb = document.getElementById('wz-kb').value;
  const fb = document.getElementById('wz-feedback');

  showFeedback(fb, 'Applying system configuration...', 'success');
  try {
    const res = await fetch('/api/firstboot/complete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ locale: lang, keyboard: kb })
    });
    const result = await res.json();
    if (!result.success) {
      showFeedback(fb, result.error || 'Could not save the language.', 'error');
      return;
    }
    showFeedback(fb, '✓ Language saved.', 'success');
    setTimeout(() => {
      switchTab('overview');
    }, 1200);
  } catch (e) {
    showFeedback(fb, 'Could not reach DevOS Dashboard. Nothing was saved.', 'error');
  }
}

// App Launching
async function launchApp(actionName) {
  try {
    const res = await fetch('/api/actions/launch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: actionName })
    });
    const result = await res.json();
    if (!result.success) console.warn(result.error || `Could not open ${actionName}`);
  } catch (e) {
    console.warn(`Could not open ${actionName}`, e);
  }
}

function rebootAndEject() {
  if (confirm('Restart now? Remove the USB stick when the screen goes dark.')) {
    applyStorageAction('', 'reboot_system');
  }
}

function showFeedback(el, msg, type) {
  if (!el) return;
  el.textContent = msg;
  el.className = `feedback-msg ${type}`;
}

// Storage & Boot Doctor
async function fetchStorageDevices() {
  const container = document.getElementById('storage-devices-container');
  if (!container) return;

  try {
    const res = await fetch('/api/storage/devices');
    if (!res.ok) throw new Error('Failed to fetch storage');
    const data = await res.json();
    renderStorageDevices(data.devices || [], data.is_uefi, data.error);
  } catch (err) {
    if (container) {
      container.innerHTML = '<div class="glass-card" style="padding: 20px; color: #f43f5e;">Unable to load storage devices. Ensure daemon is running.</div>';
    }
  }
}

function renderStorageDevices(devices, isUefi, error) {
  // Update firmware banner
  const fwTitle = document.getElementById('firmware-title');
  const fwDesc = document.getElementById('firmware-desc');
  const fwIcon = document.getElementById('firmware-icon');
  if (fwTitle && fwDesc) {
    if (isUefi) {
      fwTitle.textContent = 'System Boot Mode: UEFI';
      fwDesc.textContent = 'UEFI systems require GPT partition tables and a 512 MB FAT32 EFI partition (/boot/efi).';
      if (fwIcon) fwIcon.textContent = '🛡️';
    } else {
      fwTitle.textContent = 'System Boot Mode: Legacy BIOS / CSM';
      fwDesc.textContent = 'Legacy BIOS systems support MBR partition tables or GPT with a 1MB bios_grub partition.';
      if (fwIcon) fwIcon.textContent = '⚙️';
    }
  }

  const container = document.getElementById('storage-devices-container');
  if (!container) return;

  if (!devices || devices.length === 0) {
    const why = error ? ` (${escapeHtml(error)})` : '';
    container.innerHTML = `<div class="glass-card" style="padding: 24px; text-align: center;">No storage disks found${why}.</div>`;
    return;
  }

  let html = '';
  devices.forEach(disk => {
    const isGpt = disk.raw_pttype === 'gpt';
    const ptBadgeClass = isGpt ? 'badge-cyan' : (disk.raw_pttype === 'dos' || disk.raw_pttype === 'mbr' ? 'badge-amber' : 'badge-muted');

    html += `
      <div class="glass-card disk-card">
        <div class="disk-card-header">
          <div class="disk-title-group">
            <div class="disk-icon">🖴</div>
            <div>
              <div class="disk-name">${escapeHtml(disk.device)} <span class="disk-size-tag">${escapeHtml(disk.size_human)}</span></div>
              <div class="disk-model">${escapeHtml(disk.model)}</div>
            </div>
          </div>
          <span class="pt-badge ${ptBadgeClass}">${escapeHtml(disk.partition_table)}</span>
        </div>

        <!-- Partitions List -->
        <div class="partitions-table-wrap">
          <div class="partitions-table-head">
            <span>Partition</span>
            <span>Size</span>
            <span>Filesystem</span>
            <span>Mount / Role</span>
          </div>
          <div class="partitions-list">
    `;

    if (disk.partitions && disk.partitions.length > 0) {
      disk.partitions.forEach(p => {
        const mountOrLabel = p.mountpoint ? escapeHtml(p.mountpoint)
          : (p.label ? `Label: ${escapeHtml(p.label)}` : '<span style="color: #64748b;">[unmounted]</span>');
        html += `
          <div class="partition-row">
            <span class="part-dev">${escapeHtml(p.device)}</span>
            <span class="part-size">${escapeHtml(p.size_human)}</span>
            <span class="part-fs">${escapeHtml(p.fstype)}</span>
            <span class="part-mount">${mountOrLabel}</span>
          </div>
        `;
      });
    } else {
      html += `<div class="partition-row empty"><em>No partitions created. Drive is empty / unallocated.</em></div>`;
    }

    html += `
          </div>
        </div>

        <!-- Diagnostic Issues & Click-to-Solve Actions -->
        <div class="disk-issues-section">
    `;

    if (disk.issues && disk.issues.length > 0) {
      disk.issues.forEach(issue => {
        const icon = issue.severity === 'success' ? '✓' : (issue.severity === 'warning' ? '⚠️' : 'ℹ️');
        const alertClass = `alert-${issue.severity}`;
        const btnClass = issue.severity === 'success' ? 'btn-primary' : (issue.severity === 'warning' ? 'btn-warning' : 'btn-secondary');

        html += `
          <div class="disk-issue-box ${alertClass}">
            <div class="issue-info">
              <div class="issue-title">${icon} ${escapeHtml(issue.title)}</div>
              <div class="issue-desc">${escapeHtml(issue.description)}</div>
            </div>
            ${issue.action_id ? `
              <button class="btn ${btnClass} btn-sm" onclick="applyStorageAction('${escapeHtml(disk.device)}', '${escapeHtml(issue.action_id)}')">
                ${escapeHtml(issue.action_label)}
              </button>
            ` : ''}
          </div>
        `;
      });
    }

    html += `
        </div>
      </div>
    `;
  });

  container.innerHTML = html;
}

async function applyStorageAction(device, actionId) {
  const fb = document.getElementById('storage-feedback');
  showFeedback(fb, device ? `Working on ${device}... Please wait.` : 'Working... Please wait.', 'success');

  try {
    const res = await fetch('/api/storage/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device, action: actionId })
    });
    const result = await res.json();
    if (result.success) {
      showFeedback(fb, `✓ ${result.message || 'Action completed successfully.'}`, 'success');
      setTimeout(fetchStorageDevices, 1500);
    } else {
      showFeedback(fb, `✗ Error: ${result.error || 'Action failed.'}`, 'error');
    }
  } catch (err) {
    showFeedback(fb, `✗ Request failed: ${err.message}`, 'error');
  }
}
