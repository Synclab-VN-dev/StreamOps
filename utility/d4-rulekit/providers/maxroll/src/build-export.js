'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');
const { FileSystemSnapshotStore } = require('@streamops/browser-infrastructure');
const { ERROR_CODES, MaxrollProviderError } = require('./errors');

const EXPORT_SCHEMA_VERSION = 'maxroll-native-build-export/v1';
const PROFILE_PATH = /^\/d4\/planner\/([A-Za-z0-9]{8,9})\/?$/;
const SHA256_PATTERN = /^[a-f0-9]{64}$/;

function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.keys(value).sort()
    .map(key => [key, canonicalize(value[key])]));
}

function serialize(value) {
  return `${JSON.stringify(canonicalize(value), null, 2)}\n`;
}

function providerError(code, message, details, cause) {
  return new MaxrollProviderError(code, message, { details, cause });
}

function parsePlannerUrl(value) {
  let url;
  try {
    url = new URL(value);
  } catch (cause) {
    throw providerError(ERROR_CODES.INVALID_INPUT, 'Maxroll planner URL is invalid', undefined, cause);
  }
  const match = url.pathname.match(PROFILE_PATH);
  if (url.protocol !== 'https:' || url.hostname !== 'maxroll.gg'
      || url.username || url.password || url.search || !match) {
    throw providerError(ERROR_CODES.INVALID_INPUT,
      'URL must be an unauthenticated https://maxroll.gg/d4/planner/<id> URL');
  }
  let fragmentProfile = null;
  if (url.hash) {
    if (!/^#[1-9]\d*$/.test(url.hash)) {
      throw providerError(ERROR_CODES.INVALID_INPUT,
        'planner URL fragment must be a one-based visible profile number');
    }
    fragmentProfile = Number(url.hash.slice(1));
  }
  return Object.freeze({
    plannerId: match[1],
    sourceUrl: `${url.origin}${url.pathname.replace(/\/$/, '')}`,
    requestedUrl: url.href,
    fragmentProfile,
  });
}

function validateOptions(options, { requireOutput = false } = {}) {
  if (!options || typeof options !== 'object' || Array.isArray(options)) {
    throw providerError(ERROR_CODES.INVALID_INPUT, 'export options are required');
  }
  for (const name of ['url', 'snapshotRoot', 'snapshotId', 'expectedManifestSha256']) {
    if (typeof options[name] !== 'string' || !options[name]) {
      throw providerError(ERROR_CODES.INVALID_INPUT, `${name} is required`);
    }
  }
  if (!SHA256_PATTERN.test(options.expectedManifestSha256)) {
    throw providerError(ERROR_CODES.INVALID_INPUT,
      'expectedManifestSha256 must be a lowercase SHA-256');
  }
  if (options.profile !== undefined
      && (!Number.isInteger(options.profile) || options.profile < 0)) {
    throw providerError(ERROR_CODES.INVALID_INPUT, 'profile must be a non-negative native index');
  }
  if (requireOutput && (typeof options.outputPath !== 'string' || !options.outputPath)) {
    throw providerError(ERROR_CODES.INVALID_INPUT, 'outputPath is required');
  }
}

function parseNativeResponse(body, plannerId) {
  let response;
  try {
    response = JSON.parse(body.toString('utf8'));
  } catch (cause) {
    throw providerError(ERROR_CODES.NATIVE_BUILD_INVALID,
      'captured profile response is not valid JSON', undefined, cause);
  }
  if (!response || typeof response !== 'object' || Array.isArray(response)
      || response.id !== plannerId || response.game !== 'd4'
      || typeof response.data !== 'string') {
    throw providerError(ERROR_CODES.NATIVE_BUILD_INVALID,
      'captured profile response identity or shape is invalid');
  }
  let state;
  try {
    state = JSON.parse(response.data);
  } catch (cause) {
    throw providerError(ERROR_CODES.NATIVE_BUILD_INVALID,
      'captured native state is not valid JSON', undefined, cause);
  }
  validateNativeState(state);
  return { response, state };
}

function validateNativeState(state) {
  if (!state || typeof state !== 'object' || Array.isArray(state)
      || !Array.isArray(state.profiles) || !state.profiles.length
      || !state.items || typeof state.items !== 'object' || Array.isArray(state.items)
      || !Number.isInteger(state.activeProfile)) {
    throw providerError(ERROR_CODES.NATIVE_BUILD_INVALID,
      'native state is missing profiles, items, or activeProfile');
  }
  state.profiles.forEach((profile, index) => {
    if (!profile || typeof profile !== 'object' || Array.isArray(profile)
        || typeof profile.name !== 'string' || !Number.isFinite(profile.level)
        || !profile.items || typeof profile.items !== 'object' || Array.isArray(profile.items)) {
      throw providerError(ERROR_CODES.NATIVE_BUILD_INVALID,
        `native profile ${index} has an invalid shape`);
    }
    for (const itemReference of Object.values(profile.items)) {
      if (itemReference === null || itemReference === undefined || itemReference === 0) continue;
      if (!Object.hasOwn(state.items, String(itemReference))) {
        throw providerError(ERROR_CODES.NATIVE_BUILD_INVALID,
          `native profile ${index} references missing item ${itemReference}`);
      }
    }
  });
}

function profileInventory(state) {
  return state.profiles.map((profile, index) => Object.freeze({
    index,
    name: profile.name,
    hidden: profile.hidden === true,
    classId: profile.class ?? null,
    level: profile.level,
    worldTier: profile.worldTier ?? null,
    equipmentReferences: Object.values(profile.items).filter(Boolean).length,
    sections: sectionPresence(profile),
  }));
}

function sectionPresence(profile) {
  return Object.freeze({
    equipment: Boolean(profile.items && Object.values(profile.items).some(Boolean)),
    skills: Boolean(profile.skillTree && Array.isArray(profile.skillBar)),
    paragon: Boolean(profile.paragon),
    specialization: profile.specialization !== undefined,
    warPlans: Array.isArray(profile.warPlans),
    mercenary: Boolean(profile.mercenary),
  });
}

function selectProfile(state, requested, fragmentProfile) {
  let index = requested;
  let selectedBy = 'native-active-profile';
  if (index === undefined && fragmentProfile !== null) {
    const visible = state.profiles.map((profile, profileIndex) => ({ profile, profileIndex }))
      .filter(entry => entry.profile.hidden !== true);
    const entry = visible[fragmentProfile - 1];
    if (!entry) {
      throw providerError(ERROR_CODES.PROFILE_VARIANT_NOT_FOUND,
        `visible profile ${fragmentProfile} does not exist`);
    }
    index = entry.profileIndex;
    selectedBy = 'url-fragment';
  } else if (index !== undefined) {
    selectedBy = 'native-index';
  } else {
    index = state.activeProfile;
  }
  if (!state.profiles[index]) {
    throw providerError(ERROR_CODES.PROFILE_VARIANT_NOT_FOUND,
      `native profile index ${index} does not exist`);
  }
  return { index, selectedBy };
}

function loaderMetadata(response) {
  return Object.fromEntries(Object.entries(response).filter(([key]) => key !== 'data'));
}

async function loadSource(options) {
  validateOptions(options);
  const parsedUrl = parsePlannerUrl(options.url);
  const store = options.store ?? new FileSystemSnapshotStore({ rootDir: options.snapshotRoot });
  let verified;
  let snapshotPackage;
  try {
    verified = await store.verify(options.snapshotId);
    snapshotPackage = await store.loadPackage(options.snapshotId);
  } catch (cause) {
    throw providerError(ERROR_CODES.SNAPSHOT_MISMATCH,
      'snapshot verification failed', { snapshotId: options.snapshotId }, cause);
  }
  if (verified.manifestSha256 !== options.expectedManifestSha256) {
    throw providerError(ERROR_CODES.SNAPSHOT_MISMATCH,
      'snapshot manifest SHA-256 does not match the trust anchor', {
        expected: options.expectedManifestSha256,
        actual: verified.manifestSha256,
      });
  }
  const { manifest, resources } = snapshotPackage;
  if (manifest.sourceUrl !== parsedUrl.sourceUrl) {
    throw providerError(ERROR_CODES.PROFILE_NOT_IN_SNAPSHOT,
      'planner URL is not the source captured by this snapshot', {
        requested: parsedUrl.sourceUrl,
        captured: manifest.sourceUrl,
      });
  }
  const profileUrl = `https://planners.maxroll.gg/profiles/load/d4/${parsedUrl.plannerId}`;
  const profileResource = resources.get(`GET ${profileUrl}`);
  if (!profileResource) {
    throw providerError(ERROR_CODES.PROFILE_NOT_IN_SNAPSHOT,
      'profile response is not present in the verified snapshot', { profileUrl });
  }
  const runtimeAssets = manifest.resources.filter(resource =>
    /^https:\/\/maxroll\.gg\/assets\/export-[A-Za-z0-9_-]+\.js(?:[?#].*)?$/.test(resource.url));
  if (runtimeAssets.length !== 1) {
    throw providerError(ERROR_CODES.SNAPSHOT_MISMATCH,
      'snapshot must contain exactly one calculation runtime asset', {
        observedAssets: runtimeAssets.length,
      });
  }
  const { response, state } = parseNativeResponse(profileResource.body, parsedUrl.plannerId);
  return { manifest, parsedUrl, profileResource, response, runtimeAsset: runtimeAssets[0], state, verified };
}

async function listMaxrollBuildProfilesFromSnapshot(options) {
  const source = await loadSource(options);
  return Object.freeze({
    snapshotId: source.manifest.snapshotId,
    manifestSha256: source.verified.manifestSha256,
    sourceUrl: source.parsedUrl.sourceUrl,
    plannerId: source.parsedUrl.plannerId,
    nativeActiveProfile: source.state.activeProfile,
    profiles: Object.freeze(profileInventory(source.state)),
  });
}

async function exportMaxrollBuildFromSnapshot(options) {
  validateOptions(options, { requireOutput: true });
  const source = await loadSource(options);
  const selection = selectProfile(source.state, options.profile, source.parsedUrl.fragmentProfile);
  const nativeState = structuredClone(source.state);
  nativeState.activeProfile = selection.index;
  validateNativeState(nativeState);
  const selectedProfile = nativeState.profiles[selection.index];
  const nativeStateSha256 = sha256(Buffer.from(serialize(nativeState)));
  const output = {
    schemaVersion: EXPORT_SCHEMA_VERSION,
    format: 'MAXROLL_NATIVE_STATE',
    provenance: {
      source: 'APPROVED_OFFLINE_SNAPSHOT',
      requestedUrl: source.parsedUrl.requestedUrl,
      sourceUrl: source.parsedUrl.sourceUrl,
      plannerId: source.parsedUrl.plannerId,
      snapshotId: source.manifest.snapshotId,
      snapshotCapturedAt: source.manifest.capturedAt,
      snapshotManifestSha256: source.verified.manifestSha256,
      sourceResponseSha256: source.profileResource.sha256,
      runtimeVersion: source.manifest.version,
      runtimeAssetUrl: source.runtimeAsset.url,
      runtimeAssetSha256: source.runtimeAsset.sha256,
    },
    selection: {
      profileIndex: selection.index,
      selectedBy: selection.selectedBy,
      profileName: selectedProfile.name,
      class: source.response.class ?? null,
      nativeClassId: selectedProfile.class ?? null,
      level: selectedProfile.level,
      worldTier: selectedProfile.worldTier ?? null,
      equipmentReferences: Object.values(selectedProfile.items).filter(Boolean).length,
      sections: sectionPresence(selectedProfile),
    },
    loaderMetadata: loaderMetadata(source.response),
    nativeState,
    integrity: {
      algorithm: 'sha256',
      nativeStateSha256,
    },
  };
  const bytes = Buffer.from(serialize(output));
  const outputPath = path.resolve(options.outputPath);
  await writeAtomicExclusive(outputPath, bytes);
  return Object.freeze({
    outputPath,
    bytes: bytes.length,
    sha256: sha256(bytes),
    nativeStateSha256,
    profile: Object.freeze({ ...output.selection }),
    provenance: Object.freeze({ ...output.provenance }),
  });
}

async function writeAtomicExclusive(outputPath, bytes) {
  const directory = path.dirname(outputPath);
  const temporary = path.join(directory, `.${path.basename(outputPath)}.${crypto.randomUUID()}.tmp`);
  try {
    await fs.mkdir(directory, { recursive: true, mode: 0o700 });
    await fs.writeFile(temporary, bytes, { flag: 'wx', mode: 0o600 });
    await fs.link(temporary, outputPath);
  } catch (cause) {
    if (cause?.code === 'EEXIST') {
      throw providerError(ERROR_CODES.OUTPUT_EXISTS,
        'output already exists; overwrite is disabled', { outputPath });
    }
    if (cause instanceof MaxrollProviderError) throw cause;
    throw providerError(ERROR_CODES.EXPORT_FAILED,
      'failed to persist exported build atomically', { outputPath }, cause);
  } finally {
    await fs.rm(temporary, { force: true }).catch(() => {});
  }
}

module.exports = {
  EXPORT_SCHEMA_VERSION,
  exportMaxrollBuildFromSnapshot,
  listMaxrollBuildProfilesFromSnapshot,
};
