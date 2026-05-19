// ══════════════════════════════════════════
//  SORTING DASHBOARD — dashboard.js
//  Categories: applicator | inhaler | chemical | canister
// ══════════════════════════════════════════

// ── CLOCK ──
function updateClock() {
  document.getElementById('clock').textContent = new Date().toLocaleTimeString('en-GB');
}
setInterval(updateClock, 1000);
updateClock();

// ── CATEGORY CONFIG ──
const CATEGORIES = ['canister', 'chemical', 'applicator', 'inhaler'];

const CAT_COLORS = {
  applicator:   '#3b82f6',   // blue
  inhaler:      '#a855f7',   // purple
  chemical:     '#0ea5e9',   // sky blue
  canister:     '#f59e0b',   // amber
  unrecognized: '#9aa3b8',   // grey
};

const CAT_PENDING = {};

// ── PIE CHART ──
const pieCtx = document.getElementById('pieChart').getContext('2d');
const pieChart = new Chart(pieCtx, {
  type: 'doughnut',
  data: {
    labels: ['Canister', 'Chemical', 'Applicator', 'Inhaler'],
    datasets: [{
      data: [1, 1, 1, 1],
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
const counts = { canister: 0, chemical: 0, applicator: 0, inhaler: 0 };
const conveyorState = { 1: 'running', 2: 'running' };
let arduinoConnected = false;
const activeErrors = {};

const NOMINAL_WARNING = 'No Errors Detected';
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
  if (data.rate !== undefined) {
    document.getElementById('sorting-rate').textContent = data.rate;
  }
  if (data.unrecognized_rate !== undefined) {
    document.getElementById('unrecognized-rate-value').textContent = data.unrecognized_rate;
  }
}

// ── CONVEYOR — MANUAL TOGGLE ──
function toggleConveyor(id) {
  const next = conveyorState[id] === 'running' ? 'stopped' : 'running';
  setConveyorState(id, next, next === 'stopped' ? 0 : null);
  socket.emit('control_conveyor', { id, command: next === 'running' ? 'start' : 'stop' });
}

function setConveyorState(id, state, speed) {
  conveyorState[id] = state;
  const led     = document.getElementById(`conveyor-${id}-led`);
  const txt     = document.getElementById(`conveyor-${id}-text`);
  const btn     = document.getElementById(`conveyor-${id}-btn`);
  const speedEl = document.getElementById(`conveyor-${id}-speed`);
  const strokeColor = { running: '#22c55e', stopped: '#ef4444', warning: '#f97316' };
  led.className = `conveyor-status-btn ${state}`;
  led.querySelector('svg').setAttribute('stroke', strokeColor[state] || '#9aa3b8');
  if (state === 'running') {
    txt.textContent = 'Running';
    btn.className   = 'conveyor-action-btn stop-btn';
    btn.textContent = 'Stop';
  } else if (state === 'stopped') {
    txt.textContent = 'Stopped';
    btn.className   = 'conveyor-action-btn start-btn';
    btn.textContent = 'Start';
    if (speedEl) speedEl.textContent = '0.0 m/s';
  } else {
    txt.textContent = 'Warning — Check system';
    btn.className   = 'conveyor-action-btn stop-btn';
    btn.textContent = 'Stop';
  }
  if (state === 'disconnected') {
    txt.textContent = 'Disconnected';
    btn.className   = 'conveyor-action-btn disabled-btn';
    btn.textContent = 'Unavailable';
    btn.disabled    = true;
    if (speedEl) speedEl.textContent = '—';
    led.className = 'conveyor-status-btn disconnected';
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
      if (speedEl) speedEl.textContent = '0.0 m/s';
    }
  }
  if (speedEl && speed !== null && speed !== undefined && state !== 'stopped' && state !== 'disconnected') {
    speedEl.textContent = `${speed} m/s`;
  }
}

// ── SERVO ──
// Only reflects Arduino-driven activation when the board is connected.
const _servoTimers = {};

function setServoState(type, active) {
  if (active && !arduinoConnected) return;
  const item = document.getElementById(`servo-${type}`);
  if (!item) return;

  const wrap   = item.querySelector('.servo-icon-wrap');
  const svg    = item.querySelector('.servo-svg');
  const status = item.querySelector('.servo-status');
  const color  = CAT_COLORS[type] || '#9aa3b8';

  // remove any old active-* class then add the new one if active
  CATEGORIES.forEach(c => item.classList.remove(`active-${c}`));

  if (active) {
    wrap.className  = 'servo-icon-wrap active';
    wrap.style.background = `${color}22`;   // tinted bg with alpha
    svg.setAttribute('stroke', color);
    svg.classList.add('spinning');
    status.className   = 'servo-status active';
    status.textContent = 'Activated';
    item.classList.add(`active-${type}`);

    // Client-side safety reset after 4 s (server sends deactivate at 3 s)
  } else {
    clearTimeout(_servoTimers[type]);
    wrap.className  = 'servo-icon-wrap inactive';
    wrap.style.background = '';
    svg.setAttribute('stroke', '#9aa3b8');
    svg.classList.remove('spinning');
    status.className   = 'servo-status inactive';
    status.textContent = 'Deactivated';
  }
}

// ── WARNING ──
function setWarning(message, isError) {
  const el = document.getElementById('warning-message');
  if (!el) return;
  const banner = el.closest('[class*="warning"]') || el.parentElement;
  if (!message || (!isError && message === NOMINAL_WARNING)) {
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

  // Generic disconnect only when offline and no ErrorManager entries are active
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

  if (data.error_key === 'UNRECOGNIZED_OBJECT') {
    const d = data.details || {};
    showUnrecognized(
      `Unrecognized object detected${d.display ? ': ' + d.display : ''}` +
        (d.total !== undefined ? ` (total: ${d.total})` : ''),
    );
  }
}

function handleSystemLog(data) {
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

const CAT_ICON = {
  detection:    '',
  sensor:       '',
  conveyor:     '',
  servo:        '',
  unrecognized: '',
};

function formatTime(iso) {
  // Show only HH:MM:SS from ISO string
  const t = iso.split('T')[1] || iso;
  return t.substring(0, 8);
}

function appendLogRow(timestamp, category, action, details, flash = true) {
  const tbody = document.getElementById('event-log-body');

  // Remove "no events" placeholder if present
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

  // Prepend so newest is at top
  tbody.insertBefore(tr, tbody.firstChild);

  // Cap at MAX_LOG_ROWS
  while (tbody.rows.length > MAX_LOG_ROWS) {
    tbody.deleteRow(tbody.rows.length - 1);
  }
}

function clearLogDisplay() {
  const tbody = document.getElementById('event-log-body');
  tbody.innerHTML = '<tr><td colspan="4" class="log-empty">Cleared</td></tr>';
}

function populateLogFromHistory(events) {
  // events come newest-first from the API — insert oldest first so display is newest-top
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
  setConveyorState(data.id, data.running ? 'running' : 'stopped', data.speed);
  if (debugEnabled) appendLogRow(new Date().toISOString(), 'conveyor',
    `Conveyor ${data.id} ${data.running ? 'started' : 'stopped'}`,
    `speed=${data.speed} m/s`);
});
socket.on('arduino_status', (data) => {
  arduinoConnected = !!data.connected;
  if (!arduinoConnected) {
    CATEGORIES.forEach(t => setServoState(t, false));
    [1, 2].forEach(id => setConveyorState(id, 'disconnected', null));
  } else {
    [1, 2].forEach(id => setConveyorState(id, conveyorState[id] || 'stopped', null));
  }
  refreshWarningBanner();
});
socket.on('system_error', (data) => handleSystemError(data));
socket.on('system_log', (data) => handleSystemLog(data));
socket.on('error_resolved', (data) => {
  delete activeErrors[data.error_key || data.code];
  refreshWarningBanner();
});
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
  if (debugEnabled) appendLogRow(data.timestamp, 'detection',
    `Detected '${data.category}'`,
    `confidence=${Math.round(data.confidence*100)}% frames=${data.total_frames}`);
});
socket.on('update_sensor',      (data) => {
  if (debugEnabled) appendLogRow(new Date().toISOString(), 'sensor',
    `Sensor ${data.id} ${data.triggered ? 'TRIGGERED' : 'clear'}`, '');
});

// ══════════════════════════════════════════
//  INITIAL STATE
// ══════════════════════════════════════════
async function loadInitialState() {
  try {
    const res  = await fetch('/api/state');
    const data = await res.json();
    arduinoConnected = !!(data.arduino_status && data.arduino_status.connected);
    data.conveyors.forEach(c => setConveyorState(c.id, c.running ? 'running' : 'stopped', c.speed));
    if (arduinoConnected) {
      data.servos.forEach(s => setServoState(s.type, s.active));
    } else {
      CATEGORIES.forEach(t => setServoState(t, false));
      [1, 2].forEach(id => setConveyorState(id, 'disconnected', null));
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
    console.log('Initial state loaded ✅');
    if (data.recent_events) populateLogFromHistory(data.recent_events);
  } catch (e) {
    console.warn('Could not load initial state:', e);
  }
}

loadInitialState();