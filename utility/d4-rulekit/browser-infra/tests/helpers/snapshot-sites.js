'use strict';

const http = require('node:http');
const crypto = require('node:crypto');

const pixel = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  'base64');

async function listen(handler) {
  const requests = [];
  const server = http.createServer((request, response) => {
    requests.push({ method: request.method, url: request.url, headers: request.headers });
    handler(request, response);
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const origin = `http://127.0.0.1:${server.address().port}`;
  return {
    origin,
    requests,
    reset: () => { requests.length = 0; },
    close: () => new Promise((resolve, reject) =>
      server.close(error => error ? reject(error) : resolve())),
  };
}

async function startWebSocketCounter() {
  const attempts = [];
  const server = http.createServer((_request, response) => {
    response.writeHead(426);
    response.end('upgrade required');
  });
  server.on('upgrade', (request, socket) => {
    attempts.push({ url: request.url });
    const accept = crypto.createHash('sha1')
      .update(`${request.headers['sec-websocket-key']}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`)
      .digest('base64');
    socket.write('HTTP/1.1 101 Switching Protocols\r\n'
      + 'Upgrade: websocket\r\nConnection: Upgrade\r\n'
      + `Sec-WebSocket-Accept: ${accept}\r\n\r\n`);
    setTimeout(() => socket.destroy(), 100);
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  return {
    url: `ws://127.0.0.1:${server.address().port}/socket`,
    attempts,
    close: () => new Promise((resolve, reject) =>
      server.close(error => error ? reject(error) : resolve())),
  };
}

function response(response, status, type, body, extra = {}) {
  response.writeHead(status, {
    'content-type': type,
    'cache-control': 'no-store',
    ...extra,
  });
  response.end(body);
}

async function startSnapshotSites() {
  const websocket = await startWebSocketCounter();
  const asset = await listen((request, res) => {
    if (request.url === '/lazy.png') return response(res, 200, 'image/png', pixel);
    return response(res, 404, 'text/plain', 'missing');
  });
  const staticSite = await listen((request, res) => {
    if (request.url === '/') return response(res, 200, 'text/html; charset=utf-8',
      '<!doctype html><title>Static A</title><link rel="stylesheet" href="/style.css"><img id="pixel" src="/pixel.png"><h1 id="result">loading</h1><script src="/app.js"></script>');
    if (request.url === '/style.css') return response(res, 200, 'text/css',
      '@font-face{font-family:test;src:url(/font.woff2)}body{color:rgb(1,2,3);font-family:test}');
    if (request.url === '/font.woff2') return response(res, 200, 'font/woff2', Buffer.from('fixture-font'));
    if (request.url === '/pixel.png') return response(res, 200, 'image/png', pixel);
    if (request.url === '/app.js') return response(res, 200, 'application/javascript',
      'document.querySelector("#result").textContent="static-ready";');
    if (request.url === '/sensitive') return response(res, 200, 'text/html', '<h1>sensitive</h1><script>fetch("/private",{headers:{authorization:"Bearer secret"}}).catch(()=>{});fetch("/write",{method:"POST"}).catch(()=>{});</script>', {
      'set-cookie': 'session=secret; HttpOnly', 'x-secret': 'never-store', etag: 'fixture-etag',
    });
    if (request.url === '/response-policy') return response(res, 200, 'text/html',
      '<!doctype html><title>policy</title><img src="/redirect-private"><output id="done">idle</output><script>fetch("/api/private").finally(()=>document.querySelector("#done").textContent="done")</script>');
    if (request.url === '/api/private') return response(res, 200, 'application/json',
      JSON.stringify({ access_token: 'json-secret-token', profile: { email: 'private@example.test' }, safe: 42 }));
    if (request.url === '/redirect-private') return response(res, 302, 'text/plain', 'redirect', {
      location: '/landing?campaign=public#access_token=redirect-secret-token',
    });
    if (request.url === '/landing?campaign=public') return response(res, 200, 'text/plain', 'landing');
    if (request.url === '/slow') return setTimeout(() => response(res, 200, 'text/plain', 'slow'), 1_000);
    return response(res, 404, 'text/plain', 'missing');
  });
  const spa = await listen((request, res) => {
    if (request.url === '/') return response(res, 200, 'text/html; charset=utf-8',
      '<!doctype html><title>SPA B</title><button id="load">load</button><output id="result">idle</output><script type="module" src="/main.js"></script>');
    if (request.url === '/main.js') return response(res, 200, 'application/javascript',
      'document.querySelector("#load").onclick=async()=>{const [{message},data]=await Promise.all([import("/chunk.js"),fetch("/api/data?view=full").then(r=>r.json())]);document.querySelector("#result").textContent=message+":"+data.value;history.pushState({},"","/loaded");};');
    if (request.url === '/chunk.js') return response(res, 200, 'application/javascript',
      'export const message="dynamic";');
    if (request.url === '/api/data?view=full') return response(res, 200, 'application/json',
      JSON.stringify({ value: 42 }));
    return response(res, 404, 'text/plain', 'missing');
  });
  const dynamic = await listen((request, res) => {
    if (request.url === '/') return response(res, 302, 'text/plain', 'redirect', { location: '/landing?version=1' });
    if (request.url === '/landing?version=1') return response(res, 200, 'text/html; charset=utf-8',
      `<!doctype html><title>Dynamic C</title><button id="lazy">lazy</button><output id="result">idle</output><script>navigator.serviceWorker.register('/sw.js').catch(()=>{});try{new WebSocket('ws://127.0.0.1:9/socket')}catch{window.webSocketBlocked=true}document.querySelector('#lazy').onclick=async()=>{const missing=await fetch('/missing?case=404');window.missingStatus=missing.status;window.missingBody=await missing.text();const image=new Image();image.id='lazy-image';image.onload=()=>document.querySelector('#result').textContent='lazy-ready';image.src='${asset.origin}/lazy.png';document.body.append(image);};</script>`);
    if (request.url === '/sw.js') return response(res, 200, 'application/javascript', 'self.addEventListener("fetch",()=>{});');
    if (request.url === '/worker.js') return response(res, 200, 'application/javascript',
      'self.onmessage=event=>{try{const socket=new WebSocket(event.data);socket.onerror=()=>self.postMessage("blocked");socket.onopen=()=>self.postMessage("connected")}catch{self.postMessage("blocked")}};');
    return response(res, 404, 'text/plain', 'missing');
  });
  return {
    staticSite,
    spa,
    dynamic,
    asset,
    websocket,
    close: async () => Promise.all([
      staticSite.close(), spa.close(), dynamic.close(), asset.close(), websocket.close(),
    ]),
  };
}

module.exports = { startSnapshotSites };
