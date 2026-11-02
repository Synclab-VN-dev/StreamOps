/* Runs before captured scripts. CSP remains the enforcement layer for requests
 * that bypass these compatibility wrappers (CSS, module loading, DOM attributes). */
(() => {
  'use strict';
  const origin = location.origin;
  const hosts = new Set(['maxroll.gg', 'assets-ng.maxroll.gg', 'planners.maxroll.gg']);
  const nativeFetch = window.fetch.bind(window);
  const report = (kind, url) => {
    let safe = String(url);
    try { const u = new URL(safe, location.href); safe = u.origin + u.pathname; } catch { safe = 'invalid-url'; }
    nativeFetch('/__local/report', { method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ kind, url: safe.slice(0, 300) }) }).catch(() => {});
  };
  function map(value) {
    const u = new URL(value, location.href);
    if (u.origin === origin) return u.href;
    // The frozen UI selects planners-test when location.hostname is localhost.
    // Both spellings resolve to the SAME captured production response, never a network fallback.
    if (u.hostname === 'planners-test.maxroll.gg') u.hostname = 'planners.maxroll.gg';
    if (u.protocol === 'https:' && !u.username && !u.password && hosts.has(u.host)) {
      return origin + (u.host === 'maxroll.gg' ? '' : '/__snapshot/' + u.host) + u.pathname + u.search + u.hash;
    }
    report('BLOCKED_EXTERNAL', u.href);
    throw new TypeError('External network disabled by local snapshot replay');
  }
  window.fetch = (input, init) => {
    try {
      if (input instanceof Request) return nativeFetch(new Request(map(input.url), input), init);
      return nativeFetch(map(input), init);
    } catch (error) { return Promise.reject(error); }
  };
  const open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url, ...rest) { return open.call(this, method, map(url), ...rest); };
  navigator.sendBeacon = (url) => { report('BLOCKED_BEACON', url); return false; };
  for (const name of ['WebSocket', 'EventSource', 'Worker', 'SharedWorker', 'RTCPeerConnection', 'webkitRTCPeerConnection']) {
    if (name in window) Object.defineProperty(window, name, { configurable: false, writable: false,
      value: class { constructor() { report('BLOCKED_' + name, 'disabled'); throw new Error(name + ' disabled in local replay'); } } });
  }
  if (navigator.serviceWorker) {
    navigator.serviceWorker.register = () => Promise.reject(new Error('Service workers disabled in local replay'));
  }
  window.open = (url) => { report('BLOCKED_POPUP', url); return null; };
  document.addEventListener('securitypolicyviolation', event => report('CSP_' + event.effectiveDirective, event.blockedURI));
  for (const event of ['click', 'auxclick', 'submit']) document.addEventListener(event, e => {
    const element = event === 'submit' ? e.target : e.target.closest?.('a');
    if (!element) return;
    const value = event === 'submit' ? element.action : element.href;
    try {
      const mapped = map(value);
      if (event === 'submit') element.action = mapped;
      else { element.href = mapped; element.removeAttribute('target'); element.removeAttribute('ping'); }
    } catch { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);
})();
