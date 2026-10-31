'use strict';

const crypto = require('node:crypto');
const http = require('node:http');
const { METRIC_CATALOG, MaxrollPatchProfile } = require('../../src');

const BASE_BUILD = Object.freeze({
  class: 'Rogue', level: 50, difficulty: 'Torment I',
  equipment: { Helm: { itemId: 'runic-skullcap', modifiers: [] } },
});
const MODIFIED_BUILD = Object.freeze({
  class: 'Rogue', level: 50, difficulty: 'Torment I',
  equipment: { Helm: { itemId: 'runic-skullcap', modifiers: ['of-dampening'] } },
});

function sha256(value) { return crypto.createHash('sha256').update(value).digest('hex'); }

function runtimeScript() {
  const catalog = METRIC_CATALOG.map(metric => ({ id: metric.id, name: metric.name }));
  return Buffer.from(`'use strict';
const catalog=${JSON.stringify(catalog)};
let phase=0;
function calculate(build){
  const dampening=build.equipment.Helm.modifiers.includes('of-dampening');
  return catalog.map((metric,index)=>({id:metric.id,raw:metric.id==='maxroll.heroDetails.446'?(dampening?2822:22):index+1,display:index<34?String(metric.id==='maxroll.heroDetails.446'?(dampening?2822:22):index+1):null,unit:null}));
}
function apply(build){
  phase+=1;
  document.querySelector('[data-role=applied-build]').textContent=JSON.stringify(build);
  document.querySelector('[data-role=phase]').textContent=String(phase);
  const root=document.querySelector('[data-role=metrics]');root.textContent='';
  for(const metric of calculate(build)){const node=document.createElement('div');node.dataset.metricId=metric.id;node.dataset.raw=JSON.stringify(metric.raw);node.dataset.displayPresent=String(metric.display!==null);node.dataset.unit=metric.unit||'';node.dataset.phase=String(phase);node.textContent=metric.display||'';root.append(node)}
}
document.querySelector('[data-action=apply-build]').onclick=()=>{try{apply(JSON.parse(document.querySelector('[data-role=build-json]').value))}catch(error){document.querySelector('[data-role=error]').textContent=error.message}};
apply(${JSON.stringify(BASE_BUILD)});
document.querySelector('[data-role=ready]').textContent='ready';
`);
}

async function startRuntimeSite() {
  const script = runtimeScript();
  const assetSha256 = sha256(script);
  const requests = [];
  const server = http.createServer((request, response) => {
    requests.push(request.url);
    if (request.url === '/') {
      response.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' });
      response.end(`<!doctype html><title>Maxroll-shaped synthetic runtime</title>
<span data-runtime-version>synthetic-maxroll-runtime/1</span>
<span data-game-patch>3.2.1.73552</span>
<span data-asset-sha>${assetSha256}</span>
<span data-role=ready></span><textarea data-role=build-json></textarea>
<button data-action=apply-build>Apply</button><pre data-role=applied-build></pre>
<span data-role=phase>0</span><span data-role=error></span><section data-role=metrics></section>
<script src="/assets/runtime.js"></script>`);
      return;
    }
    if (request.url === '/assets/runtime.js') {
      response.writeHead(200, { 'content-type': 'application/javascript', 'cache-control': 'public,max-age=31536000' });
      response.end(script);
      return;
    }
    response.writeHead(404, { 'content-type': 'text/plain' }); response.end('missing');
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const origin = `http://127.0.0.1:${server.address().port}`;
  return {
    origin,
    sourceUrl: `${origin}/`,
    assetUrl: `${origin}/assets/runtime.js`,
    assetSha256,
    requests,
    resetRequests: () => { requests.length = 0; },
    close: () => new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve())),
  };
}

function createProfile(overrides = {}) {
  return new MaxrollPatchProfile({
    providerVersion: 'maxroll-provider/3.2.1.73552',
    runtimeVersion: 'synthetic-maxroll-runtime/1',
    gamePatch: '3.2.1.73552',
    snapshotId: 'maxroll-synthetic-3-2-1',
    snapshotManifestSha256: 'a'.repeat(64),
    sourceUrl: 'http://fixture.invalid/',
    assetUrl: 'http://fixture.invalid/assets/runtime.js',
    assetSha256: 'b'.repeat(64),
    metricCatalog: METRIC_CATALOG,
    provenanceSource: 'SYNTHETIC_MAXROLL_CDP_RUNTIME',
    displayProvenanceSource: 'SYNTHETIC_MAXROLL_UI_DOM',
    selectors: {
      ready: '[data-role=ready]', buildInput: '[data-role=build-json]',
      applyButton: '[data-action=apply-build]', readback: '[data-role=applied-build]',
      phase: '[data-role=phase]', metrics: '[data-metric-id]',
      runtimeVersion: '[data-runtime-version]', gamePatch: '[data-game-patch]',
      assetSha256: '[data-asset-sha]',
    },
    ...overrides,
  });
}

module.exports = { BASE_BUILD, MODIFIED_BUILD, createProfile, startRuntimeSite };
