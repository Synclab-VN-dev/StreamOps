'use strict';

const crypto = require('node:crypto');
const path = require('node:path');
const { MaxrollProviderError } = require('./errors');
const {
  createNativeBuildExport, parsePlannerUrl, profileInventory,
  serialize, validateNativeState, writeAtomicExclusive,
} = require('./build-export');

const MAX_HTML_BYTES = 8 * 1024 * 1024;
const sha256 = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const failure = (code, message) => new MaxrollProviderError(code, message);

function parseGuideUrl(value) {
  let url;
  try { url = new URL(value); } catch { throw failure('INVALID_INPUT', 'Invalid Maxroll guide URL'); }
  if (url.origin !== 'https://maxroll.gg' || url.username || url.password || url.search
      || !/^\/d4\/build-guides\/[a-z0-9-]+\/?$/.test(url.pathname)) {
    throw failure('INVALID_INPUT', 'Expected an unauthenticated https://maxroll.gg/d4/build-guides/<slug> URL');
  }
  // A guide fragment is a section anchor, not a planner variant selector.
  url.hash = '';
  return url.href;
}

function validateOptions(options, outputRequired = false) {
  if (!options || typeof options.url !== 'string') throw failure('INVALID_INPUT', 'url is required');
  const url = parseGuideUrl(options.url);
  if (options.profile !== undefined && (!Number.isSafeInteger(options.profile) || options.profile < 0)) {
    throw failure('INVALID_INPUT', 'profile must be a non-negative native index');
  }
  if (outputRequired && (typeof options.outputPath !== 'string' || !options.outputPath)) {
    throw failure('INVALID_INPUT', 'outputPath is required');
  }
  for (const name of ['snapshotRoot', 'snapshotId', 'expectedManifestSha256']) {
    if (options[name] !== undefined) throw failure('INVALID_INPUT', 'Guide export is live; snapshot options are not applicable');
  }
  return url;
}

async function fetchGuide(url, fetchImpl) {
  const signal = AbortSignal.timeout(30000);
  for (let redirects = 0; redirects <= 3; redirects++) {
    const response = await fetchImpl(url, {
      redirect: 'manual', signal,
      headers: { Accept: 'text/html', 'User-Agent': 'StreamOps-RuleKit-GuideExport/1.0' },
    });
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      await response.body?.cancel();
      const location = response.headers.get('location');
      if (!location) throw failure('GUIDE_FETCH_FAILED', 'Guide redirect lacks Location');
      url = parseGuideUrl(new URL(location, url).href);
      continue;
    }
    if (!response.ok || !/^text\/html(?:;|$)/i.test(response.headers.get('content-type') || '')) {
      await response.body?.cancel();
      throw failure('GUIDE_FETCH_FAILED', `Expected HTML guide response (HTTP ${response.status})`);
    }
    if (!response.body || Number(response.headers.get('content-length')) > MAX_HTML_BYTES) {
      await response.body?.cancel();
      throw failure('GUIDE_FETCH_FAILED', 'Guide body is missing or exceeds 8 MiB');
    }
    const reader = response.body.getReader();
    const chunks = []; let bytes = 0;
    try {
      while (true) {
        const part = await reader.read();
        if (part.done) break;
        bytes += part.value.length;
        if (bytes > MAX_HTML_BYTES) throw failure('GUIDE_FETCH_FAILED', 'Guide exceeds 8 MiB');
        chunks.push(Buffer.from(part.value));
      }
    } finally { await reader.cancel(); reader.releaseLock(); }
    return { body: Buffer.concat(chunks), url };
  }
  throw failure('GUIDE_FETCH_FAILED', 'Too many guide redirects');
}

function readContext(html) {
  // Parse only the literal JSON assignment in an inline script. Never eval page
  // scripts or use a greedy regex across JSON strings containing braces.
  const candidates = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script\s*>/gi)]
    .map(match => match[1].match(/^\s*window\.__remixContext\s*=\s*([\s\S]*)$/)?.[1])
    .filter(value => value !== undefined);
  if (candidates.length !== 1 || candidates[0][0] !== '{') {
    throw failure('GUIDE_DATA_INVALID', 'Expected exactly one literal Remix guide context');
  }
  const source = candidates[0]; let depth = 0; let quoted = false; let escaped = false;
  for (let i = 0; i < source.length; i++) {
    const c = source[i];
    if (quoted) {
      if (escaped) escaped = false;
      else if (c === '\\') escaped = true;
      else if (c === '"') quoted = false;
    } else if (c === '"') quoted = true;
    else if (c === '{' || c === '[') depth++;
    else if ((c === '}' || c === ']') && --depth === 0) {
      try { return JSON.parse(source.slice(0, i + 1)); }
      catch { throw failure('GUIDE_DATA_INVALID', 'Guide context is not valid JSON'); }
    }
  }
  throw failure('GUIDE_DATA_INVALID', 'Truncated guide context');
}

function extractBuild(body) {
  const context = readContext(body.toString('utf8'));
  const pending = [context?.state?.loaderData]; const blocks = []; let visited = 0;
  while (pending.length) {
    const value = pending.pop();
    if (++visited > 200000) throw failure('GUIDE_DATA_INVALID', 'Guide context is too complex');
    if (!value || typeof value !== 'object') continue;
    if (value.blockName === 'maxroll/planner-page') blocks.push(value);
    else pending.push(...Object.values(value));
  }
  if (blocks.length !== 1) throw failure('GUIDE_DATA_INVALID', 'Guide must contain exactly one planner-page block');
  const block = blocks[0];
  const parsedUrl = parsePlannerUrl(block.attributes?.link);
  const embedded = block.plannerProfile;
  if (!embedded || embedded.id !== parsedUrl.plannerId || embedded.game !== 'd4') {
    throw failure('GUIDE_DATA_INVALID', 'Embedded planner identity does not match guide link');
  }
  let state;
  try { state = typeof embedded.data === 'string' ? JSON.parse(embedded.data) : embedded.data; }
  catch { throw failure('NATIVE_BUILD_INVALID', 'Embedded build is not valid JSON'); }
  validateNativeState(state);
  if (state.activeProfile < 0 || !state.profiles[state.activeProfile]) {
    throw failure('NATIVE_BUILD_INVALID', 'Embedded active profile is out of range');
  }
  // Guide rendering defaults to data.activeProfile (not the embedded link's
  // fragment). Preserve the original link in provenance, but do not reinterpret it.
  const response = Object.fromEntries(['id', 'game', 'name', 'class', 'season', 'date']
    .filter(key => ['string', 'number'].includes(typeof embedded[key]))
    .map(key => [key, embedded[key]]));
  return { state, response, parsedUrl };
}

async function loadGuide(options, dependencies) {
  const url = validateOptions(options);
  let fetched;
  try { fetched = await fetchGuide(url, dependencies.fetch ?? globalThis.fetch); }
  catch (error) {
    if (error instanceof MaxrollProviderError) throw error;
    throw failure(error.name === 'TimeoutError' || error.name === 'AbortError' ? 'TIMEOUT' : 'GUIDE_FETCH_FAILED', 'Could not fetch Maxroll guide');
  }
  return { ...extractBuild(fetched.body), provenance: {
    source: 'LIVE_GUIDE_EMBED', requestedUrl: options.url, sourceUrl: fetched.url,
    retrievedAt: new Date().toISOString(), guideResponseSha256: sha256(fetched.body),
    snapshotVerification: 'NOT_PERFORMED', calculationStatus: 'NOT_ASSESSED',
  } };
}

async function listMaxrollBuildProfilesFromGuide(options, dependencies = {}) {
  const source = await loadGuide(options, dependencies);
  return { ...source.provenance, plannerUrl: source.parsedUrl.requestedUrl,
    plannerId: source.parsedUrl.plannerId, nativeActiveProfile: source.state.activeProfile,
    profiles: profileInventory(source.state) };
}

async function exportMaxrollBuildFromGuide(options, dependencies = {}) {
  validateOptions(options, true);
  const source = await loadGuide(options, dependencies);
  const output = createNativeBuildExport({ ...source,
    parsedUrl: { ...source.parsedUrl, fragmentProfile: null }, profile: options.profile,
    provenance: { ...source.provenance, plannerUrl: source.parsedUrl.requestedUrl },
  });
  if (options.profile === undefined) output.selection.selectedBy = 'guide-active-profile';
  const bytes = Buffer.from(serialize(output));
  const outputPath = path.resolve(options.outputPath);
  await writeAtomicExclusive(outputPath, bytes);
  return { outputPath, bytes: bytes.length, sha256: sha256(bytes),
    nativeStateSha256: output.integrity.nativeStateSha256,
    profile: output.selection, provenance: output.provenance };
}

module.exports = { parseGuideUrl, exportMaxrollBuildFromGuide, listMaxrollBuildProfilesFromGuide };
