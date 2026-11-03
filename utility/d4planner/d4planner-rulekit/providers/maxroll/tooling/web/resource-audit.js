'use strict';
const fs=require('node:fs/promises');const path=require('node:path');
const {FileSystemSnapshotStore}=require('../../../../browser-infra/src');
const {entityDependencies,auxiliaryDependencies}=require('./catalog-coverage');
const {dependencies}=require('./capture-ui');
const {moduleDependencies,htmlDependencies}=require('./resource-dependencies');
async function audit(config,selectable){
  const store=new FileSystemSnapshotStore({rootDir:config.snapshotRoot});const integrity=await store.verify(config.snapshotId);
  if(integrity.manifestSha256!==config.manifestSha256)throw Error('Configured snapshot mismatch');
  const pkg=await store.loadPackage(config.snapshotId),manifest=pkg.manifest;
  const dataResource=[...pkg.resources.values()].find(r=>r.url.includes('/game/data.min.json'));
  if(!dataResource)throw Error('Catalog missing');const data=JSON.parse(dataResource.body);
  const coverage=selectable||JSON.parse(await fs.readFile(path.join(config.snapshotRoot,config.snapshotId,'ui-coverage.json'))).selectable;
  if(!coverage)throw Error('Full selectable inventory missing');
  const rows=entityDependencies(data,coverage),aux=auxiliaryDependencies(data);
  const status=url=>{const r=pkg.resources.get('GET '+url);return !r?'MISSING':r.status!==200?'HTTP_'+r.status:!r.headers['content-type']?.startsWith('image/')?'INVALID_MIME':'PRESENT';};
  const entities=rows.map(row=>({...row,images:row.images.map(image=>({...image,status:status(image.url),blob:pkg.resources.get('GET '+image.url)?.blob,sha256:pkg.resources.get('GET '+image.url)?.sha256}))}));
  const auxiliary=aux.map(row=>({...row,status:status(row.url)}));
  const staticEdges=[];
  for(const r of pkg.resources.values()){
    const type=r.headers['content-type']||'';let links=[];
    if(type.includes('text/css'))links=dependencies(r.body.toString(),r.url);
    if(type.includes('javascript'))links=moduleDependencies(r.body.toString(),r.url);
    if(type.includes('text/html'))links=htmlDependencies(r.body.toString(),r.url);
    for(const url of links){
      const relative='./'+url.split('/').at(-1);const text=r.body.toString();
      const lazy=text.includes('import("'+relative+'")')||text.includes("import('"+relative+"')");
      staticEdges.push({from:r.url,to:url,kind:lazy?'CONDITIONAL_DYNAMIC':'STATIC',status:pkg.resources.has('GET '+url)?'PRESENT':new URL(url).pathname==='/favicon.ico'?'OPTIONAL_SITE_FAVICON':'MISSING'});
    }
  }
  const matrix={};for(const r of entities){const g=matrix[r.type]??={entities:new Set(),urls:new Set(),missing:new Set()};g.entities.add(r.entityId);for(const i of r.images){g.urls.add(i.url);if(i.status!=='PRESENT')g.missing.add(i.url);}}
  const report={integrity,version:manifest.version,groups:coverage.groups.length,selectableEntities:new Set(rows.map(r=>r.entityId)).size,
    matrix:Object.fromEntries(Object.entries(matrix).map(([k,v])=>[k,{entities:v.entities.size,artworkURLs:v.urls.size,missing:v.missing.size}])),entities,auxiliary,staticEdges,
    status:entities.every(r=>r.images.length&&r.images.every(i=>i.status==='PRESENT'))&&auxiliary.every(r=>r.status==='PRESENT')&&staticEdges.every(r=>r.status!=='MISSING')?'PASS':'FAIL'};
  return report;
}
module.exports={audit,moduleDependencies};
if(require.main===module)fs.readFile(process.argv[2],'utf8').then(JSON.parse).then(audit).then(r=>{console.log(JSON.stringify(r,null,2));if(r.status!=='PASS')process.exitCode=1;}).catch(e=>{console.error(e.message);process.exitCode=1;});
