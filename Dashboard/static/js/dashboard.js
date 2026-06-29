// ── CLOCK 
function updateClock() {document.getElementById('clock').textContent = new Date().toLocaleTimeString('en-GB');}
setInterval(updateClock, 1000);
updateClock();

// ── CATEGORY CONFIG 
const CATEGORIES = ['canister', 'chemical', 'applicator', 'inhaler','unsorted'];

const CAT_COLORS = {
  applicator:   '#00b700',   // blue
  inhaler:      '#a2e1ef',   // purple
  chemical:     '#76230c',   // sky blue
  canister:     '#696969',   // amber
  unrecognized: '#1c1c1c',   // grey
  unsorted:     '#ef4444',   // red
};



// ── PIE CHART 
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

// ── LOCAL STATE 
const counts = { canister: 0, chemical: 0, applicator: 0, inhaler: 0, unsorted: 0 };
// ── CONVEYOR one motor (conveyor_1); UI shows two status rows
const UI_CONVEYOR_IDS = [1, 2];
const BACKEND_CONVEYOR_ID = 1;
const conveyorState = { 1: 'stopped', 2: 'stopped' };
let conveyorTogglePending = false;

function updateConveyorRowUI(id, state) {
  const led = document.getElementById(`conveyor-${id}-led`);
  if (!led) return;
  const txt = document.getElementById(`conveyor-${id}-text`);
  const strokeColor = { running: '#22c55e', stopped: '#ef4444', warning: '#f97316' };

  if (state === 'disconnected') {
    txt.textContent = 'Disconnected';
    led.className   = 'conveyor-status-btn disconnected';
    led.querySelector('svg').setAttribute('stroke', '#6b7280');
    return;
  }

  led.className = `conveyor-status-btn ${state}`;
  led.querySelector('svg').setAttribute('stroke', strokeColor[state] || '#9aa3b8');
  if (state === 'running') {
    txt.textContent = 'Running';
  } else if (state === 'stopped') {
    txt.textContent = 'Stopped';
  } else {
    txt.textContent = 'Warning — Check system';
  }
}

function updateConveyorMainButton(state) {
  const btn = document.getElementById('conveyor-main-btn');
  if (!btn) return;

  if (state === 'disconnected') {
    btn.className   = 'conveyor-action-btn disabled-btn';
    btn.textContent = 'Unavailable';
    btn.disabled    = true;
    return;
  }

  btn.disabled = false;
  if (state === 'running') {
    btn.className   = 'conveyor-action-btn stop-btn';
    btn.textContent = 'Stop';
  } else if (state === 'stopped') {
    btn.className   = 'conveyor-action-btn start-btn';
    btn.textContent = 'Start';
  } else {
    btn.className   = 'conveyor-action-btn stop-btn';
    btn.textContent = 'Stop';
  }
}

function applyConveyorSystemState(state) {
  UI_CONVEYOR_IDS.forEach((id) => {
    conveyorState[id] = state;
    updateConveyorRowUI(id, state);
  });
  updateConveyorMainButton(state);
}

function toggleConveyor() {
  if (conveyorState[BACKEND_CONVEYOR_ID] === 'disconnected' || conveyorTogglePending) return;
  const next = conveyorState[BACKEND_CONVEYOR_ID] === 'running' ? 'stopped' : 'running';
  conveyorTogglePending = true;
  socket.emit('control_conveyor', {
    id: BACKEND_CONVEYOR_ID,
    command: next === 'running' ? 'start' : 'stop',
  });
  setTimeout(() => { conveyorTogglePending = false; }, 3000);
}

let arduinoConnected = false;
const activeErrors = {};
const DISCONNECT_WARNING = '⚠ Arduino disconnected — conveyors are disabled.';

// ── UPDATE COUNTERS 
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

// ── SERVO 

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
    status.textContent = 'Opened';
    item.classList.add(`active-${type}`);
  } else {
    wrap.className  = 'servo-icon-wrap inactive';
    wrap.style.background = '';
    svg.setAttribute('stroke', '#9aa3b8');
    svg.classList.remove('spinning');
    status.className   = 'servo-status inactive';
    status.textContent = 'Closed';
  }
}

// ── STATUS LAMPS 
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

// ── WARNING 
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

//  DEBUG PANEL
let debugEnabled = false;

function toggleDebug() {
  debugEnabled = !debugEnabled;
  const panel    = document.getElementById('debug-panel');
  const logPanel = document.getElementById('debug-log-panel');
  const label    = document.getElementById('debug-toggle-label');
  if (panel) panel.style.display    = debugEnabled ? 'block' : 'none';
  if (logPanel) logPanel.style.display = debugEnabled ? 'block' : 'none';
  if (label) label.textContent      = debugEnabled ? 'Debug ON' : 'Debug OFF';
}

const dbgToggle = document.getElementById('debug-toggle');
if (dbgToggle) dbgToggle.addEventListener('change', toggleDebug);

function renderDebugPanel(data) {
  // debugEnabled is always true — panel is visible by default

  const statusEl = document.getElementById('dbg-status');
  if (data.committed) {
    statusEl.textContent = `COMMITTED → ${data.winner}  (${Math.round(data.confidence * 100)}%)`;
    statusEl.className   = 'dbg-status committed';
  } else if (data.collecting) {
    statusEl.textContent = `COLLECTING`;
    statusEl.className   = 'dbg-status collecting';
  } else {
    statusEl.textContent = `IDLE`;
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

//  EVENT LOG

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

//  SOCKET.IO
const socket = io();
window.socket = socket;

socket.on('connect', () => {
  console.log('Connected to Flask server');
  document.querySelector('.live-dot').style.background = '#22c55e';
});

socket.on('disconnect', () => {
  console.log('Disconnected ❌');
  document.querySelector('.live-dot').style.background = '#ef4444';
});

socket.on('update_counts',   (data) => updateCounts(data));
socket.on('update_conveyor', (data) => {
  const state = data.running ? 'running' : 'stopped';
  applyConveyorSystemState(state);
  conveyorTogglePending = false;
  if (debugEnabled) {
    appendLogRow(new Date().toISOString(), 'conveyor',
      `Conveyor ${data.running ? 'started' : 'stopped'}`, 'conveyor_1');
  }
});
socket.on('arduino_status', (data) => {
  arduinoConnected = !!data.connected;
  if (!arduinoConnected) {
    CATEGORIES.forEach(t => setServoState(t, false));
    applyConveyorSystemState('disconnected');
  } else {
    const conv = (data.conveyors || []).find(c => c.id === BACKEND_CONVEYOR_ID);
    const state = conv && conv.running ? 'running' : 'stopped';
    applyConveyorSystemState(state);
  }
  refreshWarningBanner();
});
socket.on('system_error', (data) => handleSystemError(data));
socket.on('system_log', (data) => handleSystemLog(data));
socket.on('error_resolved', (data) => {
  delete activeErrors[data.error_key || data.code];
  refreshWarningBanner();
});
socket.on('lamp_update' , (data) => setLamps(data));
socket.on('update_servo', (data) => { setServoState(data.type, data.active);});
socket.on('servo_closed', (data) => { setServoState(data.type, false);
  if (debugEnabled) appendLogRow(new Date().toISOString(), 'servo',
    `Servo ${data.type} deactivated`,
    data.status || '');
});
socket.on('buffer_update',      (data) => renderDebugPanel(data));
socket.on('new_detection',      (data) => {
  const label = data.label || data.category || 'unknown';
  const details = data.category === 'unrecognized'
    ? `confidence=${Math.round(data.confidence * 100)}% frames=${data.total_frames}`
    : `category=${data.category} confidence=${Math.round(data.confidence * 100)}% frames=${data.total_frames}`;
  appendLogRow(data.timestamp, 'detection', `Detected '${label}'`, details);
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
    const res = await fetch('/api/state');
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || `HTTP ${res.status}`);
    }
    const data = await res.json();
    if (data.db_ok === false) {
      throw new Error(data.message || 'Database unavailable');
    }
    arduinoConnected = !!(data.arduino_status && data.arduino_status.connected);
    const conv = data.conveyors.find(c => c.id === BACKEND_CONVEYOR_ID);
    if (conv) {
      applyConveyorSystemState(conv.running ? 'running' : 'stopped');
    }
    if (arduinoConnected) {
      data.servos.forEach(s => setServoState(s.type, s.active));
    } else {
      CATEGORIES.forEach(t => setServoState(t, false));
      applyConveyorSystemState('disconnected');
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
    console.log('Initial state loaded');
    if (data.recent_events) populateLogFromHistory(data.recent_events);
  } catch (e) {
    console.warn('Could not load initial state:', e);
    setWarning('Could not load dashboard data from local database. Check that the dashboard server is running.', true);
  }
}

loadInitialState();