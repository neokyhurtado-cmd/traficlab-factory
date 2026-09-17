// TrafficLab Control — V0.1 client (vanilla JS, no build step)
//
// Threat model constraints enforced by control/tests/test_adversarial.py:
//   * This file MUST NOT contain or receive a Hermes bearer key or GitHub token.
//     Auth is an HttpOnly SameSite=Strict cookie the BFF sets on `/`; JS cannot
//     read it and never needs to.
//   * No `innerHTML` anywhere. Every value coming from the server (task titles,
//     block reasons, PR titles, error strings) is injected via textContent through
//     the `el()` helper, so hostile content renders as text and is never parsed
//     as HTML.
//
// Honesty contract: the BFF marks every fact with a state. When a fact is
// NOT_AVAILABLE_YET we render the reason the server gave. We never substitute a
// placeholder value that could be mistaken for a real reading.

(function () {
  'use strict';

  /** Safe DOM builder. Text always via textContent; attributes never via HTML. */
  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v === null || v === undefined || v === false) continue;
        if (k === 'class') node.className = v;
        else if (k === 'text') node.textContent = v;
        else if (k === 'onclick') node.addEventListener('click', v);
        else node.setAttribute(k, v);
      }
    }
    for (const c of children) {
      if (c === null || c === undefined || c === false) continue;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return node;
  }

  async function api(path, opts = {}) {
    const headers = Object.assign({}, opts.headers || {});
    if (opts.body && typeof opts.body !== 'string') {
      headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(opts.body);
    }
    const res = await fetch(path, Object.assign({ credentials: 'same-origin', headers }, opts));
    if (res.status === 401) throw new Error('sesión inválida — recargá la página');
    if (!res.ok) throw new Error(res.status + ' ' + (await res.text()));
    const ct = res.headers.get('content-type') || '';
    return ct.includes('application/json') ? res.json() : res.text();
  }

  function toast(msg, ms = 2600) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => t.classList.remove('show'), ms);
  }

  function setStatus(ok, label) {
    const dot = document.getElementById('bff-status');
    dot.classList.toggle('ok', !!ok);
    dot.title = label || (ok ? 'conectado' : 'desconectado');
  }

  // ---------- formatting ----------

  /** Relative age. Freshness is the whole point of this panel — an absolute
   *  timestamp makes the reader do subtraction; "hace 3 min" does not. */
  function ago(iso) {
    if (!iso) return '—';
    const then = Date.parse(iso);
    if (Number.isNaN(then)) return String(iso);
    const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
    if (secs < 60) return 'hace ' + secs + 's';
    if (secs < 3600) return 'hace ' + Math.floor(secs / 60) + ' min';
    if (secs < 86400) return 'hace ' + Math.floor(secs / 3600) + ' h';
    return 'hace ' + Math.floor(secs / 86400) + ' d';
  }

  function clock(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  /** Render a `Fact` envelope: value when VERIFIED, otherwise the server's
   *  reason. This is the single place the NOT_AVAILABLE_YET rule is applied. */
  function factLine(label, fact, formatter) {
    const ok = fact && fact.state === 'VERIFIED' && fact.value !== null;
    const body = ok
      ? (formatter ? formatter(fact.value) : String(fact.value))
      : ((fact && fact.reason) || 'sin datos');
    return el('div', { class: 'kv' },
      el('span', { class: 'k', text: label }),
      el('span', { class: 'v' + (ok ? '' : ' na'), text: body }),
      ok ? null : el('span', { class: 'badge warn', text: 'NOT_AVAILABLE_YET' }),
    );
  }

  function provenance(fact) {
    if (!fact) return null;
    return el('div', { class: 'prov', title: fact.source || '' },
      el('span', { text: 'fuente: ' + (fact.source || '?') }),
      el('span', { text: ' · ' + ago(fact.captured_at) }),
    );
  }

  function emptyCard(msg) {
    return el('div', { class: 'tile muted', text: msg });
  }

  // ---------- Tabs ----------
  document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(b => {
        b.classList.remove('active');
        b.setAttribute('aria-selected', 'false');
      });
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      btn.setAttribute('aria-selected', 'true');
      document.getElementById('panel-' + btn.dataset.tab).classList.add('active');
    });
  });

  // ---------- Mission Control ----------
  async function loadMission() {
    let m;
    try {
      m = await api('/api/v1/mission');
    } catch (e) {
      document.getElementById('goal-card').replaceChildren(
        el('div', { class: 'na', text: 'Mission Control no disponible: ' + e.message }));
      setStatus(false, e.message);
      return;
    }

    // --- active goal ---
    const card = document.getElementById('goal-card');
    card.replaceChildren();
    if (m.goal) {
      const g = m.goal;
      const run = g.run || {};
      card.appendChild(el('div', { class: 'goal-top' },
        el('span', { class: 'badge ' + (g.status === 'running' ? 'good' : 'warn'), text: g.status }),
        el('span', { class: 'mono small', text: g.task_id }),
      ));
      card.appendChild(el('h2', { class: 'goal-title', text: g.title }));
      card.appendChild(el('div', { class: 'kvs' },
        el('div', { class: 'kv' },
          el('span', { class: 'k', text: 'Owner' }),
          el('span', { class: 'v', text: g.assignee })),
        el('div', { class: 'kv' },
          el('span', { class: 'k', text: 'Gate' }),
          el('span', { class: 'v', text: run.status ? ('run #' + run.run_id + ' · ' + run.status) : 'sin run' })),
        el('div', { class: 'kv' },
          el('span', { class: 'k', text: 'Arrancó' }),
          el('span', { class: 'v', text: ago(g.started_at) })),
        el('div', { class: 'kv' },
          el('span', { class: 'k', text: 'Último latido' }),
          el('span', { class: 'v', text: ago(run.last_heartbeat_at) })),
        el('div', { class: 'kv' },
          el('span', { class: 'k', text: 'PID' }),
          el('span', { class: 'v mono', text: run.worker_pid ? String(run.worker_pid) : '—' })),
      ));
      if (run.summary) card.appendChild(el('p', { class: 'muted small', text: run.summary }));
      card.appendChild(provenance(g.run_provenance));
    } else {
      card.appendChild(el('div', { class: 'na', text: 'Sin meta activa' }));
      card.appendChild(el('div', { class: 'muted small', text: m.goal_absent_reason || '' }));
    }

    // --- queue KPIs ---
    const q = document.getElementById('queue-grid');
    q.replaceChildren();
    const order = [['running', 'corriendo'], ['ready', 'en cola'], ['review', 'en review'],
                   ['blocked', 'bloqueadas'], ['done', 'hechas']];
    for (const [key, label] of order) {
      q.appendChild(el('div', { class: 'kpi' },
        el('div', { class: 'kpi-n' + (key === 'blocked' && m.queue[key] > 0 ? ' alert' : ''),
                    text: String(m.queue[key]) }),
        el('div', { class: 'kpi-l', text: label }),
      ));
    }

    // --- code / CI / tests ---
    const code = document.getElementById('code-grid');
    code.replaceChildren();
    const git = m.git;
    const gitTile = el('div', { class: 'tile' }, el('h3', { text: 'Repo de control' }));
    gitTile.appendChild(el('div', { class: 'sub', text: m.repo }));
    if (git && git.state === 'VERIFIED') {
      const v = git.value;
      gitTile.appendChild(el('div', { class: 'kvs' },
        el('div', { class: 'kv' },
          el('span', { class: 'k', text: 'Rama' }),
          el('span', { class: 'v mono', text: v.branch })),
        el('div', { class: 'kv' },
          el('span', { class: 'k', text: 'HEAD' }),
          el('span', { class: 'v mono', text: v.head_sha_short })),
        el('div', { class: 'kv' },
          el('span', { class: 'k', text: 'Árbol' }),
          el('span', { class: 'v', text: v.clean ? 'limpio' : (v.dirty_file_count + ' archivos sin commitear') })),
      ));
      gitTile.appendChild(el('div', { class: 'sub', text: v.head_subject }));
    } else {
      gitTile.appendChild(el('div', { class: 'na', text: (git && git.reason) || 'sin datos de git' }));
    }
    gitTile.appendChild(provenance(git));
    code.appendChild(gitTile);

    const ciTile = el('div', { class: 'tile' }, el('h3', { text: 'CI' }));
    ciTile.appendChild(factLine('Estado', m.ci, v => String(v.state) + ' (' + v.total + ' checks)'));
    ciTile.appendChild(provenance(m.ci));
    code.appendChild(ciTile);

    const tTile = el('div', { class: 'tile' }, el('h3', { text: 'Tests' }));
    tTile.appendChild(factLine('Última corrida', m.tests,
      v => v.passed + '/' + v.total + ' pass' + (v.ok ? '' : ' — HAY FALLOS')));
    if (m.tests && m.tests.state === 'VERIFIED') {
      tTile.appendChild(el('div', { class: 'sub', text: 'corrida ' + ago(m.tests.value.ran_at) }));
      tTile.appendChild(el('div', { class: 'sub mono', text: (m.tests.value.head_sha || '').slice(0, 12) }));
      tTile.appendChild(el('span', {
        class: 'badge ' + (m.tests.value.ok ? 'good' : 'bad'),
        text: m.tests.value.ok ? 'verde' : 'rojo',
      }));
    }
    tTile.appendChild(provenance(m.tests));
    code.appendChild(tTile);

    // --- PRs ---
    const prg = document.getElementById('pr-grid');
    prg.replaceChildren();
    if (m.pull_requests && m.pull_requests.state === 'VERIFIED') {
      const prs = m.pull_requests.value || [];
      if (!prs.length) prg.appendChild(emptyCard('Sin PRs abiertos.'));
      for (const pr of prs) {
        prg.appendChild(el('div', { class: 'tile' },
          el('h3', { text: '#' + pr.number + ' ' + pr.title }),
          el('div', { class: 'sub mono', text: pr.head + ' → ' + pr.base }),
          el('div', { class: 'sub mono', text: (pr.head_sha || '').slice(0, 12) }),
          el('div', null,
            el('span', { class: 'badge ' + (pr.draft ? 'warn' : 'neutral'),
                         text: pr.draft ? 'draft' : 'abierto' }),
            el('span', { class: 'badge bad', text: 'merge = HUMAN_GO' }),
          ),
          el('div', { class: 'sub', text: 'actualizado ' + ago(pr.updated_at) }),
          pr.url ? el('a', { href: pr.url, target: '_blank', rel: 'noopener', text: 'ver PR ↗' }) : null,
        ));
      }
    } else {
      prg.appendChild(emptyCard((m.pull_requests && m.pull_requests.reason) || 'PRs no disponibles'));
    }

    document.getElementById('bff-version').textContent = m.schema_version || '';
    setStatus(true, 'mission ok');
  }

  // ---------- Products ----------
  async function loadProducts() {
    const grid = document.getElementById('product-grid');
    let data;
    try {
      data = await api('/api/v1/products');
    } catch (e) {
      grid.replaceChildren(emptyCard('Productos no disponibles: ' + e.message));
      return;
    }
    grid.replaceChildren();
    for (const card of data.cards) {
      const tile = el('div', { class: 'tile' },
        el('h3', { text: card.display_name }),
        el('div', { class: 'sub mono', text: card.repo }),
      );
      tile.appendChild(factLine('main', card.remote_head, v => String(v).slice(0, 12)));
      for (const t of card.targets) {
        const live = t.state === 'VERIFIED';
        tile.appendChild(el('div', { class: 'target' },
          el('span', { class: 'badge ' + (live ? 'good' : 'warn'),
                       text: live ? 'VERIFIED' : 'NOT_AVAILABLE_YET' }),
          el('span', { class: 'tl-label', text: t.label }),
          live
            ? el('a', { href: t.endpoint, target: '_blank', rel: 'noopener', text: 'abrir ↗' })
            : el('span', { class: 'na small', text: t.reason }),
        ));
      }
      tile.appendChild(el('div', { class: 'sub', text: card.review_note }));
      tile.appendChild(el('div', { class: 'prov', text: card.mutation_policy }));
      grid.appendChild(tile);
    }
  }

  // ---------- Human-Go Inbox ----------
  async function loadHumanGo() {
    const grid = document.getElementById('humango-grid');
    const autoGrid = document.getElementById('humango-auto-grid');
    let data;
    try {
      data = await api('/api/v1/human-go');
    } catch (e) {
      grid.replaceChildren(emptyCard('Inbox no disponible: ' + e.message));
      return;
    }
    grid.replaceChildren();
    autoGrid.replaceChildren();

    const badge = document.getElementById('human-go-count');
    if (data.pending_count > 0) {
      badge.textContent = data.pending_count + ' esperan';
      badge.hidden = false;
    } else {
      badge.hidden = true;
    }

    if (!data.pending.length) {
      grid.appendChild(emptyCard('Nada esperando por vos. 🎉'));
    }
    for (const d of data.pending) {
      const isMerge = d.kind === 'PR_MERGE_GATE';
      grid.appendChild(el('div', { class: 'tile ' + (isMerge ? 'tile-gate' : 'tile-block') },
        el('div', null,
          el('span', { class: 'badge ' + (isMerge ? 'bad' : 'warn'), text: d.block_kind }),
          el('span', { class: 'badge neutral', text: d.kind }),
        ),
        el('h3', { text: d.title }),
        d.reason ? el('div', { class: 'sub', text: d.reason }) : null,
        el('div', { class: 'sub', text: 'owner: ' + d.assignee + ' · ' + ago(d.created_at) }),
        el('div', { class: 'hint', text: d.action_hint }),
        d.url ? el('a', { href: d.url, target: '_blank', rel: 'noopener', text: 'abrir ↗' }) : null,
        d.task_id ? el('div', { class: 'prov mono', text: d.task_id }) : null,
      ));
    }

    if (!data.auto_resolving.length) {
      autoGrid.appendChild(emptyCard('Ninguna.'));
    }
    for (const d of data.auto_resolving) {
      autoGrid.appendChild(el('div', { class: 'tile muted' },
        el('span', { class: 'badge neutral', text: d.block_kind }),
        el('h3', { text: d.title }),
        el('div', { class: 'hint', text: d.action_hint }),
      ));
    }

    if (data.partial && data.degraded_reasons.length) {
      grid.appendChild(emptyCard('Parcial: ' + data.degraded_reasons.join(' | ')));
    }
  }

  // ---------- Evidence Timeline ----------
  async function loadTimeline() {
    const list = document.getElementById('timeline-list');
    const hb = document.getElementById('tl-heartbeats').checked ? '1' : '0';
    let data;
    try {
      data = await api('/api/v1/timeline?limit=40&heartbeats=' + hb);
    } catch (e) {
      list.replaceChildren(el('li', { class: 'na', text: 'Timeline no disponible: ' + e.message }));
      return;
    }
    list.replaceChildren();
    document.getElementById('tl-meta').textContent =
      data.count + ' eventos · ' + data.state + ' · ' + ago(data.captured_at);

    if (!data.items.length) {
      list.appendChild(el('li', { class: 'na', text: data.reason || 'sin eventos' }));
      return;
    }
    for (const it of data.items) {
      list.appendChild(el('li', { class: 'tl-item tone-' + it.tone },
        el('div', { class: 'tl-time', text: clock(it.created_at) }),
        el('div', { class: 'tl-body' },
          el('div', { class: 'tl-head' },
            el('span', { class: 'tl-label', text: it.label }),
            it.human_go ? el('span', { class: 'badge bad', text: 'HUMAN-GO' }) : null,
          ),
          it.task_title ? el('div', { class: 'sub', text: it.task_title }) : null,
          it.detail ? el('div', { class: 'sub mono', text: it.detail }) : null,
          el('div', { class: 'prov', text: it.assignee + ' · ' + (it.task_id || '') + ' · ' + ago(it.created_at) }),
        ),
      ));
    }
  }

  document.getElementById('tl-heartbeats').addEventListener('change', loadTimeline);

  // ---------- Review (previews + findings) ----------
  async function loadPreviews() {
    try {
      const previews = await api('/api/v1/previews');
      const reviewGrid = document.getElementById('review-previews');
      const sel = document.getElementById('finding-preview');
      reviewGrid.replaceChildren();
      sel.replaceChildren();
      for (const p of previews) {
        reviewGrid.appendChild(el('div', { class: 'tile' },
          el('h3', { text: p.title }),
          el('div', { class: 'sub', text: p.project_id + ' · ' + p.kind }),
          el('div', null, el('span', {
            class: 'badge ' + (p.available ? 'good' : 'warn'),
            text: p.available ? 'VERIFIED' : 'NOT_AVAILABLE_YET',
          })),
          el('div', { class: 'sub', text: p.available_reason }),
          p.available
            ? el('a', { href: p.endpoint, target: '_blank', rel: 'noopener', text: 'abrir visor ↗' })
            : null,
        ));
        const opt = document.createElement('option');
        opt.value = p.preview_id;
        opt.textContent = p.title;
        sel.appendChild(opt);
      }
    } catch (e) {
      toast('error cargando previews: ' + e.message);
    }
  }

  async function loadFindings() {
    try {
      const findings = await api('/api/v1/findings');
      const grid = document.getElementById('findings-grid');
      grid.replaceChildren();
      if (!findings.length) grid.appendChild(emptyCard('Sin findings todavía.'));
      for (const f of findings) {
        const kindClass = f.kind === 'looks_good' ? 'good' : (f.kind === 'needs_work' ? 'warn' : 'bad');
        grid.appendChild(el('div', { class: 'tile' },
          el('h3', { text: f.title }),
          el('div', null, el('span', { class: 'badge ' + kindClass, text: f.kind })),
          el('div', { class: 'sub', text: f.preview_id }),
          el('div', { class: 'sub', text: ago(f.created_at) }),
          el('div', { class: 'prov', text: 'by ' + f.created_by + ' · triage: ' + f.triage_state }),
        ));
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

  // ---------- Health ----------
  async function loadHealth() {
    try {
      const h = await api('/api/v1/health');
      document.getElementById('health-pre').textContent = JSON.stringify(h, null, 2);
      const grid = document.getElementById('health-grid');
      grid.replaceChildren();
      const rows = [
        ['Hermes', h.hermes_version, true],
        ['API Server', h.hermes_api_base, h.gateway_alive],
        ['BFF', h.bff_version, true],
        ['DB', h.db_path, true],
      ];
      for (const [label, value, ok] of rows) {
        grid.appendChild(el('div', { class: 'tile' },
          el('h3', { text: label }),
          el('div', { class: 'sub mono', text: String(value) }),
          el('span', {
            class: 'badge ' + (ok ? 'good' : 'warn'),
            text: ok ? 'VERIFIED' : 'NOT_AVAILABLE_YET',
          }),
          !ok ? el('div', { class: 'na small', text: 'no responde en ' + value }) : null,
        ));
      }
      setStatus(true, h.hermes_version);
    } catch (e) {
      setStatus(false, e.message);
      document.getElementById('health-pre').textContent = 'ERROR: ' + e.message;
    }
  }

  // ---------- SSE ----------
  async function subscribeEvents() {
    try {
      const res = await fetch('/api/v1/events', { credentials: 'same-origin' });
      if (!res.ok) return;
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf('\n\n')) !== -1) {
          const block = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          let event = 'message', data = '';
          for (const line of block.split('\n')) {
            if (line.startsWith('event:')) event = line.slice(6).trim();
            else if (line.startsWith('data:')) data += line.slice(5).trim();
          }
          if (event === 'finding_created') {
            let title = '?';
            try { title = JSON.parse(data).payload.title; } catch (_) { /* ignore */ }
            toast('nuevo finding: ' + title);
            loadFindings();
          }
        }
      }
    } catch (e) {
      // transient disconnect — retry
    }
    setTimeout(subscribeEvents, 5000);
  }

  // ---------- wiring ----------
  document.getElementById('refresh-mission').addEventListener('click', () => {
    loadMission(); loadProducts();
  });
  document.getElementById('refresh-humango').addEventListener('click', loadHumanGo);
  document.getElementById('refresh-timeline').addEventListener('click', loadTimeline);

  function refreshAll() {
    loadMission();
    loadProducts();
    loadHumanGo();
    loadTimeline();
    loadHealth();
  }

  refreshAll();
  loadPreviews();
  loadFindings();
  subscribeEvents();
  setInterval(refreshAll, 30000);
})();
