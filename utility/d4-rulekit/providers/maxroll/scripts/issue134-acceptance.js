#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BUILD_FIXTURES, withEncryptedBuildFixture } = require('../src/encrypted-build-fixture');
const { FIXTURE, withDecryptedFixture } = require('../src/encrypted-fixture');
const { sanitizeChildEnvironment } = require('../src/offline-real-e2e');

const REPOSITORY = 'Synclab-VN-dev/StreamOps';
const SNAPSHOT_TAG = 'test-fixture/enc-e2e-20261023-r01';
const GROUPS = new Set(['static', 'synthetic', 'multiclass', 'mutations', 'application', 'regression']);

function parse(argv, env = process.env) {
  const options = { identity: env.MAXROLL_FIXTURE_AGE_IDENTITY_FILE,
    ageBin: env.AGE_BIN, chromium: env.BROWSER_INFRA_CHROMIUM_PATH,
    ghBin: 'gh', resume: 'all' };
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index]; const value = argv[index + 1];
    if (!['--identity', '--age-bin', '--chromium', '--gh-bin', '--resume'].includes(key)
        || !value) throw new Error(`unsupported or incomplete argument: ${key}`);
    options[key.slice(2).replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase())] = value;
  }
  for (const key of ['identity', 'ageBin', 'chromium']) {
    if (typeof options[key] !== 'string' || !options[key]) throw new Error(`${key} is required`);
  }
  const selected = options.resume === 'all' ? [...GROUPS] : options.resume.split(',');
  if (!selected.length || selected.some(group => !GROUPS.has(group))) {
    throw new Error(`resume must be all or comma-separated: ${[...GROUPS].join(',')}`);
  }
  return Object.freeze({ ...options, selected: Object.freeze(selected) });
}

function run(command, args, options = {}) {
  const started = Date.now();
  const result = spawnSync(command, args, { cwd: options.cwd, env: options.env,
    encoding: 'utf8', stdio: options.inherit ? 'inherit' : 'pipe',
    timeout: options.timeoutMs ?? 540_000 });
  if (result.error || result.status !== 0) throw new Error(result.error?.message
    ?? result.stderr?.trim() ?? `${path.basename(command)} exited ${result.status}`);
  return Object.freeze({ durationMs: Date.now() - started,
    stdout: options.inherit ? '' : result.stdout?.trim() ?? '' });
}

function download(execute, ghBin, tag, names, directory) {
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  const args = ['release', 'download', tag, '--repo', REPOSITORY, '--dir', directory];
  for (const name of names) args.push('--pattern', name);
  execute(ghBin, args, { timeoutMs: 120_000 });
}

async function runAcceptance(options, dependencies = {}) {
  const execute = dependencies.run ?? run;
  const packageRoot = path.resolve(__dirname, '..');
  const repositoryRoot = path.resolve(packageRoot, '../../../..');
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'streamops-issue134-'));
  const results = [];
  const executeGroup = (name, command, args, cwd, env) => {
    if (!options.selected.includes(name)) return;
    const result = execute(command, args, { cwd, env, timeoutMs: 540_000, inherit: true });
    results.push({ name, command: [path.basename(command), ...args].join(' '),
      durationMs: result.durationMs ?? null, status: 'PASS' });
  };
  try {
    const snapshotDownload = path.join(temporary, 'snapshot');
    const r01Download = path.join(temporary, 'r01');
    const r02Download = path.join(temporary, 'r02');
    download(execute, options.ghBin, SNAPSHOT_TAG,
      [FIXTURE.assetName, FIXTURE.checksumName], snapshotDownload);
    download(execute, options.ghBin, BUILD_FIXTURES.r01.tag,
      [BUILD_FIXTURES.r01.asset, BUILD_FIXTURES.r01.checksum], r01Download);
    download(execute, options.ghBin, BUILD_FIXTURES.r02.tag,
      [BUILD_FIXTURES.r02.asset, BUILD_FIXTURES.r02.checksum], r02Download);
    return await withDecryptedFixture({
      encrypted: path.join(snapshotDownload, FIXTURE.assetName),
      checksum: path.join(snapshotDownload, FIXTURE.checksumName),
      identity: options.identity, ageBin: options.ageBin,
    }, async snapshot => withEncryptedBuildFixture({
      encrypted: path.join(r01Download, BUILD_FIXTURES.r01.asset),
      checksum: path.join(r01Download, BUILD_FIXTURES.r01.checksum),
      identity: options.identity, ageBin: options.ageBin, spec: BUILD_FIXTURES.r01,
    }, async r01 => withEncryptedBuildFixture({
      encrypted: path.join(r02Download, BUILD_FIXTURES.r02.asset),
      checksum: path.join(r02Download, BUILD_FIXTURES.r02.checksum),
      identity: options.identity, ageBin: options.ageBin, spec: BUILD_FIXTURES.r02,
    }, async r02 => {
      const env = { ...sanitizeChildEnvironment(process.env),
        BROWSER_INFRA_CHROMIUM_PATH: options.chromium,
        MAXROLL_AUTHORIZED_SNAPSHOT_ROOT: snapshot.rootDir,
        MAXROLL_B0_FIXTURE_ROOT: r01.root,
        MAXROLL_MULTICLASS_FIXTURE_ROOT: r02.root };
      executeGroup('static', 'npm', ['run', 'typecheck'], packageRoot, env);
      executeGroup('static', 'npm', ['run', 'test:unit'], packageRoot, env);
      executeGroup('static', 'npm', ['run', 'test:contract'], packageRoot, env);
      executeGroup('synthetic', 'npm', ['run', 'test:e2e'], packageRoot, env);
      executeGroup('multiclass', process.execPath,
        ['--test', 'tests/adapter-real/universal-multiclass.test.js'], packageRoot, env);
      executeGroup('multiclass', process.execPath,
        ['--test', 'tests/adapter-real/universal-authored.test.js'], packageRoot, env);
      executeGroup('mutations', process.execPath,
        ['--test', 'tests/adapter-real/universal-mutations.test.js'], packageRoot, env);
      executeGroup('application', process.execPath, ['--test', '--test-name-pattern=B6 all eight',
        'tests/adapter-real/universal-provider.test.js'], packageRoot, env);
      executeGroup('regression', 'npm', ['test'], path.resolve(repositoryRoot,
        'utility/d4-rulekit/application'), env);
      executeGroup('regression', 'npm', ['test'], path.resolve(repositoryRoot,
        'utility/d4-rulekit/browser-infra'), env);
      executeGroup('regression', process.env.PYTHON_BIN ?? 'python3', ['-m', 'pytest', '-q',
        'utility/d4-rulekit/tests'], repositoryRoot, env);
      return Object.freeze({ schemaVersion: 'issue-134-local-acceptance/v1', status: 'PASS',
        head: execute('git', ['rev-parse', 'HEAD'], { cwd: repositoryRoot }).stdout,
        fixtureTrust: { snapshotManifestSha256: snapshot.verified.manifestSha256,
          r01ManifestSha256: r01.manifestSha256, r02ManifestSha256: r02.manifestSha256 },
        selectedGroups: options.selected, results, plaintextCleanup: 'PENDING',
        ci: 'NOT_CHECKED' });
    })));
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
}

async function main() {
  const report = await runAcceptance(parse(process.argv.slice(2)));
  const completed = { ...report, plaintextCleanup: 'PASS' };
  const output = path.resolve(__dirname, '../artifacts/issue134-acceptance.json');
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, `${JSON.stringify(completed, null, 2)}\n`, { mode: 0o600 });
  process.stdout.write(`${JSON.stringify(completed)}\n`);
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`${error.name}: ${error.message}\n`); process.exitCode = 1;
});

module.exports = { GROUPS, parse, runAcceptance };
