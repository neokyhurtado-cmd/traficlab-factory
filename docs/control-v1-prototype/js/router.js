/* router.js — minimal hash-based screen router */
(function (root) {
  'use strict';

  const handlers = new Map();
  let current = null;

  function on(screen, fn) { handlers.set(screen, fn); }

  function start(initial) {
    function render() {
      const hash = (root.location.hash || '').replace(/^#\/?/, '') || initial || 'home';
      const fn = handlers.get(hash) || handlers.get(initial || 'home');
      const main = document.querySelector('.app-main');
      if (!main) return;
      main.innerHTML = '';
      main.dataset.screen = hash;
      // mark nav
      document.querySelectorAll('.nav-item').forEach((b) => {
        if (b.dataset.screen === hash) b.setAttribute('aria-current', 'page');
        else b.removeAttribute('aria-current');
      });
      current = hash;
      Promise.resolve(fn ? fn(main) : '').catch((e) => {
        main.innerHTML = '<div class="error">screen error: ' + Redact.redact(String(e)) + '</div>';
      });
    }
    root.addEventListener('hashchange', render);
    if (!root.location.hash) root.location.hash = '#/' + (initial || 'home');
    render();
  }

  function go(screen) {
    root.location.hash = '#/' + screen;
  }

  function currentScreen() { return current; }

  root.Router = { on, start, go, currentScreen };
})(window);
