// TrafficLab Control — V0 client (vanilla JS)
// Threat model: this file MUST NOT receive or hold Hermes bearer keys or GitHub tokens.
// It only talks to Control BFF at /api/v1/* with the HttpOnly session cookie.

(function () {
  'use strict';

  /** Fetch wrapper that sends cookies for session auth (HttpOnly cookie set by BFF at /).
   *  Threat model: this file MUST NOT receive or hold Hermes bearer keys or GitHub tokens.
   *  The BFF sets `control_session` cookie HttpOnly SameSite=Strict; JS cannot read it. */
  async function api(path, opts = {}) {
    const headers = Object.assign({}, opts.headers || {});
    if (opts.body && typeof opts.body !== 'string') {
      headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(opts.body);
    }
    const res = await fetch(path, Object.assign({ credentials: 'same-origin', headers }, opts));
    if (res.status === 401) {
      throw new Error('unauthorized');
    }
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${res.status} ${text}`);
    }
    const ct = res.headers.get('content-type') || '';
    return ct.includes('application/json') ? res.json() : res.text();
  }

  function toast(msg, ms = 2500) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.remove('show'), ms);
  }

  function setStatus(ok, label) {
    const dot = document.getElementById('bff-status');
    dot.classList.toggle('ok', !!ok);
    dot.title = label || (ok ? 'connected' : 'disconnected');
  }

  // ---------- Tabs ----------
  document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('panel-' + btn.dataset.tab).classList.add('active');
    });
  });

  // ---------- Health ----------
  async function loadHealth() {
    try {
      const h = await api('/api/v1/health');
      document.getElementById('health-pre').textContent = JSON.stringify(h, null, 2);
      document.getElementById('bff-version').textContent = 'bff v' + (h.bff_version || '?');
      setStatus(true, h.hermes_version);
    } catch (e) {
      setStatus(false, e.message);
      document.getElementById('health-pre').textContent = 'ERROR: ' + e.message;
    }
  }
  loadHealth();
  setInterval(loadHealth, 30000);

  // ---------- Projects + Previews ----------
  async function loadProjects() {
    try {
      const projects = await api('/api/v1/projects');
      const grid = document.getElementById('projects-grid');
      grid.innerHTML = '';
      for (const p of projects) {
        const el = document.createElement('div');
        el.className = 'tile';
        el.innerHTML = `
          <h3>${p.display_name}</h3>
          <div class="sub">${p.repo}</div>
          <div><span class="badge ${p.visor_alive ? 'good' : 'bad'}">${p.visor_alive ? 'visor alive' : 'visor down'}</span></div>
          ${p.visor_endpoint ? `<div class="sub">${p.visor_endpoint}</div>` : ''}
        `;
        grid.appendChild(el);
      }
    } catch (e) {
      toast('error cargando projects: ' + e.message);
    }
  }

  async function loadPreviews() {
    try {
      const previews = await api('/api/v1/previews');
      const grid = document.getElementById('previews-grid');
      const reviewGrid = document.getElementById('review-previews');
      const sel = document.getElementById('finding-preview');
      grid.innerHTML = '';
      reviewGrid.innerHTML = '';
      sel.innerHTML = '';
      for (const p of previews) {
        const tile = document.createElement('div');
        tile.className = 'tile';
        tile.innerHTML = `
          <h3>${p.title}</h3>
          <div class="sub">${p.project_id} · ${p.kind}</div>
          <div><span class="badge ${p.available ? 'good' : 'warn'}">${p.available ? 'available' : 'unavailable'}</span></div>
          <div class="sub">${p.available_reason}</div>
          ${p.available ? `<a href="${p.endpoint}" target="_blank" rel="noopener">abrir visor ↗</a>` : ''}
        `;
        grid.appendChild(tile);

        const reviewTile = tile.cloneNode(true);
        reviewGrid.appendChild(reviewTile);

        const opt = document.createElement('option');
        opt.value = p.preview_id;
        opt.textContent = p.title;
        sel.appendChild(opt);
      }
    } catch (e) {
      toast('error cargando previews: ' + e.message);
    }
  }

  // ---------- Findings ----------
  async function loadFindings() {
    try {
      const findings = await api('/api/v1/findings');
      const grid = document.getElementById('findings-grid');
      grid.innerHTML = '';
      for (const f of findings) {
        const tile = document.createElement('div');
        tile.className = 'tile';
        const kindClass = f.kind === 'looks_good' ? 'good' : (f.kind === 'needs_work' ? 'warn' : 'bad');
        tile.innerHTML = `
          <h3>${f.title}</h3>
          <div><span class="badge ${kindClass}">${f.kind}</span></div>
          <div class="sub">${f.preview_id}</div>
          <div class="sub">${f.created_at}</div>
          <div class="sub">by ${f.created_by} · triage: ${f.triage_state}</div>
        `;
        grid.appendChild(tile);
      }
    } catch (e) {
      toast('error cargando findings: ' + e.message);
    }
  }

  document.getElementById('finding-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const body = {
      preview_id: document.getElementById('finding-preview').value,
      kind: document.getElementById('finding-kind').value,
      title: document.getElementById('finding-title').value.trim(),
      frame_ref: {},
      context: { free_text: document.getElementById('finding-context').value },
    };
    if (!body.title) return;
    try {
      await api('/api/v1/findings', { method: 'POST', body });
      toast('finding creado');
      document.getElementById('finding-title').value = '';
      document.getElementById('finding-context').value = '';
      loadFindings();
    } catch (e) {
      toast('error creando finding: ' + e.message);
    }
  });

  // ---------- Chat (V0 stub — M3+ will connect to Hermes API Server) ----------
  const log = document.getElementById('chat-log');
  function appendMsg(role, text) {
    const div = document.createElement('div');
    div.className = 'msg ' + role;
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }
  appendMsg('system', 'V0 stub: chat local. M3+ will stream from Hermes API Server /v1/chat/completions.');
  document.getElementById('chat-form').addEventListener('submit', (ev) => {
    ev.preventDefault();
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text) return;
    appendMsg('user', text);
    appendMsg('assistant', `Recibido: "${text}". [V0 stub — sin agent loop todavía.]`);
    input.value = '';
  });

  // ---------- SSE stream subscription (control-event/v1.0.0) ----------
  // V0 connect uses fetch + ReadableStream; no EventSource dependency on session token via headers.
  // M3+ will dedup events by event_id (5min window).
  async function subscribeEvents() {
    try {
      const res = await fetch('/api/v1/events', {
        credentials: 'same-origin',
      });
      if (!res.ok) {
        toast('event stream failed: ' + res.status);
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf('\n\n')) !== -1) {
          const block = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const lines = block.split('\n');
          let event = 'message', data = '';
          for (const line of lines) {
            if (line.startsWith('event:')) event = line.slice(6).trim();
            else if (line.startsWith('data:')) data += line.slice(5).trim();
          }
          if (event === 'finding_created') {
            toast('nuevo finding: ' + (data ? JSON.parse(data).payload.title : '?'));
            loadFindings();
          }
        }
      }
    } catch (e) {
      // silent retry
      setTimeout(subscribeEvents, 5000);
    }
  }
  subscribeEvents();

  // ---------- Init ----------
  loadProjects();
  loadPreviews();
  loadFindings();
  setInterval(loadFindings, 30000);
})();