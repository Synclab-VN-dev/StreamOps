'use strict';

const { ApplicationError, ERROR_CODES } = require('./errors');
const { immutableCopy, sha256 } = require('./value');

class BuildStateManager {
  constructor(build) {
    this.initial = immutableCopy(build);
    this.committed = this.initial;
    this.fingerprint = sha256(this.committed);
    this.revision = 0;
    this.previews = new Map();
  }

  issuePreview(identity, changes, candidateBuild) {
    const candidateFingerprint = sha256(candidateBuild);
    const payload = immutableCopy({
      ...identity,
      revision: this.revision,
      baseFingerprint: this.fingerprint,
      candidateFingerprint,
      changesFingerprint: sha256(changes),
    });
    const token = sha256(payload);
    this.previews.set(token, payload);
    return { token, payload };
  }

  validatePreview(token, changes) {
    const preview = this.previews.get(token);
    if (!preview || preview.revision !== this.revision || preview.baseFingerprint !== this.fingerprint ||
        preview.changesFingerprint !== sha256(changes)) {
      throw new ApplicationError(ERROR_CODES.STALE_PREVIEW, 'preview token does not match current state');
    }
    return preview;
  }

  commit(build, expectedFingerprint) {
    const actual = sha256(build);
    if (actual !== expectedFingerprint) {
      throw new ApplicationError(ERROR_CODES.STALE_PREVIEW, 'provider commit differs from preview');
    }
    this.committed = immutableCopy(build);
    this.fingerprint = actual;
    this.revision += 1;
    this.previews.clear();
  }

  reset(build) {
    const fingerprint = sha256(build);
    if (fingerprint !== sha256(this.initial)) {
      throw new ApplicationError(ERROR_CODES.RECOVERY_FAILED, 'provider did not restore baseline');
    }
    this.committed = this.initial;
    this.fingerprint = fingerprint;
    this.revision += 1;
    this.previews.clear();
  }

  invalidatePreviews() { this.previews.clear(); }
}

module.exports = { BuildStateManager };
