'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {validate,RELEASE}=require('../../../../catalog-export/run');
const {FIXTURE}=require('../../src/encrypted-fixture');
const config={snapshot:FIXTURE.snapshotId,manifestSha256:FIXTURE.manifestSha256,ageRecipient:FIXTURE.recipient};
test('catalog CI accepts pinned ID/release and rejects untrusted source, hashes, recipients and fields',()=>{
 assert.equal(validate(config),config);
 const {ageRecipient,...plainConfig}=config;
 assert.deepEqual(validate(plainConfig),plainConfig);
 assert.equal(validate({...config,snapshot:RELEASE}).snapshot,RELEASE);
 for(const patch of [{snapshot:'https://example.com/evil'},{snapshot:'unknown'},{manifestSha256:'0'.repeat(64)},{ageRecipient:'other'},{families:[]},{command:'echo'}])assert.throws(()=>validate({...config,...patch}));
});
