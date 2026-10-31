'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const fsPromises = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const {
  BrowserInfrastructure,
  FileSystemSnapshotStore,
  WebSnapshotManager,
} = require('@streamops/browser-infrastructure');
const { chromium } = require('playwright-core');
const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const { METRIC_CATALOG } = require('./metric-catalog');
const { RealMaxrollMetricsExtractor } = require('./real-metrics-extractor');
const { RealMaxrollRuntimeAdapter } = require('./real-runtime-adapter');
const {
  MAXROLL_32173552_REFERENCE,
  createMaxroll32173552RealProfile,
} = require('./real-profile');
const { sha256 } = require('./value');

const LIVE_SOURCE_URL = 'https://maxroll.gg/d4/planner/1g1any0x#3';
const LIVE_ALLOWED_ORIGINS = Object.freeze([
  'https://maxroll.gg',
  'https://assets-ng.maxroll.gg',
  'https://planners.maxroll.gg',
]);
const OWNER_POLICY_REFERENCE = 'StreamOps#132-owner-directive-2026-10-23';
const LIVE_BASE_BUILD = Object.freeze({
  class: 'Rogue',
  level: 50,
  difficulty: 'Torment I',
  equipment: Object.freeze({
    Helm: Object.freeze({ itemId: 'runic-skullcap', modifiers: Object.freeze([]) }),
  }),
});
const LIVE_MODIFIED_BUILD = Object.freeze({
  ...LIVE_BASE_BUILD,
  equipment: Object.freeze({
    Helm: Object.freeze({
      itemId: 'runic-skullcap', modifiers: Object.freeze(['of-dampening']),
    }),
  }),
});

const LIVE_CAPTURE_ERROR_CODES = Object.freeze({
  BROWSER_UNAVAILABLE: 'BROWSER_UNAVAILABLE',
  SITE_UNREACHABLE: 'SITE_UNREACHABLE',
  CAPTURE_INCOMPLETE: 'CAPTURE_INCOMPLETE',
  PATCH_DRIFT: 'PATCH_DRIFT',
  ASSET_HASH_MISMATCH: 'ASSET_HASH_MISMATCH',
  MANIFEST_INVALID: 'MANIFEST_INVALID',
  OFFLINE_EGRESS: 'OFFLINE_EGRESS',
  REAL_E2E_FAILED: 'REAL_E2E_FAILED',
  TIMEOUT: 'TIMEOUT',
  CANCELLED: 'CANCELLED',
  CLEANUP_FAILED: 'CLEANUP_FAILED',
});

class LiveCaptureError extends Error {
  constructor(code, message, options = {}) {
    super(message, options.cause ? { cause: options.cause } : undefined);
    this.name = 'LiveCaptureError';
    this.code = code;
    this.details = options.details ? Object.freeze({ ...options.details }) : undefined;
  }
}

function discoverBrowser(env = process.env) {
  const candidates = [
    env.BROWSER_INFRA_CHROMIUM_PATH,
    ...['chromium', 'chromium-browser', 'google-chrome', 'google-chrome-stable']
      .map(command => spawnSync('sh', ['-c', `command -v ${command}`], {
        encoding: 'utf8', timeout: 2_000,
      }).stdout?.trim()),
    chromium.executablePath(),
  ].filter(Boolean);
  return candidates.find(candidate => {
    try { fs.accessSync(candidate, fs.constants.X_OK); return true; } catch { return false; }
  }) ?? null;
}

function sanitizedFailure(error) {
  const result = {
    code: error?.code ?? 'UNEXPECTED_ERROR',
    name: error?.name ?? 'Error',
    message: String(error?.message ?? error).replace(/([?&](?:token|key|auth|session)=[^&\s]+)/gi,
      '[REDACTED]'),
  };
  if (error?.cause) {
    result.cause = {
      code: error.cause.code ?? 'UNEXPECTED_ERROR',
      name: error.cause.name ?? 'Error',
      message: String(error.cause.message ?? error.cause)
        .replace(/([?&](?:token|key|auth|session)=[^&\s]+)/gi, '[REDACTED]'),
    };
  }
  return Object.freeze(result);
}

function junit(report) {
  const failed = report.status !== 'PASS';
  const message = failed
    ? String(report.failure?.message ?? report.status).replace(/[<>&"]/g, character => ({
      '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;',
    })[character]) : '';
  return `<?xml version="1.0" encoding="UTF-8"?>\n` +
    `<testsuite name="maxroll-live-capture" tests="1" failures="${failed ? 1 : 0}">` +
    `<testcase name="online-capture-to-offline-real-e2e" time="${(report.durationMs / 1000).toFixed(3)}">` +
    `${failed ? `<failure message="${message}"/>` : ''}</testcase></testsuite>\n`;
}

async function defaultCaptureInteraction({ page }, { profile }) {
  await page.getByRole('button', {
    name: profile.realRuntime.newProfileButton,
    exact: true,
  }).waitFor({
    state: 'visible',
    timeout: profile.realRuntime.navigationTimeoutMs ?? 30_000,
  });
  const preflight = await page.evaluate(({ patchPattern }) => {
    const body = document.body?.innerText ?? '';
    return {
      gamePatch: body.match(new RegExp(patchPattern))?.[1]?.trim() ?? null,
      exportAssetUrls: performance.getEntriesByType('resource')
        .map(entry => entry.name)
        .filter(url => {
          try { return new URL(url).pathname.startsWith('/assets/export-'); } catch { return false; }
        }),
    };
  }, { patchPattern: profile.realRuntime.gamePatchPattern });
  if (preflight.gamePatch !== profile.gamePatch ||
      !preflight.exportAssetUrls.some(url => {
        const observed = new URL(url);
        const expected = new URL(profile.assetUrl);
        return observed.origin === expected.origin && observed.pathname === expected.pathname;
      })) {
    return Object.freeze({
      gamePatch: preflight.gamePatch,
      runtimeVersion: null,
      breakpointLocations: 0,
      phases: Object.freeze([]),
      observedExportAssetUrls: Object.freeze(preflight.exportAssetUrls),
      driftDetected: true,
    });
  }
  const lease = {
    valid: true,
    page,
    context: page.context(),
    createCDPSession: () => page.context().newCDPSession(page),
  };
  const adapter = new RealMaxrollRuntimeAdapter({ lease, profile });
  const extractor = new RealMaxrollMetricsExtractor(profile);
  try {
    const identity = await adapter.initialize();
    const phases = [];
    for (const build of [LIVE_BASE_BUILD, LIVE_MODIFIED_BUILD, LIVE_BASE_BUILD]) {
      const fingerprint = sha256(build);
      const applied = await adapter.apply(build, fingerprint);
      const metrics = await extractor.extract(adapter, applied);
      phases.push(Object.freeze({
        inputFingerprint: fingerprint,
        rawCount: metrics.length,
        displayCount: metrics.filter(metric => metric.displayValue !== null).length,
        outputSha256: sha256(metrics.map(metric => metric.rawValue)),
      }));
    }
    return Object.freeze({
      gamePatch: identity.gamePatch,
      runtimeVersion: profile.runtimeVersion,
      breakpointLocations: identity.breakpointLocations,
      phases: Object.freeze(phases),
      observedExportAssetUrls: Object.freeze(preflight.exportAssetUrls),
      driftDetected: false,
    });
  } finally {
    await adapter.close().catch(() => {});
  }
}

function defaultRealTestRunner({ packageRoot, env, timeoutMs }) {
  const acceptancePath = path.join(packageRoot, 'artifacts', 'real-acceptance.json');
  fs.rmSync(acceptancePath, { force: true });
  const result = spawnSync('npm', ['run', 'test:real'], {
    cwd: packageRoot,
    env: { ...process.env, ...env },
    encoding: 'utf8',
    stdio: ['ignore', 'inherit', 'inherit'],
    timeout: timeoutMs,
  });
  let acceptance = null;
  try { acceptance = JSON.parse(fs.readFileSync(acceptancePath, 'utf8')); } catch {}
  return Object.freeze({
    exitCode: result.status,
    signal: result.signal,
    error: result.error ? sanitizedFailure(result.error) : null,
    acceptance,
  });
}

class MaxrollLiveCaptureOrchestrator {
  #dependencies;

  constructor(dependencies = {}) {
    this.#dependencies = {
      browserFactory: executablePath => new BrowserInfrastructure({
        executablePath,
        headless: true,
        maxContexts: 1,
        maxQueue: 1,
        contextOptions: { serviceWorkers: 'block' },
      }),
      managerFactory: (browser, rootDir) => new WebSnapshotManager({
        browser,
        store: new FileSystemSnapshotStore({ rootDir }),
      }),
      captureInteraction: defaultCaptureInteraction,
      realTestRunner: defaultRealTestRunner,
      makeTemporaryRoot: base => fsPromises.mkdtemp(path.join(base, 'maxroll-live-')),
      cleanup: root => fsPromises.rm(root, { recursive: true, force: true }),
      writeFile: (filename, contents) => fsPromises.writeFile(filename, contents),
      mkdir: directory => fsPromises.mkdir(directory, { recursive: true }),
      ...dependencies,
    };
  }

  async run(options = {}) {
    const started = Date.now();
    const packageRoot = options.packageRoot ?? path.resolve(__dirname, '..');
    const artifactsDir = options.artifactsDir ?? path.join(packageRoot, 'artifacts');
    const reportPath = path.join(artifactsDir, 'live-capture-real.json');
    const junitPath = path.join(artifactsDir, 'live-capture-real.junit.xml');
    const executablePath = options.executablePath ?? discoverBrowser(options.env);
    const sourceUrl = options.sourceUrl ?? LIVE_SOURCE_URL;
    const snapshotId = options.snapshotId ??
      `maxroll-live-${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const temporaryBase = options.temporaryBase ?? process.env.RUNNER_TEMP ?? os.tmpdir();
    const report = {
      schemaVersion: 'maxroll-live-capture-e2e/1',
      status: 'RUNNING',
      startedAt: new Date(started).toISOString(),
      nodeVersion: process.version,
      browser: { executablePath: executablePath ?? null, version: null },
      policy: {
        authorizationRef: OWNER_POLICY_REFERENCE,
        readOnlyMethods: ['GET', 'HEAD'],
        allowedOrigins: [...LIVE_ALLOWED_ORIGINS],
        loginUsed: false,
        saveOrPublishUsed: false,
      },
      capture: null,
      runtime: {
        expectedPatch: MAXROLL_32173552_REFERENCE.gamePatch,
        expectedAssetPath: MAXROLL_32173552_REFERENCE.applicationAssetPath,
        expectedAssetSha256: MAXROLL_32173552_REFERENCE.applicationAssetSha256,
      },
      offline: null,
      cleanup: 'PENDING',
    };
    let temporaryRoot = null;
    let browser = null;
    let failure = null;
    try {
      if (!executablePath) {
        throw new LiveCaptureError(LIVE_CAPTURE_ERROR_CODES.BROWSER_UNAVAILABLE,
          'no compatible preinstalled Chromium/Chrome executable was found');
      }
      if (Number(process.versions.node.split('.')[0]) < 20) {
        throw new LiveCaptureError(LIVE_CAPTURE_ERROR_CODES.BROWSER_UNAVAILABLE,
          'Node.js 20 or newer is required');
      }
      temporaryRoot = await this.#dependencies.makeTemporaryRoot(temporaryBase);
      browser = this.#dependencies.browserFactory(executablePath);
      await browser.start();
      report.browser.version = await browser.withLease({}, lease =>
        lease.context.browser()?.version() ?? null);
      const snapshots = this.#dependencies.managerFactory(browser, temporaryRoot);
      const captureProfile = createMaxroll32173552RealProfile({
        snapshotId,
        snapshotManifestSha256: '0'.repeat(64),
        sourceUrl,
        authorizationRef: OWNER_POLICY_REFERENCE,
        metricCatalog: METRIC_CATALOG,
      });
      let onlineObservation = null;
      let draft;
      try {
        draft = await snapshots.capture({
          snapshotId,
          site: 'maxroll-d4-planner',
          version: MAXROLL_32173552_REFERENCE.gamePatch,
          url: sourceUrl,
          allowedOrigins: LIVE_ALLOWED_ORIGINS,
          timeoutMs: options.captureTimeoutMs ?? 180_000,
          maxResources: 2_000,
          maxResourceBytes: 40 * 1024 * 1024,
          maxTotalBytes: 128 * 1024 * 1024,
          capturePolicy: {
            allowResource: ({ method, resourceType, url }) => {
              const parsed = new URL(url);
              return ['GET', 'HEAD'].includes(method) && resourceType !== 'media' &&
                !(parsed.origin === 'https://planners.maxroll.gg' &&
                  parsed.pathname === '/users/whoami');
            },
            // BrowserInfrastructure creates a fresh context for every lease. This mode does not
            // inspect or persist browser-managed anonymous cookies and the hook performs no login.
            requestHeaderPolicy: 'fresh-anonymous-context',
            navigationWaitUntil: 'domcontentloaded',
            settleWaitUntil: 'domcontentloaded',
            responseBodyTimeoutMs: 15_000,
          },
          interact: async context => {
            onlineObservation = await this.#dependencies.captureInteraction(context, {
              profile: captureProfile,
            });
          },
          signal: options.signal,
        });
      } catch (error) {
        throw this.#mapCaptureFailure(error);
      }
      await snapshots.save(draft);
      let verification;
      let manifest;
      try {
        verification = await snapshots.verify(snapshotId);
        manifest = await snapshots.load(snapshotId);
      } catch (error) {
        throw new LiveCaptureError(LIVE_CAPTURE_ERROR_CODES.MANIFEST_INVALID,
          'saved snapshot failed immutable manifest/resource verification', { cause: error });
      }
      const runtimeAsset = manifest.resources.find(resource =>
        resource.url === captureProfile.assetUrl);
      const observedExportAssets = manifest.resources
        .filter(resource => new URL(resource.url).pathname.startsWith('/assets/export-'))
        .map(resource => Object.freeze({
          path: new URL(resource.url).pathname,
          sha256: resource.sha256,
          size: resource.size,
        }));
      report.capture = {
        snapshotId,
        manifestSha256: verification.manifestSha256,
        resourceCount: verification.resourceCount,
        totalBytes: verification.totalBytes,
        durationMs: draft.capture?.durationMs ?? null,
        blockedRequestCount: draft.capture?.blockedRequestCount ?? null,
        observedExportAssets,
      };
      report.runtime.observedPatch = onlineObservation?.gamePatch ?? null;
      report.runtime.breakpointLocations = onlineObservation?.breakpointLocations ?? 0;
      report.runtime.onlinePhases = onlineObservation?.phases ?? [];
      report.runtime.driftDetected = onlineObservation?.driftDetected ?? null;
      if (onlineObservation?.gamePatch !== MAXROLL_32173552_REFERENCE.gamePatch) {
        throw new LiveCaptureError(LIVE_CAPTURE_ERROR_CODES.PATCH_DRIFT,
          'observed Maxroll game patch does not match the independently pinned profile', {
            details: { observedPatch: onlineObservation?.gamePatch ?? null },
          });
      }
      if (!runtimeAsset) {
        const hasDifferentExportAsset = observedExportAssets.length > 0;
        throw new LiveCaptureError(hasDifferentExportAsset
          ? LIVE_CAPTURE_ERROR_CODES.PATCH_DRIFT
          : LIVE_CAPTURE_ERROR_CODES.CAPTURE_INCOMPLETE,
        hasDifferentExportAsset
          ? 'Maxroll calculation asset identity drifted from the pinned profile'
          : 'pinned calculation runtime asset was not captured', {
            details: { observedExportAssets },
          });
      }
      report.runtime.observedAssetSha256 = runtimeAsset.sha256;
      if (runtimeAsset.sha256 !== MAXROLL_32173552_REFERENCE.applicationAssetSha256) {
        throw new LiveCaptureError(LIVE_CAPTURE_ERROR_CODES.ASSET_HASH_MISMATCH,
          'calculation runtime asset hash differs from the independent trust anchor', {
            details: { observedAssetSha256: runtimeAsset.sha256 },
          });
      }
      if (onlineObservation.breakpointLocations < 1) {
        throw new LiveCaptureError(LIVE_CAPTURE_ERROR_CODES.PATCH_DRIFT,
          'pinned CDP breakpoint did not resolve in the observed runtime');
      }
      await browser.stop();
      browser = null;
      const runner = await this.#dependencies.realTestRunner({
        packageRoot,
        timeoutMs: options.realTestTimeoutMs ?? 360_000,
        env: {
          BROWSER_INFRA_CHROMIUM_PATH: executablePath,
          MAXROLL_AUTHORIZED_SNAPSHOT_ROOT: temporaryRoot,
          MAXROLL_AUTHORIZED_SNAPSHOT_ID: snapshotId,
          MAXROLL_AUTHORIZED_MANIFEST_SHA256: verification.manifestSha256,
          MAXROLL_SNAPSHOT_AUTHORIZATION_REF: OWNER_POLICY_REFERENCE,
          MAXROLL_SOURCE_URL: sourceUrl,
        },
      });
      report.offline = runner.acceptance;
      if (runner.exitCode !== 0 || runner.acceptance?.status !== 'PASS') {
        throw new LiveCaptureError(LIVE_CAPTURE_ERROR_CODES.REAL_E2E_FAILED,
          'offline real Maxroll test suite did not pass', {
            details: { exitCode: runner.exitCode, signal: runner.signal },
          });
      }
      if (runner.acceptance.externalEgressCompleted !== 0 ||
          runner.acceptance.transportOfflineEveryEvaluation !== true) {
        throw new LiveCaptureError(LIVE_CAPTURE_ERROR_CODES.OFFLINE_EGRESS,
          'offline-strict evidence did not prove zero external egress');
      }
      report.status = 'PASS';
    } catch (error) {
      failure = error instanceof LiveCaptureError ? error :
        new LiveCaptureError(LIVE_CAPTURE_ERROR_CODES.CAPTURE_INCOMPLETE,
          'live-capture orchestration failed', { cause: error });
      report.status = failure.code;
      report.failure = sanitizedFailure(failure);
    } finally {
      if (browser) await browser.stop().catch(error => {
        report.browserCleanupFailure = sanitizedFailure(error);
      });
      if (temporaryRoot) {
        try {
          await this.#dependencies.cleanup(temporaryRoot);
          report.cleanup = 'PASS';
        } catch (error) {
          report.cleanup = 'FAIL';
          report.cleanupFailure = sanitizedFailure(error);
          if (!failure) {
            failure = new LiveCaptureError(LIVE_CAPTURE_ERROR_CODES.CLEANUP_FAILED,
              'ephemeral snapshot cleanup failed', { cause: error });
            report.status = failure.code;
            report.failure = sanitizedFailure(failure);
          }
        }
      } else {
        report.cleanup = 'NOT_CREATED';
      }
      report.durationMs = Date.now() - started;
      report.finishedAt = new Date().toISOString();
      await this.#dependencies.mkdir(artifactsDir);
      await this.#dependencies.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`);
      await this.#dependencies.writeFile(junitPath, junit(report));
    }
    if (failure) {
      failure.report = Object.freeze(structuredClone(report));
      throw failure;
    }
    return Object.freeze(structuredClone(report));
  }

  #mapCaptureFailure(error) {
    if (error instanceof MaxrollProviderError) {
      if (error.code === ERROR_CODES.RUNTIME_MISMATCH) {
        return new LiveCaptureError(LIVE_CAPTURE_ERROR_CODES.PATCH_DRIFT,
          'live runtime identity, selector or CDP breakpoint drifted', { cause: error });
      }
      if (error.code === ERROR_CODES.READBACK_MISMATCH) {
        return new LiveCaptureError(LIVE_CAPTURE_ERROR_CODES.CAPTURE_INCOMPLETE,
          'live read-back did not match the requested disposable state', { cause: error });
      }
      return new LiveCaptureError(LIVE_CAPTURE_ERROR_CODES.CAPTURE_INCOMPLETE,
        'live calculation-critical interaction failed', { cause: error });
    }
    if (error?.code === 'CAPTURE_TIMEOUT') {
      return new LiveCaptureError(LIVE_CAPTURE_ERROR_CODES.TIMEOUT,
        'live capture timed out', { cause: error });
    }
    if (error?.code === 'CAPTURE_CANCELLED' || error?.name === 'AbortError') {
      return new LiveCaptureError(LIVE_CAPTURE_ERROR_CODES.CANCELLED,
        'live capture was cancelled', { cause: error });
    }
    if (['ENOTFOUND', 'ECONNREFUSED', 'ERR_NAME_NOT_RESOLVED'].includes(error?.code)
        || /ERR_NAME_NOT_RESOLVED|net::ERR_|unreachable/i.test(error?.message ?? '')) {
      return new LiveCaptureError(LIVE_CAPTURE_ERROR_CODES.SITE_UNREACHABLE,
        'Maxroll public planner was unreachable', { cause: error });
    }
    return new LiveCaptureError(LIVE_CAPTURE_ERROR_CODES.CAPTURE_INCOMPLETE,
      'live snapshot capture failed', { cause: error });
  }
}

module.exports = {
  LIVE_ALLOWED_ORIGINS,
  LIVE_BASE_BUILD,
  LIVE_CAPTURE_ERROR_CODES,
  LIVE_MODIFIED_BUILD,
  LIVE_SOURCE_URL,
  LiveCaptureError,
  MaxrollLiveCaptureOrchestrator,
  OWNER_POLICY_REFERENCE,
  discoverBrowser,
};
