/* data.js — composition-A data layer
 *
 * Sources:
 *   - GitHub REST public API (issues, pulls, commits, single resource).
 *     Used unauthenticated for read paths. For private data (rare; only when
 *     David grants the Control an explicit anonymous-readable view) we fall
 *     back to a /api/bridge/document?resource=... call.
 *   - Local VisualReviewFinding evidence dir (browser localStorage).
 *   - Static HERMES_INSTALLED_VERSION + capability matrix (encoded below).
 *
 * Idempotent polling cache via ETag/If-None-Match. SSE-style resume via the
 * `poll:<url>` cache (no Hermes API server available — polling only for V0).
 *
 * IMPORTANT: this code NEVER sends any Authorization header. The browser
 * never holds a key. Public GitHub REST is what's used; for any private
 * resource the request is rejected with a clear error asking the user to
 * dispatch from HERMES-ORCH.
 */
(function (root) {
  'use strict';

  const GH = 'https://api.github.com';
  const PRODUCT_REPOS = {
    'IA-VISION': 'neokyhurtado-cmd/IA-VISION',
    'SUINI':     'neokyhurtado-cmd/suini',
    'FACTORY':   'neokyhurtado-cmd/traficlab-factory'
  };

  // Static snapshot of Hermes v0.20.6 capability matrix derived from the
  // installed docs at $LOCALAPPDATA/hermes/hermes-agent/website/docs/.
  // Read-only; reflects the *installed* state, not the desired state.
  const HERMES = {
    installed_version: 'v0.20.6 (2026.8.27)',
    installed_path: 'C:\\Users\\david\\AppData\\Local\\hermes\\hermes-agent',
    serve_running: false,
    dashboard_running: false,
    api_server_enabled: false,
    webhook_enabled: false,
    mcp_servers_count: 0,
    peers_count: 0,
    hooks_count: 0,
    platforms_live: ['telegram', 'discord', 'whatsapp'],
    capabilities: {
      chat_completions: 'available-not-enabled',
      responses_api: 'available-not-enabled',
      run_submission: 'available-not-enabled',
      run_events_sse: 'available-not-enabled',
      run_stop: 'available-not-enabled',
      capabilities_endpoint: 'available-not-enabled',
      mcp_serve: 'available-not-enabled',
      acp: 'available',
      webhooks: 'available-not-enabled',
      outbound_hooks: 'available-not-enabled',
      peer_dm: 'available-not-enabled',
      peer_run: 'available-not-enabled',
      gateway_hooks: 'available-not-enabled',
      web_dashboard: 'available-not-enabled',
      serve_backend: 'available-not-enabled'
    }
  };

  // Default multiplex runtime owner (PID 4892 confirmed in M0).
  const RUNTIME = {
    default_pid: 4892,
    default_role: 'multiplex master + telegram owner + kanban dispatcher + cron scheduler + notifier',
    multiplex: true,
    orchestrator_running: false,
    suini_running: false,
    iavision_running: false
  };

  /** Lightweight HTTP fetch with timeout, ETag cache, and redaction-safe
   *  error wrapping. NEVER sends credentials. */
  async function fetchGH(path, opts) {
    opts = opts || {};
    const cacheKey = 'poll:' + path;
    const cached = await IDB.get(cacheKey);
    const headers = { 'Accept': 'application/vnd.github+json' };
    if (cached && cached.etag && opts.useCache !== false) {
      headers['If-None-Match'] = cached.etag;
    }
    const ctl = new AbortController();
    const tmo = setTimeout(() => ctl.abort(), opts.timeoutMs || 8000);
    try {
      const res = await fetch(GH + path, { headers, signal: ctl.signal, credentials: 'omit' });
      if (res.status === 304 && cached) {
        return { notModified: true, etag: cached.etag, body: cached.body, ts: cached.ts };
      }
      if (res.status === 404) {
        // Public anonymous endpoint — private resource. Caller decides fallback.
        return { error: 'NOT_FOUND_PUBLIC', status: 404 };
      }
      if (!res.ok) {
        return { error: 'GITHUB_' + res.status, status: res.status };
      }
      const etag = res.headers.get('etag');
      const data = await res.json();
      const out = { body: data, etag, ts: Date.now() };
      if (etag) await IDB.set(cacheKey, out);
      return out;
    } catch (e) {
      return { error: 'NETWORK', message: String(e) };
    } finally {
      clearTimeout(tmo);
    }
  }

  async function repoSummary(repoSlug) {
    const r = await fetchGH('/repos/' + repoSlug);
    if (r.error) return { error: r.error };
    return {
      project_id: projectFromRepo(repoSlug),
      repo: repoSlug,
      default_branch: r.body.default_branch,
      remote_head_sha: (r.body && '') || (await latestCommitSha(repoSlug)),
      open_issues: r.body.open_issues_count,
      pushed_at: r.body.pushed_at,
      description: r.body.description
    };
  }

  async function latestCommitSha(repoSlug, branch) {
    const b = branch || 'main';
    const r = await fetchGH('/repos/' + repoSlug + '/commits/' + b);
    if (r.error) return null;
    return r.body.sha;
  }

  function projectFromRepo(slug) {
    if (slug === PRODUCT_REPOS['IA-VISION']) return 'IA-VISION';
    if (slug === PRODUCT_REPOS['SUINI'])     return 'SUINI';
    if (slug === PRODUCT_REPOS['FACTORY'])   return 'TRAFFICLAB-CONTROL';
    return slug;
  }

  async function listOpenIssues(repoSlug, limit) {
    const lim = limit || 12;
    const r = await fetchGH('/repos/' + repoSlug + '/issues?state=open&per_page=' + lim);
    if (r.error) return [];
    // filter out pull requests (GitHub returns PRs here too)
    return (r.body || []).filter((i) => !i.pull_request).map(toGoalSummary);
  }

  async function listOpenPulls(repoSlug, limit) {
    const lim = limit || 12;
    const r = await fetchGH('/repos/' + repoSlug + '/pulls?state=open&per_page=' + lim);
    if (r.error) return [];
    return (r.body || []).map(toPullSummary);
  }

  async function listRecentCommits(repoSlug, limit) {
    const lim = limit || 8;
    const r = await fetchGH('/repos/' + repoSlug + '/commits?per_page=' + lim);
    if (r.error) return [];
    return r.body.map(toCommitSummary);
  }

  async function getIssue(repoSlug, number) {
    const r = await fetchGH('/repos/' + repoSlug + '/issues/' + number);
    if (r.error) return null;
    return toGoalSummary(r.body, true);
  }

  async function getPull(repoSlug, number) {
    const r = await fetchGH('/repos/' + repoSlug + '/pulls/' + number);
    if (r.error) return null;
    return toPullSummary(r.body, true);
  }

  /** Build a VisionFinding from a screenshot/canvas + identity context. */
  async function saveFinding(finding) {
    finding.evidence_id = finding.evidence_id || IDB.uid();
    finding.schema_version = 'control.visual.finding/v1';
    finding.created_at = finding.created_at || new Date().toISOString();
    await IDB.set('finding:' + finding.evidence_id, finding);
    return finding;
  }

  async function listFindings() {
    const all = [];
    for (let i = 0; i < root.localStorage.length; i++) {
      const rawKey = root.localStorage.key(i);
      if (rawKey && rawKey.startsWith('tlfb:v0:finding:')) {
        const v = await IDB.get(rawKey.replace('tlfb:v0:', ''));
        if (v) all.push(v);
      }
    }
    return all.sort((a, b) => b.created_at.localeCompare(a.created_at));
  }

  function toGoalSummary(i, full) {
    return {
      schema_version: 'control.goal.summary/v1',
      goal_id: String(i.number),
      project_id: projectFromRepo((i.repository_url || '').split('/repos/')[1] || ''),
      title: i.title,
      body: full ? (i.body || '') : ((i.body || '').slice(0, 480)),
      state: i.state,
      labels: (i.labels || []).map((l) => l.name || l),
      assignees: (i.assignees || []).map((a) => a.login),
      milestone: i.milestone ? i.milestone.title : null,
      url: i.html_url,
      created_at: i.created_at,
      updated_at: i.updated_at,
      kind: (i.labels || []).some((l) => (l.name || l) === 'hermes-work-order') ? 'MACRO_GOAL' : 'PRODUCT_GOAL',
      macro_parent_id: null,
      human_go_required: ((i.labels || []).some((l) => /humango|human-go/i.test(l.name || l))) || /HUMAN_GO/.test(i.title || ''),
      blocked_by_external: /BLOCKED/i.test(i.title || ''),
      evidence_refs: [],
      comments: full ? i.comments : undefined
    };
  }

  function toPullSummary(p, full) {
    return {
      schema_version: 'control.pr/v1',
      goal_id: String(p.number),
      project_id: projectFromRepo((p.base && p.base.repo && p.base.repo.full_name) || ''),
      title: p.title,
      state: p.state + (p.merged ? '(merged)' : ''),
      url: p.html_url,
      branch: p.head ? p.head.ref : null,
      base: p.base ? p.base.ref : null,
      head_sha: p.head ? p.head.sha : null,
      created_at: p.created_at,
      updated_at: p.updated_at,
      draft: p.draft || false,
      body: full ? (p.body || '') : ((p.body || '').slice(0, 240))
    };
  }

  function toCommitSummary(c) {
    return {
      sha: c.sha,
      short_sha: (c.sha || '').slice(0, 7),
      message: (c.commit && c.commit.message) ? c.commit.message.split('\n')[0] : '',
      author: c.commit && c.commit.author ? c.commit.author.name : '',
      url: c.html_url,
      ts: c.commit && c.commit.author ? c.commit.author.date : ''
    };
  }

  async function healthSnapshot() {
    const iav = await repoSummary(PRODUCT_REPOS['IA-VISION']);
    const suini = await repoSummary(PRODUCT_REPOS['SUINI']);
    return {
      schema_version: 'control.health.snapshot/v1',
      captured_at: new Date().toISOString(),
      hermes: {
        version: HERMES.installed_version,
        install_dir: HERMES.installed_path,
        default_pid: RUNTIME.default_pid,
        default_role: RUNTIME.default_role,
        multiplex: RUNTIME.multiplex,
        serve_running: HERMES.serve_running,
        dashboard_running: HERMES.dashboard_running,
        api_server_enabled: HERMES.api_server_enabled,
        webhook_enabled: HERMES.webhook_enabled,
        mcp_servers_count: HERMES.mcp_servers_count,
        peers_count: HERMES.peers_count,
        platforms_live: HERMES.platforms_live.slice()
      },
      products: {
        'IA-VISION': iav && !iav.error ? { remote_head_sha: iav.remote_head_sha, open_issues: iav.open_issues, pushed_at: iav.pushed_at, error: null } : { error: (iav && iav.error) || 'unknown' },
        'SUINI':     suini && !suini.error ? { remote_head_sha: suini.remote_head_sha, open_issues: suini.open_issues, pushed_at: suini.pushed_at, error: null } : { error: (suini && suini.error) || 'unknown' }
      },
      hermes_capabilities: HERMES.capabilities
    };
  }

  root.Data = {
    PRODUCT_REPOS,
    HERMES,
    RUNTIME,
    repoSummary, listOpenIssues, listOpenPulls, listRecentCommits,
    getIssue, getPull, saveFinding, listFindings, healthSnapshot
  };
})(window);
