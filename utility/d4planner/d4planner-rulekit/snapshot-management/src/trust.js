'use strict';
const crypto = require('node:crypto');
const Ajv = require('ajv');
const schema = require('../schemas/registry.schema.json');

class SnapshotError extends Error {
  constructor(code, message = code) { super(message); this.name = 'SnapshotError'; this.code = code; }
}
const fail = (condition, code) => { if (!condition) throw new SnapshotError(code); };
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
function canonical(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
}
const ajv = new Ajv({ allErrors: true, strict: true });
ajv.addFormat('date-time', value => typeof value === 'string' && /^\d{4}-\d\d-\d\dT/.test(value) && Number.isFinite(Date.parse(value)));
const validate = ajv.compile(schema);

class TrustedRegistry {
  constructor({ anchors, ruleKitVersion, scope = 'PRODUCTION', now = () => Date.now() } = {}) {
    fail(anchors && typeof anchors === 'object' && !Array.isArray(anchors), 'TRUST_POLICY_NOT_CONFIGURED');
    fail(Object.keys(anchors).length > 0, 'TRUST_POLICY_NOT_CONFIGURED');
    fail(['PRODUCTION', 'ISOLATED_TEST'].includes(scope), 'INVALID_TRUST_SCOPE');
    this.anchors = Object.freeze(Object.fromEntries(Object.entries(anchors).map(([id, value]) => [id, Object.freeze({ ...value })]))); this.ruleKitVersion = ruleKitVersion;
    this.scope = scope; this.now = now; this.envelope = null; this.revision = 0;
    this.sha256 = null; this.revokedKeys = new Set();
  }
  verify(envelope, minimumRevision = 0) {
    fail(validate(envelope), 'REGISTRY_SCHEMA_INVALID');
    const anchor = this.anchors[envelope.keyId];
    fail(anchor && !this.revokedKeys.has(envelope.keyId), 'REGISTRY_SIGNER_UNTRUSTED');
    const payloadBytes = Buffer.from(canonical(envelope.payload));
    let key;
    try { key = crypto.createPublicKey(anchor.publicKey); } catch { throw new SnapshotError('TRUST_ANCHOR_INVALID'); }
    fail(key.asymmetricKeyType === 'ed25519', 'TRUST_ANCHOR_INVALID');
    fail(crypto.verify(null, payloadBytes, key, Buffer.from(envelope.signature, 'base64')), 'REGISTRY_SIGNATURE_INVALID');
    const payload = envelope.payload;
    fail(payload.revision >= Math.max(minimumRevision, anchor.minimumRegistryRevision ?? 1), 'REGISTRY_ROLLBACK');
    fail(Date.parse(payload.issuedAt) <= this.now() && Date.parse(payload.expiresAt) > this.now(), 'REGISTRY_EXPIRED_OR_NOT_YET_VALID');
    fail(new Set(payload.entries.map(entry => entry.entryId)).size === payload.entries.length, 'DUPLICATE_COMPATIBILITY_ENTRY');
    const hash = digest(Buffer.from(canonical(envelope)));
    if (this.envelope) {
      fail(payload.revision >= this.revision, 'REGISTRY_ROLLBACK');
      fail(this.envelope.payload.revokedEntryIds.every(id=>payload.revokedEntryIds.includes(id)) && this.envelope.payload.revokedKeyIds.every(id=>payload.revokedKeyIds.includes(id)), 'REGISTRY_REVOCATION_ROLLBACK');
      fail(payload.revision !== this.revision || hash === this.sha256, 'REGISTRY_REVISION_COLLISION');
    }
    return { envelope: structuredClone(envelope), hash };
  }
  accept(envelope, minimumRevision = 0) {
    const checked = this.verify(envelope, minimumRevision);
    this.envelope = checked.envelope; this.sha256 = checked.hash; this.revision = envelope.payload.revision;
    for (const id of envelope.payload.revokedKeyIds) this.revokedKeys.add(id);
    return { revision: this.revision, sha256: this.sha256 };
  }
  resolve(entryId) {
    fail(this.envelope, 'REGISTRY_NOT_INSTALLED');
    fail(Date.parse(this.envelope.payload.expiresAt) > this.now(), 'REGISTRY_EXPIRED_OR_NOT_YET_VALID');
    const entry = this.envelope.payload.entries.find(row => row.entryId === entryId);
    fail(entry, 'SNAPSHOT_COMPATIBILITY_UNKNOWN');
    fail(entry.status === 'APPROVED' && !this.envelope.payload.revokedEntryIds.includes(entryId), 'COMPATIBILITY_REVOKED');
    fail(!this.revokedKeys.has(this.envelope.keyId), 'REGISTRY_SIGNER_REVOKED');
    fail(entry.ruleKitVersion === this.ruleKitVersion, 'RULEKIT_VERSION_INCOMPATIBLE');
    fail(this.scope !== 'PRODUCTION' || entry.approval.testClass === 'REAL_PROVIDER', 'SYNTHETIC_BINDING_NOT_PRODUCTION');
    return structuredClone(entry);
  }
  listBindings() {
    fail(this.envelope, 'REGISTRY_NOT_INSTALLED');
    return this.envelope.payload.entries.map(entry => {
      try { return { entryId:entry.entryId, snapshotId:entry.snapshotId, compatible:true, ...this.resolve(entry.entryId) }; }
      catch (error) { return { entryId:entry.entryId, snapshotId:entry.snapshotId, compatible:false, reason:error.code }; }
    });
  }
}
module.exports = { TrustedRegistry, SnapshotError, fail, digest, canonical };
