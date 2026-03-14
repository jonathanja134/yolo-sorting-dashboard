// ══════════════════════════════════════════
//  SORTING DASHBOARD — dashboard.js
// ══════════════════════════════════════════

// ── CLOCK ──
function updateClock() {
  document.getElementById('clock').textContent = new Date().toLocaleTimeString('en-GB');
}
setInterval(updateClock, 1000);
updateClock();

// ── PIE CHART ──
const pieCtx = document.getElementById('pieChart').getContext('2d');
const pieChart = new Chart(pieCtx, {
  type: 'doughnut',
  data: {
    labels: ['Applicator', 'Inhaler', 'Sharps', 'Hazardous'],
    datasets: [{
      data: [1, 1, 1, 1],
      backgroundColor: ['#3b82f6', '#a855f7', '#f97316', '#ef4444'],
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
const counts = { applicator: 0, inhaler: 0, sharps: 0, hazardous: 0 };
const conveyorState = { 1: 'running', 2: 'running' };

// ── UPDATE COUNTERS ──
function updateCounts(data) {
  // data may be { counts: {...}, unrecognized: n }
  // or a flat counts object — handle both
  const c = data.counts || data;
  Object.assign(counts, c);

  const types = ['applicator', 'inhaler', 'sharps', 'hazardous'];
  const total = types.reduce((a, t) => a + (counts[t] || 0), 0);

  document.getElementById('pie-total').textContent = total;

  types.forEach((t, i) => {
    const v   = counts[t] || 0;
    const pct = total > 0 ? Math.round(v / total * 100) : 0;
    document.getElementById(`cnt-${t}`).textContent   = v;
    document.getElementById(`leg-${t}`).textContent   = `${v} objects`;
    document.getElementById(`pct-${t}`).textContent   = `${pct}%`;
    document.getElementById(`bar-${t}`).style.width   = `${pct}%`;
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
function setServoState(type, active) {
  const item = document.getElementById(`servo-${type}`);
  if (!item) return;
  const wrap   = item.querySelector('.servo-icon-wrap');
  const svg    = item.querySelector('.servo-svg');
  const status = item.querySelector('.servo-status');
  wrap.className = `servo-icon-wrap ${active ? 'active' : 'inactive'}`;
  svg.setAttribute('stroke', active ? '#3b82f6' : '#9aa3b8');
  if (active) {
    svg.classList.add('spinning');
    status.className   = 'servo-status active';
    status.textContent = 'Activated';
  } else {
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

// Toggle switch state
let debugEnabled = false;

function toggleDebug() {
  debugEnabled = !debugEnabled;
  const panel  = document.getElementById('debug-panel');
  const label  = document.getElementById('debug-toggle-label');
  panel.style.display   = debugEnabled ? 'block' : 'none';
  label.textContent     = debugEnabled ? 'Debug ON' : 'Debug OFF';
}

// Add event listener to the checkbox
document.getElementById('debug-toggle').addEventListener('change', toggleDebug);

// Category colours matching CSS vars
const CAT_COLORS = {
  applicator: '#3b82f6',
  inhaler:    '#a855f7',
  sharps:     '#f97316',
  hazardous:  '#ef4444',
  unrecognized: '#9aa3b8',
};

function renderDebugPanel(data) {
  if (!debugEnabled) return;

  // Status line
  const statusEl = document.getElementById('dbg-status');
  if (data.committed) {
    statusEl.textContent  = `✅ COMMITTED → ${data.winner}  (${Math.round(data.confidence * 100)}%)`;
    statusEl.className    = 'dbg-status committed';
  } else if (data.collecting) {
    statusEl.textContent  = `● COLLECTING`;
    statusEl.className    = 'dbg-status collecting';
  } else {
    statusEl.textContent  = `◌ IDLE`;
    statusEl.className    = 'dbg-status idle';
  }

  // Frame counter & gap bar
  const frames   = data.total_frames || 0;
  const minF     = data.min_frames   || 5;
  const gap      = data.gap_counter  || 0;
  const gapLimit = data.gap_limit    || 4;

  document.getElementById('dbg-frames').textContent =
    `${frames} frame${frames !== 1 ? 's' : ''}  (min ${minF})`;

  // Gap progress bar
  const gapPct = Math.min(gap / gapLimit * 100, 100);
  document.getElementById('dbg-gap-fill').style.width = `${gapPct}%`;
  document.getElementById('dbg-gap-text').textContent  = `Gap: ${gap}/${gapLimit}`;

  // Breakdown bars
  const barsEl    = document.getElementById('dbg-bars');
  const breakdown = data.breakdown || {};
  barsEl.innerHTML = '';

  // Sort by count descending
  const entries = Object.entries(breakdown).sort((a, b) => b[1].count - a[1].count);

  if (entries.length === 0) {
    barsEl.innerHTML = '<div class="dbg-empty">No votes yet</div>';
    return;
  }

  entries.forEach(([cat, info]) => {
    const pct   = info.pct || 0;
    const color = CAT_COLORS[cat] || '#9aa3b8';
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
//  SOCKET.IO CONNECTION
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

socket.on('update_counts',       (data) => updateCounts(data));
socket.on('update_conveyor',     (data) => setConveyorState(data.id, data.running ? 'running' : 'stopped', data.speed));
socket.on('update_servo',        (data) => setServoState(data.type, data.active));
socket.on('new_alert',           (data) => setWarning(data.message));
socket.on('unrecognized_alert',  (data) => showUnrecognized(
  `Unrecognized object detected${data.display ? ': ' + data.display : ''} (total: ${data.total})`
));
socket.on('buffer_update',       (data) => renderDebugPanel(data));

// ══════════════════════════════════════════
//  LOAD INITIAL STATE
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
  } catch (e) {
    console.warn('Could not load initial state:', e);
  }
}

loadInitialState();