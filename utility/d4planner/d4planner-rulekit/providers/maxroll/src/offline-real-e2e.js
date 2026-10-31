'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { FIXTURE, withDecryptedFixture } = require('./encrypted-fixture');

const RELEASE = Object.freeze({
  repository: 'Synclab-VN-dev/StreamOps',
  tag: 'test-fixture/enc-e2e-20261023-r01',
});
const PROFILE_ID = 'd12am6kt-candidate';
const SOURCE_URL = 'https://maxroll.gg/d4/planner/1g1any0x';

async function runOfflineRealE2e(options, dependencies = {}) {
  validateOptions(options);
  const execute = dependencies.run ?? run;
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'streamops-real-e2e-'));
  const downloadDir = path.join(temporary, 'download');
  const artifactPath = options.artifactPath ?? path.resolve(__dirname, '../artifacts/offline-real-e2e.json');
  let report = null;
  fs.mkdirSync(downloadDir, { mode: 0o700 });
  try {
    execute(options.ghBin ?? 'gh', [
      'release', 'download', RELEASE.tag,
      '--repo', RELEASE.repository,
      '--dir', downloadDir,
      '--pattern', FIXTURE.assetName,
      '--pattern', FIXTURE.checksumName,
    ], { timeoutMs: 120_000 });
    const encrypted = path.join(downloadDir, FIXTURE.assetName);
    const checksum = path.join(downloadDir, FIXTURE.checksumName);
    report = await withDecryptedFixture({
      encrypted, checksum, ageBin: options.ageBin, identity: options.identity,
    }, async provisioned => {
      if (options.ephemeralIdentity) fs.rmSync(options.identity, { force: true });
      const env = {
        ...sanitizeChildEnvironment(process.env),
        BROWSER_INFRA_CHROMIUM_PATH: options.chromium,
        MAXROLL_AUTHORIZED_SNAPSHOT_ROOT: provisioned.rootDir,
        MAXROLL_AUTHORIZED_SNAPSHOT_ID: provisioned.snapshotId,
        MAXROLL_AUTHORIZED_MANIFEST_SHA256: FIXTURE.manifestSha256,
        MAXROLL_SNAPSHOT_AUTHORIZATION_REF: 'StreamOps#132-encrypted-release-r01',
        MAXROLL_SOURCE_URL: SOURCE_URL,
        MAXROLL_REAL_PROFILE_ID: PROFILE_ID,
      };
      execute('npm', ['run', 'test:real'], {
        cwd: path.resolve(__dirname, '..'), env, timeoutMs: 360_000, inherit: true,
      });
      const acceptancePath = path.resolve(__dirname, '../artifacts/real-acceptance.json');
      const acceptance = JSON.parse(fs.readFileSync(acceptancePath, 'utf8'));
      if (acceptance.status !== 'PASS' || acceptance.profileId !== PROFILE_ID) {
        throw new Error('full real acceptance did not pass with the pinned candidate profile');
      }
      return Object.freeze({
        schemaVersion: 'maxroll-offline-real-e2e/1',
        status: 'PASS',
        releaseTag: RELEASE.tag,
        encryptedSha256: FIXTURE.encryptedSha256,
        manifestSha256: provisioned.verified.manifestSha256,
        resources: provisioned.verified.resources,
        uniqueBlobs: provisioned.verified.uniqueBlobs,
        logicalBytes: provisioned.verified.logicalBytes,
        profileId: PROFILE_ID,
        acceptance: {
          cycles: acceptance.cycles,
          rawCoverage: acceptance.rawCoverage,
          displayCoverage: acceptance.displayCoverage,
          applicationApis: acceptance.applicationApis.length,
          externalEgressCompleted: Object.values(acceptance.networkEvidence)
            .reduce((total, value) => total + value.externalEgressCompleted, 0),
          cleanup: acceptance.cleanup,
        },
        temporaryDataCleanup: 'PENDING',
      });
    });
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
  report = Object.freeze({ ...report, temporaryDataCleanup: 'PASS' });
  fs.mkdirSync(path.dirname(artifactPath), { recursive: true });
  fs.writeFileSync(artifactPath, `${JSON.stringify(report, null, 2)}\n`);
  return report;
}

function sanitizeChildEnvironment(environment) {
  return Object.fromEntries(Object.entries(environment).filter(([name]) =>
    !/(?:^|_)(?:authorization|cookie|credential|identity|password|private_?key|secret|token)(?:_|$)/i
      .test(name)));
}

function validateOptions(options) {
  for (const key of ['identity', 'ageBin', 'chromium']) {
    if (typeof options?.[key] !== 'string' || !options[key]) {
      throw new Error(`${key} is required`);
    }
  }
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd,
    env: options.env ?? process.env,
    encoding: 'utf8',
    stdio: options.inherit ? 'inherit' : 'pipe',
    timeout: options.timeoutMs ?? 120_000,
  });
  if (result.error || result.status !== 0) {
    throw new Error(result.error?.message ?? result.stderr?.trim() ??
      `${path.basename(command)} exited ${result.status}`);
  }
  return result.stdout ?? '';
}

module.exports = {
  PROFILE_ID, RELEASE, SOURCE_URL, runOfflineRealE2e, sanitizeChildEnvironment,
};
