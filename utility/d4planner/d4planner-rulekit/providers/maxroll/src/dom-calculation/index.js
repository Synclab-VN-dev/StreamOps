'use strict';

const { randomUUID, createHash } = require('node:crypto');
const { performance } = require('node:perf_hooks');
const { BrowserInfrastructure, FileSystemSnapshotStore, WebSnapshotManager } = require('@streamops/browser-infrastructure');
const { parsePlannerUrl } = require('../build-export');
const { nativeInput, digest } = require('./input');
const { catalogFrom, extractStats, readStatsDom, fail } = require('./stats');

/** Independent display-value path. Never instantiates the raw/CDP provider or falls back to it. */
class DomCalculationPath {
  #config; #browser; #store; #snapshots; #source; #busy = false; #closed = false; #starting;
  constructor(config) {
    if (!config?.snapshotRoot || !config.snapshotId || !/^[a-f0-9]{64}$/.test(config.manifestSha256 ?? '')) {
      fail('DOM_INVALID_CONFIG', 'snapshotRoot, snapshotId and manifestSha256 are required');
    }
    this.#config = { timeoutMs: 30000, quietMs: 400, ...config };
    if (!Number.isInteger(this.#config.timeoutMs) || this.#config.timeoutMs < 1000 || this.#config.timeoutMs > 120000
        || !Number.isInteger(this.#config.quietMs) || this.#config.quietMs < 100 || this.#config.quietMs > 2000) {
      fail('DOM_INVALID_CONFIG', 'Invalid timeout/quiet window');
    }
    this.#store = new FileSystemSnapshotStore({ rootDir: config.snapshotRoot });
    const loadPackage = this.#store.loadPackage.bind(this.#store);
    this.#store.loadPackage = async id => {
      const pkg = await loadPackage(id);
      const verification = await this.#store.verify(id);
      if (verification.manifestSha256 !== config.manifestSha256
          || JSON.stringify(await this.#store.load(id)) !== JSON.stringify(pkg.manifest)) {
        fail('DOM_SNAPSHOT_INTEGRITY', 'Snapshot changed since selection');
      }
      for (const resource of pkg.resources.values()) {
        if (createHash('sha256').update(resource.body).digest('hex') !== resource.sha256) {
          fail('DOM_SNAPSHOT_INTEGRITY', 'Loaded replay bytes failed integrity');
        }
      }
      return pkg;
    };
    this.#browser = config.browser ?? new BrowserInfrastructure({ executablePath: config.executablePath,
      headless: true, maxContexts: 1, maxQueue: 1, contextOptions: { serviceWorkers: 'block', viewport: { width: 1600, height: 1100 } } });
    this.#snapshots = new WebSnapshotManager({ browser: this.#browser, store: this.#store });
  }
  async start() {
    if (this.#closed) fail('DOM_CLOSED', 'DOM path is closed');
    this.#starting ??= (async () => {
      const verified = await this.#store.verify(this.#config.snapshotId);
      if (verified.manifestSha256 !== this.#config.manifestSha256) fail('DOM_SNAPSHOT_INTEGRITY', 'Manifest differs from the selected artifact');
      const pkg = await this.#store.loadPackage(this.#config.snapshotId);
      const parsed = parsePlannerUrl(pkg.manifest.sourceUrl);
      const loadUrl = `https://planners.maxroll.gg/profiles/load/d4/${parsed.plannerId}`;
      const one = pattern => {
        const values = [...pkg.resources.values()].filter(r => pattern.test(r.url));
        if (values.length !== 1) fail('DOM_CATALOG_UNSUPPORTED', `Expected one snapshot resource: ${pattern}`);
        return JSON.parse(values[0].body.toString('utf8'));
      };
      const loader = pkg.resources.get(`GET ${loadUrl}`);
      if (!loader) fail('DOM_LOADER_UNSUPPORTED', 'Captured native profile loader is missing');
      this.#source = { manifest: pkg.manifest, sourceUrl: parsed.sourceUrl, loadUrl,
        loader: JSON.parse(loader.body.toString('utf8')), data: one(/\/game\/data\.min\.json(?:\?|$)/),
        locale: one(/\/game\/data\.enus\.json(?:\?|$)/) };
      await this.#browser.start();
    })();
    await this.#starting;
  }

  async evaluate(build, { metricIds } = {}) {
    if (this.#closed) fail('DOM_CLOSED', 'DOM path is closed');
    if (this.#busy) fail('DOM_BUSY', 'Concurrent evaluations on one DOM path are not supported');
    this.#busy = true;
    const begin = performance.now(), evaluationId = randomUUID();
    let lease, mount, timer, timedOut = false, result, lastObservation;
    try {
      const state = nativeInput(build), inputFingerprint = digest(state);
      await this.start();
      const source = this.#source, active = state.profiles[state.activeProfile];
      const catalog = catalogFrom(source.data, source.locale, active.class);
      const applyBegin = performance.now();
      lease = await this.#browser.acquire({ leaseTimeoutMs: this.#config.timeoutMs + 5000 });
      // Each lease has a fresh context: no old document, localStorage view position, or cached build.
      const page = lease.page;
      page.setDefaultTimeout(this.#config.timeoutMs);
      timer = setTimeout(() => { timedOut = true; void page.close().catch(() => {}); }, this.#config.timeoutMs);
      const errors = [], resourceTypes = new Map();
      page.on('request', request => { const url = new URL(request.url()); resourceTypes.set(url.origin + url.pathname, request.resourceType()); });
      page.on('pageerror', e => errors.push(e.message));
      mount = await this.#snapshots.mount(lease, this.#config.snapshotId, { mode: 'offline-strict', onMissingResource: 'abort' });
      let loadCount = 0, readback = null;
      const response = { ...source.loader, name: `DOM evaluation ${evaluationId}`,
        class: source.data.classes[active.class].name, season: String(state.season), data: JSON.stringify(state) };
      await page.route(source.loadUrl, async route => {
        if (route.request().method() !== 'GET') return route.abort('blockedbyclient');
        loadCount += 1;
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(response) });
      });
      const saveUrl = 'https://planners.maxroll.gg/profiles/d4';
      await page.route(saveUrl, async route => {
        if (route.request().method() !== 'POST') return route.abort('blockedbyclient');
        try { readback = JSON.parse(route.request().postDataJSON().data); }
        catch { readback = { invalidSavePayload: true }; }
        // Read the native Save serializer locally; no cloud mutation, and no successful save response.
        await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ error: 'Offline readback only; no cloud save.' }) });
      });
      await page.goto(source.sourceUrl, { waitUntil: 'domcontentloaded' });
      await page.getByRole('button', { name: 'New Profile', exact: true }).waitFor();
      await page.addLocatorHandler(page.getByText('No Thanks', { exact: true }), button => button.click());
      await page.locator('.StatsTest [class*="stats_StatSection"] li').first().waitFor();
      if (loadCount !== 1) fail('DOM_INPUT_UNVERIFIED', 'Expected exactly one current native loader response');
      // Native UI serialization verifies all profiles, items and options; no private JS state access.
      await page.getByRole('button', { name: 'My Profiles', exact: true }).click();
      await page.locator('input.d4t-save-name').fill(`DOM readback ${evaluationId}`);
      await page.locator('.d4t-section-save button').last().click();
      const readbackDeadline = performance.now() + this.#config.timeoutMs;
      while (!readback && performance.now() < readbackDeadline && !timedOut) await page.waitForTimeout(25);
      if (!readback || digest(readback) !== inputFingerprint) {
        const paths = [];
        const diff = (a, b, path = '') => { if (paths.length >= 20 || JSON.stringify(a) === JSON.stringify(b)) return; if (!a || !b || typeof a !== 'object' || typeof b !== 'object') { paths.push(path); return; } for (const key of new Set([...Object.keys(a), ...Object.keys(b)])) diff(a[key], b[key], `${path}.${key}`); };
        diff(state, readback);
        fail('DOM_INPUT_UNVERIFIED', `Native Save readback differs from requested Build JSON: ${paths.join(', ')}`);
      }
      await page.locator('[class*=profiles_ProfileDialog]').locator(':scope > [class*=DialogHeader] button').last().click();
      const applyEnd = performance.now();
      // Verify every render group is open. Headerless summary has no toggle.
      const sections = page.locator('.StatsTest [class*="stats_StatSection"]');
      for (let i = 0; i < await sections.count(); i++) {
        const section = sections.nth(i), header = section.locator('h3');
        if (!(await header.textContent())?.trim()) continue;
        if (!await section.locator('ul').isVisible()) await header.click();
      }
      let signature = null, stableSince = performance.now(), observation;
      while (true) {
        observation = await page.evaluate(readStatsDom);
        lastObservation = { ready: observation.ready, level: observation.level, className: observation.className };
        if (errors.length) fail('DOM_RUNTIME_ERROR', errors.join('; '));
        if (observation.ready && Number(observation.level) === active.level) {
          // Absence of a mandatory row is never accepted as an implicit zero.
          try { extractStats(observation.rows, catalog, metricIds); }
          catch (error) {
            if (error.code !== 'DOM_INCOMPLETE') throw error;
            signature = null; stableSince = performance.now();
            await page.waitForTimeout(50); continue;
          }
          const next = JSON.stringify(observation.rows);
          if (next !== signature) { signature = next; stableSince = performance.now(); }
          if (performance.now() - stableSince >= this.#config.quietMs) break;
        } else { signature = null; stableSince = performance.now(); }
        await page.waitForTimeout(50);
      }
      const calculationEnd = performance.now();
      // Re-read after the settle barrier and reject a late mutation rather than returning earlier data.
      const final = await page.evaluate(readStatsDom);
      if (JSON.stringify(final.rows) !== signature) fail('DOM_UNSTABLE', 'Stats changed after the completion barrier');
      const extracted = extractStats(final.rows, catalog, metricIds);
      if (errors.length) fail('DOM_RUNTIME_ERROR', errors.join('; '));
      const diagnostics = mount.getDiagnostics();
      const requiredMisses = diagnostics.misses.filter(miss => !optionalReplayMiss({ ...miss, resourceType: resourceTypes.get(new URL(miss.url).origin + new URL(miss.url).pathname) }));
      if (requiredMisses.length) throw Object.assign(new Error('Snapshot replay missed calculation/UI resources'), { code: 'DOM_REPLAY_INCOMPLETE', details: requiredMisses });
      result = { schemaVersion: 'maxroll-dom-calculation/v1', path: 'DOM', evaluationId, inputFingerprint,
        status: 'DISPLAY_COMPLETE', ...extracted, completion: { kind: 'FRESH_DOCUMENT_NATIVE_READBACK_DOM_SETTLED', quietMs: this.#config.quietMs,
          nativeReadbackSha256: digest(readback), loaderRequests: loadCount, rawCalculationAttestation: false },
        provenance: { snapshotId: this.#config.snapshotId, manifestSha256: this.#config.manifestSha256,
          gameVersion: source.manifest.version, offline: diagnostics.transportOffline, network: diagnostics },
        timingsMs: { startup: applyBegin - begin, buildApply: applyEnd - applyBegin,
          calculation: calculationEnd - applyEnd, domExtraction: performance.now() - calculationEnd } };
    } catch (error) {
      if (timedOut) throw Object.assign(new Error('DOM evaluation timed out; no cached result returned'), { code: 'DOM_TIMEOUT', cause: error, details: lastObservation });
      throw error;
    } finally {
      clearTimeout(timer);
      try { await mount?.unmount(); } finally {
        try { await lease?.release(); } finally { this.#busy = false; }
      }
    }
    result.timingsMs.endToEnd = performance.now() - begin;
    return result;
  }
  async close() {
    if (this.#busy) fail('DOM_BUSY', 'Wait for the current evaluation before closing');
    if (this.#closed) return;
    this.#closed = true;
    await this.#starting?.catch(() => {});
    await this.#browser.stop();
  }
}
function optionalReplayMiss({ method, url, resourceType }) {
  const parsed = new URL(url);
  if (method === 'POST' && parsed.origin === 'https://analytics.maxroll.gg' && parsed.pathname === '/api/event') return true;
  if (method !== 'GET') return false;
  if (resourceType === 'image' && parsed.origin === 'https://assets-ng.maxroll.gg'
      && /^\/(?:d4-tools\/(?:images|static\/media)|images\/d4)\//.test(parsed.pathname)) return true;
  if (parsed.origin === 'https://planners.maxroll.gg' && parsed.pathname === '/users/whoami') return true;
  if (parsed.origin === 'https://maxroll.gg' && ['/api/me', '/js/sponsor.js'].includes(parsed.pathname)) return true;
  return ['cdn.ziffstatic.com', 'securepubads.g.doubleclick.net', 'static.cloudflareinsights.com',
    'fonts.googleapis.com', 'fonts.gstatic.com'].includes(parsed.hostname);
}
module.exports = { DomCalculationPath };
