'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const {MaxrollRuntimeAttestationObserver} = require('../../src/runtime-attestation');

async function observerFixture() {
  let closed = false;
  let fail = false;
  const commands = [];
  const cdp = {
    on() {},
    async send(command) {
      commands.push(command);
      if (closed || fail) throw new Error(closed ? 'Target closed' : 'Injected live transport failure');
      return {locations:[]};
    },
    async detach() {
      commands.push('detach');
      if (closed || fail) throw new Error('Cannot detach');
    },
  };
  const lease = {valid:true, page:{isClosed:()=>closed}, createCDPSession:async()=>cdp};
  const observer = new MaxrollRuntimeAttestationObserver({lease,
    nativeState:{profiles:[{items:{}}],items:{}},profileIndex:0,
    profile:{realRuntime:{attestationReadbackExpression:'x',calculationEpochExpression:'x',
      assetUrlRegex:'fixture',breakpoint:{lineNumber:0,columnNumber:0}}},
  });
  await observer.initialize(); commands.length = 0;
  return {observer, lease, commands, closePage:()=>{closed=true;lease.valid=false;}, fail:()=>{fail=true;}};
}

test('confirmed page closure after lease expiry makes observer teardown idempotent', async()=>{
  const fixture = await observerFixture(); fixture.closePage();
  await fixture.observer.close(); await fixture.observer.close();
  assert.deepEqual(fixture.commands, [], 'Do not issue CDP commands to a confirmed destroyed target');
});

test('invalid lease alone never conceals a live target cleanup failure', async()=>{
  const fixture = await observerFixture(); fixture.lease.valid=false;fixture.fail();
  await assert.rejects(fixture.observer.close(), AggregateError);
  assert.deepEqual(fixture.commands,['Network.disable','Debugger.disable','detach']);
});

test('live target teardown still disables both domains and detaches', async()=>{
  const fixture = await observerFixture(); await fixture.observer.close();
  assert.deepEqual(fixture.commands,['Network.disable','Debugger.disable','detach']);
});
