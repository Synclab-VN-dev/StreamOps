#!/usr/bin/env node
'use strict';
const http = require('node:http');
const {exportBuild,importBuild,readJson}=require('./native-transfer');
const fs = require('node:fs/promises');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { FileSystemSnapshotStore } = require('../../../../browser-infra/src');
const { resourceKey } = require('../../../../browser-infra/src/snapshot/interceptor');
const { UI_ORIGINS: ORIGINS, verifyUiReceipt } = require('./ui-package');
const CSP = "default-src 'none'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; frame-src 'self'; worker-src 'none'; object-src 'none'; base-uri 'self'; form-action 'self'; manifest-src 'none'";
const FRAME_CSP = CSP + "; sandbox allow-scripts allow-same-origin allow-forms; frame-ancestors 'self'";
function mappedUrl(url, origin) {
  const u = new URL(url);
  if (!ORIGINS.includes(u.origin)) throw new Error('Uncaptured origin');
  return origin + (u.hostname === 'maxroll.gg' ? '' : '/__snapshot/' + u.hostname) + u.pathname + u.search + u.hash;
}
function originalUrl(local) {
  const match = local.pathname.match(/^\/__snapshot\/([^/]+)(\/.*)$/);
  if (match) {
    const origin = 'https://' + match[1];
    if (!ORIGINS.includes(origin) || match[1] === 'maxroll.gg') return null;
    return origin + match[2] + local.search;
  }
  if (local.pathname.startsWith('/__snapshot/') || local.pathname.startsWith('/__local/')) return null;
  return 'https://maxroll.gg' + local.pathname + local.search;
}
function rewrite(text, origin) {
  for (const source of ORIGINS) {
    const dest = mappedUrl(source + '/', origin).replace(/\/$/, '');
    text = text.replaceAll(source, dest).replaceAll(source.replaceAll('/', '\\/'), dest.replaceAll('/', '\\/'));
  }
  return text;
}
function rewriteCss(text, original, origin) {
  // A root-relative URL belongs to the source stylesheet's origin, not Maxroll's HTML origin.
  const resolve = value => {
    try { const u = new URL(value, original); return ORIGINS.includes(u.origin) ? mappedUrl(u.href, origin) : value; }
    catch { return value; }
  };
  return text.replace(/url\(\s*(["']?)([^"'()]+)\1\s*\)/g, (_, quote, value) => 'url("' + resolve(value.trim()) + '")')
    .replace(/(@import\s*)(["'])([^"']+)\2/g, (_, prefix, quote, value) => prefix + quote + resolve(value) + quote);
}
function rewriteHtml(text, origin) {
  // Remove speculative DNS/preconnect and third-party script tags before the parser can issue requests.
  text = text.replace(/<link\b[^>]*\brel=["'](?:preconnect|dns-prefetch)["'][^>]*>/gi, '');
  text = text.replace(/<script\b([^>]*\bsrc=["']([^"']+)["'][^>]*)>[\s\S]*?<\/script>/gi, (tag, attrs, src) => {
    try { const u = new URL(src, 'https://maxroll.gg'); return ORIGINS.includes(u.origin) && u.pathname !== '/js/sponsor.js' ? tag : ''; } catch { return ''; }
  });
  text = text.replace(/\s(?:integrity|nonce)=["'][^"']*["']/gi, '');
  text = rewrite(text, origin);
  return text.replace(/<head([^>]*)>/i, '<head$1><script src="/__local/client.js"></script>');
}
async function loadSnapshot(config) {
  if (!path.isAbsolute(config.snapshotRoot || '')) throw new Error('snapshotRoot must be absolute');
  if (!config.uiTrust) {
    // Backward-compatible legacy mode only. Independent UI captures never load calculation bindings.
    const { loadCatalog } = require('../../../../snapshot-management/compatibility/loader');
    const definition = loadCatalog().definitions.find(d => d.identity.snapshotId === config.snapshotId
      && d.identity.snapshotManifestSha256 === config.manifestSha256);
    if (!definition) throw new Error('Unsupported configured snapshot binding');
  }
  const store = new FileSystemSnapshotStore({ rootDir: config.snapshotRoot });
  const verified = await store.verify(config.snapshotId);
  if (verified.manifestSha256 !== config.manifestSha256) throw new Error('Snapshot digest mismatch');
  // Reuse store verification, manifest and exact method/URL resource map. No capture or HTTP client.
  const snapshot = await store.loadPackage(config.snapshotId);
  const uiVerification = config.uiTrust ? await verifyUiReceipt(config, snapshot.manifest, verified) : { status: 'LEGACY_CALCULATION_PIN' };
  if (snapshot.manifest.allowedOrigins.some(o => !ORIGINS.includes(o))) throw new Error('Unsupported replay origin');
  return { ...snapshot, uiVerification };
}
async function startServer(config, { snapshot: suppliedSnapshot } = {}) {
  if (!Number.isInteger(config.port) || config.port < 1024 || config.port > 65535) throw new Error('Unprivileged port required');
  const snapshot = suppliedSnapshot || await loadSnapshot(config);
  const client = await fs.readFile(path.join(__dirname, 'client.js'));
  const shell = await fs.readFile(path.join(__dirname, 'shell.js'));
  const clientEvents = [];
  const categories = Object.create(null);
  const recent = [];
  let missing = 0, blocked = 0, served = 0;
  function record(kind, url) {
    const u = new URL(url, 'http://127.0.0.1');
    recent.push({ kind, url: (u.origin + u.pathname).slice(0, 300) });
    if (recent.length > 100) recent.shift();
    categories[kind] = (categories[kind] || 0) + 1;
    if (kind === 'MISSING') missing++; else blocked++;
  }
  function diagnostic() { return { snapshotId: snapshot.manifest.snapshotId, manifestSha256: config.manifestSha256, uiVerification: snapshot.uiVerification, uiMode: config.uiTrust ? 'INDEPENDENT_CAPTURE' : 'LEGACY_CALCULATION_PIN', calculationStatus: 'NOT_ASSESSED', served, missing, blocked, recent, categories, clientEvents }; }
  const sourcePath = new URL(snapshot.manifest.sourceUrl).pathname;
  const server = http.createServer(async (req, res) => {
    try {
      const host = req.headers.host || '';
      if (!/^127\.0\.0\.1:\d{1,5}$/.test(host)) { res.writeHead(403); res.end('Loopback Host required'); return; }
      const origin = 'http://' + host;
      const url = new URL(req.url, origin);
      const common = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'no-referrer', 'X-DNS-Prefetch-Control': 'off',
        'Content-Security-Policy': CSP, 'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=()' };
      function send(status, body, type = 'application/json', extra = {}) {
        res.writeHead(status, { ...common, 'Content-Type': type, ...extra });
        res.end(req.method === 'HEAD' ? undefined : body);
      }
      if (req.headers['sec-fetch-site'] === 'cross-site') return send(403, '{"error":"Cross-site access disabled"}');
      if (!['GET', 'HEAD'].includes(req.method)) {
        if (req.headers.origin !== origin) return send(403, '{"error":"Same-origin POST required"}');
        if (req.method === 'POST' && ['/__local/export','/__local/import'].includes(url.pathname)) {
          if(req.headers['x-local-snapshot']!==config.manifestSha256) return send(409,JSON.stringify({error:'UI package changed. Reload local Planner before transferring JSON.'}));
          try {
            const input=await readJson(req);
            const output=url.pathname.endsWith('/export')?exportBuild(input,snapshot,config):importBuild(input,snapshot,config);
            return send(200,JSON.stringify(output), 'application/json',url.pathname.endsWith('/export')?{'Content-Disposition':'attachment; filename="maxroll-native-build.json"'}:{});
          } catch { return send(422,JSON.stringify({error:'Invalid native build, integrity or snapshot mismatch. No build was saved.'})); }
        }
        if (req.method === 'POST' && url.pathname === '/__local/report') {
          let bytes = 0, body = '';
          for await (const part of req) { bytes += part.length; if (bytes > 2048) return send(413, '{}'); body += part; }
          const event = JSON.parse(body);
          const kind = String(event.kind).slice(0, 64);
          if (['CLIENT_BOOT', 'DOM_READY', 'PAGE_SHOW', 'JS_ERROR', 'UNHANDLED_REJECTION', 'CONSOLE_ERROR', 'RESOURCE_ERROR', 'FRAME_STATE'].includes(kind)) {
            const safeUrl = new URL(String(event.url), origin);
            const entry = { time: new Date().toISOString(), kind, session: String(event.session || '').replace(/[^a-zA-Z0-9-]/g, '').slice(0, 50),
              url: safeUrl.origin + safeUrl.pathname, detail: event.detail };
            clientEvents.push(entry);
            if (clientEvents.length > 200) clientEvents.shift();
            console.log(JSON.stringify({ clientEvent: entry }));
          } else record(kind, String(event.url));
          return send(204, '');
        }
        record('BLOCKED_METHOD', url.href);
        return send(405, '{"error":"Cloud save unavailable; use local Export JSON. No request was sent online"}');
      }
      if (url.pathname === '/__local/shell.js') return send(200, Buffer.concat([Buffer.from('const LOCAL_SNAPSHOT_HASH = '+JSON.stringify(config.manifestSha256||null)+';\n'),shell]), 'application/javascript');
      if (url.pathname === '/__local/client.js') return send(200, client, 'application/javascript');
      if (url.pathname === '/__local/diagnostics') return send(200, JSON.stringify(diagnostic()));
      if (url.pathname === '/') {
        // Parent frame-src + child sandbox block navigation/popups to production.
        const html = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Local frozen Maxroll Planner</title><style>html,body{margin:0;height:100%;background:#101010;color:white;font:13px sans-serif}body{display:flex;flex-direction:column}header{min-height:36px;display:flex;flex-wrap:wrap;gap:4px;align-items:center;padding:4px 8px}iframe{border:0;width:100%;flex:1;min-height:0}a{color:#8cf}</style></head><body><header>Frozen snapshot · UI UAT · Cloud save unavailable · Native JSON download supported · <button id="export-build">Export JSON</button><label>Import JSON <input id="import-build" type="file" accept=".json,application/json"></label><span id="transfer-status" role="status"></span> · <span id="status">loading diagnostics</span> · <a href="/__local/diagnostics" target="_blank">diagnostics</a></header><iframe name="${randomUUID()}" title="Frozen Maxroll Planner" sandbox="allow-scripts allow-same-origin allow-forms" src="${sourcePath}"></iframe><script src="/__local/shell.js"></script></body></html>`;
        return send(200, html, 'text/html; charset=utf-8', { 'Content-Security-Policy': CSP + "; frame-ancestors 'none'" });
      }
      const original = originalUrl(url);
      const resource = original && snapshot.resources.get(resourceKey('GET', original));
      if (!resource) { record('MISSING', original || url.href); return send(404, '{"error":"SNAPSHOT_RESOURCE_MISSING"}'); }
      if (resource.status >= 300 && resource.status < 400 && resource.headers.location) {
        const target = new URL(resource.headers.location, original).href;
        if (!snapshot.resources.has(resourceKey('GET', target))) { record('MISSING', target); return send(404, '{}'); }
        return send(resource.status, '', 'text/plain', { Location: mappedUrl(target, origin) });
      }
      const type = resource.headers['content-type'] || 'application/octet-stream';
      let body = resource.body;
      const isHtml = type.includes('text/html');
      if (isHtml && req.headers['sec-fetch-dest'] === 'document') return send(302, '', 'text/plain', { Location: '/' });
      if (/javascript|text\/css|text\/html/.test(type)) {
        body = isHtml ? rewriteHtml(body.toString('utf8'), origin)
          : type.includes('text/css') ? rewriteCss(body.toString('utf8'), original, origin)
          : rewrite(body.toString('utf8'), origin);
      }
      served++;
      return send(resource.status, body, type, isHtml ? { 'Content-Security-Policy': FRAME_CSP } : {});
    } catch { if (!res.headersSent) res.writeHead(400); res.end('Invalid local request'); }
  });
  server.requestTimeout = 10000;
  server.headersTimeout = 10000;
  server.on('upgrade', (req, socket) => { record('BLOCKED_WEBSOCKET', req.url); socket.destroy(); });
  // Binding itself is the atomic port availability check; EADDRINUSE never kills/reuses another service.
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(config.port, '127.0.0.1', resolve); });
  return { server, diagnostics: diagnostic, close: () => new Promise(resolve => {
    server.close(resolve); server.closeAllConnections();
  }) };
}
async function main() {
  if (process.argv[2] !== '--config' || !process.argv[3]) throw new Error('Usage: node server.js --config /absolute/config.json');
  if(process.env.LOCAL_UI_OWNER_STATE){
    // Do not bind if the CLI dies between spawning us and durably recording ownership.
    let recorded=false;
    for(let i=0;i<100;i++){
      try{recorded=JSON.parse(await fs.readFile(process.env.LOCAL_UI_OWNER_STATE,'utf8')).pid===process.pid;}catch{}
      if(recorded)break;
      await new Promise(resolve=>setTimeout(resolve,20));
    }
    if(!recorded)throw Error('CLI ownership was not committed; refusing orphan listener');
  }
  const config = JSON.parse(await fs.readFile(process.argv[3], 'utf8'));
  const running = await startServer(config);
  console.log(JSON.stringify({ ready: true, pid: process.pid, url: `http://127.0.0.1:${config.port}/`, snapshotId: config.snapshotId }));
  const stop = async () => { await running.close(); console.log(JSON.stringify({ stopped: true, diagnostics: running.diagnostics() })); };
  process.once('SIGTERM', stop); process.once('SIGINT', stop);
}
if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
module.exports = { startServer, loadSnapshot, originalUrl, mappedUrl, rewrite, rewriteHtml, rewriteCss };
