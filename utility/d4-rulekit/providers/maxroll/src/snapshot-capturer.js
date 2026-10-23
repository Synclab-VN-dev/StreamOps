'use strict';

const crypto = require('node:crypto');
const fsPromises = require('node:fs/promises');
const path = require('node:path');
const {
  BrowserInfrastructure,
  FileSystemSnapshotStore,
  WebSnapshotManager,
} = require('@streamops/browser-infrastructure');
const {
  LIVE_ALLOWED_ORIGINS,
  LIVE_SOURCE_URL,
  OWNER_POLICY_REFERENCE,
  discoverBrowser,
} = require('./live-capture-orchestrator');
const {
  MAXROLL_32173552_REFERENCE,
  createMaxroll32173552RealProfile,
} = require('./real-profile');
const { METRIC_CATALOG } = require('./metric-catalog');

const CAPTURE_STATUS = Object.freeze({
  CAPTURED_UNVALIDATED: 'CAPTURED_UNVALIDATED',
  PATCH_DRIFT: 'PATCH_DRIFT',
  PIN_MATCH_UNVALIDATED: 'PIN_MATCH_UNVALIDATED',
  REAL_E2E_NOT_RUN: 'NOT_RUN',
});

class MaxrollSnapshotCaptureError extends Error {
  constructor(code, message, options = {}) {
    super(message, options.cause ? { cause: options.cause } : undefined);
    this.name = 'MaxrollSnapshotCaptureError';
    this.code = code;
    this.details = options.details ? Object.freeze({ ...options.details }) : undefined;
  }
}

function digest(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function assertOutputPath(value) {
  if (typeof value !== 'string' || value.trim().length === 0) {
    throw new MaxrollSnapshotCaptureError('INVALID_OUTPUT',
      'snapshot capture requires --output <folder>');
  }
  const outputPath = path.resolve(value);
  const snapshotId = path.basename(outputPath);
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(snapshotId) || snapshotId.includes('..')) {
    throw new MaxrollSnapshotCaptureError('INVALID_OUTPUT',
      'output folder name must be a safe snapshot identifier');
  }
  return Object.freeze({ outputPath, rootDir: path.dirname(outputPath), snapshotId });
}

async function observeRuntimeIdentity({ page }, { profile }) {
  await page.getByRole('button', {
    name: profile.realRuntime.newProfileButton,
    exact: true,
  }).waitFor({
    state: 'visible',
    timeout: profile.realRuntime.navigationTimeoutMs ?? 30_000,
  });
  return page.evaluate(({ patchPattern }) => {
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
}

class MaxrollSnapshotCapturer {
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
      captureInteraction: observeRuntimeIdentity,
      lstat: filename => fsPromises.lstat(filename),
      writeFile: (filename, contents) => fsPromises.writeFile(filename, contents, { flag: 'wx' }),
      ...dependencies,
    };
  }

  async capture(options = {}) {
    const started = Date.now();
    const { outputPath, rootDir, snapshotId } = assertOutputPath(options.output);
    const executablePath = options.executablePath ?? discoverBrowser(options.env);
    const sourceUrl = options.sourceUrl ?? LIVE_SOURCE_URL;
    if (!executablePath) {
      throw new MaxrollSnapshotCaptureError('BROWSER_UNAVAILABLE',
        'no compatible preinstalled Chromium/Chrome executable was found');
    }
    try {
      await this.#dependencies.lstat(outputPath);
      throw new MaxrollSnapshotCaptureError('OUTPUT_EXISTS',
        'output folder already exists; snapshots are immutable and are never overwritten');
    } catch (error) {
      if (error instanceof MaxrollSnapshotCaptureError) throw error;
      if (error?.code !== 'ENOENT') {
        throw new MaxrollSnapshotCaptureError('OUTPUT_CHECK_FAILED',
          'unable to verify that the output folder is new', { cause: error });
      }
    }

    const profile = createMaxroll32173552RealProfile({
      snapshotId,
      snapshotManifestSha256: '0'.repeat(64),
      sourceUrl,
      authorizationRef: OWNER_POLICY_REFERENCE,
      metricCatalog: METRIC_CATALOG,
    });
    const report = {
      schemaVersion: 'maxroll-snapshot-capture-report/1',
      status: 'RUNNING',
      validation: null,
      realE2E: CAPTURE_STATUS.REAL_E2E_NOT_RUN,
      startedAt: new Date(started).toISOString(),
      outputPath,
      snapshotId,
      sourceUrl,
      policy: {
        authorizationRef: OWNER_POLICY_REFERENCE,
        acquisition: 'OWNER_REQUESTED_MANUAL_CAPTURE',
        readOnlyMethods: ['GET', 'HEAD'],
        allowedOrigins: [...LIVE_ALLOWED_ORIGINS],
        loginUsed: false,
        saveOrPublishUsed: false,
        autoSync: false,
        autoFetch: false,
        autoRuntimeUpgrade: false,
      },
      browser: { executablePath, version: null },
      runtime: {
        expectedPatch: MAXROLL_32173552_REFERENCE.gamePatch,
        expectedAssetPath: MAXROLL_32173552_REFERENCE.applicationAssetPath,
        expectedAssetSha256: MAXROLL_32173552_REFERENCE.applicationAssetSha256,
        observedPatch: null,
        observedAssets: [],
      },
      integrity: { status: 'PENDING' },
      capture: null,
      cleanup: 'PENDING',
    };
    let browser;
    let saved = false;
    let failure;
    try {
      browser = this.#dependencies.browserFactory(executablePath);
      await browser.start();
      report.browser.version = await browser.withLease({}, lease =>
        lease.context.browser()?.version() ?? null);
      const manager = this.#dependencies.managerFactory(browser, rootDir);
      let observation = null;
      const draft = await manager.capture({
        snapshotId,
        site: 'maxroll-d4-planner',
        version: 'CAPTURED_UNVALIDATED',
        url: sourceUrl,
        allowedOrigins: LIVE_ALLOWED_ORIGINS,
        timeoutMs: options.timeoutMs ?? 180_000,
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
          requestHeaderPolicy: 'fresh-anonymous-context',
          navigationWaitUntil: 'domcontentloaded',
          settleWaitUntil: 'domcontentloaded',
          responseBodyTimeoutMs: 15_000,
        },
        interact: async context => {
          observation = await this.#dependencies.captureInteraction(context, { profile });
        },
        signal: options.signal,
      });
      const versionedDraft = Object.freeze({
        ...draft,
        version: observation?.gamePatch ?? 'UNKNOWN',
      });
      await manager.save(versionedDraft);
      saved = true;
      const verification = await manager.verify(snapshotId);
      const manifest = await manager.load(snapshotId);
      const exportAssets = manifest.resources.filter(resource => {
        try { return new URL(resource.url).pathname.startsWith('/assets/export-'); }
        catch { return false; }
      }).map(resource => Object.freeze({
        url: resource.url,
        path: new URL(resource.url).pathname,
        sha256: resource.sha256,
        size: resource.size,
      }));
      const expectedAsset = exportAssets.find(asset =>
        asset.path === MAXROLL_32173552_REFERENCE.applicationAssetPath);
      const drift = observation?.gamePatch !== MAXROLL_32173552_REFERENCE.gamePatch ||
        !expectedAsset ||
        expectedAsset.sha256 !== MAXROLL_32173552_REFERENCE.applicationAssetSha256;
      const inventory = {
        schemaVersion: 'maxroll-resource-inventory/1',
        snapshotId,
        manifestSha256: verification.manifestSha256,
        resourceCount: manifest.resourceCount,
        totalBytes: manifest.totalBytes,
        uniqueBlobCount: new Set(manifest.resources.map(resource => resource.sha256)).size,
        resources: manifest.resources.map(resource => ({
          method: resource.method,
          url: resource.url,
          status: resource.status,
          contentType: resource.headers['content-type'] ?? null,
          size: resource.size,
          sha256: resource.sha256,
          blob: resource.blob,
        })),
      };
      const inventoryBytes = Buffer.from(`${JSON.stringify(inventory, null, 2)}\n`);
      await this.#dependencies.writeFile(path.join(outputPath, 'resource-inventory.json'),
        inventoryBytes);
      report.status = CAPTURE_STATUS.CAPTURED_UNVALIDATED;
      report.validation = drift ? CAPTURE_STATUS.PATCH_DRIFT :
        CAPTURE_STATUS.PIN_MATCH_UNVALIDATED;
      report.runtime.observedPatch = observation?.gamePatch ?? null;
      report.runtime.observedAssets = exportAssets;
      report.capture = {
        resourceCount: verification.resourceCount,
        uniqueBlobCount: inventory.uniqueBlobCount,
        totalBytes: verification.totalBytes,
        durationMs: draft.capture?.durationMs ?? null,
        blockedRequestCount: draft.capture?.blockedRequestCount ?? null,
        excludedResponseCount: draft.capture?.excludedResponseCount ?? null,
        redactedResponseCount: draft.capture?.redactedResponseCount ?? null,
      };
      report.integrity = {
        status: 'PASS',
        algorithm: verification.algorithm,
        manifestSha256: verification.manifestSha256,
        verifiedResources: verification.resourceCount,
        verifiedBytes: verification.totalBytes,
        resourceInventorySha256: digest(inventoryBytes),
      };
    } catch (error) {
      failure = error instanceof MaxrollSnapshotCaptureError ? error :
        new MaxrollSnapshotCaptureError('CAPTURE_FAILED',
          'persistent Maxroll snapshot capture failed', { cause: error });
      report.status = failure.code;
    } finally {
      if (browser) {
        try {
          await browser.stop();
          report.cleanup = 'PASS';
        } catch (error) {
          report.cleanup = 'FAIL';
          if (!failure) {
            failure = new MaxrollSnapshotCaptureError('CLEANUP_FAILED',
              'browser cleanup failed after capture', { cause: error });
            report.status = failure.code;
          }
        }
      } else {
        report.cleanup = 'NOT_STARTED';
      }
      report.finishedAt = new Date().toISOString();
      report.durationMs = Date.now() - started;
      if (saved) {
        await this.#dependencies.writeFile(path.join(outputPath, 'capture-report.json'),
          `${JSON.stringify(report, null, 2)}\n`).catch(error => {
          if (!failure) {
            failure = new MaxrollSnapshotCaptureError('REPORT_WRITE_FAILED',
              'snapshot was saved but capture report could not be written', { cause: error });
          }
        });
      }
    }
    if (failure) {
      failure.report = Object.freeze(structuredClone(report));
      throw failure;
    }
    return Object.freeze(structuredClone(report));
  }
}

module.exports = {
  CAPTURE_STATUS,
  MaxrollSnapshotCaptureError,
  MaxrollSnapshotCapturer,
  assertOutputPath,
  observeRuntimeIdentity,
};
