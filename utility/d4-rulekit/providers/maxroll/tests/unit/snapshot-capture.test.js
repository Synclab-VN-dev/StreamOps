'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const {
  CAPTURE_STATUS,
  MaxrollSnapshotCapturer,
} = require('../../src/snapshot-capturer');
const { parseArguments } = require('../../scripts/snapshot-capture');
const { MAXROLL_32173552_REFERENCE } = require('../../src/real-profile');

function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function fixture(overrides = {}) {
  const body = Buffer.from(overrides.body ?? 'calculation-runtime');
  const assetPath = overrides.assetPath ?? MAXROLL_32173552_REFERENCE.applicationAssetPath;
  const assetSha256 = sha256(body);
  const resource = {
    key: `GET https://maxroll.gg${assetPath}`,
    method: 'GET',
    url: `https://maxroll.gg${assetPath}`,
    status: 200,
    headers: { 'content-type': 'application/javascript' },
    redirectedFrom: null,
    sha256: assetSha256,
    size: body.length,
    blob: `blobs/${assetSha256}.bin`,
  };
  const state = { starts: 0, stops: 0, captures: 0 };
  const browser = {
    async start() { state.starts += 1; },
    async stop() {
      state.stops += 1;
      if (overrides.stopError) throw overrides.stopError;
    },
    async withLease(_options, callback) {
      return callback({ context: { browser: () => ({ version: () => 'Fake Chromium 1' }) } });
    },
  };
  const managerFactory = (_browser, rootDir) => {
   const {FileSystemSnapshotStore}=require('../../../../browser-infra/src');
   const store=new FileSystemSnapshotStore({rootDir});
   return ({
    async capture(options) {
      state.captures += 1;
      if (overrides.captureError) throw overrides.captureError;
      await options.interact({ page: {} });
      const normalizedUrl=new URL(options.url);normalizedUrl.hash="";options={...options,url:normalizedUrl.href};
      return {
        snapshotId: options.snapshotId,
        sourceUrl: options.url,
        capturedAt: '2026-10-23T00:00:00.000Z',
        allowedOrigins: options.allowedOrigins,
        site: options.site,
        version: options.version,
        browserVersion: 'Fake Chromium 1',
        playwrightVersion: '1.64.1',
        schemaVersion:'web-snapshot-draft/v1',
        resources: [
          {key:'GET '+options.url,method:'GET',url:options.url,status:200,headers:{'content-type':'text/html'},redirectedFrom:null,body:Buffer.from('<html>SYNTHETIC</html>')},
          {key:'GET '+resource.url,method:'GET',url:resource.url,status:200,headers:resource.headers,redirectedFrom:null,body},
        ],
        capture: { durationMs: 10, blockedRequestCount: 2,
          excludedResponseCount: 1, redactedResponseCount: 0,
          completion: overrides.omitCompletion ? undefined : {
            policy:'bounded-quiescence/v1',pendingRequests:0,failedRequests:[],
            roots:[{method:'GET',url:options.url}],
            nodes:[{method:'GET',url:options.url,resourceType:'document'},{method:'GET',url:resource.url,resourceType:'script'},...(overrides.missingNode?[{method:'GET',url:'https://maxroll.gg/api/twitch',resourceType:'fetch'}]:[])],
            edges:[{from:{method:'GET',url:options.url},to:{method:'GET',url:resource.url}}],
          } },
      };
    },
    async save(draft) { return store.save(draft); },
    async verify(snapshotId) {
      if (overrides.verifyError) throw overrides.verifyError;
      return store.verify(snapshotId);
    },
    async load(snapshotId) { return store.load(snapshotId); },
  });
  };
  return {
    state,
    dependencies: {
      browserFactory: () => browser,
      managerFactory,
      captureInteraction: async () => ({
        gamePatch: overrides.gamePatch ?? MAXROLL_32173552_REFERENCE.gamePatch,
        exportAssetUrls: [`https://maxroll.gg${assetPath}`],
      }),
    },
  };
}

async function temporaryOutput(t, name = 'snapshot-1') {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'mxp-capture-test-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  return path.join(root, name);
}

test('snapshot:capture persists immutable verified package and review artifacts', async t => {
  const output = await temporaryOutput(t);
  const fake = fixture();
  const report = await new MaxrollSnapshotCapturer(fake.dependencies).capture({
    output, executablePath: process.execPath,
  });
  assert.equal(report.status, CAPTURE_STATUS.CAPTURED_UNVALIDATED);
  assert.equal(report.validation, CAPTURE_STATUS.PATCH_DRIFT); // Synthetic bytes never claim the pinned real runtime.
  assert.equal(report.realE2E, 'NOT_RUN');
  assert.equal(report.integrity.status, 'PASS');
  assert.equal(report.cleanup, 'PASS');
  assert.deepEqual(fake.state, { starts: 1, stops: 1, captures: 1 });
  assert.deepEqual((await fs.readdir(output)).sort(), [
    'blobs', 'capture-report.json', 'manifest.json', 'manifest.sha256',
    'resource-inventory.json',
  ]);
  const inventory = JSON.parse(await fs.readFile(
    path.join(output, 'resource-inventory.json'), 'utf8'));
  assert.equal(inventory.resourceCount, 2);
  assert.equal(report.capture.coverageValidation.state,'COMPLETE');
  assert.equal(inventory.resources.find(r=>r.url.includes('/assets/export-')).sha256,sha256('calculation-runtime'));
});

test('snapshot:capture preserves verified snapshot and reports PATCH_DRIFT', async t => {
  const output = await temporaryOutput(t, 'snapshot-drift');
  const fake = fixture({
    gamePatch: 'future-patch', assetPath: '/assets/export-new.js',
    assetSha256: 'c'.repeat(64),
  });
  const report = await new MaxrollSnapshotCapturer(fake.dependencies).capture({
    output, executablePath: process.execPath,
  });
  assert.equal(report.status, CAPTURE_STATUS.CAPTURED_UNVALIDATED);
  assert.equal(report.validation, CAPTURE_STATUS.PATCH_DRIFT);
  assert.equal(report.runtime.observedPatch, 'future-patch');
  assert.equal(report.integrity.status, 'PASS');
  await fs.access(path.join(output, 'blobs', `${sha256('calculation-runtime')}.bin`));
});

test('snapshot:capture refuses overwrite before launching Chromium', async t => {
  const output = await temporaryOutput(t, 'existing');
  await fs.mkdir(output);
  await fs.writeFile(path.join(output, 'sentinel'), 'keep');
  const fake = fixture();
  await assert.rejects(new MaxrollSnapshotCapturer(fake.dependencies).capture({
    output, executablePath: process.execPath,
  }), error => error.code === 'OUTPUT_EXISTS');
  assert.equal(await fs.readFile(path.join(output, 'sentinel'), 'utf8'), 'keep');
  assert.deepEqual(fake.state, { starts: 0, stops: 0, captures: 0 });
});

test('snapshot:capture retains saved data but fails closed on integrity or cleanup error', async t => {
  const integrityOutput = await temporaryOutput(t, 'integrity-failure');
  const integrity = fixture({ verifyError: new Error('blob mismatch') });
  await assert.rejects(new MaxrollSnapshotCapturer(integrity.dependencies).capture({
    output: integrityOutput, executablePath: process.execPath,
  }), error => error.code === 'CAPTURE_FAILED' && error.report.integrity.status === 'PENDING');
  await fs.access(path.join(integrityOutput, 'manifest.json'));

  const cleanupOutput = await temporaryOutput(t, 'cleanup-failure');
  const cleanup = fixture({ stopError: new Error('browser stuck') });
  await assert.rejects(new MaxrollSnapshotCapturer(cleanup.dependencies).capture({
    output: cleanupOutput, executablePath: process.execPath,
  }), error => error.code === 'CLEANUP_FAILED' && error.report.cleanup === 'FAIL');
  await fs.access(path.join(cleanupOutput, 'capture-report.json'));
});

test('snapshot capture CLI requires exactly one output folder argument', () => {
  assert.deepEqual(parseArguments(['--output', '/tmp/capture']), { output: '/tmp/capture' });
  assert.throws(() => parseArguments([]), /usage/);
  assert.throws(() => parseArguments(['--unknown']), /unsupported/);
});

test('capture keeps GET /api/twitch in scope and enables bounded completion',async t=>{
 const {CAPTURE_COMPLETION,createMaxrollSnapshotScope}=require('../../src/snapshot-capturer');
 const output=await temporaryOutput(t,'completion-config'),fake=fixture();let policy;
 const original=fake.dependencies.managerFactory;
 fake.dependencies.managerFactory=(...args)=>{const manager=original(...args),capture=manager.capture.bind(manager);manager.capture=async options=>{policy=options.capturePolicy;return capture(options);};return manager;};
 await new MaxrollSnapshotCapturer(fake.dependencies).capture({output,executablePath:process.execPath});
 assert.deepEqual(policy.completion,CAPTURE_COMPLETION);
 assert.equal(await policy.allowResource({method:'GET',url:'https://maxroll.gg/api/twitch',resourceType:'fetch'}),true);
 const scope=createMaxrollSnapshotScope('https://maxroll.gg/d4/planner/1g1any0x#3');
 assert.equal(scope.policyVersion,'2');assert(!scope.exclude.some(rule=>rule.path==='/api/twitch'));
});

for(const overrides of [{missingNode:true},{omitCompletion:true}])test('capture fails closed without complete observed coverage '+JSON.stringify(overrides),async t=>{
 const output=await temporaryOutput(t,'incomplete'),fake=fixture(overrides);
 await assert.rejects(new MaxrollSnapshotCapturer(fake.dependencies).capture({output,executablePath:process.execPath}),error=>error.code==='CAPTURE_INCOMPLETE');
 const report=JSON.parse(await fs.readFile(path.join(output,'capture-report.json'),'utf8'));
 assert.equal(report.status,'CAPTURE_INCOMPLETE');assert.equal(report.cleanup,'PASS');
 const {FileSystemSnapshotStore}=require('../../../../browser-infra/src');
 assert.equal((await new FileSystemSnapshotStore({rootDir:path.dirname(output)}).verify(path.basename(output))).valid,true);
});
