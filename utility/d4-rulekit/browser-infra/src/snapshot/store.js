'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');
const { SNAPSHOT_ERROR_CODES, WebSnapshotError, snapshotError } = require('./errors');
const {
  normalizeOrigins,
  sanitizeResponseHeaders,
  validateSafeUrl,
  validateSnapshotId,
} = require('./policy');

const SNAPSHOT_SCHEMA_VERSION = 'web-snapshot/v1';
const DEFAULT_STORE_LIMITS = Object.freeze({
  maxSnapshots: 100,
  maxResources: 5_000,
  maxResourceBytes: 32 * 1024 * 1024,
  maxTotalBytes: 256 * 1024 * 1024,
});

function sha256(body) {
  return crypto.createHash('sha256').update(body).digest('hex');
}

function deepFreeze(value) {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const child of Object.values(value)) deepFreeze(child);
  }
  return value;
}

class FileSystemSnapshotStore {
  #rootDir;
  #fs;
  #limits;
  #saveTail = Promise.resolve();

  constructor({ rootDir, fsImpl = fs, limits = {} } = {}) {
    if (typeof rootDir !== 'string' || rootDir.length === 0) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
        'snapshot store rootDir is required');
    }
    this.#rootDir = path.resolve(rootDir);
    this.#fs = fsImpl;
    this.#limits = Object.freeze({ ...DEFAULT_STORE_LIMITS, ...limits });
    for (const [name, value] of Object.entries(this.#limits)) {
      if (!Number.isInteger(value) || value < 1) {
        throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
          `${name} must be a positive integer`);
      }
    }
  }

  get limits() {
    return this.#limits;
  }

  save(draft) {
    const operation = this.#saveTail.then(() => this.#save(draft));
    this.#saveTail = operation.catch(() => {});
    return operation;
  }

  async #save(draft) {
    const snapshotId = validateSnapshotId(draft?.snapshotId);
    this.#validateDraft(draft);
    await this.#ensureRoot();
    const existing = await this.#snapshotCount();
    if (existing >= this.#limits.maxSnapshots) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.STORAGE_LIMIT,
        'snapshot count limit exceeded');
    }
    const destination = this.#snapshotPath(snapshotId);
    if (await this.#exists(destination)) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.DUPLICATE_SNAPSHOT,
        'snapshot ID already exists');
    }
    const temporary = path.join(this.#rootDir,
      `.tmp-${snapshotId}-${crypto.randomUUID()}`);
    try {
      await this.#fs.mkdir(path.join(temporary, 'blobs'), { recursive: true });
      let totalBytes = 0;
      const resources = [];
      const written = new Set();
      for (const resource of draft.resources) {
        const body = Buffer.isBuffer(resource.body)
          ? resource.body : Buffer.from(resource.body ?? '');
        if (body.length > this.#limits.maxResourceBytes) {
          throw snapshotError(SNAPSHOT_ERROR_CODES.RESOURCE_LIMIT,
            'resource size limit exceeded');
        }
        totalBytes += body.length;
        if (totalBytes > this.#limits.maxTotalBytes) {
          throw snapshotError(SNAPSHOT_ERROR_CODES.STORAGE_LIMIT,
            'snapshot byte limit exceeded');
        }
        const digest = sha256(body);
        const blobName = `${digest}.bin`;
        if (!written.has(digest)) {
          await this.#fs.writeFile(path.join(temporary, 'blobs', blobName), body, { flag: 'wx' });
          written.add(digest);
        }
        resources.push(Object.freeze({
          key: resource.key,
          method: resource.method,
          url: resource.url,
          status: resource.status,
          headers: { ...resource.headers },
          redirectedFrom: resource.redirectedFrom ?? null,
          sha256: digest,
          size: body.length,
          blob: `blobs/${blobName}`,
        }));
      }
      const manifest = {
        schemaVersion: SNAPSHOT_SCHEMA_VERSION,
        snapshotId,
        sourceUrl: draft.sourceUrl,
        capturedAt: draft.capturedAt,
        allowedOrigins: [...draft.allowedOrigins],
        site: draft.site ?? null,
        version: draft.version ?? null,
        browserVersion: draft.browserVersion ?? null,
        playwrightVersion: draft.playwrightVersion,
        serviceWorkerPolicy: 'block',
        resources,
        resourceCount: resources.length,
        totalBytes,
        integrity: { algorithm: 'sha256' },
      };
      await this.#fs.writeFile(path.join(temporary, 'manifest.json'),
        `${JSON.stringify(manifest, null, 2)}\n`, { flag: 'wx' });
      try {
        await this.#fs.rename(temporary, destination);
      } catch (error) {
        if (['EEXIST', 'ENOTEMPTY'].includes(error?.code)) {
          throw snapshotError(SNAPSHOT_ERROR_CODES.DUPLICATE_SNAPSHOT,
            'snapshot ID already exists', error);
        }
        throw error;
      }
      return deepFreeze(structuredClone(manifest));
    } catch (error) {
      await this.#fs.rm(temporary, { recursive: true, force: true }).catch(() => {});
      throw this.#storageError(error);
    }
  }

  async load(snapshotId) {
    validateSnapshotId(snapshotId);
    let text;
    try {
      const directory = this.#snapshotPath(snapshotId);
      const stat = await this.#fs.lstat(directory);
      if (!stat.isDirectory() || stat.isSymbolicLink()) {
        throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_SNAPSHOT,
          'snapshot package must be a real directory');
      }
      text = await this.#fs.readFile(path.join(directory, 'manifest.json'), 'utf8');
    } catch (error) {
      if (error?.code === 'ENOENT') {
        throw snapshotError(SNAPSHOT_ERROR_CODES.SNAPSHOT_NOT_FOUND,
          'snapshot was not found', error);
      }
      throw this.#storageError(error);
    }
    let manifest;
    try {
      manifest = JSON.parse(text);
    } catch (error) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_SNAPSHOT,
        'snapshot manifest is not valid JSON', error);
    }
    this.#validateManifest(manifest, snapshotId);
    return deepFreeze(structuredClone(manifest));
  }

  async list(filter = {}) {
    if (filter === null || typeof filter !== 'object' || Array.isArray(filter)) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS, 'snapshot filter must be an object');
    }
    await this.#ensureRoot();
    let entries;
    try {
      entries = await this.#fs.readdir(this.#rootDir, { withFileTypes: true });
    } catch (error) {
      throw this.#storageError(error);
    }
    const manifests = [];
    for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
      if (!entry.isDirectory() || entry.name.startsWith('.tmp-')) continue;
      const manifest = await this.load(entry.name);
      if (filter.site !== undefined && manifest.site !== filter.site) continue;
      if (filter.version !== undefined && manifest.version !== filter.version) continue;
      if (filter.origin !== undefined && new URL(manifest.sourceUrl).origin !== filter.origin) continue;
      manifests.push(manifest);
    }
    return Object.freeze(manifests);
  }

  async verify(snapshotId) {
    const manifest = await this.load(snapshotId);
    let verifiedBytes = 0;
    for (const resource of manifest.resources) {
      let body;
      try {
        const blobPath = path.join(this.#snapshotPath(snapshotId), resource.blob);
        const stat = await this.#fs.lstat(blobPath);
        if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('blob is not a regular file');
        body = await this.#fs.readFile(blobPath);
      } catch (error) {
        throw snapshotError(SNAPSHOT_ERROR_CODES.RESOURCE_MISSING,
          'snapshot resource is missing or unreadable', error);
      }
      if (body.length !== resource.size || sha256(body) !== resource.sha256) {
        throw snapshotError(SNAPSHOT_ERROR_CODES.INTEGRITY_MISMATCH,
          'snapshot resource integrity mismatch');
      }
      verifiedBytes += body.length;
    }
    if (verifiedBytes !== manifest.totalBytes) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INTEGRITY_MISMATCH,
        'snapshot total byte count mismatch');
    }
    return deepFreeze({
      snapshotId,
      valid: true,
      resourceCount: manifest.resourceCount,
      totalBytes: manifest.totalBytes,
      algorithm: 'sha256',
    });
  }

  async loadPackage(snapshotId) {
    await this.verify(snapshotId);
    const manifest = await this.load(snapshotId);
    const resources = new Map();
    for (const resource of manifest.resources) {
      const body = await this.#fs.readFile(
        path.join(this.#snapshotPath(snapshotId), resource.blob));
      resources.set(resource.key, Object.freeze({ ...resource, body }));
    }
    return Object.freeze({ manifest, resources });
  }

  #validateDraft(draft) {
    if (!draft || typeof draft !== 'object' || !Array.isArray(draft.resources)) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_SNAPSHOT,
        'snapshot draft is invalid');
    }
    if (draft.resources.length > this.#limits.maxResources) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.RESOURCE_LIMIT,
        'resource count limit exceeded');
    }
    if (typeof draft.sourceUrl !== 'string' || !Array.isArray(draft.allowedOrigins)
        || typeof draft.capturedAt !== 'string' || !Number.isFinite(Date.parse(draft.capturedAt))
        || typeof draft.playwrightVersion !== 'string') {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_SNAPSHOT,
        'snapshot draft metadata is incomplete');
    }
    let allowedOrigins;
    try {
      allowedOrigins = normalizeOrigins(draft.allowedOrigins);
      if (validateSafeUrl(draft.sourceUrl, allowedOrigins) !== draft.sourceUrl) throw new Error();
    } catch (error) {
      if (error instanceof WebSnapshotError) throw error;
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_SNAPSHOT,
        'snapshot source metadata is unsafe', error);
    }
    const keys = new Set();
    for (const resource of draft.resources) {
      let safeUrl;
      try {
        safeUrl = validateSafeUrl(resource?.url, allowedOrigins);
      } catch (error) {
        throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_SNAPSHOT,
          'snapshot resource URL is unsafe', error);
      }
      const sanitizedHeaders = sanitizeResponseHeaders(resource.headers);
      if (!resource || typeof resource.key !== 'string' || typeof resource.url !== 'string'
          || !['GET', 'HEAD'].includes(resource.method)
          || !Number.isInteger(resource.status) || resource.status < 100 || resource.status > 599
          || typeof resource.headers !== 'object' || resource.headers === null
          || JSON.stringify(resource.headers) !== JSON.stringify(sanitizedHeaders)
          || resource.key !== `${resource.method} ${safeUrl}`
          || (resource.redirectedFrom !== null && resource.redirectedFrom !== undefined
            && validateSafeUrl(resource.redirectedFrom, allowedOrigins) !== resource.redirectedFrom)
          || !(Buffer.isBuffer(resource.body) || resource.body instanceof Uint8Array
            || typeof resource.body === 'string')
          || keys.has(resource.key)) {
        throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_SNAPSHOT,
          'snapshot draft contains an invalid or duplicate resource');
      }
      keys.add(resource.key);
    }
  }

  #validateManifest(manifest, expectedId) {
    if (!manifest || manifest.schemaVersion !== SNAPSHOT_SCHEMA_VERSION
        || manifest.snapshotId !== expectedId || !Array.isArray(manifest.resources)
        || manifest.resourceCount !== manifest.resources.length
        || !Number.isInteger(manifest.totalBytes) || manifest.totalBytes < 0
        || manifest.integrity?.algorithm !== 'sha256'
        || !Array.isArray(manifest.allowedOrigins)
        || typeof manifest.sourceUrl !== 'string'
        || typeof manifest.capturedAt !== 'string' || !Number.isFinite(Date.parse(manifest.capturedAt))
        || typeof manifest.playwrightVersion !== 'string'
        || (manifest.browserVersion !== null && typeof manifest.browserVersion !== 'string')
        || manifest.serviceWorkerPolicy !== 'block') {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_SNAPSHOT,
        'snapshot manifest does not satisfy web-snapshot/v1');
    }
    if (manifest.resources.length > this.#limits.maxResources
        || manifest.totalBytes > this.#limits.maxTotalBytes) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.STORAGE_LIMIT,
        'snapshot manifest exceeds configured limits');
    }
    let allowedOrigins;
    try {
      allowedOrigins = normalizeOrigins(manifest.allowedOrigins);
      if (validateSafeUrl(manifest.sourceUrl, allowedOrigins) !== manifest.sourceUrl) throw new Error();
    } catch (error) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_SNAPSHOT,
        'snapshot manifest source metadata is unsafe', error);
    }
    const keys = new Set();
    for (const resource of manifest.resources) {
      const expectedBlob = `blobs/${resource.sha256}.bin`;
      let safeUrl;
      try {
        safeUrl = validateSafeUrl(resource.url, allowedOrigins);
        if (resource.redirectedFrom !== null
            && validateSafeUrl(resource.redirectedFrom, allowedOrigins) !== resource.redirectedFrom) {
          throw new Error('redirect source URL is not normalized');
        }
      } catch (error) {
        throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_SNAPSHOT,
          'snapshot manifest resource URL is unsafe', error);
      }
      if (typeof resource.key !== 'string' || keys.has(resource.key)
          || !['GET', 'HEAD'].includes(resource.method)
          || typeof resource.url !== 'string'
          || resource.key !== `${resource.method} ${safeUrl}`
          || typeof resource.headers !== 'object' || resource.headers === null
          || JSON.stringify(resource.headers) !== JSON.stringify(sanitizeResponseHeaders(resource.headers))
          || !/^[a-f0-9]{64}$/.test(resource.sha256)
          || resource.blob !== expectedBlob
          || !Number.isInteger(resource.size) || resource.size < 0
          || resource.size > this.#limits.maxResourceBytes
          || !Number.isInteger(resource.status) || resource.status < 100 || resource.status > 599) {
        throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_SNAPSHOT,
          'snapshot manifest resource is invalid');
      }
      keys.add(resource.key);
    }
  }

  async #ensureRoot() {
    try {
      await this.#fs.mkdir(this.#rootDir, { recursive: true });
      const stat = await this.#fs.lstat(this.#rootDir);
      if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error('store root is not a directory');
    } catch (error) {
      throw this.#storageError(error);
    }
  }

  async #snapshotCount() {
    try {
      const entries = await this.#fs.readdir(this.#rootDir, { withFileTypes: true });
      return entries.filter(entry => entry.isDirectory() && !entry.name.startsWith('.tmp-')).length;
    } catch (error) {
      throw this.#storageError(error);
    }
  }

  #snapshotPath(snapshotId) {
    return path.join(this.#rootDir, snapshotId);
  }

  async #exists(target) {
    try {
      await this.#fs.lstat(target);
      return true;
    } catch (error) {
      if (error?.code === 'ENOENT') return false;
      throw this.#storageError(error);
    }
  }

  #storageError(error) {
    if (error instanceof WebSnapshotError) return error;
    return snapshotError(SNAPSHOT_ERROR_CODES.STORAGE_IO,
      'snapshot storage operation failed', error);
  }
}

module.exports = {
  DEFAULT_STORE_LIMITS,
  FileSystemSnapshotStore,
  SNAPSHOT_SCHEMA_VERSION,
  sha256,
};
