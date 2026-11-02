/* Parent-side visibility diagnostics still work when the child fails to execute. */
(() => {
  'use strict';
  const frame = document.querySelector('iframe');
  let last = '', ticks = 0;
  const inspect = () => {
    const box = frame.getBoundingClientRect();
    let detail = { width: Math.round(box.width), height: Math.round(box.height),
      viewportWidth: innerWidth, viewportHeight: innerHeight, userAgent: navigator.userAgent.slice(0, 250) };
    try {
      const doc = frame.contentDocument;
      const button = doc && [...doc.querySelectorAll('button')].find(e => e.textContent.trim() === 'New Profile');
      detail = { ...detail, readyState: doc?.readyState || 'no-document',
        newProfile: !!button, buttonBox: button?.getBoundingClientRect().toJSON(),
        bodyChildren: doc?.body?.children.length || 0 };
    } catch { detail.frameAccess = 'denied'; }
    const state = JSON.stringify(detail);
    if (state !== last) {
      last = state;
      fetch('/__local/report', { method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({kind:'FRAME_STATE', session:frame.name, url:location.href, detail}) }).catch(() => {});
    }
  };
  frame.addEventListener('load', inspect);
  window.addEventListener('resize', inspect);
  const timer = setInterval(() => { inspect(); if (++ticks >= 30) clearInterval(timer); }, 1000);
  const update = () => fetch('/__local/diagnostics').then(r => r.json()).then(d => {
    document.getElementById('status').textContent = d.missing + ' missing / ' + d.blocked + ' blocked (server totals)';
  }).catch(() => {});
  update(); setInterval(update, 3000);
})();
