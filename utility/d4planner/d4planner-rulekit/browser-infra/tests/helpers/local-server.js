'use strict';

const http = require('http');

async function startLocalServer() {
  const requests = [];
  const server = http.createServer((request, response) => {
    requests.push({ method: request.method, url: request.url });
    response.setHeader('content-type', 'text/html; charset=utf-8');
    response.setHeader('cache-control', 'no-store');
    if (request.url === '/generic') {
      response.end('<!doctype html><title>fixture</title><h1 id="value">generic consumer</h1>');
      return;
    }
    if (request.url === '/state') {
      response.end('<!doctype html><title>state</title><p id="ready">ready</p>');
      return;
    }
    response.statusCode = 404;
    response.end('<!doctype html><title>not found</title>');
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  return {
    origin: `http://127.0.0.1:${address.port}`,
    requests,
    close: () => new Promise((resolve, reject) =>
      server.close(error => error ? reject(error) : resolve())),
  };
}

module.exports = { startLocalServer };
