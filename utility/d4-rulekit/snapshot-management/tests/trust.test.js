'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { TrustedRegistry, canonical } = require('../src/trust');
function setup(scope = 'ISOLATED_TEST') {
  const { publicKey, privateKey } = crypto.generateKeyPairSync('ed25519');
  const registry = new TrustedRegistry({ anchors:{owner:{publicKey:publicKey.export({type:'spki',format:'pem'}),minimumRegistryRevision:1}},ruleKitVersion:'test-rulekit/v1',scope });
  const payload = {schemaVersion:'d4-rulekit-compatibility-registry/v1',revision:1,issuedAt:'2026-01-01T00:00:00Z',expiresAt:'2035-01-01T00:00:00Z',entries:[],revokedEntryIds:[],revokedKeyIds:[]};
  const sign = value => ({schemaVersion:'d4-rulekit-registry-envelope/v1',keyId:'owner',payload:value,signature:crypto.sign(null,Buffer.from(canonical(value)),privateKey).toString('base64')});
  return {registry,payload,sign};
}
test('local APPROVED JSON and tampered signed registries cannot confer trust', () => {
  const {registry,payload,sign}=setup();
  assert.throws(()=>registry.accept({APPROVED:true}),{code:'REGISTRY_SCHEMA_INVALID'});
  const good=sign(payload); registry.accept(good);
  const tampered=structuredClone(good); tampered.payload.revision=2;
  assert.throws(()=>registry.accept(tampered),{code:'REGISTRY_SIGNATURE_INVALID'});
  const wrong=setup().sign({...payload,revision:2});
  assert.throws(()=>registry.accept(wrong),{code:'REGISTRY_SIGNATURE_INVALID'});
});
test('registry revisions cannot rollback or collide; expiry fails closed', () => {
  const {registry,payload,sign}=setup(); registry.accept(sign({...payload,revision:2}));
  assert.throws(()=>registry.accept(sign(payload)),{code:'REGISTRY_ROLLBACK'});
  assert.throws(()=>registry.accept(sign({...payload,revision:2,revokedEntryIds:['revoked']})),{code:'REGISTRY_REVISION_COLLISION'});
  assert.throws(()=>registry.accept(sign({...payload,revision:3,expiresAt:'2020-01-01T00:00:00Z'})),{code:'REGISTRY_EXPIRED_OR_NOT_YET_VALID'});
});
test('production has no implicit trust anchor or enabled policy', () => {
  const pending=require('../src/production-trust-anchors.json');
  assert.equal(pending.policyStatus,'OWNER_TRUST_ANCHOR_PENDING');
  assert.throws(()=>new TrustedRegistry({anchors:pending.keys}),{code:'TRUST_POLICY_NOT_CONFIGURED'});
});
module.exports={setup};
