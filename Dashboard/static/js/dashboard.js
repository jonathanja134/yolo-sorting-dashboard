// ══════════════════════════════════════════
//  SORTING DASHBOARD — dashboard.js
// ══════════════════════════════════════════

// ── HORLOGE ──
function updateClock() {
  document.getElementById('clock').textContent = new Date().toLocaleTimeString('fr-FR');
}
setInterval(updateClock, 1000);
updateClock();

// ── PIE CHART ──
const pieCtx = document.getElementById('pieChart').getContext('2d');
const pieChart = new Chart(pieCtx, {
  type: 'doughnut',
  data: {
    labels: ['Applicator', 'Ihmulator', 'Sharps', 'Hazardous'],
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

// ── STATE LOCAL ──
const counts = { applicator: 0, ihmulator: 0, sharps: 0, hazardous: 0 };
const conveyorState = { 1: 'running', 2: 'running' };

// ── MISE À JOUR DES COMPTEURS ──
function updateCounts(data) {
  Object.assign(counts, data);
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  document.getElementById('pie-total').textContent = total;

  const types = ['applicator', 'ihmulator', 'sharps', 'hazardous'];
  types.forEach((t, i) => {
    const v = counts[t];
    const pct = total > 0 ? Math.round(v / total * 100) : 0;
    document.getElementById(`cnt-${t}`).textContent = v;
    document.getElementById(`leg-${t}`).textContent = `${v} objects`;
    document.getElementById(`pct-${t}`).textContent = `${pct}%`;
    document.getElementById(`bar-${t}`).style.width = `${pct}%`;
    pieChart.data.datasets[0].data[i] = v || 1;
  });
  pieChart.update();

  // Sorting rate (calculé côté serveur et envoyé dans les données)
  if (data.rate !== undefined) {
    document.getElementById('sorting-rate').textContent = data.rate;
  }

  // Taux objets non reconnus / heure
  if (data.unrecognized_rate !== undefined) {
    document.getElementById('unrecognized-rate-value').textContent = data.unrecognized_rate;
  }
}

// ── CONVOYEUR — BOUTON MANUEL ──
function toggleConveyor(id) {
  const current = conveyorState[id];
  const next = current === 'running' ? 'stopped' : 'running';
  setConveyorState(id, next, next === 'running' ? null : 0);
  socket.emit('control_conveyor', { id, command: next === 'running' ? 'start' : 'stop' });
}

function setConveyorState(id, state, speed) {
  conveyorState[id] = state;
  const led = document.getElementById(`conveyor-${id}-led`);
  const txt = document.getElementById(`conveyor-${id}-text`);
  const btn = document.getElementById(`conveyor-${id}-btn`);
  const speedEl = document.getElementById(`conveyor-${id}-speed`);
  const iconStroke = { running: '#22c55e', stopped: '#ef4444', warning: '#f97316' };

  led.className = `conveyor-status-btn ${state}`;
  led.querySelector('svg').setAttribute('stroke', iconStroke[state] || '#9aa3b8');

  if (state === 'running') {
    txt.textContent = 'Running';
    btn.className = 'conveyor-action-btn stop-btn';
    btn.textContent = 'Stop';
  } else if (state === 'stopped') {
    txt.textContent = 'Stopped';
    btn.className = 'conveyor-action-btn start-btn';
    btn.textContent = 'Start';
    if (speedEl) speedEl.textContent = '0.0 m/s';
  } else {
    txt.textContent = 'Warning — Check system';
    btn.className = 'conveyor-action-btn stop-btn';
    btn.textContent = 'Stop';
  }

  // Mise à jour de la vitesse si fournie
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
    status.className = 'servo-status active';
    status.textContent = 'Activated';
  } else {
    svg.classList.remove('spinning');
    status.className = 'servo-status inactive';
    status.textContent = 'Deactivated';
  }
}

// ── WARNING ──
function setWarning(message) {
  document.getElementById('warning-message').textContent = message;
}

// ── OBJET NON RECONNU ──
let unrecognizedTimeout = null;

function showUnrecognized(message) {
  const alertEl = document.getElementById('unrecognized-alert');
  const msgEl   = document.getElementById('unrecognized-message');

  msgEl.textContent = message;
  alertEl.style.display = 'flex';

  // Auto-masquage après 6 secondes
  clearTimeout(unrecognizedTimeout);
  unrecognizedTimeout = setTimeout(() => {
    alertEl.style.display = 'none';
  }, 6000);
}

// WebSocket for live video stream
const streamImg = document.getElementById('stream');
const streamStatus = document.getElementById('stream-status');
const streamWs = new WebSocket('ws://127.0.0.1:8765');
streamWs.binaryType = 'arraybuffer';
let previousUrl = null;

streamWs.onopen = () => {
  streamStatus.textContent = 'Connected';
};

streamWs.onmessage = (event) => {
  const blob = new Blob([event.data], { type: 'image/jpeg' });
  const url = URL.createObjectURL(blob);
  if (previousUrl) URL.revokeObjectURL(previousUrl);
  previousUrl = url;
  streamImg.src = url;
  streamStatus.style.display = 'none';
};

streamWs.onclose = () => {
  streamStatus.textContent = 'Disconnected';
  streamStatus.style.display = 'block';
};

streamWs.onerror = (error) => {
  console.error('Stream error:', error);
  streamStatus.textContent = 'Error';
  streamStatus.style.display = 'block';
};

// ══════════════════════════════════════════
//  CONNEXION SOCKET.IO → Flask
// ══════════════════════════════════════════
const socket = io();

socket.on('connect', () => {
  console.log('Connecté au serveur Flask ✅');
  document.querySelector('.live-dot').style.background = '#22c55e';
});

socket.on('disconnect', () => {
  console.log('Déconnecté ❌');
  document.querySelector('.live-dot').style.background = '#ef4444';
});

// Compteurs + rate
socket.on('update_counts', (data) => {
  updateCounts(data);
});

// Convoyeur : état + vitesse
socket.on('update_conveyor', (data) => {
  const state = data.running ? 'running' : 'stopped';
  setConveyorState(data.id, state, data.speed);
});

// Servo
socket.on('update_servo', (data) => {
  setServoState(data.type, data.active);
});

// Alerte système
socket.on('new_alert', (data) => {
  setWarning(data.message);
});

// Objet non reconnu
socket.on('unrecognized_object', (data) => {
  showUnrecognized(data.message);
});