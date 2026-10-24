'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');
const {
  BrowserInfrastructure,
  FileSystemSnapshotStore,
} = require('@streamops/browser-infrastructure');
const {
  createNativeBuildExport,
  parseNativeResponse,
  parsePlannerUrl,
  serialize,
  writeAtomicExclusive,
} = require('./build-export');
const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const {
  compareCaptures,
  runCapture,
  validateCaptureEvidence,
  verifiedSnapshot,
} = require('./fixture-attestation');
const { METRIC_CATALOG } = require('./metric-catalog');
const {
  MAXROLL_32173552_D12AM6KT_REFERENCE,
  createMaxroll32173552D12aM6KTCandidateProfile,
} = require('./real-profile');
const { MaxrollRuntimeAttestationObserver, semanticHash } = require('./runtime-attestation');

const CLASS_FIXTURE_SCHEMA_VERSION = 'maxroll-class-fixture-capture/v1';
const MATRIX_SCHEMA_VERSION = 'maxroll-class-fixture-matrix/v1';
const ALLOWED_CLASSES = new Set([
  'Sorcerer', 'Druid', 'Barbarian', 'Rogue', 'Necromancer', 'Spiritborn', 'Paladin', 'Warlock',
]);
const SHA256_PATTERN = /^[a-f0-9]{64}$/;
const ONLINE_ALLOWED_ORIGINS = new Set([
  'https://maxroll.gg', 'https://assets-ng.maxroll.gg', 'https://planners.maxroll.gg',
]);

function digest(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function fail(code, message, details, cause) {
  return new MaxrollProviderError(code, message, { details, cause });
}

async function installReadOnlyPolicy(page) {
  await page.route('**/*', route => {
    const request = route.request();
    let origin;
    try { origin = new URL(request.url()).origin; } catch { return route.abort('blockedbyclient'); }
    return ['GET', 'HEAD'].includes(request.method()) && ONLINE_ALLOWED_ORIGINS.has(origin)
      ? route.continue()
      : route.abort('blockedbyclient');
  });
}

function validateMatrix(matrix) {
  if (!matrix || matrix.schemaVersion !== MATRIX_SCHEMA_VERSION || !Array.isArray(matrix.fixtures)) {
    throw fail(ERROR_CODES.INVALID_INPUT, 'fixture matrix schema is invalid');
  }
  const classes = new Set();
  const slugs = new Set();
  for (const entry of matrix.fixtures) {
    if (!entry || entry.action !== 'CAPTURE' || !ALLOWED_CLASSES.has(entry.class)
        || typeof entry.slug !== 'string' || !/^[a-z0-9-]+$/.test(entry.slug)
        || typeof entry.url !== 'string'
        || !Number.isInteger(entry.expectedRawMetrics) || entry.expectedRawMetrics < 1) {
      throw fail(ERROR_CODES.INVALID_INPUT, 'fixture matrix entry is invalid', { entry });
    }
    parsePlannerUrl(entry.url);
    if (classes.has(entry.class) || slugs.has(entry.slug)) {
      throw fail(ERROR_CODES.INVALID_INPUT, 'fixture matrix contains duplicate class or slug', {
        class: entry.class, slug: entry.slug,
      });
    }
    classes.add(entry.class);
    slugs.add(entry.slug);
  }
  return matrix;
}

function validateOptions(options) {
  for (const key of ['outputRoot', 'snapshotRoot', 'snapshotId',
    'expectedManifestSha256', 'chromiumExecutablePath']) {
    if (typeof options?.[key] !== 'string' || !options[key]) {
      throw fail(ERROR_CODES.INVALID_INPUT, `${key} is required`);
    }
  }
  if (!SHA256_PATTERN.test(options.expectedManifestSha256)) {
    throw fail(ERROR_CODES.INVALID_INPUT, 'expectedManifestSha256 must be a lowercase SHA-256');
  }
  validateMatrix(options.matrix);
  if (options.matrix.reuse?.length
      && (typeof options.reuseRoot !== 'string' || !options.reuseRoot)) {
    throw fail(ERROR_CODES.INVALID_INPUT, 'reuseRoot is required when the matrix reuses fixtures');
  }
}

async function verifiedReuseFixtures(matrix, reuseRoot, expectedManifestSha256) {
  const results = [];
  for (const entry of matrix.reuse ?? []) {
    if (!entry || !ALLOWED_CLASSES.has(entry.class) || typeof entry.fixture !== 'string'
        || !/^[a-z0-9-]+$/.test(entry.fixture)
        || ![entry.inputSha256, entry.statsSha256, entry.nativeStateSha256,
          entry.trustedPackageManifestSha256, entry.runtimeAssetSha256]
          .every(value => SHA256_PATTERN.test(value ?? ''))
        || !Number.isInteger(entry.profileIndex)
        || !Number.isInteger(entry.rawCount) || !Number.isInteger(entry.displayCount)) {
      throw fail(ERROR_CODES.INVALID_INPUT, 'reused fixture matrix entry is invalid', { entry });
    }
    const root = path.resolve(reuseRoot);
    const inputName = `${entry.fixture}.json`;
    const statsName = `${entry.fixture}.stats.json`;
    const inputPath = path.join(root, inputName);
    const statsPath = path.join(root, statsName);
    const [manifestBytes, inputBytes, statsBytes] = await Promise.all([
      fs.readFile(path.join(root, 'manifest.json')), fs.readFile(inputPath), fs.readFile(statsPath),
    ]);
    if (digest(manifestBytes) !== entry.trustedPackageManifestSha256
        || digest(inputBytes) !== entry.inputSha256 || digest(statsBytes) !== entry.statsSha256) {
      throw fail(ERROR_CODES.OUTPUT_NOT_LINKED,
        'reused fixture bytes do not match independent trust anchors', { class: entry.class });
    }
    const manifest = JSON.parse(manifestBytes);
    const input = JSON.parse(inputBytes);
    const stats = JSON.parse(statsBytes);
    const sourceReplay = typeof stats.sourceReplay === 'string'
      ? stats.sourceReplay : stats.sourceReplay?.status;
    const pair = manifest.pairs?.find(candidate => candidate.name === entry.fixture);
    const rawIds = (stats.rawMetrics ?? []).map(metric => metric.metricId);
    const displayAnchors = (stats.displayMetrics ?? []).map(metric => metric.labelAnchor);
    const rawComplete = stats.rawMetrics?.length === entry.rawCount
      && new Set(rawIds).size === rawIds.length
      && stats.rawMetrics.every(metric => Number.isFinite(metric.rawValue)
        && metric.status === 'OBSERVED' && typeof metric.metricId === 'string');
    const displayComplete = stats.displayMetrics?.length === entry.displayCount
      && new Set(displayAnchors).size === displayAnchors.length
      && stats.displayMetrics.every(metric => metric.status === 'OBSERVED'
        && typeof metric.metricId === 'string' && typeof metric.displayValue === 'string');
    const cleanupVerified = ['source', 'replay'].every(side => {
      const cleanup = stats.cleanup?.[side];
      return cleanup?.status === 'PASS' && cleanup.activeLeases === 0
        && cleanup.currentContexts === 0 && cleanup.browserState === 'stopped'
        && cleanup.ownedProcessExited === true;
    });
    const networkVerified = ['source', 'replay'].every(side =>
      stats.network?.[side]?.externalEgressCompleted === 0);
    if (input.selection?.class !== entry.class || stats.input?.class !== entry.class
        || input.selection?.profileIndex !== entry.profileIndex
        || input.provenance?.snapshotManifestSha256 !== expectedManifestSha256
        || input.provenance?.runtimeAssetSha256 !== entry.runtimeAssetSha256
        || digest(Buffer.from(serialize(input.nativeState))) !== entry.nativeStateSha256
        || input.integrity?.nativeStateSha256 !== entry.nativeStateSha256
        || stats.schemaVersion !== entry.schemaVersion
        || stats.input?.buildSha256 !== entry.inputSha256
        || stats.input?.nativeStateSha256 !== entry.nativeStateSha256
        || stats.engine?.snapshotManifestSha256 !== expectedManifestSha256
        || stats.engine?.assetSha256 !== entry.runtimeAssetSha256
        || manifest.files?.[inputName]?.sha256 !== entry.inputSha256
        || manifest.files?.[statsName]?.sha256 !== entry.statsSha256
        || pair?.inputSha256 !== entry.inputSha256
        || pair?.outputSha256 !== entry.statsSha256
        || pair?.nativeStateSha256 !== entry.nativeStateSha256
        || sourceReplay !== 'EXACT'
        || !rawComplete || !displayComplete || !cleanupVerified || !networkVerified
        || !['G1', 'G2', 'G3', 'G4'].every(gate => stats.gates?.[gate]?.status === 'PASS')) {
      throw fail(ERROR_CODES.OUTPUT_NOT_LINKED,
        'reused fixture does not satisfy trusted class attestation', { class: entry.class });
    }
    results.push(Object.freeze({
      class: entry.class,
      slug: entry.fixture,
      mode: 'REUSED_VERIFIED',
      sourceUrl: entry.sourceUrl,
      profileIndex: input.selection.profileIndex,
      profileName: input.selection.profileName,
      inputSha256: digest(inputBytes),
      nativeStateSha256: input.integrity.nativeStateSha256,
      statsSha256: digest(statsBytes),
      rawCount: stats.coverage.rawCount,
      displayCount: stats.coverage.displayCount,
      sourceReplay,
      offlineExternalEgressCompleted: stats.network.replay.externalEgressCompleted,
      cleanup: cleanupVerified ? 'PASS' : 'FAIL',
      privateInputPath: inputPath,
      privateStatsPath: statsPath,
      durationMs: 0,
    }));
  }
  return results;
}

async function fetchNativeProfileWithChromium({ browserFactory, executablePath, parsedUrl,
  timeoutMs }) {
  const browser = browserFactory(executablePath);
  let lease;
  let ownedPid;
  let primaryError;
  let result;
  const cleanupFailures = [];
  try {
    await browser.start();
    ownedPid = browser.getStatus().pid;
    lease = await browser.acquire({ timeoutMs });
    await installReadOnlyPolicy(lease.page);
    const profileUrl = `https://planners.maxroll.gg/profiles/load/d4/${parsedUrl.plannerId}`;
    const response = await lease.page.goto(profileUrl, {
      waitUntil: 'domcontentloaded', timeout: timeoutMs,
    });
    if (!response || response.status() !== 200) {
      throw fail(ERROR_CODES.PROFILE_NOT_IN_SNAPSHOT,
        'online profile load did not return HTTP 200', { status: response?.status() ?? null });
    }
    const body = await response.body();
    const parsed = parseNativeResponse(body, parsedUrl.plannerId);
    result = Object.freeze({
      ...parsed,
      profileUrl,
      responseSha256: digest(body),
    });
  } catch (error) {
    primaryError = error;
  }
  for (const operation of [() => lease?.release(), () => browser.stop()]) {
    try { await operation(); } catch (error) { cleanupFailures.push(error); }
  }
  const status = browser.getStatus();
  const metrics = browser.getMetrics();
  if (status.state !== 'stopped' || status.pid !== null || status.activeLeases !== 0
      || metrics.currentContexts !== 0 || (ownedPid && !await processExited(ownedPid))) {
    cleanupFailures.push(new Error('online profile browser did not fully stop'));
  }
  if (primaryError || cleanupFailures.length) {
    const errors = [...(primaryError ? [primaryError] : []), ...cleanupFailures];
    throw errors.length === 1 ? errors[0] : new AggregateError(errors,
      'online profile acquisition and cleanup failed');
  }
  return result;
}

async function runOnlineCapture({ browserFactory, executablePath, profile, fixture, timeoutMs }) {
  const browser = browserFactory(executablePath);
  let lease;
  let observer;
  let ownedPid;
  let primaryError;
  let result;
  const cleanupFailures = [];
  try {
    await browser.start();
    ownedPid = browser.getStatus().pid;
    lease = await browser.acquire({ timeoutMs });
    await installReadOnlyPolicy(lease.page);
    observer = new MaxrollRuntimeAttestationObserver({
      lease,
      profile,
      nativeState: fixture.nativeState,
      profileIndex: fixture.selection.profileIndex,
    });
    await observer.initialize();
    result = await observer.capture({ navigateUrl: fixture.provenance.requestedUrl });
    validateCaptureEvidence(result, { requireZeroEgress: false });
  } catch (error) {
    primaryError = error;
  }
  for (const operation of [
    () => observer?.close(),
    () => lease?.release(),
    () => browser.stop(),
  ]) {
    try { await operation(); } catch (error) { cleanupFailures.push(error); }
  }
  const status = browser.getStatus();
  const metrics = browser.getMetrics();
  if (status.state !== 'stopped' || status.pid !== null || status.activeLeases !== 0
      || metrics.currentContexts !== 0 || (ownedPid && !await processExited(ownedPid))) {
    cleanupFailures.push(new Error('online source Chromium resources did not fully stop'));
  }
  if (primaryError || cleanupFailures.length) {
    const errors = [...(primaryError ? [primaryError] : []), ...cleanupFailures];
    throw errors.length === 1 ? errors[0] : new AggregateError(errors,
      'online source capture and cleanup failed');
  }
  return Object.freeze({
    ...result,
    cleanup: Object.freeze({ status: 'PASS', browserState: status.state,
      activeLeases: status.activeLeases, currentContexts: metrics.currentContexts,
      ownedProcessExited: true }),
  });
}

async function readDisplayInventoryWithChromium({ browserFactory, executablePath, sourceUrl,
  timeoutMs }) {
  const browser = browserFactory(executablePath);
  let lease;
  let ownedPid;
  let primaryError;
  let result;
  const cleanupFailures = [];
  try {
    await browser.start();
    ownedPid = browser.getStatus().pid;
    lease = await browser.acquire({ timeoutMs });
    await installReadOnlyPolicy(lease.page);
    await lease.page.goto(sourceUrl, { waitUntil: 'domcontentloaded', timeout: timeoutMs });
    await lease.page.getByRole('button', { name: 'New Profile', exact: true })
      .waitFor({ state: 'visible', timeout: timeoutMs });
    await lease.page.waitForFunction(selector => {
      const sections = [...document.querySelectorAll(selector)];
      return sections.reduce((count, section) => count + section.querySelectorAll('li').length, 0)
        >= 40;
    }, 'div[class*="stats_StatSection"]', { timeout: timeoutMs });
    result = await lease.page.evaluate(selector => {
      const rows = [...document.querySelectorAll(selector)].flatMap(section => {
        const sectionLabel = (section.querySelector('h3')?.textContent ?? '').trim();
        return [...section.querySelectorAll('li')].map(row => ({
          section: sectionLabel,
          label: (row.querySelector(':scope > span')?.textContent ?? '').trim(),
        })).filter(row => row.label);
      });
      return { rowCount: rows.length, labels: [...new Set(rows.map(row => row.label))], rows };
    }, 'div[class*="stats_StatSection"]');
  } catch (error) {
    primaryError = error;
  }
  for (const operation of [() => lease?.release(), () => browser.stop()]) {
    try { await operation(); } catch (error) { cleanupFailures.push(error); }
  }
  const status = browser.getStatus();
  const metrics = browser.getMetrics();
  if (status.state !== 'stopped' || status.pid !== null || status.activeLeases !== 0
      || metrics.currentContexts !== 0 || (ownedPid && !await processExited(ownedPid))) {
    cleanupFailures.push(new Error('display inventory Chromium resources did not fully stop'));
  }
  if (primaryError || cleanupFailures.length) {
    const errors = [...(primaryError ? [primaryError] : []), ...cleanupFailures];
    throw errors.length === 1 ? errors[0] : new AggregateError(errors,
      'display inventory and cleanup failed');
  }
  return Object.freeze({ rowCount: result.rowCount,
    labels: Object.freeze(result.labels), rows: Object.freeze(result.rows) });
}

function findSnapshotProfileRoute(manifest) {
  const resources = manifest.resources.filter(resource =>
    resource.method === 'GET'
      && /^https:\/\/planners\.maxroll\.gg\/profiles\/load\/d4\/[A-Za-z0-9]+$/.test(resource.url));
  if (resources.length !== 1) {
    throw fail(ERROR_CODES.SNAPSHOT_MISMATCH,
      'approved snapshot must contain exactly one native profile route', {
        observedRoutes: resources.map(resource => resource.url),
      });
  }
  return resources[0].url;
}

function createStatsOutput({ fixture, source, replay, comparison, snapshot }) {
  return {
    schemaVersion: CLASS_FIXTURE_SCHEMA_VERSION,
    status: 'OBSERVED',
    capturedAt: new Date().toISOString(),
    input: {
      buildSha256: digest(Buffer.from(serialize(fixture))),
      nativeStateSha256: fixture.integrity.nativeStateSha256,
      class: fixture.selection.class,
      profileIndex: fixture.selection.profileIndex,
      profileName: fixture.selection.profileName,
      level: fixture.selection.level,
      sourceUrl: fixture.provenance.sourceUrl,
    },
    engine: {
      gamePatch: MAXROLL_32173552_D12AM6KT_REFERENCE.gamePatch,
      assetPath: MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetPath,
      assetSha256: MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetSha256,
      snapshotId: snapshot.snapshotPackage.manifest.snapshotId,
      snapshotManifestSha256: snapshot.verified.manifestSha256,
    },
    gates: {
      G1: { status: 'PASS', manifestSha256: snapshot.verified.manifestSha256 },
      G2: { status: 'PASS', source: source.engine, replay: replay.engine },
      G3: { status: 'PASS', source: source.profileReadback, replay: replay.profileReadback },
      G4: { status: 'PASS', source: source.phase, replay: replay.phase },
    },
    rawMetrics: source.rawMetrics,
    displayMetrics: source.displayMetrics,
    coverage: { rawCount: source.rawMetrics.length, displayCount: source.displayMetrics.length },
    fingerprints: {
      rawMetricsSha256: comparison.rawSha256,
      displayMetricsSha256: comparison.displaySha256,
    },
    sourceReplay: comparison,
    network: {
      source: { ...source.network, mode: 'ONLINE_READ_ONLY' },
      replay: { ...replay.network, mode: 'OFFLINE_STRICT' },
    },
    cleanup: { source: source.cleanup, replay: replay.cleanup },
  };
}

class MaxrollClassFixtureCapturer {
  #dependencies;

  constructor(dependencies = {}) {
    this.#dependencies = {
      browserFactory: executablePath => new BrowserInfrastructure({
        executablePath, headless: true, maxContexts: 1, maxQueue: 1,
        contextOptions: { serviceWorkers: 'block' },
      }),
      storeFactory: rootDir => new FileSystemSnapshotStore({ rootDir }),
      ...dependencies,
    };
  }

  async capture(options) {
    validateOptions(options);
    const outputRoot = path.resolve(options.outputRoot);
    try {
      await fs.access(outputRoot);
      throw fail(ERROR_CODES.OUTPUT_EXISTS,
        'fixture output folder already exists; overwrite is disabled', { outputRoot });
    } catch (error) {
      if (error instanceof MaxrollProviderError) throw error;
      if (error?.code !== 'ENOENT') throw error;
    }
    const store = this.#dependencies.storeFactory(options.snapshotRoot);
    const manifest = await store.load(options.snapshotId);
    const snapshot = await verifiedSnapshot({
      ...options,
      store,
      sourceUrl: manifest.sourceUrl,
      assetUrl: `https://maxroll.gg${MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetPath}`,
      assetSha256: MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetSha256,
    });
    const replayProfileUrl = findSnapshotProfileRoute(snapshot.snapshotPackage.manifest);
    const replayPlannerId = replayProfileUrl.split('/').at(-1);
    const results = [];
    await fs.mkdir(outputRoot, { recursive: false, mode: 0o700 });
    for (const entry of options.matrix.fixtures) {
      const started = Date.now();
      const parsedUrl = parsePlannerUrl(entry.url);
      const native = await fetchNativeProfileWithChromium({
        browserFactory: this.#dependencies.browserFactory,
        executablePath: options.chromiumExecutablePath,
        parsedUrl,
        timeoutMs: options.timeoutMs ?? 60_000,
      });
      const fixture = createNativeBuildExport({
        response: native.response,
        state: native.state,
        parsedUrl,
        profile: entry.profile,
        provenance: {
          source: 'MAXROLL_ONLINE_READ_ONLY',
          sourceResponseSha256: native.responseSha256,
          snapshotId: options.snapshotId,
          snapshotManifestSha256: options.expectedManifestSha256,
          runtimeVersion: MAXROLL_32173552_D12AM6KT_REFERENCE.gamePatch,
          runtimeAssetUrl:
            `https://maxroll.gg${MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetPath}`,
          runtimeAssetSha256: MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetSha256,
        },
      });
      if (fixture.selection.class !== entry.class || fixture.selection.level !== 70) {
        throw fail(ERROR_CODES.READBACK_MISMATCH,
          'source class or level does not match the fixture matrix', {
            expected: { class: entry.class, level: 70 },
            actual: { class: fixture.selection.class, level: fixture.selection.level },
          });
      }
      const displayInventory = await readDisplayInventoryWithChromium({
        browserFactory: this.#dependencies.browserFactory,
        executablePath: options.chromiumExecutablePath,
        sourceUrl: fixture.provenance.requestedUrl,
        timeoutMs: options.timeoutMs ?? 60_000,
      });
      const sourceProfile = createMaxroll32173552D12aM6KTCandidateProfile({
        snapshotId: options.snapshotId,
        snapshotManifestSha256: options.expectedManifestSha256,
        sourceUrl: parsedUrl.sourceUrl,
        assetUrl: `https://maxroll.gg${MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetPath}`,
        metricCatalog: METRIC_CATALOG.slice(0, entry.expectedRawMetrics),
        authorizationRef: 'issue-134-owner-approved-multiclass-source-capture',
        realRuntime: {
          discoverMetricCatalog: true,
          metricLabelAllowlist: displayInventory.labels,
          expectedRawMetrics: entry.expectedRawMetrics,
        },
      });
      const source = await runOnlineCapture({
        browserFactory: this.#dependencies.browserFactory,
        executablePath: options.chromiumExecutablePath,
        profile: sourceProfile,
        fixture,
        timeoutMs: options.timeoutMs ?? 60_000,
      });
      const replayProfile = createMaxroll32173552D12aM6KTCandidateProfile({
        snapshotId: options.snapshotId,
        snapshotManifestSha256: options.expectedManifestSha256,
        sourceUrl: snapshot.snapshotPackage.manifest.sourceUrl,
        assetUrl: `https://maxroll.gg${MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetPath}`,
        metricCatalog: source.rawMetrics.map(metric => Object.freeze({
          id: metric.metricId,
          internalId: metric.internalId,
          category: metric.category,
          name: metric.label,
          rawValueType: 'finite-number',
        })),
        authorizationRef: 'issue-134-approved-offline-snapshot',
        realRuntime: { expectedRawMetrics: source.rawMetrics.length },
      });
      const replayFixture = structuredClone(fixture);
      replayFixture.provenance.sourceUrl = snapshot.snapshotPackage.manifest.sourceUrl;
      replayFixture.provenance.plannerId = replayPlannerId;
      const replay = await runCapture({
        options: { ...options, store }, fixture: replayFixture, snapshot,
        profile: replayProfile, mode: 'replay',
      });
      const comparison = compareCaptures(source, replay, { sourceOnline: true });
      const stats = createStatsOutput({ fixture, source, replay, comparison, snapshot });
      const sourceEvidence = {
        schemaVersion: 'maxroll-class-fixture-source-evidence/v1',
        capturedAt: stats.capturedAt,
        source: {
          url: entry.url,
          class: fixture.selection.class,
          profileIndex: fixture.selection.profileIndex,
          profileName: fixture.selection.profileName,
          sourceResponseSha256: fixture.provenance.sourceResponseSha256,
        },
        policy: {
          browserContext: 'FRESH_ANONYMOUS',
          allowedMethods: ['GET', 'HEAD'],
          allowedOrigins: [...ONLINE_ALLOWED_ORIGINS],
          loginUsed: false,
          saveOrPublishUsed: false,
        },
        engine: source.engine,
        semanticReadback: source.profileReadback,
        calculationPhase: source.phase,
        displayInventory,
        network: source.network,
        cleanup: source.cleanup,
      };
      const fixtureBytes = Buffer.from(serialize(fixture));
      const statsBytes = Buffer.from(serialize(stats));
      const evidenceBytes = Buffer.from(serialize(sourceEvidence));
      const fixturePath = path.join(outputRoot, `${entry.slug}.json`);
      const statsPath = path.join(outputRoot, `${entry.slug}.stats.json`);
      const evidencePath = path.join(outputRoot, `${entry.slug}.source-evidence.json`);
      await writeAtomicExclusive(fixturePath, fixtureBytes);
      await writeAtomicExclusive(statsPath, statsBytes);
      await writeAtomicExclusive(evidencePath, evidenceBytes);
      results.push(Object.freeze({
        class: entry.class,
        slug: entry.slug,
        sourceUrl: entry.url,
        profileIndex: fixture.selection.profileIndex,
        profileName: fixture.selection.profileName,
        inputSha256: digest(fixtureBytes),
        nativeStateSha256: fixture.integrity.nativeStateSha256,
        statsSha256: digest(statsBytes),
        sourceEvidenceSha256: digest(evidenceBytes),
        rawCount: stats.coverage.rawCount,
        displayCount: stats.coverage.displayCount,
        sourceDisplayRowCount: displayInventory.rowCount,
        sourceReplay: comparison.status,
        offlineExternalEgressCompleted: replay.network.externalEgressCompleted,
        cleanup: source.cleanup.status === 'PASS' && replay.cleanup.status === 'PASS'
          ? 'PASS' : 'FAIL',
        durationMs: Date.now() - started,
      }));
    }
    const reused = await verifiedReuseFixtures(options.matrix, options.reuseRoot,
      options.expectedManifestSha256);
    const allResults = [...results, ...reused];
    if (new Set(allResults.map(result => result.class)).size !== allResults.length) {
      throw fail(ERROR_CODES.INVALID_INPUT, 'captured and reused fixture classes overlap');
    }
    const report = {
      schemaVersion: MATRIX_SCHEMA_VERSION,
      status: allResults.length === options.matrix.fixtures.length + (options.matrix.reuse?.length ?? 0)
        ? 'PASS' : 'PARTIAL',
      capturedAt: new Date().toISOString(),
      snapshotId: options.snapshotId,
      snapshotManifestSha256: options.expectedManifestSha256,
      engineAssetSha256: MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetSha256,
      classCoverage: { numerator: allResults.length, denominator: ALLOWED_CLASSES.size,
        percent: (allResults.length / ALLOWED_CLASSES.size) * 100 },
      fixtures: allResults,
    };
    const reportBytes = Buffer.from(serialize(report));
    await writeAtomicExclusive(path.join(outputRoot, 'fixture-matrix.json'), reportBytes);
    const checksums = [...results.flatMap(result => [
      `${result.inputSha256}  ${result.slug}.json`,
      `${result.statsSha256}  ${result.slug}.stats.json`,
      `${result.sourceEvidenceSha256}  ${result.slug}.source-evidence.json`,
    ]), `${digest(reportBytes)}  fixture-matrix.json`].join('\n') + '\n';
    await writeAtomicExclusive(path.join(outputRoot, 'manifest.sha256'), Buffer.from(checksums));
    return Object.freeze({ outputRoot, ...report });
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
  ALLOWED_CLASSES,
  CLASS_FIXTURE_SCHEMA_VERSION,
  MATRIX_SCHEMA_VERSION,
  MaxrollClassFixtureCapturer,
  fetchNativeProfileWithChromium,
  installReadOnlyPolicy,
  readDisplayInventoryWithChromium,
  runOnlineCapture,
  validateMatrix,
  verifiedReuseFixtures,
};
