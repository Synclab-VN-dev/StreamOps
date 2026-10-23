'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const {
  BrowserInfrastructure,
  FileSystemSnapshotStore,
  WebSnapshotManager,
} = require('@streamops/browser-infrastructure');
const { exportMaxrollBuildFromSnapshot } = require('../../src');
const {
  NetworkEgressProbe,
  cleanupOwnedRuntime,
} = require('../helpers/adapter-acceptance');

const SNAPSHOT_ID = 'maxroll-20261023T034150Z';
const MANIFEST_SHA = '638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54';
const SOURCE_URL = 'https://maxroll.gg/d4/planner/1g1any0x';
const PROFILE_URL = 'https://planners.maxroll.gg/profiles/load/d4/1g1any0x';
const EXPECTED = Object.freeze({
  3: Object.freeze({
    name: 'Midgame',
    statsSha256: '5f86a2b1fce7ca2fca2a58ab1dd02608c415603f08c02eb8d940e989deaadc28',
    summary: 'Weapon Damage30,123Toughness1,324,453',
  }),
  4: Object.freeze({
    name: 'Endgame',
    statsSha256: '86e137bbdc9fffa1cc50974e337dfd6b1c3f3909b46797412005bc3e5498bd34',
    summary: 'Weapon Damage52,051Toughness2,885,757',
  }),
});

function requiredEnvironment() {
  const executablePath = process.env.BROWSER_INFRA_CHROMIUM_PATH;
  const snapshotRoot = process.env.MAXROLL_AUTHORIZED_SNAPSHOT_ROOT;
  if (!executablePath || !snapshotRoot) {
    throw new Error('BROWSER_INFRA_CHROMIUM_PATH and MAXROLL_AUTHORIZED_SNAPSHOT_ROOT are required');
  }
  return { executablePath, snapshotRoot };
}

function digest(value) {
  return crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
}

async function loadExport(outputPath) {
  return JSON.parse(await fsp.readFile(outputPath, 'utf8'));
}

async function closeMountAndLease(mount, lease) {
  const failures = [];
  try { await mount?.unmount(); } catch (error) { failures.push(error); }
  try { await lease?.release(); } catch (error) { failures.push(error); }
  if (failures.length) throw new AggregateError(failures, 'round-trip lease cleanup failed');
}

async function importAndObserve({ executablePath, snapshotRoot, exported }) {
  const browser = new BrowserInfrastructure({
    executablePath, headless: true, maxContexts: 1, maxQueue: 1,
    contextOptions: { serviceWorkers: 'block' },
  });
  let lease;
  let mount;
  let networkProbe;
  let ownedPid;
  try {
    await browser.start();
    ownedPid = browser.getStatus().pid;
    const snapshots = new WebSnapshotManager({
      browser, store: new FileSystemSnapshotStore({ rootDir: snapshotRoot }),
    });
    await snapshots.verify(SNAPSHOT_ID);
    lease = await browser.acquire({ timeoutMs: 30_000 });
    networkProbe = await NetworkEgressProbe.attach(lease);
    mount = await snapshots.mount(lease, SNAPSHOT_ID, { mode: 'offline-strict' });
    let loaderHits = 0;
    await lease.page.route(PROFILE_URL, route => {
      loaderHits += 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'access-control-allow-origin': '*' },
        body: JSON.stringify({
          ...exported.loaderMetadata,
          data: JSON.stringify(exported.nativeState),
        }),
      });
    });
    await lease.page.goto(SOURCE_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await lease.page.waitForTimeout(7_000);
    const observed = await lease.page.evaluate(() => {
      const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
      const sections = [...document.querySelectorAll('div[class*="stats_StatSection"]')]
        .map(section => ({
          heading: normalize(section.querySelector('h3,h4')?.textContent),
          text: normalize(section.textContent),
        }));
      const body = normalize(document.body.innerText);
      return {
        sections,
        classRogue: body.includes('Rogue'),
        level70: /Level\s*70|Level70/.test(body),
        tormentOne: /Torment\s*I/.test(body),
        equipmentSlots: document.querySelectorAll('[class*="equipment_slot-"]').length,
      };
    });
    const network = networkProbe.getDiagnostics();
    return {
      loaderHits,
      statsSha256: digest(observed.sections),
      summary: observed.sections[0]?.text ?? null,
      sections: observed.sections.length,
      classRogue: observed.classRogue,
      level70: observed.level70,
      tormentOne: observed.tormentOne,
      equipmentSlots: observed.equipmentSlots,
      network,
      cleanup: await cleanupOwnedRuntime({
        browser, networkProbe,
        session: {
          close: () => closeMountAndLease(mount, lease),
        },
        mount, lease, ownedPid,
      }),
    };
  } catch (primaryError) {
    try {
      await cleanupOwnedRuntime({
        browser, networkProbe,
        session: { close: () => closeMountAndLease(mount, lease) },
        mount, lease, ownedPid,
      });
    } catch (cleanupError) {
      throw new AggregateError([primaryError, cleanupError],
        'build export round-trip and cleanup both failed');
    }
    throw primaryError;
  }
}

test('GB-E0 exports and native-loads two real variants with fresh offline calculations', {
  timeout: 120_000,
}, async t => {
  const environment = requiredEnvironment();
  const outputRoot = await fsp.mkdtemp(path.join(os.tmpdir(), 'maxroll-real-export-'));
  t.after(() => fsp.rm(outputRoot, { recursive: true, force: true }));
  const report = { schemaVersion: 'maxroll-build-export-acceptance/1', status: 'FAIL', builds: [] };
  for (const profile of [3, 4]) {
    const outputPath = path.join(outputRoot, `profile-${profile}.json`);
    const exportedResult = await exportMaxrollBuildFromSnapshot({
      url: SOURCE_URL,
      snapshotRoot: environment.snapshotRoot,
      snapshotId: SNAPSHOT_ID,
      expectedManifestSha256: MANIFEST_SHA,
      profile,
      outputPath,
    });
    const exported = await loadExport(outputPath);
    const observed = await importAndObserve({ ...environment, exported });
    assert.equal(exported.selection.profileName, EXPECTED[profile].name);
    assert.equal(exported.nativeState.activeProfile, profile);
    assert.equal(observed.loaderHits, 1);
    assert.equal(observed.sections, 7);
    assert.equal(observed.classRogue, true);
    assert.equal(observed.level70, true);
    assert.equal(observed.tormentOne, true);
    assert.equal(observed.equipmentSlots, 18);
    assert.equal(observed.statsSha256, EXPECTED[profile].statsSha256);
    assert.equal(observed.summary, EXPECTED[profile].summary);
    assert.equal(observed.network.requestAttempts > 0, true);
    assert.equal(observed.network.externalEgressCompleted, 0);
    assert.equal(observed.network.webSocketHandshakes, 0);
    assert.equal(observed.cleanup.browserState, 'stopped');
    assert.equal(observed.cleanup.ownedProcessExited, true);
    report.builds.push({
      profile,
      fixtureSha256: exportedResult.sha256,
      nativeStateSha256: exportedResult.nativeStateSha256,
      statsSha256: observed.statsSha256,
      externalEgressCompleted: observed.network.externalEgressCompleted,
      cleanup: observed.cleanup,
    });
  }
  assert.notEqual(report.builds[0].fixtureSha256, report.builds[1].fixtureSha256);
  assert.notEqual(report.builds[0].statsSha256, report.builds[1].statsSha256);
  report.status = 'PASS';
  const artifactPath = path.resolve(__dirname, '../../artifacts/build-export-real.json');
  fs.mkdirSync(path.dirname(artifactPath), { recursive: true });
  fs.writeFileSync(artifactPath, `${JSON.stringify(report, null, 2)}\n`);
});
