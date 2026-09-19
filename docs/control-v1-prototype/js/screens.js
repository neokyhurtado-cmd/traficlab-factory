/* screens.js — 10 required screens (M1)
 *
 * All screens are read-only against public GitHub data + the local
 * VisualReviewFinding evidence cache. No inbound Hermes call; never
 * carries an Authorization header.
 */
(function (root) {
  'use strict';

  const { PRODUCT_REPOS } = root.Data;

  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    if (attrs) {
      for (const k in attrs) {
        if (k === 'class') e.className = attrs[k];
        else if (k === 'html') e.innerHTML = attrs[k];
        else if (k.startsWith('on') && typeof attrs[k] === 'function') {
          e.addEventListener(k.slice(2), attrs[k]);
        } else if (attrs[k] != null) e.setAttribute(k, attrs[k]);
      }
    }
    if (children) {
      (Array.isArray(children) ? children : [children]).forEach((c) => {
        if (c == null) return;
        if (typeof c === 'string') e.appendChild(document.createTextNode(c));
        else e.appendChild(c);
      });
    }
    return e;
  }

  function badge(text, tone) {
    return el('span', { class: 'badge ' + (tone ? 'badge-' + tone : '') }, text);
  }

  function fmtDate(iso) {
    if (!iso) return '—';
    try { return new Date(iso).toISOString().replace('T', ' ').slice(0, 19) + ' UTC'; }
    catch (_) { return iso; }
  }

  function repoLink(repoSlug, n) {
    return 'https://github.com/' + repoSlug + '/issues/' + n;
  }

  function makeSkeleton(rows) {
    const wrap = el('div', { class: 'wo-list' });
    for (let i = 0; i < (rows || 3); i++) {
      wrap.appendChild(el('div', { class: 'wo-card' }, [
        el('div', { class: 'wo-title skel', style: 'width:60%;height:14px;border-radius:4px;' }),
        el('div', { class: 'wo-repo skel', style: 'width:30%;height:10px;margin-top:8px;border-radius:4px;' })
      ]));
    }
    return wrap;
  }

  function writeIdentityPanel(into, identity) {
    into.appendChild(el('div', { class: 'identity' }, [
      el('dl', null, [
        el('dt', null, 'product'),
        el('dd', null, identity.product || '—'),
        el('dt', null, 'repo'),
        el('dd', null, identity.repo || '—'),
        el('dt', null, 'base_sha'),
        el('dd', null, identity.base_sha || '—'),
        el('dt', null, 'candidate_sha/pr'),
        el('dd', null, identity.candidate_sha_pr || '—'),
        el('dt', null, 'preview_build_id'),
        el('dd', null, identity.preview_build_id || '—'),
        el('dt', null, 'url/route'),
        el('dd', null, identity.url_route || '—'),
        el('dt', null, 'viewport'),
        el('dd', null, identity.viewport || '—'),
        el('dt', null, 'dataset/video/network/scenario/run'),
        el('dd', null, identity.dataset_video_network_scenario_run || '—'),
        el('dt', null, 'frame_or_sim_time'),
        el('dd', null, identity.frame_or_sim_time || '—'),
        el('dt', null, 'capture_timestamp'),
        el('dd', null, identity.capture_timestamp || '—')
      ])
    ]));
  }

  /* ---------------- 1) HOME / COMMAND ---------------- */
  async function screenHome(main) {
    const [iav, suini] = await Promise.all([
      Data.repoSummary(PRODUCT_REPOS['IA-VISION']).catch((e) => ({ error: e.message })),
      Data.repoSummary(PRODUCT_REPOS['SUINI']).catch((e) => ({ error: e.message }))
    ]);
    main.appendChild(el('div', { class: 'section' }, [
      el('h2', { class: 'role-command' }, 'Command'),
      el('p', { class: 'lede' }, 'Open one URL/app and direct IA-VISION + SUINI. Mobile-first, no Telegram required, no Codex required.')
    ]));
    const kpi = el('div', { class: 'kpi-strip' });
    [
      { label: 'IA-VISION main',  value: (iav && !iav.error && iav.remote_head_sha) ? iav.remote_head_sha.slice(0, 7) : '—' },
      { label: 'SUINI main',      value: (suini && !suini.error && suini.remote_head_sha) ? suini.remote_head_sha.slice(0, 7) : '—' },
      { label: 'Hermes',          value: Data.HERMES.installed_version.split(' ')[0] },
      { label: 'Gateway PID',     value: String(Data.RUNTIME.default_pid || '—') }
    ].forEach((k) => {
      kpi.appendChild(el('div', { class: 'kpi' }, [
        el('div', { class: 'kpi-label' }, k.label),
        el('div', { class: 'kpi-value mono' }, k.value)
      ]));
    });
    main.appendChild(kpi);

    main.appendChild(el('div', { class: 'section' }, [
      el('h2', { class: 'role-decision' }, 'HUMAN-GO queue'),
      el('p', { class: 'lede muted' }, 'Decisions that genuinely require David. Everything else runs through ZERO MICRO-APPROVAL.')
    ]));
    main.appendChild(makeSkeleton(3));
    const hg = await renderHumanGoList(main, /*replace*/ true);

    main.appendChild(el('div', { class: 'section' }, [
      el('h2', { class: 'role-evidence' }, 'Project selector'),
      el('div', { class: 'grid grid-3' }, [
        el('div', { class: 'card' }, [
          el('h3', null, 'GLOBAL'),
          el('p', { class: 'muted' }, 'cross-product intelligence'),
          el('div', { class: 'row' }, [
            el('button', { class: 'btn', onclick: () => Router.go('mission') }, 'Open Mission')
          ])
        ]),
        el('div', { class: 'card' }, [
          el('h3', null, 'IA-VISION'),
          el('p', { class: 'muted' }, iav && !iav.error ? ('last push ' + fmtDate(iav.pushed_at)) : 'fetch failed'),
          el('div', { class: 'row' }, [
            el('button', { class: 'btn', onclick: () => Router.go('iavision') }, 'Open IA-VISION')
          ])
        ]),
        el('div', { class: 'card' }, [
          el('h3', null, 'SUINI'),
          el('p', { class: 'muted' }, suini && !suini.error ? ('last push ' + fmtDate(suini.pushed_at)) : 'fetch failed'),
          el('div', { class: 'row' }, [
            el('button', { class: 'btn', onclick: () => Router.go('suini') }, 'Open SUINI')
          ])
        ])
      ])
    ]));

    // command bar at the bottom — sends a placeholder intent into the
    // event log; never actually dispatches without composition-B.
    const bar = el('form', { class: 'command-bar', onsubmit: (ev) => { ev.preventDefault(); submitIntent(); } }, [
      el('select', { class: 'sel-project', 'aria-label': 'project context' }, [
        el('option', null, 'GLOBAL'),
        el('option', null, 'IA-VISION'),
        el('option', null, 'SUINI')
      ]),
      el('textarea', { placeholder: 'Direct Hermes in natural language (composition-A reads only; live dispatch requires API server — see Health).', rows: 1, 'aria-label': 'intent' }),
      el('button', { type: 'submit' }, 'Send')
    ]);
    main.appendChild(bar);
  }

  async function submitIntent() {
    const ta = document.querySelector('.command-bar textarea');
    const sel = document.querySelector('.command-bar .sel-project');
    if (!ta || !ta.value.trim()) return;
    const intent = {
      schema_version: 'control.intent/v1',
      event_id: IDB.uid(),
      project_id: sel ? sel.value : 'GLOBAL',
      created_at: new Date().toISOString(),
      text: ta.value.trim(),
      composition: 'A-readonly',
      note: 'V0 has no Hermes API server; intent is logged locally. Live dispatch is HUMAN_GO_REAL.'
    };
    await IDB.set('intent:' + intent.event_id, intent);
    ta.value = '';
    const evt = new CustomEvent('tlfb:toast', { detail: 'intent captured locally (' + intent.project_id + '). Composition-A is read-only.' });
    root.dispatchEvent(evt);
  }

  /* ---------------- 2) MISSION CONTROL ---------------- */
  async function screenMission(main) {
    main.appendChild(el('div', { class: 'section' }, [
      el('h2', { class: 'role-command' }, 'Mission Control'),
      el('p', { class: 'lede muted' }, 'What is happening now. Reads open PRs and open issues; events stream requires Hermes API server (HUMAN_GO_REAL).')
    ]));
    main.appendChild(makeSkeleton(3));
    await renderAllProjectLists(main, /*replace*/ true);
  }

  async function renderAllProjectLists(main, replace) {
    const sections = [];
    for (const [name, slug] of Object.entries(PRODUCT_REPOS)) {
      const wrap = el('div', { class: 'section' });
      wrap.appendChild(el('h2', null, name));
      const list = el('div', { class: 'wo-list' });
      list.appendChild(makeSkeleton(2));
      wrap.appendChild(list);
      sections.push({ name, slug, listEl: list });
      if (replace) {
        if (main.contains(list)) main.removeChild(list);
        main.appendChild(wrap);
      } else {
        main.appendChild(wrap);
      }
    }
    // Now populate one by one
    for (const s of sections) {
      const issues = await Data.listOpenIssues(s.slug, 6);
      const pulls  = await Data.listOpenPulls(s.slug, 4);
      s.listEl.innerHTML = '';
      pulls.forEach((p) => s.listEl.appendChild(renderPullCard(s.slug, p)));
      issues.forEach((i) => s.listEl.appendChild(renderIssueCard(s.slug, i)));
      if (pulls.length + issues.length === 0) {
        s.listEl.appendChild(el('div', { class: 'empty' }, 'no open issues / PRs reported by public GitHub REST'));
      }
    }
  }

  async function screenProduct(main, projectKey) {
    const slug = PRODUCT_REPOS[projectKey];
    const summary = await Data.repoSummary(slug);
    const issues = await Data.listOpenIssues(slug, 10);
    const pulls  = await Data.listOpenPulls(slug, 10);
    const commits = await Data.listRecentCommits(slug, 8);
    main.appendChild(el('div', { class: 'section' }, [
      el('h2', { class: 'role-world' }, projectKey + ' · project'),
      el('p', { class: 'lede muted' }, [
        'default_branch: ', el('span', { class: 'mono' }, summary.default_branch), ' · ',
        'head: ', el('a', { href: 'https://github.com/' + slug + '/commits/main', target: '_blank', rel: 'noopener' }, summary.remote_head_sha ? summary.remote_head_sha.slice(0, 7) : '—'),
        ' · ',
        'open issues: ', el('span', { class: 'mono' }, String(summary.open_issues))
      ])
    ]));

    const tabs = el('div', { class: 'tabs', role: 'tablist' });
    const tabOpen = el('button', { class: 'tab', 'aria-selected': 'true', onclick: () => switchTab('open') }, 'Open issues (' + issues.length + ')');
    const tabPR = el('button', { class: 'tab', onclick: () => switchTab('pr') }, 'Open PRs (' + pulls.length + ')');
    const tabCom = el('button', { class: 'tab', onclick: () => switchTab('com') }, 'Recent commits (' + commits.length + ')');
    tabs.appendChild(tabOpen); tabs.appendChild(tabPR); tabs.appendChild(tabCom);

    const issuesPane = el('div', { class: 'pane pane-open' });
    const pullsPane = el('div', { class: 'pane pane-pr', hidden: true });
    const comPane = el('div', { class: 'pane pane-com', hidden: true });

    function fillIssues() {
      issuesPane.innerHTML = '';
      if (!issues.length) issuesPane.appendChild(el('div', { class: 'empty' }, 'no open issues'));
      issues.forEach((i) => issuesPane.appendChild(renderIssueCard(slug, i, true)));
    }
    function fillPRs() {
      pullsPane.innerHTML = '';
      if (!pulls.length) pullsPane.appendChild(el('div', { class: 'empty' }, 'no open PRs'));
      pulls.forEach((p) => pullsPane.appendChild(renderPullCard(slug, p, true)));
    }
    function fillComs() {
      comPane.innerHTML = '';
      if (!commits.length) comPane.appendChild(el('div', { class: 'empty' }, 'no recent commits'));
      const list = el('div', { class: 'wo-list' });
      commits.forEach((c) => {
        list.appendChild(el('div', { class: 'wo-card' }, [
          el('div', { class: 'wo-title' }, [
            el('a', { href: c.url, target: '_blank', rel: 'noopener' }, c.short_sha + ' · ' + c.message)
          ]),
          el('div', { class: 'wo-repo' }, c.author + ' · ' + fmtDate(c.ts))
        ]));
      });
      comPane.appendChild(list);
    }
    fillIssues(); fillPRs(); fillComs();

    function switchTab(t) {
      [tabOpen, tabPR, tabCom].forEach((b) => b.setAttribute('aria-selected', 'false'));
      [issuesPane, pullsPane, comPane].forEach((p) => p.setAttribute('hidden', ''));
      if (t === 'open') { tabOpen.setAttribute('aria-selected', 'true'); issuesPane.removeAttribute('hidden'); }
      if (t === 'pr')   { tabPR.setAttribute('aria-selected', 'true'); pullsPane.removeAttribute('hidden'); }
      if (t === 'com')  { tabCom.setAttribute('aria-selected', 'true'); comPane.removeAttribute('hidden'); }
    }
    tabOpen.onclick = () => switchTab('open');
    tabPR.onclick = () => switchTab('pr');
    tabCom.onclick = () => switchTab('com');

    main.appendChild(tabs);
    main.appendChild(issuesPane);
    main.appendChild(pullsPane);
    main.appendChild(comPane);
  }

  function renderIssueCard(slug, i, expanded) {
    const card = el('div', { class: 'wo-card' + (i.human_go_required ? ' is-decision' : '') });
    card.appendChild(el('div', { class: 'wo-title' }, [
      el('a', { href: i.url, target: '_blank', rel: 'noopener' }, '#' + i.goal_id + ' · ' + i.title)
    ]));
    card.appendChild(el('div', { class: 'wo-repo' }, slug + ' · updated ' + fmtDate(i.updated_at)));
    const row = el('div', { class: 'row' });
    i.labels.forEach((l) => row.appendChild(badge(l, l === 'hermes-work-order' ? 'accent0' : '')));
    if (i.human_go_required) row.appendChild(badge('HUMAN-GO', 'bad'));
    if (i.blocked_by_external) row.appendChild(badge('blocked', 'warn'));
    if (i.kind === 'MACRO_GOAL') row.appendChild(badge(i.kind.toLowerCase().replace('_', ' '), 'accent2'));
    card.appendChild(row);
    if (expanded && i.body) {
      const bodyEl = el('div', { class: 'mono', style: 'margin-top:10px;color:var(--text-1);white-space:pre-wrap;' });
      bodyEl.textContent = i.body.length > 1200 ? (i.body.slice(0, 1200) + '\n\n[…truncated]') : i.body;
      card.appendChild(bodyEl);
    }
    if (i.human_go_required) {
      card.appendChild(el('div', { class: 'wo-actions' }, [
        el('button', { class: 'btn btn-decision', onclick: () => Router.go('humango') }, 'Open in HUMAN-GO inbox')
      ]));
    }
    return card;
  }

  function renderPullCard(slug, p, expanded) {
    const card = el('div', { class: 'wo-card' });
    card.appendChild(el('div', { class: 'wo-title' }, [
      el('a', { href: p.url, target: '_blank', rel: 'noopener' }, '#' + p.goal_id + ' · ' + p.title)
    ]));
    card.appendChild(el('div', { class: 'wo-repo' }, slug + ' · ' + p.base + ' ← ' + p.branch + ' · ' + (p.head_sha ? p.head_sha.slice(0, 7) : '—')));
    const row = el('div', { class: 'row' });
    row.appendChild(badge(p.state, p.state.indexOf('merged') >= 0 ? 'good' : 'info'));
    if (p.draft) row.appendChild(badge('draft', 'warn'));
    card.appendChild(row);
    if (expanded && p.body) {
      const bodyEl = el('div', { class: 'mono', style: 'margin-top:10px;color:var(--text-1);white-space:pre-wrap;' });
      bodyEl.textContent = (p.body || '').slice(0, 600);
      card.appendChild(bodyEl);
    }
    card.appendChild(el('div', { class: 'wo-actions' }, [
      el('button', { class: 'btn', onclick: () => Router.go('prlab') }, 'Open in PR Lab'),
      el('a', { class: 'btn', href: p.url, target: '_blank', rel: 'noopener' }, 'View on GitHub')
    ]));
    return card;
  }

  /* ---------------- 3) IA-VISION ---------------- */
  async function screenIA(main) { await screenProduct(main, 'IA-VISION'); }

  /* ---------------- 4) SUINI ---------------- */
  async function screenSUINI(main) {
    await screenProduct(main, 'SUINI');
    main.appendChild(el('div', { class: 'section' }, [
      el('h2', null, 'SUINI runtime (localhost)'),
      el('div', { class: 'card' }, [
        el('h3', null, 'Canonical runtime authority'),
        el('p', { class: 'muted' }, [
          'SUINI runtime is bound to the same host that runs HERMES-SUINI. ',
          'Cross-host preview is a future gate; the Control product does NOT proxy :8081.'
        ]),
        el('div', { class: 'row' }, [
          badge('localhost:8081 (host-internal)', 'warn'),
          badge('NOT_AVAILABLE_YET (cross-host)', 'bad')
        ])
      ])
    ]));
  }

  /* ---------------- 5) VISUAL REVIEW HUB ---------------- */
  async function screenReview(main) {
    main.appendChild(el('div', { class: 'section' }, [
      el('h2', { class: 'role-world' }, 'Visual Review Hub'),
      el('p', { class: 'lede muted' }, 'Open the real product visor and capture reproducible review findings. Composition-A ships the shell, capture pipeline, and identity contract.')
    ]));

    const tabs = el('div', { class: 'tabs' });
    const iaTab = el('button', { class: 'tab', 'aria-selected': 'true', onclick: () => switchMode('ia') }, 'IA-VISION review');
    const suTab = el('button', { class: 'tab', onclick: () => switchMode('su') }, 'SUINI review');
    tabs.appendChild(iaTab); tabs.appendChild(suTab);

    const iaPane = el('div');
    const suPane = el('div', { hidden: '' });

    function iaIdentity() {
      return {
        product: 'IA-VISION',
        repo: PRODUCT_REPOS['IA-VISION'],
        base_sha: '— (discover on first poll)',
        candidate_sha_pr: '— (set after PR pick)',
        preview_build_id: '— (set after visor ready)',
        url_route: 'https://github.com/' + PRODUCT_REPOS['IA-VISION'] + ' (visor URL convention lives in product)',
        viewport: window.innerWidth < 640 ? 'phone ' + window.innerWidth + 'x' + window.innerHeight : 'desktop ' + window.innerWidth + 'x' + window.innerHeight,
        dataset_video_network_scenario_run: '— (set on capture)',
        frame_or_sim_time: '— (set on capture)',
        capture_timestamp: new Date().toISOString()
      };
    }
    function suIdentity() {
      return {
        product: 'SUINI',
        repo: PRODUCT_REPOS['SUINI'],
        base_sha: '— (discover on first poll)',
        candidate_sha_pr: '— (set after PR pick)',
        preview_build_id: '— (set after visor ready)',
        url_route: 'http://localhost:8081 (host-internal)',
        viewport: window.innerWidth < 640 ? 'phone ' + window.innerWidth + 'x' + window.innerHeight : 'desktop ' + window.innerWidth + 'x' + window.innerHeight,
        dataset_video_network_scenario_run: '— (set on capture: scenario/network/run)',
        frame_or_sim_time: '— (set on capture)',
        capture_timestamp: new Date().toISOString()
      };
    }

    const iaVisor = makeVisor('IA-VISION visor (placeholder)');
    const iaMeta = el('div', { class: 'meta' }, [
      el('h3', null, 'IA-VISION visor'),
      el('div', { class: 'row' }, [badge('placeholder (real URL = product contract)', 'warn')])
    ]);
    const iaCapture = el('div', { class: 'capture-strip' }, [
      el('button', { class: 'btn', onclick: () => captureFinding('IA-VISION', iaIdentity()) }, 'Capture finding'),
      el('a', { class: 'btn', href: 'https://github.com/' + PRODUCT_REPOS['IA-VISION'], target: '_blank', rel: 'noopener' }, 'Open product page')
    ]);
    iaPane.appendChild(iaVisor);
    iaPane.appendChild(iaMeta);
    iaPane.appendChild(iaCapture);

    const suVisor = makeVisor('SUINI Panorama / visor (placeholder)');
    const suMeta = el('div', { class: 'meta' }, [
      el('h3', null, 'SUINI Panorama / visor'),
      el('div', { class: 'row' }, [badge('NOT_AVAILABLE_YET to public network', 'bad'), badge('localhost:8081 only', 'warn')])
    ]);
    const suCapture = el('div', { class: 'capture-strip' }, [
      el('button', { class: 'btn', onclick: () => captureFinding('SUINI', suIdentity()) }, 'Capture finding'),
      el('span', { class: 'muted mono', style: 'font-size:11px;' }, 'Control does not proxy :8081.')
    ]);
    suPane.appendChild(suVisor);
    suPane.appendChild(suMeta);
    suPane.appendChild(suCapture);

    function switchMode(t) {
      iaTab.setAttribute('aria-selected', 'false');
      suTab.setAttribute('aria-selected', 'false');
      iaPane.setAttribute('hidden', '');
      suPane.setAttribute('hidden', '');
      if (t === 'ia') { iaTab.setAttribute('aria-selected', 'true'); iaPane.removeAttribute('hidden'); }
      if (t === 'su') { suTab.setAttribute('aria-selected', 'true'); suPane.removeAttribute('hidden'); }
    }

    main.appendChild(tabs);
    main.appendChild(iaPane);
    main.appendChild(suPane);

    // identity dump for the current mode
    const idWrap = el('div', { class: 'section' }, [
      el('h2', null, 'Review evidence identity (IA-VISION mode)')
    ]);
    writeIdentityPanel(idWrap, iaIdentity());
    main.appendChild(idWrap);

    // recent findings
    const findings = await Data.listFindings();
    const fWrap = el('div', { class: 'section' }, [
      el('h2', null, 'Recent findings'),
      el('p', { class: 'muted' }, 'Capture takes a screenshot of the placeholder viewport and writes a durable VisualReviewFinding to local storage. Pending POST to HERMES-ORCH.')
    ]);
    if (findings.length === 0) {
      fWrap.appendChild(el('div', { class: 'empty' }, 'no findings captured yet'));
    } else {
      const fl = el('div', { class: 'finding-list' });
      findings.slice(0, 12).forEach((f) => {
        fl.appendChild(el('div', { class: 'finding' }, [
          el('div', { class: 'finding-thumb' }),
          el('div', null, [
            el('div', null, [
              badge(f.product_kind, 'accent0'),
              ' ',
              badge(f.result, f.result === 'PASS' ? 'good' : (f.result === 'INCONCLUSIVE' ? 'warn' : 'bad')),
              ' ',
              el('span', { class: 'finding-meta' }, '#' + f.evidence_id.slice(0, 8) + ' · ' + fmtDate(f.created_at))
            ]),
            el('div', { class: 'finding-meta', style: 'margin-top:6px;' }, f.summary || f.annotation || '(no summary)'),
            el('div', { class: 'finding-meta', style: 'margin-top:4px;' }, f.identity.url_route || '—')
          ])
        ]));
      });
      fWrap.appendChild(fl);
    }
    main.appendChild(fWrap);
  }

  function makeVisor(label) {
    const card = el('div', { class: 'visor-card' });
    const frame = el('div', { class: 'visor-frame' }, [
      el('div', { class: 'overlay-grid' }),
      el('span', null, label)
    ]);
    card.appendChild(frame);
    return card;
  }

  function captureFinding(productKind, identity) {
    return (async () => {
      const summary = prompt('one-sentence summary (PASS / FINDING / INCONCLUSIVE)', 'looks good baseline');
      if (summary == null) return;
      let result = 'INCONCLUSIVE';
      const r = (prompt('result? pass / finding / inconclusive', 'pass') || '').trim().toLowerCase();
      if (r === 'pass') result = 'PASS';
      else if (r === 'finding') result = 'FINDING';
      const finding = {
        reviewer: 'david',
        product_kind: productKind,
        review_mode: productKind === 'IA-VISION' ? 'IA-VISION_REVIEW' : 'SUINI_REVIEW',
        identity,
        screenshot_ref: { ref_type: 'preview_screenshot', uri: 'local-storage://tlfb:v0:finding:' },
        annotation: summary,
        result,
        summary,
        pending_post: true,
        post_target: productKind === 'IA-VISION' ? 'HERMES-IA' : 'HERMES-SUINI'
      };
      const saved = await Data.saveFinding(finding);
      Redact.safeLog('finding-saved', { evidence_id: saved.evidence_id, result: saved.result, product_kind: saved.product_kind });
      root.dispatchEvent(new CustomEvent('tlfb:toast', { detail: 'finding captured locally · pending HERMES-ORCH post' }));
      Router.go('review');
    })();
  }

  /* ---------------- 6) GOAL / RUN DETAIL ---------------- */
  async function screenGoal(main) {
    main.appendChild(el('div', { class: 'section' }, [
      el('h2', null, 'Goal / Run detail'),
      el('p', { class: 'lede muted' }, 'Pick an issue from a product repo to view its full body, comments, and downstream runs. Composition-A reads public GitHub and the local kanban DB (via hermes CLI on host).')
    ]));
    const wrap = el('div');
    wrap.appendChild(makeSkeleton(1));
    main.appendChild(wrap);
    const params = new URLSearchParams(root.location.hash.replace(/^#\/goal\?/, '').replace(/^#\/goal/, ''));
    let repo = params.get('repo'), num = params.get('n');
    if (!repo || !num) {
      // pick first open as fallback
      const iav = await Data.listOpenIssues(PRODUCT_REPOS['IA-VISION'], 1);
      const sui = await Data.listOpenIssues(PRODUCT_REPOS['SUINI'], 1);
      if (iav && iav[0]) { repo = PRODUCT_REPOS['IA-VISION']; num = iav[0].goal_id; }
      else if (sui && sui[0]) { repo = PRODUCT_REPOS['SUINI']; num = sui[0].goal_id; }
    }
    if (!repo || !num) {
      wrap.innerHTML = '';
      wrap.appendChild(el('div', { class: 'empty' }, 'no goals available via public GitHub REST — open Mission Control first'));
      return;
    }
    const goal = await Data.getIssue(repo, Number(num));
    wrap.innerHTML = '';
    if (!goal) { wrap.appendChild(el('div', { class: 'empty' }, 'goal not found in public REST')); return; }
    wrap.appendChild(el('div', { class: 'card' }, [
      el('h3', null, '#' + goal.goal_id + ' · ' + goal.title),
      el('div', { class: 'row' }, [
        badge(repo),
        badge(goal.state, goal.state === 'open' ? 'good' : ''),
        ...goal.labels.map((l) => badge(l, l === 'hermes-work-order' ? 'accent0' : ''))
      ]),
      el('div', { class: 'mono', style: 'margin-top:10px;color:var(--text-1);white-space:pre-wrap;' }, goal.body || '(no body)')
    ]));
    if (goal.human_go_required) {
      wrap.appendChild(el('div', { class: 'card is-decision' }, [
        el('h3', null, 'requires HUMAN_GO'),
        el('p', { class: 'muted' }, 'See the Inbox screen for the decision card.')
      ]));
    }
  }

  /* ---------------- 7) PR / REVIEW LAB ---------------- */
  async function screenPRLab(main) {
    main.appendChild(el('div', { class: 'section' }, [
      el('h2', null, 'PR / Review Lab'),
      el('p', { class: 'lede muted' }, 'Diff summary + CI status + targeted tests + visual captures for the selected PR. V0 ships the public GitHub REST surface; richer agent-side review details require Hermes API.')
    ]));
    const wrap = el('div', { class: 'wo-list' });
    main.appendChild(wrap);
    wrap.appendChild(makeSkeleton(4));
    const [iavPr, suPr] = await Promise.all([
      Data.listOpenPulls(PRODUCT_REPOS['IA-VISION'], 6),
      Data.listOpenPulls(PRODUCT_REPOS['SUINI'], 6)
    ]);
    wrap.innerHTML = '';
    [...iavPr, ...suPr].forEach((p) => wrap.appendChild(renderPullCard(p.url.split('/')[4], p, true)));
    if ((iavPr.length + suPr.length) === 0) {
      wrap.appendChild(el('div', { class: 'empty' }, 'no open PRs reported by public GitHub REST'));
    }
  }

  /* ---------------- 8) EVIDENCE TIMELINE ---------------- */
  async function screenEvidence(main) {
    main.appendChild(el('div', { class: 'section' }, [
      el('h2', null, 'Evidence Timeline'),
      el('p', { class: 'lede muted' }, 'Stream of events correlated across GitHub commits, kanban transitions, and VisualReviewFinding captures. Filterable by product.')
    ]));
    const evWrap = el('div', { class: 'wo-list' });
    main.appendChild(evWrap);
    evWrap.appendChild(makeSkeleton(3));

    const events = [];
    const [iavC, suiC] = await Promise.all([
      Data.listRecentCommits(PRODUCT_REPOS['IA-VISION'], 6),
      Data.listRecentCommits(PRODUCT_REPOS['SUINI'], 6)
    ]);
    iavC.forEach((c) => events.push({ ts: c.ts, kind: 'github.commit', product: 'IA-VISION', text: c.message, url: c.url, sha: c.short_sha }));
    suiC.forEach((c) => events.push({ ts: c.ts, kind: 'github.commit', product: 'SUINI', text: c.message, url: c.url, sha: c.short_sha }));

    const findings = await Data.listFindings();
    findings.forEach((f) => events.push({ ts: f.created_at, kind: 'control.finding', product: f.product_kind, text: f.summary || f.annotation, finding_id: f.evidence_id, result: f.result }));

    events.sort((a, b) => (b.ts || '').localeCompare(a.ts || ''));
    evWrap.innerHTML = '';
    if (events.length === 0) evWrap.appendChild(el('div', { class: 'empty' }, 'no events yet'));
    events.forEach((ev) => {
      const card = el('div', { class: 'wo-card' });
      card.appendChild(el('div', { class: 'wo-title' }, ev.text));
      card.appendChild(el('div', { class: 'wo-repo' }, [
        badge(ev.kind, 'info'), ' ',
        badge(ev.product, ev.product === 'IA-VISION' ? 'accent0' : 'accent2'), ' ',
        el('span', null, fmtDate(ev.ts))
      ]));
      if (ev.url) card.appendChild(el('div', { class: 'wo-actions' }, [
        el('a', { class: 'btn', href: ev.url, target: '_blank', rel: 'noopener' }, 'open')
      ]));
      evWrap.appendChild(card);
    });
  }

  /* ---------------- 9) HUMAN-GO INBOX ---------------- */
  async function screenHumanGo(main) {
    main.appendChild(el('div', { class: 'section' }, [
      el('h2', null, 'HUMAN-GO inbox'),
      el('p', { class: 'lede muted' }, 'Decisions that require David. Filtered from open product issues. Approve / reject triggers a local durable record; cross-product POST is gated.')
    ]));
    const list = el('div', { class: 'wo-list' });
    main.appendChild(list);
    list.appendChild(makeSkeleton(3));
    list.innerHTML = '';
    const items = await collectHumanGoItems();
    if (!items.length) {
      list.appendChild(el('div', { class: 'empty' }, 'no HUMAN-GO items reported by public GitHub REST'));
      return;
    }
    items.forEach((it) => list.appendChild(renderHumanGoCard(it)));
    if (main.children.length > 1) main.appendChild(el('p', { class: 'muted', style: 'margin-top:8px;' }, [
      'Reproducible idempotency: every approve/reject records a unique decision_id; refresh will not duplicate the action.'
    ]));
  }

  async function renderHumanGoList(main, replace) {
    const list = el('div', { class: 'wo-list' });
    main.appendChild(list);
    const items = await collectHumanGoItems();
    if (!items.length) list.appendChild(el('div', { class: 'empty' }, 'no HUMAN-GO items right now'));
    items.forEach((it) => list.appendChild(renderHumanGoCard(it)));
    return list;
  }

  async function collectHumanGoItems() {
    const out = [];
    for (const slug of [PRODUCT_REPOS['IA-VISION'], PRODUCT_REPOS['SUINI']]) {
      const issues = await Data.listOpenIssues(slug, 25);
      issues.filter((i) => i.human_go_required).forEach((i) => out.push(Object.assign({}, i, { repoSlug: slug })));
    }
    return out;
  }

  function renderHumanGoCard(it) {
    const card = el('div', { class: 'wo-card is-decision' });
    card.appendChild(el('div', { class: 'wo-title' }, [
      el('a', { href: it.url, target: '_blank', rel: 'noopener' }, '#' + it.goal_id + ' · ' + it.title)
    ]));
    card.appendChild(el('div', { class: 'wo-repo' }, [
      badge(it.repoSlug.split('/')[1] || it.repoSlug), ' · ', fmtDate(it.updated_at)
    ]));
    card.appendChild(el('div', { class: 'wo-actions' }, [
      el('button', { class: 'btn btn-decision', onclick: () => recordHumanGo(it, 'approved') }, 'Approve'),
      el('button', { class: 'btn', onclick: () => recordHumanGo(it, 'rejected') }, 'Reject'),
      el('button', { class: 'btn', onclick: () => recordHumanGo(it, 'deferred') }, 'Defer'),
      el('a', { class: 'btn', href: it.url, target: '_blank', rel: 'noopener' }, 'View on GitHub')
    ]));
    return card;
  }

  async function recordHumanGo(it, action) {
    const idemKey = 'humango:' + it.goal_id + ':' + action;
    const cached = await IDB.idemGet(idemKey);
    if (cached && (Date.now() - cached.ts) < 60 * 60 * 1000) {
      root.dispatchEvent(new CustomEvent('tlfb:toast', { detail: 'duplicate — already ' + action + ' in the last hour' }));
      return;
    }
    const decision = {
      schema_version: 'control.humango.decision/v1',
      decision_id: IDB.uid(),
      task_id: it.goal_id,
      goal_id: it.goal_id,
      project_id: it.project_id,
      title: it.title,
      one_sentence_decision: action + ' HUMAN_GO on #' + it.goal_id,
      status: action === 'approved' ? 'approved' : (action === 'rejected' ? 'rejected' : 'deferred'),
      decided_by: 'david (local-loop)',
      decided_at: new Date().toISOString(),
      decision_note: action + ' via TrafficLab Control V0',
      idempotency_key: idemKey,
      affected: { repo: it.repoSlug, branch: 'main', pr_url: null, sha: null },
      reversible: action !== 'rejected',
      composition: 'A-readonly',
      pending_post: true,
      post_target: 'HERMES-ORCH'
    };
    await IDB.idemPut(idemKey, decision, 200);
    await IDB.set('decision:' + decision.decision_id, decision);
    Redact.safeLog('humango', { id: decision.decision_id, status: decision.status, goal: decision.goal_id });
    root.dispatchEvent(new CustomEvent('tlfb:toast', { detail: action + ' recorded locally · pending HERMES-ORCH post' }));
  }

  /* ---------------- 10) SYSTEM HEALTH ---------------- */
  async function screenHealth(main) {
    main.appendChild(el('div', { class: 'section' }, [
      el('h2', null, 'System Health'),
      el('p', { class: 'lede muted' }, 'Hermes runtime + adapter availability. Every "not enabled" surface below is a candidate for future composition-B activation (HUMAN_GO_REAL).')
    ]));
    main.appendChild(makeSkeleton(1));
    const snap = await Data.healthSnapshot();
    main.innerHTML = '';
    main.appendChild(el('div', { class: 'section' }, [
      el('h2', null, 'Snapshot'),
      el('p', { class: 'lede muted' }, 'captured ' + fmtDate(snap.captured_at))
    ]));
    const grid = el('div', { class: 'grid grid-2' });
    grid.appendChild(el('div', { class: 'card' }, [
      el('h3', null, 'Hermes runtime'),
      el('div', { class: 'meta mono' }, [
        'version: ' + snap.hermes.version,
        ' · pid: ' + snap.hermes.default_pid,
        ' · role: ' + snap.hermes.default_role,
        ' · multiplex: ' + snap.hermes.multiplex
      ].join('')),
      el('div', { class: 'row', style: 'margin-top:10px;' }, [
        badge('serve', snap.hermes.serve_running ? 'good' : 'warn'),
        badge('dashboard', snap.hermes.dashboard_running ? 'good' : 'warn'),
        badge('api_server', snap.hermes.api_server_enabled ? 'good' : 'bad'),
        badge('webhooks', snap.hermes.webhook_enabled ? 'good' : 'bad'),
        badge('mcp_servers=' + snap.hermes.mcp_servers_count, snap.hermes.mcp_servers_count > 0 ? 'good' : 'info'),
        badge('peers=' + snap.hermes.peers_count, snap.hermes.peers_count > 0 ? 'good' : 'info')
      ]),
      el('div', { class: 'muted', style: 'margin-top:8px;font-size:12px;' }, [
        'platforms live: ', snap.hermes.platforms_live.join(', ')
      ])
    ]));
    grid.appendChild(el('div', { class: 'card' }, [
      el('h3', null, 'Product state'),
      el('div', { class: 'row' }, [
        el('div', { class: 'kpi' }, [
          el('div', { class: 'kpi-label' }, 'IA-VISION head'),
          el('div', { class: 'kpi-value mono' }, (snap.products['IA-VISION'] && snap.products['IA-VISION'].remote_head_sha) ? snap.products['IA-VISION'].remote_head_sha.slice(0, 7) : '—')
        ]),
        el('div', { class: 'kpi' }, [
          el('div', { class: 'kpi-label' }, 'SUINI head'),
          el('div', { class: 'kpi-value mono' }, (snap.products['SUINI'] && snap.products['SUINI'].remote_head_sha) ? snap.products['SUINI'].remote_head_sha.slice(0, 7) : '—')
        ])
      ])
    ]));
    main.appendChild(grid);

    main.appendChild(el('div', { class: 'section' }, [
      el('h2', null, 'Hermes capability matrix (installed v0.20.6)'),
      el('p', { class: 'lede muted' }, [
        'Status legend: ', badge('available', 'good'), ' ', badge('available-not-enabled', 'warn'),
        ' ', badge('unavailable', 'bad'), '. ',
        'Enabling any capability marked ', badge('available-not-enabled', 'warn'),
        ' requires HUMAN_GO_REAL per WO §Hard boundaries.'
      ])
    ]));
    const table = el('div', { class: 'card' });
    Object.entries(snap.hermes_capabilities).forEach(([k, v]) => {
      const tone = v === 'available' ? 'good' : (v === 'available-not-enabled' ? 'warn' : 'bad');
      table.appendChild(el('div', { class: 'row' }, [
        el('div', { class: 'mono', style: 'flex: 1 1 auto; color: var(--text-1);' }, k),
        badge(v, tone)
      ]));
    });
    main.appendChild(table);

    main.appendChild(el('div', { class: 'section' }, [
      el('h2', null, 'Human authorization log'),
      el('p', { class: 'muted' }, [
        'Minimum touches needed to activate live transport (composition B):'
      ]),
      el('ol', { class: 'mono', style: 'color: var(--text-1); padding-left: 20px;' }, [
        el('li', null, 'Add API_SERVER_ENABLED=true + API_SERVER_KEY to ~/.hermes/.env (random 32+ char)'),
        el('li', null, 'Add WEBHOOK_ENABLED=true + WEBHOOK_PORT=8644 + WEBHOOK_SECRET to ~/.hermes/.env'),
        el('li', null, 'Run: hermes serve (loopback bind 127.0.0.1:9119)'),
        el('li', null, 'Add hooks.outbound: block to ~/.hermes/config.yaml listing the Control BFF URL + signing secret'),
        el('li', null, 'Restart PID 4892 to load the new platform adapters'),
        el('li', null, 'Verify: curl http://127.0.0.1:9119/v1/capabilities returns "features": {…}')
      ])
    ]));
  }

  /* ------------- toast ------------- */
  function toast(message) {
    let host = document.querySelector('.toast-host');
    if (!host) {
      host = el('div', { class: 'toast-host', style: 'position:fixed;bottom:96px;left:50%;transform:translateX(-50%);z-index:50;display:flex;flex-direction:column;gap:8px;align-items:center;' });
      document.body.appendChild(host);
    }
    const node = el('div', { class: 'card', style: 'padding:8px 14px;font-family:var(--mono);font-size:12px;background:var(--bg-2);' }, message);
    host.appendChild(node);
    setTimeout(() => { if (node.parentNode) node.parentNode.removeChild(node); }, 4000);
  }

  root.Screens = {
    home:  screenHome,
    mission: screenMission,
    iavision: screenIA,
    suini: screenSUINI,
    review: screenReview,
    goal:  screenGoal,
    prlab: screenPRLab,
    evidence: screenEvidence,
    humango: screenHumanGo,
    health:  screenHealth,
    toast
  };
})(window);
