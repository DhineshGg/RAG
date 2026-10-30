/* ═══════════════════════════════════════════════════════
   Vespera · chat.js
   Handles: history, messaging, streaming, doc upload,
            Starlink constellation, feed rotation
═══════════════════════════════════════════════════════ */
'use strict';

// ── State ──────────────────────────────────────────────
let isStreaming   = false;
let docs          = [];
let sidebarOpen   = true;
let currentChatId = null;

let chatHistories = [
  { id: 'demo-1', title: 'Revenue analysis Q4 2024',     active: false },
  { id: 'demo-2', title: 'Product retrieval specs',      active: false },
  { id: 'demo-3', title: 'APAC expansion deep-dive',     active: false },
  { id: 'demo-4', title: 'Operating margin improvement', active: false },
];

// ── Helpers ────────────────────────────────────────────
const $ = id => document.getElementById(id);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const escapeHtml = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 180) + 'px';
}

// ── Sidebar ────────────────────────────────────────────
function toggleSidebar() {
  const sb = $('sidebar');
  sidebarOpen = !sidebarOpen;
  if (window.innerWidth <= 640) {
    sb.classList.toggle('open', sidebarOpen);
  } else {
    sb.style.width = sidebarOpen ? '' : '0';
  }
}

function checkResponsive() {
  const btn = $('mobileMenuBtn');
  if (btn) btn.style.display = window.innerWidth <= 640 ? 'flex' : 'none';
}
window.addEventListener('resize', checkResponsive);
checkResponsive();

// ── Chat History ───────────────────────────────────────
function renderHistory() {
  const container = $('chatHistory');
  container.innerHTML = '<div class="history-section-label">Conversations</div>';

  if (chatHistories.length === 0) {
    const e = document.createElement('div');
    e.className = 'doc-empty';
    e.style.cssText = 'padding:10px 8px;font-size:12px;color:var(--text-muted);';
    e.textContent = 'No conversations yet.';
    container.appendChild(e);
    return;
  }

  chatHistories.forEach(chat => {
    const item = document.createElement('div');
    item.className = 'history-item' + (chat.active ? ' active' : '');
    item.dataset.id = chat.id;
    item.innerHTML = `
      <svg class="history-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
      </svg>
      <span class="history-title">${escapeHtml(chat.title)}</span>
      <button class="history-del" title="Delete" onclick="deleteHistory(event,'${chat.id}')">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="3 6 5 6 21 6"/>
          <path d="M19 6l-1 14H6L5 6"/>
          <path d="M10 11v6M14 11v6"/>
          <path d="M9 6V4h6v2"/>
        </svg>
      </button>`;
    item.addEventListener('click', e => {
      if (!e.target.closest('.history-del')) loadChat(chat.id);
    });
    container.appendChild(item);
  });
}

function loadChat(id) {
  chatHistories.forEach(c => c.active = c.id === id);
  currentChatId = id;
  renderHistory();
}

function deleteHistory(e, id) {
  e.stopPropagation();
  chatHistories = chatHistories.filter(c => c.id !== id);
  renderHistory();
}

// ── Message rendering ──────────────────────────────────
function createMessageEl(role, content, sources) {
  const wrap = document.createElement('div');
  wrap.className = `msg-wrap ${role}`;

  const row = document.createElement('div');
  row.className = 'msg-row';

  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar';
  avatar.textContent = role === 'user' ? 'U' : '✦';

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  if (content) bubble.textContent = content;

  row.appendChild(avatar);
  row.appendChild(bubble);
  wrap.appendChild(row);

  if (sources && sources.length) {
    const sd = document.createElement('div');
    sd.className = 'msg-sources';
    sources.forEach(s => {
      const chip = document.createElement('span');
      chip.className = 'source-chip';
      chip.textContent = '↗ ' + s;
      sd.appendChild(chip);
    });
    wrap.appendChild(sd);
  }

  return { wrap, bubble };
}

function appendMessage(role, content, sources) {
  const box   = $('chatBox');
  const empty = $('chatEmpty');
  if (empty) empty.remove();
  const { wrap, bubble } = createMessageEl(role, content, sources);
  box.appendChild(wrap);
  box.scrollTop = box.scrollHeight;
  return bubble;
}

// ── Streaming typewriter ───────────────────────────────
async function streamText(bubble, text) {
  let partial = '';
  const cursor = document.createElement('span');
  cursor.className = 'cursor-blink';
  bubble.appendChild(cursor);

  for (let i = 0; i < text.length; i++) {
    await new Promise(r => setTimeout(r, 11));
    partial += text[i];
    if (bubble.childNodes[0]?.nodeType === Node.TEXT_NODE) {
      bubble.childNodes[0].textContent = partial;
    } else {
      bubble.insertBefore(document.createTextNode(partial), cursor);
      while (bubble.childNodes.length > 2) bubble.removeChild(bubble.childNodes[0]);
    }
    $('chatBox').scrollTop = $('chatBox').scrollHeight;
  }
  cursor.remove();
  bubble.textContent = text;
}

// ── Status ─────────────────────────────────────────────
function setStatus(text, spinning) {
  $('statusSpinner').style.display = spinning ? 'block' : 'none';
  $('statusText').textContent = text;
}

// ── Send message ───────────────────────────────────────
async function sendMessage() {
  if (isStreaming) return;

  const input = $('messageInput');
  const text  = input.value.trim();
  if (!text) return;

  input.value = '';
  input.style.height = 'auto';
  isStreaming = true;
  $('sendBtn').disabled = true;

  // Add new conversation entry to history
  const newId = 'chat-' + Date.now();
  chatHistories.unshift({
    id: newId,
    title: text.length > 45 ? text.slice(0, 42) + '…' : text,
    active: true,
  });
  chatHistories.forEach((c, i) => c.active = i === 0);
  currentChatId = newId;
  renderHistory();

  appendMessage('user', text);
  setStatus('Scanning knowledge archive…', true);

  try {
    let answer  = null;
    let sources = [];
    let apiError = null;

    // ── Real API call ──────────────────────────────────
    try {
      const res = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: text,
          chat_id:  currentChatId,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        answer  = data.answer;
        sources = data.sources || [];
      } else {
        let detail = `Request failed (${res.status})`;
        try {
          const errData = await res.json();
          if (errData && typeof errData.detail === 'string') detail = errData.detail;
          if (errData && typeof errData.error === 'string') detail = errData.error;
        } catch (_) {
          // Ignore JSON parsing errors and use status text fallback.
        }
        apiError = detail;
      }
    } catch (_) {
      apiError = 'Could not reach the server. Please check connection and try again.';
    }

    // ── Error fallback ─────────────────────────────────
    if (!answer && apiError) {
      answer = apiError;
    }

    // ── Last-resort fallback ───────────────────────────
    if (!answer) {
      answer = 'No answer returned by the server.';
    }

    setStatus('Composing response…', true);
    await sleep(300);

    const bubble = appendMessage('bot', '', sources);
    await streamText(bubble, answer);

  } catch (err) {
    appendMessage('bot', 'An error occurred: ' + err.message);
  }

  setStatus('', false);
  isStreaming = false;
  $('sendBtn').disabled = false;
}

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
}

// ── New Chat ───────────────────────────────────────────
function newChat() {
  currentChatId = null;
  chatHistories.forEach(c => c.active = false);
  renderHistory();

  $('chatBox').innerHTML = `
    <div class="chat-empty" id="chatEmpty">
      <div class="empty-glyph">
        <div class="empty-ring-outer"></div>
        <div class="empty-ring-inner"></div>
        <div class="empty-core">✦</div>
      </div>
      <div class="empty-title">Vespera</div>
      <div class="empty-tagline">Discover what data hides.</div>
    </div>`;

  setStatus('', false);
}

// ── Document upload ────────────────────────────────────
async function handleUpload(input) {
  const file = input.files[0];
  if (!file) return;

  // Show upload indicator dot
  const dot = $('uploadDot');
  if (dot) { dot.classList.add('visible'); }

  const doc = { name: file.name, status: 'indexing', chunks: 0, size: formatSize(file.size) };
  docs.unshift(doc);

  try {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch('/api/ingest', { method: 'POST', body: formData });
    if (res.ok) {
      const data = await res.json();
      doc.status = 'indexed';
      doc.chunks = data.chunks_added || Math.floor(Math.random() * 80) + 20;
    } else {
      throw new Error('Upload failed');
    }
  } catch (_) {
    doc.status = 'failed';
    doc.chunks = 0;
  }

  if (dot) dot.classList.remove('visible');
  input.value = '';

  // Show confirmation or failure in chat
  if (doc.status === 'indexed') {
    appendMessage('bot',
      `✓ Document "${escapeHtml(doc.name)}" indexed — ${doc.chunks} chunks ready.\n\nYou can now ask questions about its content.`
    );
  } else {
    appendMessage('bot',
      `Document upload failed for "${escapeHtml(doc.name)}". Please try again.`
    );
  }
}

function formatSize(bytes) {
  if (bytes > 1_048_576) return (bytes / 1_048_576).toFixed(1) + ' MB';
  return Math.round(bytes / 1024) + ' KB';
}

// ── Init ───────────────────────────────────────────────
renderHistory();

// ══════════════════════════════════════════════════════
//  VESPERA STARLINK — constellation / neural network
// ══════════════════════════════════════════════════════
(function initStarlink() {
  const canvas = $('starlinkCanvas');
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  let W, H;

  function resize() {
    const rect = canvas.parentElement.getBoundingClientRect();
    W = canvas.width  = rect.width  || 288;
    H = canvas.height = rect.height || 340;
  }
  resize();
  window.addEventListener('resize', resize);

  const NODE_COUNT = 22;
  const CONNECT_DIST = 90;

  // Node colors cycle through accent palette
  const COLORS = ['#7c6cff','#36d6c9','#a78bfa','#6358e8','#5ecfdc'];

  const nodes = Array.from({ length: NODE_COUNT }, (_, i) => ({
    x:      Math.random() * W,
    y:      Math.random() * H,
    vx:     (Math.random() - 0.5) * 0.38,
    vy:     (Math.random() - 0.5) * 0.38,
    r:      1.8 + Math.random() * 2.8,
    color:  COLORS[i % COLORS.length],
    phase:  Math.random() * Math.PI * 2,
    speed:  0.012 + Math.random() * 0.012,
    // Connection state — connections fade in/out
    connAlpha: {},
  }));

  // Sparse "active edge" system — edges blink in/out
  const edgeTimers = {};
  function edgeKey(i, j) { return i < j ? `${i}_${j}` : `${j}_${i}`; }

  let t = 0;

  function draw() {
    t += 0.012;
    ctx.clearRect(0, 0, W, H);

    // Background glow
    const bg = ctx.createRadialGradient(W * .5, H * .38, 0, W * .5, H * .38, W * .65);
    bg.addColorStop(0, 'rgba(124,108,255,0.045)');
    bg.addColorStop(1, 'transparent');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, W, H);

    // Update nodes
    nodes.forEach(n => {
      n.x += n.vx; n.y += n.vy;
      if (n.x < 8 || n.x > W - 8) n.vx *= -1;
      if (n.y < 8 || n.y > H - 8) n.vy *= -1;
      n.phase += n.speed;
    });

    // Draw edges
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const d = Math.hypot(nodes[i].x - nodes[j].x, nodes[i].y - nodes[j].y);
        if (d > CONNECT_DIST) continue;

        const key = edgeKey(i, j);
        if (!(key in edgeTimers)) {
          // Random chance to activate edge
          if (Math.random() < 0.002) edgeTimers[key] = Math.random() * Math.PI;
        } else {
          edgeTimers[key] += 0.018;
          if (edgeTimers[key] > Math.PI * 2.5) delete edgeTimers[key];
        }

        const proximity = 1 - d / CONNECT_DIST;
        let alpha = proximity * 0.18;
        if (key in edgeTimers) {
          alpha += Math.sin(edgeTimers[key]) * 0.38;
        }
        alpha = Math.max(0, Math.min(0.55, alpha));
        if (alpha < 0.01) continue;

        // Gradient line from node i color to j color
        const grad = ctx.createLinearGradient(nodes[i].x, nodes[i].y, nodes[j].x, nodes[j].y);
        grad.addColorStop(0, hexAlpha(nodes[i].color, alpha));
        grad.addColorStop(1, hexAlpha(nodes[j].color, alpha));

        ctx.beginPath();
        ctx.moveTo(nodes[i].x, nodes[i].y);
        ctx.lineTo(nodes[j].x, nodes[j].y);
        ctx.strokeStyle = grad;
        ctx.lineWidth   = 0.75 + proximity * 0.5;
        ctx.stroke();

        // Travelling pulse dot along active edges
        if (key in edgeTimers) {
          const progress = (Math.sin(edgeTimers[key] * 1.5) + 1) / 2;
          const px = nodes[i].x + (nodes[j].x - nodes[i].x) * progress;
          const py = nodes[i].y + (nodes[j].y - nodes[i].y) * progress;
          ctx.beginPath();
          ctx.arc(px, py, 1.6, 0, Math.PI * 2);
          ctx.fillStyle = hexAlpha('#ffffff', alpha * 1.5);
          ctx.fill();
        }
      }
    }

    // Draw nodes
    nodes.forEach((n, i) => {
      const pulse = 0.5 + 0.5 * Math.sin(n.phase);

      // Outer glow
      const grd = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, n.r * 3.5);
      grd.addColorStop(0, hexAlpha(n.color, 0.25 * pulse));
      grd.addColorStop(1, 'transparent');
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r * 3.5, 0, Math.PI * 2);
      ctx.fillStyle = grd;
      ctx.fill();

      // Core dot
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r * (0.8 + 0.25 * pulse), 0, Math.PI * 2);
      ctx.fillStyle = hexAlpha(n.color, 0.75 + 0.25 * pulse);
      ctx.fill();

      // Bright center
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r * 0.38, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255,255,255,0.7)';
      ctx.fill();
    });

    requestAnimationFrame(draw);
  }

  // Helper: hex color → rgba string
  function hexAlpha(hex, a) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},${a.toFixed(3)})`;
  }

  draw();
})();

// ══════════════════════════════════════════════════════
//  STARLINK STATUS FEED
// ══════════════════════════════════════════════════════
(function initFeed() {
  const messages = [
    { text: 'Starlink synchronizing…',       color: '#7c6cff' },
    { text: 'Analyzing hidden structures…',  color: '#36d6c9' },
    { text: 'Signal patterns emerging…',     color: '#a78bfa' },
    { text: 'Archive resonance detected…',   color: '#7c6cff' },
    { text: 'Deep scan in progress…',        color: '#36d6c9' },
    { text: 'Semantic layer active…',        color: '#a78bfa' },
    { text: 'Neural pathways aligned…',      color: '#7c6cff' },
    { text: 'Constellation mapping…',        color: '#36d6c9' },
    { text: 'Memory vectors loaded…',        color: '#a78bfa' },
    { text: 'Frequency bands nominal…',      color: '#7c6cff' },
  ];

  const container = $('feedMessages');
  if (!container) return;

  let shown = [];
  const MAX = 3;

  function addMessage() {
    const msg = messages[Math.floor(Math.random() * messages.length)];
    const el = document.createElement('div');
    el.className = 'feed-msg';
    el.innerHTML = `
      <div class="feed-msg-dot" style="background:${msg.color}"></div>
      <span>${msg.text}</span>`;
    container.insertBefore(el, container.firstChild);
    shown.unshift(el);

    // Fade old messages
    shown.forEach((e, i) => {
      e.classList.toggle('fading', i >= MAX - 1);
    });

    // Remove overflow
    while (shown.length > MAX) {
      const old = shown.pop();
      old.remove();
    }
  }

  // Initial burst
  addMessage();
  setTimeout(addMessage, 600);

  // Rotate messages
  setInterval(addMessage, 3800);
})();
