'use strict';
const fs=require('node:fs');
const path=require('node:path');
const {check,hash,canonical,validateDefinition}=require('./contracts');
const loadedBytes=new Map(); // A running worker may not relabel cached code as a new implementation.
function loadCatalog({root=path.resolve(__dirname,'../..'),index}={}){
 root=fs.realpathSync(root);
 index??=JSON.parse(fs.readFileSync(path.join(__dirname,'compatibility-index.json'),'utf8'));
 check(index.schemaVersion==='rulekit-execution-index/v1'&&Array.isArray(index.files)&&Array.isArray(index.modules),'INDEX_INVALID');
 check(index.executionSha256===hash(canonical(index.files))&&index.ruleKitVersion==='rulekit-execution/sha256:'+index.executionSha256,'INDEX_IDENTITY_INVALID');
 const seen=new Set();
 for(const row of index.files){
  check(typeof row.path==='string'&&/^[a-zA-Z0-9_./-]+$/.test(row.path)&&!row.path.split('/').some(p=>!p||p==='.'||p==='..')&&!path.isAbsolute(row.path)&&!seen.has(row.path),'INDEX_PATH_INVALID');seen.add(row.path);
  let full=root;for(const part of row.path.split('/')){full=path.join(full,part);check(!fs.lstatSync(full).isSymbolicLink(),'MODULE_SYMLINK_REJECTED');}
  check(fs.statSync(full).isFile()&&hash(fs.readFileSync(full))===row.sha256,'EXECUTION_BYTES_MISMATCH');
  check(!loadedBytes.has(full)||loadedBytes.get(full)===row.sha256,'EXECUTION_RESTART_REQUIRED');
 }
 const expected=index.files.filter(row=>row.path.startsWith('snapshot-management/compatibility/versions/')).map(row=>row.path);
 check(canonical(expected)===canonical(index.modules),'INDEX_MODULE_SET_MISMATCH');
 for(const row of index.files)loadedBytes.set(path.join(root,row.path),row.sha256);
 const definitions=[],ids=new Set(),bindings=new Set();
 for(const name of index.modules){
  check(/^snapshot-management\/compatibility\/versions\/[a-zA-Z0-9._-]+\.js$/.test(name),'MODULE_PATH_INVALID');
  const definition=validateDefinition(require(path.join(root,name)));
  check(!ids.has(definition.definitionId),'DUPLICATE_DEFINITION');ids.add(definition.definitionId);
  for(const binding of definition.bindings){check(!bindings.has(binding.id),'AMBIGUOUS_STRATEGY_BINDING');bindings.add(binding.id);}
  definitions.push(definition);
 }
 return Object.freeze({definitions:Object.freeze(definitions),ruleKitVersion:index.ruleKitVersion,executionSha256:index.executionSha256});
}
module.exports={loadCatalog};
