'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { exportMaxrollBuildFromGuide, listMaxrollBuildProfilesFromGuide } = require('../../src/guide-build-export');
const URL = 'https://maxroll.gg/d4/build-guides/synthetic-rogue-guide';
function block() {
  return {blockName:'maxroll/planner-page',attributes:{link:'https://maxroll.gg/d4/planner/test1234#4'},plannerProfile:{
    id:'test1234',game:'d4',name:'Synthetic Rogue',class:'Rogue',userId:999,token:'never-export',
    data:{activeProfile:3,profiles:[
      {name:'Hidden leveling',hidden:true},{name:'Starter'},{name:'Midgame'},
      {name:'Endgame'},{name:'Hidden notes',hidden:true},{name:'Bossing'},
    ].map(p=>({...p,level:70,class:3,items:{4:1},skillTree:{},skillBar:[],paragon:{},warPlans:[]})),
    items:{1:{id:'fixture-helm',sockets:[null]}},options:{note:'literal }; text'},season:15}}};
}
function html(blocks=[block()]) {return '<script>window.__remixContext = '+JSON.stringify({state:{loaderData:{post:{gutenbergBlock:blocks}}}})+'; window.mustNotRun = true;</script>';}
function response(body=html(),status=200,headers={'content-type':'text/html'}) {return new Response(body,{status,headers});}
async function temp(t) {const p=await fs.mkdtemp(path.join(os.tmpdir(),'guide-export-'));t.after(()=>fs.rm(p,{recursive:true,force:true}));return path.join(p,'build.json');}

test('guide defaults to embedded Endgame, not visible-variant interpretation of planner #4',async t=>{
 const outputPath=await temp(t);const source=html();
 const result=await exportMaxrollBuildFromGuide({url:URL,outputPath}, {fetch:async()=>response(source)});
 const exported=JSON.parse(await fs.readFile(outputPath,'utf8'));
 assert.equal(result.profile.profileIndex,3);assert.equal(result.profile.profileName,'Endgame');
 assert.equal(result.profile.selectedBy,'guide-active-profile');
 assert.equal(exported.provenance.source,'LIVE_GUIDE_EMBED');
 assert.equal(exported.provenance.sourceUrl,URL);assert.equal(exported.provenance.plannerUrl,'https://maxroll.gg/d4/planner/test1234#4');
 assert.equal(exported.provenance.snapshotVerification,'NOT_PERFORMED');
 assert.equal(exported.provenance.calculationStatus,'NOT_ASSESSED');
 assert.equal(exported.provenance.guideResponseSha256,crypto.createHash('sha256').update(source).digest('hex'));
 assert.equal(exported.provenance.snapshotId,undefined);
 assert.deepEqual(exported.nativeState.items,block().plannerProfile.data.items);
 assert.equal(exported.nativeState.profiles.length,6);
 assert.equal(exported.loaderMetadata.userId,undefined);assert.equal(exported.loaderMetadata.token,undefined);
 await assert.rejects(()=>exportMaxrollBuildFromGuide({url:URL,outputPath},{fetch:async()=>response()}),{code:'OUTPUT_EXISTS'});
});

test('list exposes indices, explicit profile overrides guide default',async t=>{
 const list=await listMaxrollBuildProfilesFromGuide({url:URL},{fetch:async()=>response()});
 assert.equal(list.nativeActiveProfile,3);assert.equal(list.profiles[5].name,'Bossing');
 const result=await exportMaxrollBuildFromGuide({url:URL,profile:5,outputPath:await temp(t)},{fetch:async()=>response()});
 assert.equal(result.profile.profileName,'Bossing');assert.equal(result.profile.selectedBy,'native-index');
});

test('missing or multiple planner blocks and mismatched identity fail explicitly',async()=>{
 for(const blocks of [[],[block(),block()],[{...block(),attributes:{link:'https://maxroll.gg/d4/planner/other123'}}]]) {
  await assert.rejects(()=>listMaxrollBuildProfilesFromGuide({url:URL},{fetch:async()=>response(html(blocks))}));
 }
});

test('malformed native data and invalid profile fail before writing',async t=>{
 const outputPath=await temp(t);
 for(const alter of [b=>{b.plannerProfile.data.profiles[3].items[4]=999;},b=>{b.plannerProfile.data.activeProfile=999;}]) {
  const b=block();alter(b);
  await assert.rejects(()=>exportMaxrollBuildFromGuide({url:URL,outputPath},{fetch:async()=>response(html([b]))}),{code:'NATIVE_BUILD_INVALID'});
 }
 await assert.rejects(()=>exportMaxrollBuildFromGuide({url:URL,outputPath,profile:-1},{fetch:async()=>response()}),{code:'INVALID_INPUT'});
 await assert.rejects(()=>fs.stat(outputPath),{code:'ENOENT'});
});

test('does not execute scripts or follow redirects outside allowed guide URLs',async()=>{
 let calls=0;
 await assert.rejects(()=>listMaxrollBuildProfilesFromGuide({url:URL},{fetch:async()=>{calls++;return response('',302,{location:'https://example.org/guide'});}}),{code:'INVALID_INPUT'});
 assert.equal(calls,1);
 for(const body of ['<script>window.__remixContext = (() => {throw Error("executed")})();</script>',html()+html(),'<html>challenge</html>'])
  await assert.rejects(()=>listMaxrollBuildProfilesFromGuide({url:URL},{fetch:async()=>response(body)}),{code:'GUIDE_DATA_INVALID'});
 for(const url of ['http://maxroll.gg/d4/build-guides/test','https://maxroll.gg:8443/d4/build-guides/test','https://other.test/d4/build-guides/test'])
  await assert.rejects(()=>listMaxrollBuildProfilesFromGuide({url},{fetch:async()=>{throw Error('must not fetch');}}),{code:'INVALID_INPUT'});
});

test('rejects HTTP errors, non-HTML, oversized and truncated responses',async()=>{
 for(const fake of [()=>response('fail',503),()=>response('{}',200,{'content-type':'application/json'}),()=>response('x'.repeat(8*1024*1024+1)),()=>response('<script>window.__remixContext = {')])
  await assert.rejects(()=>listMaxrollBuildProfilesFromGuide({url:URL},{fetch:async()=>fake()}));
});

test('CLI routes guide URLs without snapshot flags and reports the selected native profile',async t=>{
 const outputPath=await temp(t);const preload=path.join(path.dirname(outputPath),'fetch.cjs');
 await fs.writeFile(preload,`globalThis.fetch=async()=>new Response(${JSON.stringify(html())},{headers:{'content-type':'text/html'}});`);
 const {spawnSync}=require('node:child_process');
 const command=[ '--require',preload,path.resolve(__dirname,'../../scripts/build-export.js'),'--url',URL ];
 const listing=spawnSync(process.execPath,[...command,'--list-profiles'],{encoding:'utf8'});
 assert.equal(listing.status,0,listing.stderr);assert.equal(JSON.parse(listing.stdout).nativeActiveProfile,3);
 const exported=spawnSync(process.execPath,[...command,'--output',outputPath],{encoding:'utf8'});
 assert.equal(exported.status,0,exported.stderr);assert.equal(JSON.parse(exported.stdout).profile.profileName,'Endgame');
 const mixed=spawnSync(process.execPath,[...command,'--snapshot-id','ignored','--list-profiles'],{encoding:'utf8'});
 assert.notEqual(mixed.status,0);assert.match(mixed.stderr,/INVALID_INPUT/);
});

test('public staging allowlist includes guide export dependency of provider entrypoint',async t=>{
 const {spawnSync}=require('node:child_process');
 const repo=path.resolve(__dirname,'../../../../../../..');
 const policy=JSON.parse(await fs.readFile(path.join(repo,'utility/d4planner/d4planner-be/release1/public-content-policy.json')));
 const stage=path.dirname(await temp(t));
 for(const relative of policy.sourceAllowlist) {
  const destination=path.join(stage,relative.replace('utility/d4planner/d4planner-rulekit/','utility/d4-rulekit/'));
  await fs.mkdir(path.dirname(destination),{recursive:true});await fs.copyFile(path.join(repo,relative),destination);
 }
 const entry=path.join(stage,'utility/d4-rulekit/providers/maxroll/src/index.js');
 const child=spawnSync(process.execPath,['-e',"if(typeof require(process.argv[1]).exportMaxrollBuildFromGuide!=='function') process.exit(2)",entry],{
  encoding:'utf8',env:{...process.env,NODE_PATH:path.resolve(__dirname,'../../node_modules')},
 });
 assert.equal(child.status,0,child.stderr);
});
