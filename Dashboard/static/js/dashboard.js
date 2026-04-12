// ══════════════════════════════════════════
//  SORTING DASHBOARD — dashboard.js
//  Categories: applicator | inhaler | sharps | canister
// ══════════════════════════════════════════

// ── CLOCK ──
function updateClock() {
  document.getElementById('clock').textContent = new Date().toLocaleTimeString('en-GB');
}
setInterval(updateClock, 1000);
updateClock();

// ── CATEGORY CONFIG ──
const CATEGORIES = ['applicator', 'inhaler', 'sharps', 'canister'];

const CAT_COLORS = {
  applicator:   '#3b82f6',   // blue
  inhaler:      '#a855f7',   // purple
  sharps:       '#f97316',   // orange
  canister:     '#f59e0b',   // amber
  unrecognized: '#9aa3b8',   // grey
};

// sharps has no YOLO label yet — shown greyed out
const CAT_PENDING = { sharps: true };

// ── PIE CHART ──
const pieCtx = document.getElementById('pieChart').getContext('2d');
const pieChart = new Chart(pieCtx, {
  type: 'doughnut',
  data: {
    labels: ['Applicator', 'Inhaler', 'Sharps', 'Canister'],
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
const counts = { applicator: 0, inhaler: 0, sharps: 0, canister: 0 };
const conveyorState = { 1: 'running', 2: 'running' };

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
  if (speedEl && speed !== null && speed !== undefined && state !== 'stopped') {
    speedEl.textContent = `${speed} m/s`;
  }
}

// ── SERVO ──
// active servo timers — auto-reset after 3 s if server doesn't send deactivate
const _servoTimers = {};

function setServoState(type, active) {
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
function setWarning(message) {
  document.getElementById('warning-message').textContent = message;
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
socket.on('update_servo',       (data) => setServoState(data.type, data.active));
socket.on('servo_closed', (data) => {
  setServoState(data.type, false);
  if (debugEnabled) appendLogRow(new Date().toISOString(), 'servo',
    `Servo ${data.type} deactivated`,
    data.status || '');
});
socket.on('new_alert',          (data) => setWarning(data.message));
socket.on('unrecognized_alert', (data) => {
  showUnrecognized(`Unrecognized object detected${data.display ? ': ' + data.display : ''} (total: ${data.total})`);
  if (debugEnabled) appendLogRow(data.timestamp || new Date().toISOString(), 'unrecognized', 'Unrecognized object', data.display || '');
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
    data.conveyors.forEach(c => setConveyorState(c.id, c.running ? 'running' : 'stopped', c.speed));
    data.servos.forEach(s => setServoState(s.type, s.active));
    updateCounts(data.counts);
    document.getElementById('unrecognized-rate-value').textContent = data.unrecognized || 0;
    console.log('Initial state loaded ✅');
    if (data.recent_events) populateLogFromHistory(data.recent_events);
  } catch (e) {
    console.warn('Could not load initial state:', e);
  }
}

loadInitialState();