'use strict';
// Compose existing Rule Kit trust/import and UI validation. No new approvals.
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const {matchCapture} = require('./pair');
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const read = async file => JSON.parse(await fs.readFile(file, 'utf8'));
const rulekit = path.resolve(__dirname, '../..');
const provider = path.join(rulekit, 'providers/maxroll');
function check(ok, code) { if (!ok) throw Object.assign(new Error(code), {code}); }
async function verify(config) {
  const {FileSystemSnapshotStore} = require(path.join(rulekit, 'browser-infra/src'));
  const {identity} = require(path.join(provider, 'tooling/capture-workflow'));
  const {verifyUiReceipt} = require(path.join(provider, 'tooling/web/ui-package'));
  const {createProductionManager} = require('../src');
  const report = await read(config.report);
  const pair = matchCapture(report);
  const calculation = report.packages.find(p => p.kind === 'calculation');
  const ui = report.packages.find(p => p.kind === 'ui');
  for (const p of report.packages) {
    const actual = await identity(p.snapshotRoot, p.snapshotId);
    check(actual.integrity.manifestSha256 === p.manifestSha256 && actual.integrity.valid, 'BLOCKED_INTEGRITY');
    check(JSON.stringify(actual.identity) === JSON.stringify(p.identity), 'BLOCKED_RUNTIME_IDENTITY');
  }
  const uiPath = path.join(ui.snapshotRoot, ui.snapshotId);
  const coverageBytes = await fs.readFile(path.join(uiPath, 'ui-coverage.json'));
  const receiptBytes = await fs.readFile(path.join(uiPath, 'ui-validation.json'));
  const receipt = JSON.parse(receiptBytes);
  const acceptanceBytes = await fs.readFile(config.uiAcceptance);
  const acceptance = JSON.parse(acceptanceBytes);
  check(sha(acceptanceBytes) === receipt.acceptanceSha256 && acceptance.status === 'AUTOMATED_PASS' &&
    acceptance.scope === 'ui' && acceptance.head === config.source && acceptance.snapshotId === ui.snapshotId &&
    acceptance.manifestSha256 === ui.manifestSha256, 'BLOCKED_UI_PROVENANCE');
  check(receipt.captureRunId === report.runId && receipt.head === config.source, 'BLOCKED_UI_PROVENANCE');
  const store = new FileSystemSnapshotStore({rootDir: ui.snapshotRoot});
  await verifyUiReceipt({snapshotRoot:ui.snapshotRoot, snapshotId:ui.snapshotId, manifestSha256:ui.manifestSha256,
    uiTrust:{schemaVersion:'maxroll-ui-trust/v1', coverageSha256:sha(coverageBytes), validationSha256:sha(receiptBytes),
      authorizationRef:config.authorizationRef}}, await store.load(ui.snapshotId), await store.verify(ui.snapshotId));
  const manager = createProductionManager({dataRoot:config.dataRoot, installationRoot:rulekit, workerGeneration:1});
  check(manager.registry, 'BLOCKED_COMPATIBILITY');
  await manager.start();
  try {
    await manager.updateRegistry(await read(config.registry));
    const checked = await manager.checkCompatibility({entryId:config.entryId,
      storeRoot:calculation.snapshotRoot, profilePath:config.profile});
    check(checked.snapshotId === calculation.snapshotId && checked.manifestSha256 === calculation.manifestSha256,
      'BLOCKED_COMPATIBILITY');
    if (config.packagePath) await manager.importPackage({packagePath:config.packagePath});
    const entry = manager.registry.resolve(config.entryId);
    return {...pair, coverageSha256:sha(coverageBytes), validationSha256:sha(receiptBytes),
      acceptanceSha256:receipt.acceptanceSha256, calculation:checked, distribution:{permission:entry.distribution.permission, referenceSha256:sha(Buffer.from(entry.distribution.reference))}};
  } finally { await manager.close(); }
}
if (require.main === module) {
  read(process.argv[2]).then(verify).then(result => fs.writeFile(process.argv[3], JSON.stringify(result)))
    .catch(error => { process.stderr.write((error.code || 'BLOCKED_VALIDATION') + '\n'); process.exitCode=2; });
}
module.exports = {verify};
