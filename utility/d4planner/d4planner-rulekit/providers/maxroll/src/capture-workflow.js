'use strict';
// Provider-owned composition of existing capturers and local UI acceptance. No compatibility approval.
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const {spawn} = require('node:child_process');
const {BrowserInfrastructure, FileSystemSnapshotStore} = require('../../../browser-infra/src');
const {MaxrollSnapshotCapturer} = require('./snapshot-capturer');
const {discoverBrowser} = require('./live-capture-orchestrator');
const {capture: captureUi} = require('../tooling/web/capture-ui');
const {audit} = require('../tooling/web/resource-audit');
const WEB = path.resolve(__dirname, '../tooling/web');
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const defaultConfig = () => process.env.MAXROLL_CAPTURE_CONFIG || path.join(process.env.XDG_CONFIG_HOME || path.join(os.homedir(), '.config'), 'streamops/maxroll-capture.json');

async function loadConfig(filename = defaultConfig()) {
  const stat = await fs.lstat(filename);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.uid !== process.getuid() || (stat.mode & 0o077)) throw Error('Private configuration requires owned regular file mode 0600');
  const c = JSON.parse(await fs.readFile(filename, 'utf8'));
  if (c.schemaVersion !== 'maxroll-capture-config/v1' || !c.authorizationRef?.trim()) throw Error('Capture configuration/authorization required');
  if (!/^https:\/\/maxroll\.gg\/d4\/planner\/[a-zA-Z0-9]+(?:#[^?]*)?$/.test(c.sourceUrl || '')) throw Error('Configured anonymous Planner source URL required');
  const repo = path.resolve(__dirname, '../../../../../..');
  for (const key of ['stateRoot', 'uiRoot', 'calculationRoot']) {
    if (!path.isAbsolute(c[key] || '') || !path.relative(repo, c[key]).startsWith('..' + path.sep)) throw Error('Private capture roots must be absolute and outside repository: ' + key);
    await fs.mkdir(c[key], {recursive: true, mode: 0o700});
    const s = await fs.lstat(c[key]);
    if (s.isSymbolicLink() || s.uid !== process.getuid() || (s.mode & 0o077)) throw Error('Unsafe private capture root: ' + key);
    if (!path.relative(await fs.realpath(repo), await fs.realpath(c[key])).startsWith('..' + path.sep)) throw Error('Capture root resolves inside repository');
  }
  c.chromium = c.chromium || discoverBrowser(process.env);
  if (!c.chromium) throw Error('BROWSER_UNAVAILABLE: configure an installed Chromium once');
  await fs.access(c.chromium, 1);
  return c;
}

function processCommand(bin, args, {input, log, signal, timeout = 900000} = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(bin, args, {stdio: ['pipe', 'pipe', 'pipe'], signal});
    let stdout = '', stderr = '';
    const timer = setTimeout(() => child.kill('SIGTERM'), timeout);
    child.stdout.on('data', bytes => {if (log) log.write(bytes); else stdout += bytes;});
    child.stderr.on('data', bytes => {if (log) log.write(bytes); stderr = (stderr + bytes).slice(-4000);});
    child.once('error', reject);
    child.once('close', code => {clearTimeout(timer); code === 0 ? resolve(stdout) : reject(Object.assign(Error('Child gate failed (' + code + '): ' + stderr), {code: 'GATE_FAILED'}));});
    child.stdin.end(input);
  });
}
async function state(root, command) {
  return JSON.parse(await processCommand('python3', [path.join(WEB, 'capture_state.py'), root], {input: JSON.stringify(command)}));
}
async function identity(root, id) {
  const store = new FileSystemSnapshotStore({rootDir: root});
  const integrity = await store.verify(id), manifest = await store.load(id);
  const fingerprints = {};
  for (const resource of manifest.resources) {
    const pathname = new URL(resource.url).pathname;
    if (/\/assets\/export-|\/game\/data\.(?:min|enus)\.json/.test(pathname)) fingerprints[resource.url] = resource.sha256;
  }
  if (!Object.keys(fingerprints).some(u => u.includes('/assets/export-')) ||
      !Object.keys(fingerprints).some(u => u.includes('/game/data.min.json')) ||
      !Object.keys(fingerprints).some(u => u.includes('/game/data.enus.json'))) throw Error('Runtime/data identity incomplete');
  return {integrity, identity: {version: manifest.version, fingerprints}, capturedAt: manifest.capturedAt};
}
function consistent(a, b) {
  return a.version === b.version && JSON.stringify(Object.entries(a.fingerprints).sort()) === JSON.stringify(Object.entries(b.fingerprints).sort());
}

async function run(options, dependencies = {}) {
  process.umask(0o077);
  const c = await (dependencies.loadConfig || loadConfig)(options.config);
  const mode = options.mode || 'calculation';
  if (options.output) {
    const output = path.resolve(options.output), repo = path.resolve(__dirname, '../../../../../..');
    if (!path.relative(repo, output).startsWith('..' + path.sep)) throw Error('Private output must be outside repository');
    await fs.mkdir(path.dirname(output), {recursive: true, mode: 0o700});
    if (!path.relative(await fs.realpath(repo), await fs.realpath(path.dirname(output))).startsWith('..' + path.sep)) throw Error('Private output resolves inside repository');
  }
  const runId = 'maxroll-' + new Date().toISOString().replace(/[-:.]/g, '') + '-' + crypto.randomUUID().slice(0, 8);
  const runDir = path.join(c.stateRoot, 'runs', runId);
  await fs.mkdir(runDir, {recursive: true, mode: 0o700});
  const kinds = mode === 'all' ? ['calculation', 'ui'] : [mode];
  const packages = kinds.map(kind => ({snapshotId: options.output ? path.basename(path.resolve(options.output)) : runId + '-' + kind,
    kind, mode, runId, relatedSnapshots: [], capturedAt: new Date().toISOString(), validationStatus: 'CAPTURED_UNVALIDATED',
    snapshotRoot: options.output ? path.dirname(path.resolve(options.output)) : kind === 'ui' ? c.uiRoot : c.calculationRoot}));
  for (const p of packages) p.relatedSnapshots = packages.filter(other => other !== p).map(other => other.snapshotId);
  const db = command => (dependencies.state || state)(c.stateRoot, command);
  await db({operation: 'begin', run: {id: runId, mode, ownerPid: process.pid, startedAt: new Date().toISOString(), status: 'RUNNING', snapshotIds: packages.map(p => p.snapshotId)}, packages});
  const report = {schemaVersion: 'maxroll-capture-run/v1', runId, mode, status: 'RUNNING', consistency: mode === 'all' ? 'PENDING' : 'NOT_APPLICABLE', packages: []};
  let browser;
  async function gate(name, script, config) {
    const filename = path.join(runDir, name + '-config.json');
    await fs.writeFile(filename, JSON.stringify(config), {flag: 'wx', mode: 0o600});
    const log = require('node:fs').createWriteStream(path.join(runDir, name + '.log'), {flags: 'wx', mode: 0o600});
    try {await (dependencies.command || processCommand)(process.execPath, [path.join(WEB, script), filename], {log, signal: options.signal});}
    finally {await new Promise(resolve => log.end(resolve));}
  }
  try {
    browser = (dependencies.browserFactory || (opts => new BrowserInfrastructure(opts)))({executablePath: c.chromium, headless: true, maxContexts: 2, maxQueue: 1, contextOptions: {serviceWorkers: 'block', viewport: {width: 1440, height: 1100}}});
    await browser.start();
    // Separate anonymous contexts preserve each capture policy; only the browser process is shared.
    const facade = {start: async () => {}, stop: async () => {}, withLease: (...args) => browser.withLease(...args)};
    for (const p of packages) {
      try {
        if (p.kind === 'calculation') {
          const capturer = dependencies.calculation || new MaxrollSnapshotCapturer({browserFactory: () => facade});
          const result = await capturer.capture({output: path.join(p.snapshotRoot, p.snapshotId), executablePath: c.chromium, sourceUrl: c.sourceUrl, signal: options.signal});
          p.compatibility = result.validation; // PATCH_DRIFT is preserved, never promoted to calculation READY.
        } else {
          await (dependencies.captureUi || captureUi)({snapshotRoot: p.snapshotRoot, snapshotId: p.snapshotId, chromium: c.chromium,
            evidenceDir: path.join(runDir, 'capture-ui'), authorizationRef: c.authorizationRef, sourceUrl: c.sourceUrl,
            comprehensive: true, signal: options.signal}, {browser});
        }
        const observed = await (dependencies.identity || identity)(p.snapshotRoot, p.snapshotId);
        Object.assign(p, {identity: observed.identity, manifestSha256: observed.integrity.manifestSha256});
        const patch = {identity: p.identity, manifestSha256: p.manifestSha256, capturedAt: observed.capturedAt || p.capturedAt, validationStatus: 'CAPTURED_UNVALIDATED'};
        if (p.compatibility) patch.compatibility = p.compatibility;
        await db({operation: 'package', snapshotId: p.snapshotId, patch});
      } catch (error) {
        p.validationStatus = p.kind === 'ui' && !options.signal?.aborted && error.code !== 'ABORT_ERR' ? 'UNSUPPORTED_VERSION' : 'FAILED';
        await db({operation: 'package', snapshotId: p.snapshotId, patch: {validationStatus: p.validationStatus, error: error.code || 'CAPTURE_FAILED'}});
        throw error;
      }
    }
    await browser.stop(); browser = null;
    if (mode === 'all') {
      report.consistency = consistent(packages[0].identity, packages[1].identity) ? 'PASS' : 'FAILED';
      if (report.consistency !== 'PASS') throw Object.assign(Error('UI/calculation runtime or game-data drift; pair not eligible for activation'), {code: 'CONSISTENCY_FAILED'});
    }
    const ui = packages.find(p => p.kind === 'ui');
    if (ui) {
      try {
        const coverage = await fs.readFile(path.join(ui.snapshotRoot, ui.snapshotId, 'ui-coverage.json'));
        const config = {snapshotRoot: ui.snapshotRoot, snapshotId: ui.snapshotId, manifestSha256: ui.manifestSha256, chromium: c.chromium,
          uiTrust: {schemaVersion: 'maxroll-ui-trust/v1', coverageSha256: sha(coverage), authorizationRef: c.authorizationRef}};
        await db({operation: 'package', snapshotId: ui.snapshotId, patch: {validationStatus: 'VALIDATING', coverageSha256: sha(coverage)}});
        const resource = await (dependencies.audit || audit)(config);
        await fs.writeFile(path.join(runDir, 'resource-audit.json'), JSON.stringify(resource));
        if (resource.status !== 'PASS') throw Error('Resource closure failed');
        await gate('reference', 'full-ui-check.js', {...config, online: true, output: path.join(runDir, 'reference')});
        const referenceReport = await fs.readFile(path.join(runDir, 'reference/report.json'));
        await gate('acceptance', 'full-acceptance.js', {...config, scope: 'ui', output: path.join(runDir, 'acceptance'),
          referenceDir: path.join(runDir, 'reference'), referenceReportSha256: sha(referenceReport)});
        const bytes = await fs.readFile(path.join(runDir, 'acceptance/acceptance.json')), validation = JSON.parse(bytes);
        if (validation.status !== 'AUTOMATED_PASS' || validation.scope !== 'ui') throw Error('Required UI gates failed');
        const receipt = {schemaVersion: 'maxroll-ui-validation/v1', status: 'AUTOMATED_VALIDATED', snapshotId: ui.snapshotId,
          manifestSha256: ui.manifestSha256, coverageSha256: sha(coverage), calculationStatus: 'NOT_ASSESSED',
          captureRunId: runId, head: validation.head, validatedAt: validation.finishedAt, acceptanceSha256: sha(bytes), referenceReportSha256: sha(referenceReport)};
        const receiptBytes = Buffer.from(JSON.stringify(receipt, null, 2));
        await fs.writeFile(path.join(ui.snapshotRoot, ui.snapshotId, 'ui-validation.json'), receiptBytes, {flag: 'wx'});
        config.uiTrust.validationSha256 = sha(receiptBytes);
        ui.validationStatus = 'VALIDATED';
        await db({operation: 'package', snapshotId: ui.snapshotId, patch: {validationStatus: 'VALIDATED', validationSha256: sha(receiptBytes), config}});
      } catch (error) {
        ui.validationStatus = options.signal?.aborted ? 'FAILED' : 'UNSUPPORTED_VERSION';
        await db({operation: 'package', snapshotId: ui.snapshotId, patch: {validationStatus: ui.validationStatus, error: error.code || 'UI_VALIDATION_FAILED'}});
        throw error;
      }
    }
    report.status = 'COMPLETE';
  } catch (error) {
    report.status = 'FAILED'; report.error = error.code || 'CAPTURE_OR_VALIDATION_FAILED';
    throw Object.assign(error, {report});
  } finally {
    try {if (browser) await browser.stop();} catch {report.status = 'FAILED'; report.error = 'CLEANUP_FAILED';}
    report.packages = packages; report.finishedAt = new Date().toISOString();
    await fs.writeFile(path.join(runDir, 'run-report.json'), JSON.stringify(report, null, 2), {flag: 'wx'});
    await db({operation: 'finish', runId, result: {status: report.status, consistency: report.consistency, finishedAt: report.finishedAt, error: report.error || null}});
  }
  if (report.status !== 'COMPLETE') throw Error(report.error);
  return report;
}
module.exports = {run, loadConfig, defaultConfig, processCommand, state, identity, consistent};
