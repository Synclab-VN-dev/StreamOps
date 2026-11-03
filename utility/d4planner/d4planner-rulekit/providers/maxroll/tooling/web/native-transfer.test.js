'use strict';
const {test}=require('node:test');const assert=require('node:assert/strict');
const {exportBuild,importBuild}=require('./native-transfer');const {startServer}=require('./server');
const state={profiles:[{name:'Synthetic fixture',level:69,items:{4:1},skillTree:{steps:[{data:{28:1}}]},paragon:{steps:[{data:[{nodes:{283:1},glyph:{id:12,level:20}}]}]},effects:[{unknownFutureNativeKey:[1,null,3]}]}],items:{1:{id:'fixture-only',sockets:[null,'gem-fixture',null],explicits:[{id:'affix-fixture',values:[9,2]}],aspects:[{id:'aspect-fixture'}],tempered:[{id:'temper-fixture'}],future:{untouched:[false,null,0]}}},activeProfile:0};
const config={manifestSha256:'a'.repeat(64)};
const snapshot={manifest:{snapshotId:'fixture-ui',sourceUrl:'https://maxroll.gg/d4/planner/12345678',version:'fixture'},resources:new Map([['GET https://planners.maxroll.gg/profiles/load/d4/12345678',{body:Buffer.from(JSON.stringify({id:'12345678',game:'d4',data:'{}'}))}]])};
test('native envelope preserves every value/array/order/null/unknown field and import rejects tampering',()=>{
 const e=exportBuild({data:JSON.stringify(state),name:'fixture',token:'secret'},snapshot,config);
 assert.deepEqual(e.nativeState,state);assert(!JSON.stringify(e).includes('secret'));
 assert.deepEqual(JSON.parse(importBuild(e,snapshot,config).data),state);
 assert.throws(()=>importBuild(e,snapshot,{manifestSha256:'b'.repeat(64)}));
 e.nativeState.items[1].sockets=[];assert.throws(()=>importBuild(e,snapshot,config));
});
test('transfer HTTP requires same origin JSON, returns attachment, rejects cloud writes and never logs raw build',async()=>{
 const net=require('node:net');const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));
 const s=await startServer({...config,port},{snapshot});const base='http://127.0.0.1:'+port;
 try{
 const input=JSON.stringify({data:JSON.stringify(state)});
 assert.equal((await fetch(base+'/__local/export',{method:'POST',body:input})).status,403);
 assert.equal((await fetch(base+'/__local/export',{method:'POST',headers:{Origin:'https://example.invalid','Content-Type':'application/json'},body:input})).status,403);
 const headers={Origin:base,'Content-Type':'application/json','X-Local-Snapshot':config.manifestSha256};
 assert.equal((await fetch(base+'/__local/export',{method:'POST',headers:{...headers,'X-Local-Snapshot':'0'.repeat(64)},body:input})).status,409);
 assert.equal((await fetch(base+'/__local/export',{method:'POST',headers:{Origin:base,'Content-Type':'application/json'},body:input})).status,409,'A stale pre-pin tab must reload, never silently retag its native state');
 const r=await fetch(base+'/__local/export',{method:'POST',headers,body:input});assert.equal(r.status,200);assert.match(r.headers.get('content-disposition'),/attachment/);const envelope=await r.json();
 const imp=await fetch(base+'/__local/import',{method:'POST',headers,body:JSON.stringify(envelope)});assert.equal(imp.status,200);assert.deepEqual(JSON.parse((await imp.json()).data),state);
 for(const body of ['{broken','{}'])assert.equal((await fetch(base+'/__local/export',{method:'POST',headers,body})).status,422);
 assert.equal((await fetch(base+'/__local/export',{method:'POST',headers,body:' '.repeat(8*1024*1024+1)})).status,422);
 assert.equal((await fetch(base+'/__snapshot/planners.maxroll.gg/profiles/d4',{method:'POST',headers,body:input})).status,405);
 assert(!JSON.stringify(s.diagnostics()).includes('fixture-only'));
 }finally{await s.close();}
});

test('published canonical socket contract rejects null without altering native export',()=>{
 const Ajv=require('../../node_modules/ajv/dist/2020');
 const schema=require('../../d4-build-v1.schema.json');
 const validate=new Ajv({strict:true}).compile(schema.$defs.item.properties.sockets);
 assert.equal(validate([null,null]),false);
 const e=exportBuild({data:JSON.stringify(state)},snapshot,config);
 assert.equal(e.provenance.canonicalConversion.code,'CANONICAL_EXPORT_UNSUPPORTED');
 assert.deepEqual(e.nativeState.items[1].sockets,[null,'gem-fixture',null]);
});
