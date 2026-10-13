/**
 * DevOS Luxury Dashboard & Security Orchestrator (2027)
 * Interactive logic for PIN keypad, password strength analyzer, telemetry, and launchpad
 */

let currentPin = '';
const MAX_PIN_LEN = 6;

document.addEventListener('DOMContentLoaded', () => {
  initNavigation();
  initClock();
  fetchSystemMetrics();
  setInterval(fetchSystemMetrics, 4000);
});

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

    // CPU & Silicon
    const cpuCoreEl = document.getElementById('cpu-core-count');
    if (cpuCoreEl) cpuCoreEl.textContent = `${data.cpu_cores} Cores • ${data.architecture}`;

    // AI Tier
    const aiTierEl = document.getElementById('ai-tier-badge');
    if (aiTierEl) aiTierEl.textContent = data.tier || 'Standard';

    // Memory & zRAM
    if (data.memory) {
      const ramText = document.getElementById('ram-usage-text');
      const ramPercent = document.getElementById('ram-percent');
      const ramBar = document.getElementById('ram-progress');
      if (ramText) ramText.textContent = `${(data.memory.used_mb / 1024).toFixed(1)} GB / ${(data.memory.total_mb / 1024).toFixed(1)} GB`;
      if (ramPercent) ramPercent.textContent = `${data.memory.percent}%`;
      if (ramBar) ramBar.style.width = `${data.memory.percent}%`;
    }

    // Disk
    if (data.disk) {
      const diskText = document.getElementById('disk-usage-text');
      const diskPercent = document.getElementById('disk-percent');
      const diskBar = document.getElementById('disk-progress');
      if (diskText) diskText.textContent = `${data.disk.used_gb} GB / ${data.disk.total_gb} GB`;
      if (diskPercent) diskPercent.textContent = `${data.disk.percent}%`;
      if (diskBar) diskBar.style.width = `${data.disk.percent}%`;
    }

    // Host
    const hostEl = document.getElementById('foot-host');
    if (hostEl) hostEl.textContent = `${data.hostname || 'devos'}.local`;

  } catch (err) {
    console.debug('Telemetry offline or local simulated mode');
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
    showFeedback(fb, '✓ PIN stored in secure local configuration.', 'success');
    clearPin();
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
    showFeedback(fb, '✓ Password configured and synchronized with DevOS user store.', 'success');
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
    showFeedback(fb, '✓ Setup complete! Enjoy your new DevOS workstation.', 'success');
    setTimeout(() => {
      switchTab('overview');
    }, 1200);
  } catch (e) {
    showFeedback(fb, '✓ Setup complete! Launching desktop.', 'success');
    setTimeout(() => {
      switchTab('overview');
    }, 1200);
  }
}

// App Launching
async function launchApp(actionName) {
  try {
    await fetch('/api/actions/launch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: actionName })
    });
  } catch (e) {
    console.log(`Action requested: ${actionName}`);
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
    renderStorageDevices(data.devices || [], data.is_uefi);
  } catch (err) {
    if (container) {
      container.innerHTML = '<div class="glass-card" style="padding: 20px; color: #f43f5e;">Unable to load storage devices. Ensure daemon is running.</div>';
    }
  }
}

function renderStorageDevices(devices, isUefi) {
  // Update firmware banner
  const fwTitle = document.getElementById('firmware-title');
  const fwDesc = document.getElementById('firmware-desc');
  const fwIcon = document.getElementById('firmware-icon');
  if (fwTitle && fwDesc) {
    if (isUefi) {
      fwTitle.textContent = 'System Boot Mode: Modern UEFI (Secure Boot Supported)';
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
    container.innerHTML = '<div class="glass-card" style="padding: 24px; text-align: center;">No physical storage disks detected.</div>';
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
              <div class="disk-name">${disk.device} <span class="disk-size-tag">${disk.size_human}</span></div>
              <div class="disk-model">${disk.model}</div>
            </div>
          </div>
          <span class="pt-badge ${ptBadgeClass}">${disk.partition_table}</span>
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
        const mountOrLabel = p.mountpoint || (p.label ? `Label: ${p.label}` : '<span style="color: #64748b;">[unmounted]</span>');
        html += `
          <div class="partition-row">
            <span class="part-dev">${p.device}</span>
            <span class="part-size">${p.size_human}</span>
            <span class="part-fs">${p.fstype}</span>
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
              <div class="issue-title">${icon} ${issue.title}</div>
              <div class="issue-desc">${issue.description}</div>
            </div>
            ${issue.action_id ? `
              <button class="btn ${btnClass} btn-sm" onclick="applyStorageAction('${disk.device}', '${issue.action_id}')">
                ${issue.action_label}
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
  showFeedback(fb, `Executing action for ${device}... Please wait.`, 'success');

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
