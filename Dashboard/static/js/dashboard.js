// ══════════════════════════════════════════
//  SORTING DASHBOARD — dashboard.js
//  Categories: applicator | inhaler | chemical | canister
// ══════════════════════════════════════════

// ── CLOCK ──
function updateClock() {document.getElementById('clock').textContent = new Date().toLocaleTimeString('en-GB');}
setInterval(updateClock, 1000);
updateClock();

// ── CATEGORY CONFIG ──
const CATEGORIES = ['canister', 'chemical', 'applicator', 'inhaler','unsorted'];

const CAT_COLORS = {
  applicator:   '#00b700',   // blue
  inhaler:      '#a2e1ef',   // purple
  chemical:     '#76230c',   // sky blue
  canister:     '#696969',   // amber
  unrecognized: '#1c1c1c',   // grey
  unsorted:     '#ef4444',   // red
};



// ── PIE CHART ──
const pieCtx = document.getElementById('pieChart').getContext('2d');
const pieChart = new Chart(pieCtx, {
  type: 'doughnut',
  data: {
    labels: ['Canister', 'Chemical', 'Applicator', 'Inhaler', 'Unsorted'],
    datasets: [{
      data: [1, 1, 1, 1, 1],
      backgroundColor: CATEGORIES.map(c => CAT_COLORS[c]),
      borderWidth: 0,
      hoverOffset: 6
    }]
  },
  options: {
    cutout: '68%',
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          label: ctx => ` ${ctx.label}: ${ctx.raw} objects`
        }
      }
    },
    animation: { animateRotate: true, duration: 600 }
  }
});

// ── LOCAL STATE ──
const counts = { canister: 0, chemical: 0, applicator: 0, inhaler: 0, unsorted: 0 };
const conveyorState = { 1: 'stopped', 2: 'stopped' };

function normalizeConveyorId(id) {
  return parseInt(id, 10) || 1;
}
let arduinoConnected = false;
const activeErrors = {};
const DISCONNECT_WARNING = '⚠ Arduino disconnected — conveyors are disabled.';

// ── UPDATE COUNTERS ──
function updateCounts(data) {
  const c = data.counts || data;
  Object.assign(counts, c);

  const total = CATEGORIES.reduce((a, t) => a + (counts[t] || 0), 0);
  document.getElementById('pie-total').textContent = total;

  CATEGORIES.forEach((t, i) => {
    const v   = counts[t] || 0;
    const pct = total > 0 ? Math.round(v / total * 100) : 0;
    const cntEl = document.getElementById(`cnt-${t}`);
    const legEl = document.getElementById(`leg-${t}`);
    const pctEl = document.getElementById(`pct-${t}`);
    const barEl = document.getElementById(`bar-${t}`);
    if (cntEl) cntEl.textContent = v;
    if (legEl) legEl.textContent = `${v} objects`;
    if (pctEl) pctEl.textContent = `${pct}%`;
    if (barEl) barEl.style.width = `${pct}%`;
    pieChart.data.datasets[0].data[i] = v || 1;
  });
  pieChart.update();

  if (data.unrecognized !== undefined) {
    document.getElementById('unrecognized-rate-value').textContent = data.unrecognized;
  }
  const unsortedCount = c.unsorted !== undefined ? c.unsorted : data.unsorted;
  if (unsortedCount !== undefined) {
    const unsortedEl = document.getElementById('cnt-unsorted');
    if (unsortedEl) unsortedEl.textContent = unsortedCount;
  }
  if (data.rate !== undefined) {
    document.getElementById('sorting-rate').textContent = data.rate;
  }
  if (data.unrecognized_rate !== undefined) {
    document.getElementById('unrecognized-rate-value').textContent = data.unrecognized_rate;
  }
}

// ── CONVEYOR — MANUAL TOGGLE (one physical motor → both UI rows stay in sync) ──
let conveyorTogglePending = false;

function toggleConveyor(id) {
  const cid = normalizeConveyorId(id);
  if (conveyorState[cid] === 'disconnected' || conveyorTogglePending) return;
  const next = conveyorState[cid] === 'running' ? 'stopped' : 'running';
  conveyorTogglePending = true;
  socket.emit('control_conveyor', { id: cid, command: next === 'running' ? 'start' : 'stop' });
  setTimeout(() => { conveyorTogglePending = false; }, 3000);
}

function setConveyorState(id, state) {
  const cid = normalizeConveyorId(id);
  const led = document.getElementById(`conveyor-${cid}-led`);
  if (!led) return;
  conveyorState[cid] = state;
  const txt = document.getElementById(`conveyor-${cid}-text`);
  const btn = document.getElementById('conveyor-main-btn');
  const strokeColor = { running: '#22c55e', stopped: '#ef4444', warning: '#f97316' };
  led.className = `conveyor-status-btn ${state}`;
  led.querySelector('svg').setAttribute('stroke', strokeColor[state] || '#9aa3b8');

  if (state === 'disconnected') {
    txt.textContent = 'Disconnected';
    btn.className   = 'conveyor-action-btn disabled-btn';
    btn.textContent = 'Unavailable';
    btn.disabled    = true;
    led.className   = 'conveyor-status-btn disconnected';
    led.querySelector('svg').setAttribute('stroke', '#6b7280');
  } else {
    btn.disabled = false;
    if (state === 'running') {
      txt.textContent = 'Running';
      btn.className   = 'conveyor-action-btn stop-btn';
      btn.textContent = 'Stop';
    } else if (state === 'stopped') {
      txt.textContent = 'Stopped';
      btn.className   = 'conveyor-action-btn start-btn';
      btn.textContent = 'Start';
    } else {
      txt.textContent = 'Warning — Check system';
      btn.className   = 'conveyor-action-btn stop-btn';
      btn.textContent = 'Stop';
    }
  }
}

// ── SERVO ──

function setServoState(type, active) {
  if (active && !arduinoConnected) return;
  const item = document.getElementById(`servo-${type}`);
  if (!item) return;

  const wrap   = item.querySelector('.servo-icon-wrap');
  const svg    = item.querySelector('.servo-svg');
  const status = item.querySelector('.servo-status');
  const color  = CAT_COLORS[type] || '#9aa3b8';

  CATEGORIES.forEach(c => item.classList.remove(`active-${c}`));

  if (active) {
    wrap.className  = 'servo-icon-wrap active';
    wrap.style.background = `${color}22`;
    svg.setAttribute('stroke', color);
    svg.classList.add('spinning');
    status.className   = 'servo-status active';
    status.textContent = 'Activated';
    item.classList.add(`active-${type}`);
  } else {
    wrap.className  = 'servo-icon-wrap inactive';
    wrap.style.background = '';
    svg.setAttribute('stroke', '#9aa3b8');
    svg.classList.remove('spinning');
    status.className   = 'servo-status inactive';
    status.textContent = 'Deactivated';
  }
}

// ── STATUS LAMPS ──
function setLamps(data) {
  if (!data) return;
  const names = ['red', 'orange', 'green', 'blue'];
  names.forEach((n) => {
    const el = document.getElementById(`lamp-${n}`);
    if (!el) return;
    const on = !!data[n];
    el.classList.toggle('on', on);
    el.classList.toggle('off', !on);
  });
}

// ── WARNING ──
function setWarning(message, isError) {
  const el = document.getElementById('warning-message');
  if (!el) return;
  const banner = el.closest('[class*="warning"]') || el.parentElement;
  if (!message) {
    banner.style.display = 'none';
    return;
  }
  banner.style.display = '';
  el.textContent = message;
  el.style.color = isError ? '#b91c1c' : '';
  el.classList.toggle('warning-error', !!isError);
}

const _recentLogKeys = new Map();
const LOG_DEDUPE_MS = 2000;

function refreshWarningBanner() {
  const parts = [];
  const keys = Object.keys(activeErrors);

  keys.forEach((k) => {
    const e = activeErrors[k];
    if (e.message && !parts.includes(e.message)) {
      parts.push(e.message);
    }
  });

  if (!arduinoConnected && keys.length === 0) {
    parts.push(DISCONNECT_WARNING);
  }

  if (parts.length > 0) {
    setWarning(parts.join('\n'), true);
    return;
  }

  const el = document.getElementById('warning-message');
  if (el) el.closest('.warning-banner, [id*="warning"], [class*="warning"]').style.display = 'none';
}

function formatSystemError(data) {
  if (data.title && data.message) {
    return `${data.title}: ${data.message}`;
  }
  return data.error || data.message || 'System error';
}

function errorTrackingKey(data) {
  return data.error_key || data.code || 'UNKNOWN';
}

function appendErrorLogRow(data) {
  const tbody = document.getElementById('event-log-body');
  if (!tbody) return;
  appendLogRow(
    data.timestamp || new Date().toISOString(),
    'error',
    formatSystemError(data),
    data.details ? JSON.stringify(data.details) : '',
    true,
  );
}

function shouldLogError(data) {
  const key = errorTrackingKey(data);
  const now = Date.now();
  const last = _recentLogKeys.get(key);
  if (last != null && now - last < LOG_DEDUPE_MS) {
    return false;
  }
  _recentLogKeys.set(key, now);
  return true;
}

function handleSystemError(data) {
  if (data.error_key === 'UNRECOGNIZED_OBJECT') return;

  if (shouldLogError(data)) {
    appendErrorLogRow(data);
  }
  if (data.severity === 'info') return;

  const key = errorTrackingKey(data);
  activeErrors[key] = {
    message: `⚠ ${formatSystemError(data)}`,
    isError: true,
  };
  refreshWarningBanner();

  if (data.error_key === 'CONTROL_CONVEYOR_BLOCKED') {
    conveyorTogglePending = false;
  }
}

function handleSystemLog(data) {
  if (data.error_key === 'UNRECOGNIZED_OBJECT') return;
  appendErrorLogRow(data);
}

// ── UNRECOGNIZED ALERT ──
let unrecognizedTimeout = null;
function showUnrecognized(message) {
  const alertEl = document.getElementById('unrecognized-alert');
  const msgEl   = document.getElementById('unrecognized-message');
  msgEl.textContent     = message;
  alertEl.style.display = 'flex';
  clearTimeout(unrecognizedTimeout);
  unrecognizedTimeout = setTimeout(() => {
    alertEl.style.display = 'none';
  }, 6000);
}

// ══════════════════════════════════════════
//  DEBUG PANEL
// ══════════════════════════════════════════

let debugEnabled = false;

function toggleDebug() {
  debugEnabled = !debugEnabled;
  const panel    = document.getElementById('debug-panel');
  const logPanel = document.getElementById('debug-log-panel');
  const label    = document.getElementById('debug-toggle-label');
  panel.style.display    = debugEnabled ? 'block' : 'none';
  logPanel.style.display = debugEnabled ? 'block' : 'none';
  label.textContent      = debugEnabled ? 'Debug ON' : 'Debug OFF';
}

document.getElementById('debug-toggle').addEventListener('change', toggleDebug);

function renderDebugPanel(data) {
  if (!debugEnabled) return;

  const statusEl = document.getElementById('dbg-status');
  if (data.committed) {
    statusEl.textContent = `✅ COMMITTED → ${data.winner}  (${Math.round(data.confidence * 100)}%)`;
    statusEl.className   = 'dbg-status committed';
  } else if (data.collecting) {
    statusEl.textContent = `● COLLECTING`;
    statusEl.className   = 'dbg-status collecting';
  } else {
    statusEl.textContent = `◌ IDLE`;
    statusEl.className   = 'dbg-status idle';
  }

  const frames   = data.total_frames || 0;
  const minF     = data.min_frames   || 5;
  const gap      = data.gap_counter  || 0;
  const gapLimit = data.gap_limit    || 20;

  document.getElementById('dbg-frames').textContent =
    `${frames} frame${frames !== 1 ? 's' : ''}  (min ${minF})`;

  const gapPct = Math.min(gap / gapLimit * 100, 100);
  document.getElementById('dbg-gap-fill').style.width = `${gapPct}%`;
  document.getElementById('dbg-gap-text').textContent  = `Gap: ${gap}/${gapLimit}`;

  const barsEl    = document.getElementById('dbg-bars');
  const breakdown = data.breakdown || {};
  barsEl.innerHTML = '';

  const entries = Object.entries(breakdown).sort((a, b) => b[1].count - a[1].count);

  if (entries.length === 0) {
    barsEl.innerHTML = '<div class="dbg-empty">No votes yet</div>';
    return;
  }

  entries.forEach(([cat, info]) => {
    const pct      = info.pct || 0;
    const color    = CAT_COLORS[cat] || '#9aa3b8';
    const isLeader = cat === data.leader;

    const row = document.createElement('div');
    row.className = 'dbg-row' + (isLeader ? ' leader' : '');
    row.innerHTML = `
      <div class="dbg-label">
        <span class="dbg-dot" style="background:${color}"></span>
        <span class="dbg-cat">${cat.charAt(0).toUpperCase() + cat.slice(1)}</span>
        ${isLeader ? '<span class="dbg-leader-tag">LEADER</span>' : ''}
      </div>
      <div class="dbg-bar-wrap">
        <div class="dbg-bar-fill" style="width:${pct}%;background:${color}"></div>
      </div>
      <div class="dbg-stats">
        <span class="dbg-count">${info.count}f</span>
        <span class="dbg-pct">${pct}%</span>
      </div>
    `;
    barsEl.appendChild(row);
  });
}

// ══════════════════════════════════════════
//  EVENT LOG
// ══════════════════════════════════════════

const MAX_LOG_ROWS = 100;

function formatTime(iso) {
  const t = iso.split('T')[1] || iso;
  return t.substring(0, 8);
}

function appendLogRow(timestamp, category, action, details, flash = true) {
  const tbody = document.getElementById('event-log-body');

  const empty = tbody.querySelector('.log-empty');
  if (empty) empty.parentElement.remove();

  const tr = document.createElement('tr');
  if (flash) tr.className = 'log-new';

  const badge = category || 'unknown';
  tr.innerHTML = `
    <td class="log-time">${formatTime(timestamp)}</td>
    <td><span class="log-badge ${badge}">${badge}</span></td>
    <td class="log-action">${action || ''}${details ? `<span class="log-details"> — ${details}</span>` : ''}</td>
  `;

  tbody.insertBefore(tr, tbody.firstChild);

  while (tbody.rows.length > MAX_LOG_ROWS) {
    tbody.deleteRow(tbody.rows.length - 1);
  }
}

function clearLogDisplay() {
  const tbody = document.getElementById('event-log-body');
  tbody.innerHTML = '<tr><td colspan="4" class="log-empty">Cleared</td></tr>';
}

function populateLogFromHistory(events) {
  const oldest_first = [...events].reverse();
  oldest_first.forEach(e => appendLogRow(e.timestamp, e.category, e.action, e.details, false));
}

// ══════════════════════════════════════════
//  SOCKET.IO
// ══════════════════════════════════════════
const socket = io();
window.socket = socket;

socket.on('connect', () => {
  console.log('Connected to Flask server ✅');
  document.querySelector('.live-dot').style.background = '#22c55e';
});

socket.on('disconnect', () => {
  console.log('Disconnected ❌');
  document.querySelector('.live-dot').style.background = '#ef4444';
});

socket.on('update_counts',      (data) => updateCounts(data));
socket.on('update_conveyor',    (data) => {
  const cid = normalizeConveyorId(data.id);
  const running = !!data.running;
  const state = running ? 'running' : 'stopped';
  setConveyorState(cid, state);
  const mirrorIds = cid === 3 ? [1, 2] : (cid === 1 || cid === 2 ? [cid === 1 ? 2 : 1] : []);
  mirrorIds.forEach((n) => {
    if (conveyorState[n] !== 'disconnected') {
      setConveyorState(n, state);
    }
  });
  conveyorTogglePending = false;
  if (debugEnabled) appendLogRow(new Date().toISOString(), 'conveyor',
    `Conveyor ${data.id} ${data.running ? 'started' : 'stopped'}`, '');
});
socket.on('arduino_status', (data) => {
  arduinoConnected = !!data.connected;
  if (!arduinoConnected) {
    CATEGORIES.forEach(t => setServoState(t, false));
    [1, 2].forEach(id => setConveyorState(id, 'disconnected'));
  } else {
    const conveyors = data.conveyors || [];
    if (conveyors.length) {
      conveyors.forEach(c => setConveyorState(normalizeConveyorId(c.id), c.running ? 'running' : 'stopped'));
    } else {
      [1, 2].forEach(id => setConveyorState(id, conveyorState[id] || 'stopped'));
    }
  }
  refreshWarningBanner();
});
socket.on('system_error', (data) => handleSystemError(data));
socket.on('system_log', (data) => handleSystemLog(data));
socket.on('error_resolved', (data) => {
  delete activeErrors[data.error_key || data.code];
  refreshWarningBanner();
});
socket.on('lamp_update', (data) => setLamps(data));

socket.on('lamp_update', (data) => console.log('lamp_update received', data));
socket.on('update_servo', (data) => {
  setServoState(data.type, data.active);
});
socket.on('servo_closed', (data) => {
  setServoState(data.type, false);
  if (debugEnabled) appendLogRow(new Date().toISOString(), 'servo',
    `Servo ${data.type} deactivated`,
    data.status || '');
});
socket.on('buffer_update',      (data) => renderDebugPanel(data));
socket.on('new_detection',      (data) => {
  if (data.category === 'unrecognized' || debugEnabled) {
    appendLogRow(data.timestamp, 'detection',
      `Detected '${data.category}'`,
      `confidence=${Math.round(data.confidence * 100)}% frames=${data.total_frames}`);
  }
  if (data.category === 'unrecognized') {
    const label = data.label || data.display || 'unrecognized';
    showUnrecognized(`Unrecognized object detected: ${label}`);
  }
});
socket.on('update_sensor',      (data) => {
  if (debugEnabled) appendLogRow(new Date().toISOString(), 'sensor',
    `Sensor ${data.id} ${data.triggered ? 'TRIGGERED' : 'clear'}`, '');
});
socket.on('unsorted_object_detected', (data) => {
  if (debugEnabled) appendLogRow(new Date().toISOString(), 'sensor',
    `Unsorted object detected`, `type=${data.type}`);
  if (data.count !== undefined) {
    updateCounts({ unsorted: data.count });
  }
});

// ══════════════════════════════════════════
//  INITIAL STATE
// ══════════════════════════════════════════
async function loadInitialState() {
  try {
    const res  = await fetch('/api/state');
    const data = await res.json();
    arduinoConnected = !!(data.arduino_status && data.arduino_status.connected);
    data.conveyors.forEach(c => setConveyorState(normalizeConveyorId(c.id), c.running ? 'running' : 'stopped'));
    if (arduinoConnected) {
      data.servos.forEach(s => setServoState(s.type, s.active));
    } else {
      CATEGORIES.forEach(t => setServoState(t, false));
      [1, 2].forEach(id => setConveyorState(id, 'disconnected'));
    }
    if (data.active_errors) {
      data.active_errors.forEach((err) => {
        if (err.severity === 'info') return;
        activeErrors[errorTrackingKey(err)] = {
          message: `⚠ ${formatSystemError(err)}`,
          isError: true,
        };
      });
    }
    refreshWarningBanner();
    updateCounts({ ...data.counts, rate: data.rate, unrecognized: data.unrecognized });
    if (data.lamps) setLamps(data.lamps);
    console.log('Initial state loaded ✅');
    if (data.recent_events) populateLogFromHistory(data.recent_events);
  } catch (e) {
    console.warn('Could not load initial state:', e);
  }
}

loadInitialState();