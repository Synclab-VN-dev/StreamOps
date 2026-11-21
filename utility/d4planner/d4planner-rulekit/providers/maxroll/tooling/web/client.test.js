'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');

test('LAN analytics XHR is aborted without a send or success; other destinations stay fail-closed',async()=>{
  const network=[],reports=[];
  class XHR {
    open(method,url){this.url=url;this.readyState=1;}
    send(body){assert.equal(this.readyState,1);network.push({url:this.url,body});}
    abort(){this.readyState=0;}
  }
  const origin='https://192.168.1.20:6091';
  const context={URL,Request,Response,XMLHttpRequest:XHR,location:{origin,href:origin+'/d4/planner/test'},
    fetch:async(url,options)=>{reports.push({url,body:JSON.parse(options.body)});return new Response(null,{status:204});},
    addEventListener(){},document:{addEventListener(){}},navigator:{userAgent:'synthetic'},
    console:{error(){}},innerWidth:400,innerHeight:800,isSecureContext:true};
  context.window=context;context.parent=context;
  vm.runInNewContext(fs.readFileSync(__dirname+'/client.js','utf8'),context);
  const xhr=new XHR();let success=false;xhr.onload=()=>{success=true;};
  assert.doesNotThrow(()=>xhr.open('POST','https://analytics.maxroll.gg/api/event?ignored=private'));
  xhr.send('private analytics payload');
  xhr.send('private analytics payload again');
  assert.equal(success,false);assert.deepEqual(network,[]);
  assert(reports.some(r=>r.body.kind==='BLOCKED_ANALYTICS'));
  assert(!JSON.stringify(reports).includes('private'));
  // The same instance remains usable for real captured API calls.
  xhr.open('GET','https://planners.maxroll.gg/profiles/load/d4/test');xhr.send();
  assert.equal(network[0].url,origin+'/__snapshot/planners.maxroll.gg/profiles/load/d4/test');
  for(const url of ['https://evil.test/api/event','https://analytics.maxroll.gg/other','http://analytics.maxroll.gg/api/event','https://user@analytics.maxroll.gg/api/event']){
    assert.throws(()=>xhr.open('POST',url),/External network disabled/);
  }
  await assert.rejects(context.fetch('https://evil.test/'),/External network disabled/);
  assert.equal(network.length,1);
});
