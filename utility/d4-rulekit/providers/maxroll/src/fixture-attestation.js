'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');
const {
  BrowserInfrastructure,
  FileSystemSnapshotStore,
  WebSnapshotManager,
} = require('@streamops/browser-infrastructure');
const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const { METRIC_CATALOG } = require('./metric-catalog');
const {
  MAXROLL_32173552_D12AM6KT_REFERENCE,
  createMaxroll32173552D12aM6KTCandidateProfile,
} = require('./real-profile');
const { MaxrollRuntimeAttestationObserver, semanticHash } = require('./runtime-attestation');

const ATTESTATION_SCHEMA_VERSION = 'maxroll-character-stats-attestation/v1';
const EXPORT_SCHEMA_VERSION = 'maxroll-native-build-export/v1';

function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonicalize(value[key])]));
}

function serialize(value) {
  return `${JSON.stringify(canonicalize(value), null, 2)}\n`;
}

function fail(code, message, details, cause) {
  return new MaxrollProviderError(code, message, { details, cause });
}

function visibleFragment(nativeState, profileIndex) {
  const visible = nativeState.profiles
    .map((profile, index) => ({ profile, index }))
    .filter(entry => entry.profile.hidden !== true);
  const offset = visible.findIndex(entry => entry.index === profileIndex);
  if (offset < 0) throw fail(ERROR_CODES.PROFILE_VARIANT_NOT_FOUND,
    `profile ${profileIndex} is not a visible source variant`);
  return offset + 1;
}

function validateFixture(fixture, fileSha256, options) {
  if (!fixture || fixture.schemaVersion !== EXPORT_SCHEMA_VERSION
      || fixture.format !== 'MAXROLL_NATIVE_STATE'
      || !fixture.nativeState || !fixture.loaderMetadata
      || !Number.isInteger(fixture.selection?.profileIndex)) {
    throw fail(ERROR_CODES.NATIVE_BUILD_INVALID, 'input is not a complete Maxroll native export');
  }
  if (fixture.provenance?.snapshotId !== options.snapshotId
      || fixture.provenance?.snapshotManifestSha256 !== options.expectedManifestSha256) {
    throw fail(ERROR_CODES.SNAPSHOT_MISMATCH, 'input provenance does not match the trusted snapshot');
  }
  const nativeStateSha256 = sha256(Buffer.from(serialize(fixture.nativeState)));
  if (nativeStateSha256 !== fixture.integrity?.nativeStateSha256) {
    throw fail(ERROR_CODES.NATIVE_BUILD_INVALID, 'native state SHA-256 does not match its export');
  }
  return Object.freeze({ fileSha256, nativeStateSha256 });
}

async function verifiedSnapshot(options) {
  const store = options.store ?? new FileSystemSnapshotStore({ rootDir: options.snapshotRoot });
  const verified = await store.verify(options.snapshotId);
  if (verified.manifestSha256 !== options.expectedManifestSha256) {
    throw fail(ERROR_CODES.SNAPSHOT_MISMATCH, 'snapshot manifest does not match trust anchor', {
      expected: options.expectedManifestSha256, actual: verified.manifestSha256,
    });
  }
  const snapshotPackage = await store.loadPackage(options.snapshotId);
  if (snapshotPackage.manifest.sourceUrl !== options.sourceUrl) {
    throw fail(ERROR_CODES.SNAPSHOT_MISMATCH,
      'build source URL is not the trusted snapshot source URL');
  }
  const runtime = snapshotPackage.manifest.resources.find(resource =>
    resource.url === options.assetUrl);
  const body = runtime && snapshotPackage.resources.get(`GET ${runtime.url}`)?.body;
  if (!runtime || !body || sha256(body) !== options.assetSha256 || runtime.sha256 !== options.assetSha256) {
    throw fail(ERROR_CODES.RUNTIME_MISMATCH,
      'trusted snapshot does not contain the pinned calculation asset bytes');
  }
  return { store, verified, snapshotPackage, runtimeBytes: body.length };
}

function compareCaptures(source, replay) {
  for (const capture of [source, replay]) validateCaptureEvidence(capture);
  if (source.captureId === replay.captureId
      || source.phase.inputProfileSha256 !== replay.phase.inputProfileSha256
      || source.phase.inputItemsSha256 !== replay.phase.inputItemsSha256
      || source.profileReadback.normalizedProfileSha256
        !== replay.profileReadback.normalizedProfileSha256
      || source.profileReadback.resolvedItemsSha256
        !== replay.profileReadback.resolvedItemsSha256) {
    throw fail(ERROR_CODES.INPUT_READBACK_UNVERIFIED,
      'source and replay are not linked to the same independently captured input');
  }
  const raw = metricsBy(source.rawMetrics, 'metricId', 'rawValue');
  const replayRaw = metricsBy(replay.rawMetrics, 'metricId', 'rawValue');
  const display = metricsBy(source.displayMetrics, 'labelAnchor', 'displayValue');
  const replayDisplay = metricsBy(replay.displayMetrics, 'labelAnchor', 'displayValue');
  if (source.rawMetrics.length !== 50 || replay.rawMetrics.length !== 50
      || raw.size !== 50 || replayRaw.size !== 50) {
    throw fail(ERROR_CODES.METRICS_INCOMPLETE, 'attestation requires 50 unique raw metrics');
  }
  for (const [id, value] of raw) {
    if (!replayRaw.has(id) || !Object.is(replayRaw.get(id), value)) {
      throw fail(ERROR_CODES.OUTPUT_NOT_LINKED, `source/replay raw metric mismatch: ${id}`);
    }
  }
  if (display.size !== replayDisplay.size) {
    throw fail(ERROR_CODES.OUTPUT_NOT_LINKED, 'source/replay display metric count differs');
  }
  for (const [id, value] of display) {
    if (replayDisplay.get(id) !== value) {
      throw fail(ERROR_CODES.OUTPUT_NOT_LINKED, `source/replay display mismatch: ${id}`);
    }
  }
  return Object.freeze({
    status: 'EXACT', rawExact: true, displayExact: true,
    rawSha256: semanticHash([...raw]), displaySha256: semanticHash([...display]),
  });
}

function validateCaptureEvidence(capture) {
  if (capture.engine?.status !== 'EXECUTED'
      || !capture.engine.scriptId
      || capture.engine.scriptId !== capture.engine.pauseScriptId
      || capture.engine.pinnedSha256 !== capture.engine.wireSha256
      || capture.engine.pinnedSha256 !== capture.engine.scriptSourceSha256) {
    throw fail(ERROR_CODES.ENGINE_IDENTITY_UNVERIFIED,
      'capture is not linked to the pinned executing engine');
  }
  if (capture.profileReadback?.status !== 'EXACT'
      || capture.profileReadback.normalizedProfileSha256 !== capture.phase?.inputProfileSha256
      || capture.profileReadback.resolvedItemsSha256 !== capture.phase?.inputItemsSha256) {
    throw fail(ERROR_CODES.INPUT_READBACK_UNVERIFIED,
      'capture is not linked to exact runtime semantic read-back');
  }
  if (!capture.captureId || capture.phase.captureId !== capture.captureId
      || !capture.phase.epochIdentitySha256
      || capture.phase.epochIdentitySource !== 'CDP_RUNTIME_OBJECT_IDENTITY:l.context'
      || capture.phase.coherentMetricCount !== 50
      || capture.phase.firstMetricPauseOrdinal < capture.phase.matchedPauseOrdinal
      || capture.phase.lastMetricPauseOrdinal < capture.phase.firstMetricPauseOrdinal) {
    throw fail(ERROR_CODES.STALE_METRICS,
      'capture phase does not prove fresh output after matching input');
  }
  if (capture.network?.externalEgressCompleted !== 0
      || capture.network?.webSocketHandshakes !== 0) {
    throw fail(ERROR_CODES.OUTPUT_NOT_LINKED,
      'offline capture completed external network egress');
  }
}

function metricsBy(metrics, identity, value) {
  const output = new Map();
  for (const metric of metrics) {
    if (metric[identity] == null || output.has(metric[identity])) {
      throw fail(ERROR_CODES.METRICS_INCOMPLETE, `missing or duplicate metric identity: ${identity}`);
    }
    output.set(metric[identity], metric[value]);
  }
  return output;
}

async function runCapture({ options, fixture, snapshot, profile, mode }) {
  const browser = new BrowserInfrastructure({
    executablePath: options.chromiumExecutablePath,
    headless: true,
    maxContexts: 1,
    maxQueue: 1,
    contextOptions: { serviceWorkers: 'block' },
  });
  let lease;
  let mount;
  let observer;
  let ownedPid;
  let primaryError;
  let result;
  try {
    await browser.start();
    ownedPid = browser.getStatus().pid;
    const manager = new WebSnapshotManager({ browser, store: snapshot.store });
    lease = await browser.acquire({ timeoutMs: options.timeoutMs ?? 30_000 });
    mount = await manager.mount(lease, options.snapshotId, { mode: 'offline-strict' });
    observer = new MaxrollRuntimeAttestationObserver({
      lease,
      profile,
      nativeState: fixture.nativeState,
      profileIndex: fixture.selection.profileIndex,
    });
    await observer.initialize();
    const profileUrl = `https://planners.maxroll.gg/profiles/load/d4/${fixture.provenance.plannerId}`;
    const fragment = visibleFragment(fixture.nativeState, fixture.selection.profileIndex);
    result = await observer.capture({
      navigateUrl: mode === 'source'
        ? `${fixture.provenance.sourceUrl}#${fragment}`
        : fixture.provenance.sourceUrl,
      replayResponse: mode === 'replay' ? {
        url: profileUrl,
        body: JSON.stringify({
          ...fixture.loaderMetadata,
          data: JSON.stringify(fixture.nativeState),
        }),
      } : null,
    });
  } catch (error) {
    primaryError = error;
  }
  const failures = [];
  for (const operation of [
    () => observer?.close(),
    () => mount?.unmount(),
    () => lease?.release(),
    () => browser.stop(),
  ]) {
    try { await operation(); } catch (error) { failures.push(error); }
  }
  const status = browser.getStatus();
  const metrics = browser.getMetrics();
  if (status.state !== 'stopped' || status.pid !== null || status.activeLeases !== 0
      || metrics.currentContexts !== 0 || (ownedPid && !await processExited(ownedPid))) {
    failures.push(new Error('owned Chromium resources did not reach a verified stopped state'));
  }
  if (primaryError || failures.length) {
    const errors = [...(primaryError ? [primaryError] : []), ...failures];
    throw errors.length === 1 ? errors[0] : new AggregateError(errors,
      `${mode} attestation and cleanup failed`);
  }
  return Object.freeze({
    ...result,
    cleanup: Object.freeze({ status: 'PASS', browserState: status.state,
      activeLeases: status.activeLeases, currentContexts: metrics.currentContexts,
      ownedProcessExited: true }),
  });
}

async function attestMaxrollBuildFixture(options) {
  for (const key of ['inputPath', 'outputPath', 'snapshotRoot', 'snapshotId',
    'expectedManifestSha256', 'chromiumExecutablePath']) {
    if (typeof options?.[key] !== 'string' || !options[key]) {
      throw fail(ERROR_CODES.INVALID_INPUT, `${key} is required`);
    }
  }
  try {
    await fs.access(options.outputPath);
    throw fail(ERROR_CODES.OUTPUT_EXISTS,
      'attestation output already exists; overwrite is disabled');
  } catch (error) {
    if (error instanceof MaxrollProviderError) throw error;
    if (error?.code !== 'ENOENT') throw error;
  }
  const inputBytes = await fs.readFile(options.inputPath);
  let fixture;
  try {
    fixture = JSON.parse(inputBytes.toString('utf8'));
  } catch (cause) {
    throw fail(ERROR_CODES.NATIVE_BUILD_INVALID, 'input build export is not valid JSON',
      undefined, cause);
  }
  const integrity = validateFixture(fixture, sha256(inputBytes), options);
  const assetUrl = `https://maxroll.gg${MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetPath}`;
  const assetSha256 = MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetSha256;
  if (fixture.provenance.runtimeAssetUrl !== assetUrl
      || fixture.provenance.runtimeAssetSha256 !== assetSha256) {
    throw fail(ERROR_CODES.RUNTIME_MISMATCH,
      'build provenance does not identify the trusted attestation engine');
  }
  const snapshot = await verifiedSnapshot({ ...options, assetUrl, assetSha256,
    sourceUrl: fixture.provenance.sourceUrl });
  const profile = createMaxroll32173552D12aM6KTCandidateProfile({
    snapshotId: options.snapshotId,
    snapshotManifestSha256: options.expectedManifestSha256,
    sourceUrl: fixture.provenance.sourceUrl,
    assetUrl,
    metricCatalog: METRIC_CATALOG,
    authorizationRef: 'issue-134-gb-e1-att-approved-offline-snapshot',
  });
  const source = await runCapture({ options, fixture, snapshot, profile, mode: 'source' });
  const replay = await runCapture({ options, fixture, snapshot, profile, mode: 'replay' });
  const comparison = compareCaptures(source, replay);
  const output = {
    schemaVersion: ATTESTATION_SCHEMA_VERSION,
    status: 'OBSERVED',
    source: 'MAXROLL_REFERENCE_OBSERVATION',
    capturedAt: new Date().toISOString(),
    input: {
      buildSha256: integrity.fileSha256,
      nativeStateSha256: integrity.nativeStateSha256,
      profileIndex: fixture.selection.profileIndex,
      profileName: fixture.selection.profileName,
      class: fixture.selection.class,
      level: fixture.selection.level,
      sourceUrl: fixture.provenance.sourceUrl,
      plannerId: fixture.provenance.plannerId,
    },
    engine: {
      snapshotId: options.snapshotId,
      snapshotManifestSha256: snapshot.verified.manifestSha256,
      assetUrl,
      assetSha256,
      assetBytes: snapshot.runtimeBytes,
      gamePatch: profile.gamePatch,
      providerVersion: profile.providerVersion,
      runtimeVersion: profile.runtimeVersion,
      metricCatalogSha256: semanticHash(profile.metricCatalog),
    },
    gates: {
      G1: { status: 'PASS', manifestSha256: snapshot.verified.manifestSha256,
        resourceSha256: assetSha256 },
      G2: { status: 'PASS', source: source.engine, replay: replay.engine },
      G3: { status: 'PASS', source: source.profileReadback, replay: replay.profileReadback },
      G4: { status: 'PASS', source: source.phase, replay: replay.phase },
    },
    rawMetrics: source.rawMetrics,
    displayMetrics: source.displayMetrics,
    coverage: { rawCount: source.rawMetrics.length,
      displayCount: source.displayMetrics.length },
    fingerprints: { rawMetricsSha256: comparison.rawSha256,
      displayMetricsSha256: comparison.displaySha256 },
    sourceReplay: comparison,
    network: { source: source.network, replay: replay.network },
    cleanup: { source: source.cleanup, replay: replay.cleanup },
  };
  await writeExclusive(options.outputPath, Buffer.from(serialize(output)));
  return Object.freeze({
    outputPath: path.resolve(options.outputPath),
    outputSha256: sha256(Buffer.from(serialize(output))),
    rawCount: output.rawMetrics.length,
    displayCount: output.displayMetrics.length,
    sourceReplay: comparison.status,
  });
}

async function writeExclusive(outputPath, bytes) {
  const resolved = path.resolve(outputPath);
  const directory = path.dirname(resolved);
  const temporary = path.join(directory, `.${path.basename(resolved)}.${crypto.randomUUID()}.tmp`);
  try {
    await fs.mkdir(directory, { recursive: true, mode: 0o700 });
    await fs.writeFile(temporary, bytes, { flag: 'wx', mode: 0o600 });
    await fs.link(temporary, resolved);
  } catch (cause) {
    if (cause?.code === 'EEXIST') throw fail(ERROR_CODES.OUTPUT_EXISTS,
      'attestation output already exists; overwrite is disabled');
    throw cause;
  } finally {
    await fs.rm(temporary, { force: true }).catch(() => {});
  }
}

async function processExited(pid) {
  const deadline = Date.now() + 2_000;
  while (Date.now() <= deadline) {
    try { process.kill(pid, 0); } catch (error) {
      if (error.code === 'ESRCH') return true;
      throw error;
    }
    await new Promise(resolve => setTimeout(resolve, 25));
  }
  return false;
}

module.exports = {
  ATTESTATION_SCHEMA_VERSION,
  attestMaxrollBuildFixture,
  compareCaptures,
  runCapture,
  verifiedSnapshot,
  validateCaptureEvidence,
};
