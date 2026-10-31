'use strict';
// Structural evidence only, not a proof of all formulas or class compatibility.
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const crypto=require('node:crypto');
const ts=require('../../../providers/maxroll/node_modules/typescript');
const {FileSystemSnapshotStore}=require('../../../browser-infra/src');
const {loadCatalog}=require('../../compatibility/loader');
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
function inspect(text){
 const source=ts.createSourceFile('private.js',text,ts.ScriptTarget.Latest,true,ts.ScriptKind.JS);assert.equal(source.parseDiagnostics.length,0);
 const rows={},shared={};
 function shape(node){const values=[];function walk(n){let value=null;if(ts.isIdentifier(n)){const p=n.parent;value=(ts.isPropertyAccessExpression(p)&&p.name===n||ts.isPropertyAssignment(p)&&p.name===n)?n.text:'#';}else if(ts.isStringLiteral(n)||ts.isNumericLiteral(n))value=n.text;values.push([n.kind,value]);ts.forEachChild(n,walk);}walk(node);return sha(JSON.stringify(values));}
 function visit(n){
  if(ts.isBinaryExpression(n)&&n.operatorToken.kind===ts.SyntaxKind.EqualsToken&&ts.isPropertyAccessExpression(n.left)&&['sharedFlags','sharedParams','sharedOptions'].includes(n.left.name.text))(shared[n.left.name.text]??=[]).push(shape(n.right));
  if(ts.isCallExpression(n)&&n.arguments.length>1&&ts.isStringLiteral(n.arguments[0])&&/register(?:Power|Skill)/.test(n.expression.getText(source)))(rows[n.arguments[0].text]??=[]).push({sourceSha256:sha(n.getText(source)),shape:shape(n)});
  ts.forEachChild(n,visit);
 }
 visit(source);return {rows,shared};
}
(async()=>{
 assert.ok(process.env.MAXROLL_AUTHORIZED_SNAPSHOT_ROOT&&process.env.COMPATIBILITY_AUDIT_OUTPUT);
 const all=loadCatalog().definitions,definitions=['maxroll-20261023','maxroll-20261027'].map(id=>all.find(d=>d.definitionId===id));assert.ok(definitions.every(Boolean));
 const store=new FileSystemSnapshotStore({rootDir:process.env.MAXROLL_AUTHORIZED_SNAPSHOT_ROOT}),data=[];
 for(const d of definitions){const v=await store.verify(d.identity.snapshotId);assert.equal(v.manifestSha256,d.identity.snapshotManifestSha256);const p=await store.loadPackage(d.identity.snapshotId),r=p.manifest.resources.find(r=>r.sha256===d.identity.engineAssetSha256);assert.ok(r);data.push(inspect(p.resources.get(r.key).body.toString()));}
 const results=Object.keys(definitions[1].optionRules).map(id=>{assert.ok(data[0].rows[id]&&data[1].rows[id]);assert.deepEqual(data[0].rows[id].map(x=>x.shape),data[1].rows[id].map(x=>x.shape));return {id,baseline:data[0].rows[id],candidate:data[1].rows[id],structureEqual:true};});
 for(const name of ['sharedFlags','sharedParams','sharedOptions']){assert.ok(data[0].shared[name]?.length>0);assert.deepEqual(data[0].shared[name],data[1].shared[name]);}
 const report={classification:'AST_STRUCTURE_NOT_GLOBAL_SEMANTICS_PROOF',engines:definitions.map(d=>d.identity.engineAssetSha256),results,shared:data.map(d=>d.shared)};
 await fs.writeFile(process.env.COMPATIBILITY_AUDIT_OUTPUT,JSON.stringify(report,null,2)+'\n',{mode:0o600});console.log(JSON.stringify({status:'PASS',registeredRuleGroups:results.length,sharedGroups:3}));
})().catch(e=>{console.error(e.name,e.message);process.exitCode=1;});
