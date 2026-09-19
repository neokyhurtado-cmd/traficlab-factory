/* app.js — bootstrap */
(function (root) {
  'use strict';

  function $(sel) { return document.querySelector(sel); }

  function bindNav() {
    document.querySelectorAll('.nav-item').forEach((b) => {
      b.addEventListener('click', () => {
        const s = b.dataset.screen;
        if (s) Router.go(s);
      });
    });
  }

  function setStatus(state, text) {
    const dot = document.querySelector('#header-status .dot');
    const t = document.getElementById('status-text');
    if (!dot || !t) return;
    dot.classList.remove('dot-running', 'dot-warn', 'dot-bad', 'dot-idle');
    if (state === 'ok') dot.classList.add('dot-running');
    else if (state === 'warn') dot.classList.add('dot-warn');
    else if (state === 'err') dot.classList.add('dot-bad');
    else dot.classList.add('dot-idle');
    t.textContent = text;
  }

  function tickFreshness() {
    const f = document.getElementById('footer-freshness');
    if (!f) return;
    const ts = window.__lastFetchTs || null;
    if (!ts) { f.textContent = 'freshness: —'; }
    else { f.textContent = 'freshness: ' + Math.max(0, Math.round((Date.now() - ts) / 1000)) + 's ago'; }
  }

  async function ping() {
    try {
      const r = await fetch('https://api.github.com/', { method: 'HEAD', mode: 'cors', cache: 'no-store', credentials: 'omit' });
      setStatus(r.ok ? 'ok' : 'warn', r.ok ? 'github reachable' : ('github http ' + r.status));
    } catch (e) {
      setStatus('err', 'github unreachable (composition-A is offline)');
    }
    window.__lastFetchTs = Date.now();
    tickFreshness();
  }

  function installToasts() {
    root.addEventListener('tlfb:toast', (e) => { if (e && e.detail && root.Screens) root.Screens.toast(e.detail); });
  }

  function refreshTickLoop() {
    ping();
    setInterval(() => { tickFreshness(); }, 5000);
  }

  document.addEventListener('DOMContentLoaded', () => {
    bindNav();
    installToasts();
    Router.on('home', Screens.home);
    Router.on('mission', Screens.mission);
    Router.on('iavision', Screens.iavision);
    Router.on('suini', Screens.suini);
    Router.on('review', Screens.review);
    Router.on('goal', Screens.goal);
    Router.on('prlab', Screens.prlab);
    Router.on('evidence', Screens.evidence);
    Router.on('humango', Screens.humango);
    Router.on('health', Screens.health);
    Router.start('home');
    refreshTickLoop();
  });
})(window);
