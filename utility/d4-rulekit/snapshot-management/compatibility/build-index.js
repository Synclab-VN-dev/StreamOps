'use strict';
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const {check,hash,canonical}=require('./contracts');
const PREFIX='snapshot-management/compatibility/versions/';
function buildIndex({root=path.resolve(__dirname,'../..')}={}){
 root=fs.realpathSync(root);
 const names=execFileSync('git',['ls-files','-z','--','.'],{cwd:root}).toString().split('\0').filter(Boolean);
 // Bind the entire shipped execution tree, including schemas/dependency locks,
 // not just the version module. Tests/docs/generated index are not executable inputs.
 const selected=names.filter(name=>!name.includes('/tests/')&&!name.includes('/docs/')&&!name.includes('/node_modules/')&&
  (name.includes('/src/')||name.includes('/schemas/')||name.startsWith('snapshot-management/compatibility/')||name.endsWith('package-lock.json')||name.endsWith('package.json'))&&/\.(js|json)$/.test(name)&&!name.endsWith('compatibility-index.json')).sort();
 const files=selected.map(name=>{
  const full=path.join(root,name);let cursor=root;
  for(const part of name.split('/')){cursor=path.join(cursor,part);check(!fs.lstatSync(cursor).isSymbolicLink(),'BUILD_SYMLINK_REJECTED');}
  check(fs.statSync(full).isFile(),'BUILD_FILE_INVALID');return {path:name,sha256:hash(fs.readFileSync(full))};
 });
 const modules=files.filter(row=>row.path.startsWith(PREFIX)).map(row=>row.path);
 check(modules.length>0,'NO_TRACKED_COMPATIBILITY_MODULES');
 for(const name of modules)check(new RegExp('^'+PREFIX+'[a-zA-Z0-9._-]+\\.js$').test(name),'MODULE_PATH_INVALID');
 const executionSha256=hash(canonical(files));
 return {schemaVersion:'rulekit-execution-index/v1',files,modules,executionSha256,ruleKitVersion:'rulekit-execution/sha256:'+executionSha256};
}
if(require.main===module){const index=buildIndex();const output=path.join(__dirname,'compatibility-index.json');fs.writeFileSync(output,JSON.stringify(index,null,2)+'\n');process.stdout.write(JSON.stringify({modules:index.modules.length,files:index.files.length,ruleKitVersion:index.ruleKitVersion})+'\n');}
module.exports={buildIndex};
