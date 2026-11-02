'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const net = require('node:net');
const http = require('node:http');
const { startServer, loadSnapshot, originalUrl, rewriteHtml, rewriteCss } = require('./server');
const { resourceKey } = require('../../../../browser-infra/src/snapshot/interceptor');
async function freePort() {
  const s = net.createServer(); await new Promise(r => s.listen(0, '127.0.0.1', r));
  const port = s.address().port; await new Promise(r => s.close(r)); return port;
}
function snapshot() {
  const resources = new Map();
  function add(url, body, type='application/json', status=200, headers={}) {
    resources.set(resourceKey('GET', 'https://maxroll.gg' + url), {status, body:Buffer.from(body), headers:{'content-type':type, ...headers}});
  }
  add('/d4/planner/example', '<html><head></head><body>Frozen fixture</body></html>', 'text/html');
  add('/__manifest?p=x', '{"route":"captured"}');
  add('/redirect', '', 'text/plain', 302, {location:'/d4/planner/example'});
  add('/bad-redirect', '', 'text/plain', 302, {location:'https://example.invalid'});
  return {manifest:{snapshotId:'synthetic-test-only', sourceUrl:'https://maxroll.gg/d4/planner/example'}, resources};
}
test('exact captured route mapping includes router __manifest; unknown namespaces rejected', () => {
  assert.equal(originalUrl(new URL('http://127.0.0.1:6085/__manifest?p=x')), 'https://maxroll.gg/__manifest?p=x');
  assert.equal(originalUrl(new URL('http://127.0.0.1:6085/__snapshot/evil.test/path')), null);
  assert.equal(originalUrl(new URL('http://127.0.0.1:6085/__local/private')), null);
});
test('HTML maps captured origins and removes speculative/third-party scripts', () => {
  const out = rewriteHtml('<head><link rel="preconnect" href="https://evil.test"><script src="https://evil.test/track.js"></script><script integrity="abc" src="https://maxroll.gg/main.js"></script></head>', 'http://127.0.0.1:1234');
  assert(!out.includes('evil.test')); assert(!out.includes('integrity='));
  assert(out.includes('http://127.0.0.1:1234/main.js')); assert(out.indexOf('/__local/client.js') < out.indexOf('/main.js'));
});
test('compatibility mismatch fails before opening server', async () => {
  await assert.rejects(loadSnapshot({snapshotRoot:'/nonexistent', snapshotId:'unknown', manifestSha256:'0'.repeat(64)}), /Unsupported configured snapshot/);
  await assert.rejects(startServer({port:80}), /Unprivileged port/);
});
test('HTTP replay, no proxy fallback, POST/Host protection, conflict and cleanup', async () => {
  const port = await freePort(); const running = await startServer({port}, {snapshot:snapshot()});
  const base = `http://127.0.0.1:${port}`;
  try {
    assert.equal(running.server.address().address, '127.0.0.1');
    const root = await fetch(base); assert.match(await root.text(), /sandbox=/);
    assert.match(root.headers.get('content-security-policy'), /connect-src 'self'/);
    assert.equal((await fetch(base+'/__manifest?p=x')).status, 200);
    assert.equal((await fetch(base+'/__manifest?p=other')).status, 404);
    assert.equal((await fetch(base+'/__snapshot/evil.test/resource')).status, 404);
    assert.equal((await fetch(base+'/redirect', {redirect:'manual'})).headers.get('location'), base+'/d4/planner/example');
    assert.equal((await fetch(base+'/bad-redirect', {redirect:'manual'})).status, 404);
    assert.equal((await fetch(base+'/anything', {method:'POST', headers:{Origin:base}})).status, 405);
    assert.equal((await fetch(base+'/anything', {method:'POST', headers:{Origin:'https://maxroll.gg'}})).status, 403);
    assert.equal(await new Promise((resolve, reject) => { http.get(base, {headers:{Host:'evil.test'}}, r => { r.resume(); resolve(r.statusCode); }).on('error', reject); }), 403);
    assert.equal((await fetch(base, {headers:{'Sec-Fetch-Site':'cross-site'}})).status, 403);
    assert.equal((await fetch(base+'/__local/report', {method:'POST',headers:{Origin:base},body:JSON.stringify({kind:'test',url:'https://example.invalid/path?secret=hidden'})})).status, 204);
    const blockedBefore = (await (await fetch(base+'/__local/diagnostics')).json()).blocked;
    await fetch(base+'/__local/report', {method:'POST',headers:{Origin:base},body:JSON.stringify({kind:'JS_ERROR',session:'test-session',url:base+'/main.js?token=hidden',detail:{message:'Synthetic startup failure',line:7}})});
    const diag = await (await fetch(base+'/__local/diagnostics')).json();
    assert.equal(diag.blocked, blockedBefore, 'Runtime errors are separate from network blocks');
    assert.equal(diag.clientEvents[0].kind, 'JS_ERROR');
    assert.equal(diag.clientEvents[0].session, 'test-session');
    assert.equal(diag.clientEvents[0].detail.line, 7);
    assert(!JSON.stringify(diag.clientEvents).includes('token='));
    assert.equal((await fetch(base+'/__local/shell.js')).status, 200);
    assert(diag.missing>=3); assert(!JSON.stringify(diag).includes('secret'));
    // SSH forwarding may use a different client-side port: rewritten URLs use that Host.
    const forwarded = await fetch(base+'/d4/planner/example', {headers:{Host:'127.0.0.1:6095'}});
    assert.match(await forwarded.text(), /__local\/client.js/);
    await assert.rejects(startServer({port}, {snapshot:snapshot()}), {code:'EADDRINUSE'});
    assert.equal((await fetch(base)).status, 200, 'Conflict did not stop existing server');
  } finally { await running.close(); }
  const next = net.createServer(); await new Promise((r,j)=>next.once('error',j).listen(port,'127.0.0.1',r));
  await new Promise(r=>next.close(r));
});

test('stylesheet URLs retain source origin, parent path, query and root semantics', () => {
  const css = '@import"../theme.css?v=1"; a{background:url(/images/icon.webp);border-image:url(../border.png) 5;mask:url(data:image/svg+xml;base64,AA==)}';
  const result = rewriteCss(css, 'https://assets-ng.maxroll.gg/d4-tools/css/main.css', 'http://127.0.0.1:6085');
  assert(result.includes('/__snapshot/assets-ng.maxroll.gg/d4-tools/theme.css?v=1'));
  assert(result.includes('/__snapshot/assets-ng.maxroll.gg/images/icon.webp'));
  assert(result.includes('/__snapshot/assets-ng.maxroll.gg/d4-tools/border.png'));
  assert(result.includes('data:image/svg+xml;base64,AA=='));
});
