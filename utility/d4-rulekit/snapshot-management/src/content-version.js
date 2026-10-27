'use strict';

// Offline content identity only. No network, registry, provider, activation or
// compatibility decision is made here. Integrity is delegated to the store.
const Ajv = require('ajv');
const { FileSystemSnapshotStore } = require('../../browser-infra/src/snapshot/store');
const { validateSafeUrl, normalizeOrigins } = require('../../browser-infra/src/snapshot/policy');
const { fail, SnapshotError, digest, canonical } = require('./trust');
const schema = require('../schemas/content-version.schema.json');
const ajv = new Ajv({strict:true,allErrors:true});
ajv.addSchema(schema);
const validateParams = ajv.compile({$ref:'d4-rulekit-content-version/v1#/definitions/compareParams'});
const validateScope = ajv.compile({$ref:'d4-rulekit-content-version/v1#/definitions/scope'});
const CONTRACT = 'd4-rulekit-content-version/v1';
const sorted = values => [...values].sort();
const uniqueObjects = values => [...new Map(values.map(value => [canonical(value),value])).entries()]
  .sort(([a],[b]) => a < b ? -1 : a > b ? 1 : 0).map(([,value]) => value);

function normalizeUrl(value) {
  let url;
  try {url = new URL(value);} catch {throw new SnapshotError('CONTENT_RESOURCE_URL_INVALID');}
  // Reuse capture URL safety: credentials/sensitive query names are forbidden.
  return validateSafeUrl(value,[url.origin]);
}
function normalizeScope(input) {
  fail(validateScope(input),'CONTENT_SCOPE_SCHEMA_INVALID');
  const scope = structuredClone(input);
  scope.origins = [...normalizeOrigins(scope.origins)];
  scope.methods = sorted(scope.methods);
  scope.excludedResourceTypes = sorted(scope.excludedResourceTypes);
  for (const field of ['include','exclude']) {
    scope[field] = uniqueObjects(scope[field].map(rule => {
      const origin = new URL(normalizeUrl(rule.origin)).origin;
      fail(scope.origins.includes(origin),'CONTENT_RULE_ORIGIN_OUTSIDE_SCOPE');
      fail(rule.path.startsWith('/') && !/[?#\\]/.test(rule.path),'CONTENT_SCOPE_PATH_INVALID');
      const url = new URL(rule.path,origin);
      fail(url.origin === origin && url.pathname === rule.path,'CONTENT_SCOPE_PATH_INVALID');
      return {...rule,origin};
    }));
  }
  return scope;
}
function scopeFingerprint(input) {return digest(Buffer.from(canonical(normalizeScope(input))));}
function identity(ref) {
  fail(['GET','HEAD'].includes(ref.method),'CONTENT_RESOURCE_METHOD_INVALID');
  const url = normalizeUrl(ref.url);
  return {method:ref.method,url,key:ref.method+' '+url};
}
function inScope(resource,scope) {
  const url = new URL(resource.url);
  const matches = rule => url.origin === rule.origin &&
    (rule.match === 'EXACT' ? url.pathname === rule.path : url.pathname.startsWith(rule.path));
  return scope.methods.includes(resource.method) && scope.origins.includes(url.origin) &&
    scope.include.some(matches) && !scope.exclude.some(matches);
}
function freeze(value) {
  if(value && typeof value === 'object') {Object.values(value).forEach(freeze);Object.freeze(value);}
  return value;
}

async function buildScopedInventory(store,reference) {
  const scope = normalizeScope(reference.scope);
  const scopeHash = scopeFingerprint(scope);
  const first = await store.load(reference.snapshotId);
  const verified = await store.verify(reference.snapshotId);
  fail(verified.manifestSha256 === reference.manifestSha256,'CONTENT_MANIFEST_BINDING_MISMATCH');
  const manifest = await store.load(reference.snapshotId);
  fail(canonical(first) === canonical(manifest),'CONTENT_MANIFEST_CHANGED_DURING_VERIFICATION');
  const types = new Map();
  for(const node of reference.coverage?.nodes ?? []) {
    const normalized = identity(node);
    fail(!types.has(normalized.key) || types.get(normalized.key) === node.resourceType,'CONTENT_DISCOVERY_IDENTITY_CONFLICT');
    types.set(normalized.key,node.resourceType);
  }
  const all = new Map();
  const resources = new Map();
  for (const resource of manifest.resources) {
    const normalized = identity(resource);
    const old = all.get(normalized.key);
    fail(!old || old.sha256 === resource.sha256,'CONTENT_RESOURCE_IDENTITY_CONFLICT');
    const record = {...normalized,sha256:resource.sha256,status:resource.status};
    all.set(record.key,record);
    if(inScope(record,scope) && !scope.excludedResourceTypes.includes(types.get(record.key))) resources.set(record.key,record);
  }
  const records = [...resources.values()].sort((a,b) => a.key < b.key ? -1 : a.key > b.key ? 1 : 0);
  // Deliberately not manifestSha256 or resourceInventorySha256. Metadata,
  // headers/status, order, timestamps and snapshot ID never enter this hash.
  const contentFingerprint = digest(Buffer.from(canonical({
    domain:'d4-rulekit-snapshot-content/v1',scopeFingerprint:scopeHash,
    resources:records.map(({method,url,sha256}) => ({method,url,sha256})),
  })));
  const coverage = verifyCoverage(reference.coverage,reference,scope,scopeHash,all,resources,manifest.sourceUrl);
  return freeze({schemaVersion:'d4-rulekit-scoped-inventory/v1',snapshotId:reference.snapshotId,
    manifestSha256:verified.manifestSha256,scope,scopeFingerprint:scopeHash,contentFingerprint,
    fingerprintKind:coverage.state === 'COMPLETE' ? 'COMPLETE_SCOPED_CONTENT' : 'OBSERVED_SCOPED_CONTENT',
    resources:records.map(({method,url,key,sha256}) => ({method,url,identity:key,sha256})),coverage});
}

function verifyCoverage(evidence,reference,scope,scopeHash,all,resources,sourceUrl) {
  const reasons = new Set();
  const missing = new Set();
  const unreachable = new Set();
  const finish = () => ({state:reasons.size ? 'UNVERIFIED':'COMPLETE',
    reasons:sorted(reasons),missing:sorted(missing),unreachable:sorted(unreachable),
    scopedResourceCount:resources.size,manifestResourceCount:all.size,
    evidenceId:evidence?.evidenceId ?? null});
  if(!evidence) {reasons.add('COVERAGE_EVIDENCE_MISSING');return finish();}
  if(evidence.manifestSha256 !== reference.manifestSha256) reasons.add('COVERAGE_MANIFEST_BINDING_MISMATCH');
  if(evidence.scopeFingerprint !== scopeHash) reasons.add('COVERAGE_SCOPE_BINDING_MISMATCH');
  for (const [field,reason] of [['navigationComplete','NAVIGATION_INCOMPLETE'],['interactionsComplete','INTERACTIONS_INCOMPLETE'],['discoveryComplete','DISCOVERY_INCOMPLETE']]) {
    if(evidence[field] !== true) reasons.add(reason);
  }
  if(evidence.pendingRequests !== 0) reasons.add('PENDING_REQUESTS');
  const nodes = new Map();
  for (const node of evidence.nodes) {
    const normalized = identity(node);
    const old = nodes.get(normalized.key);
    fail(!old || old.resourceType === node.resourceType,'CONTENT_DISCOVERY_IDENTITY_CONFLICT');
    nodes.set(normalized.key,{...normalized,resourceType:node.resourceType});
    if(inScope(normalized,scope)) {
      if(!scope.excludedResourceTypes.includes(node.resourceType) && !resources.has(normalized.key)) missing.add(normalized.key);
    }
  }
  for (const resource of resources.values()) {
    if(!nodes.has(resource.key)) missing.add(resource.key);
    if(scope.excludedResourceTypes.length && !nodes.has(resource.key)) reasons.add('RESOURCE_TYPE_COVERAGE_MISSING');
    if(resource.method !== 'GET' || resource.status < 200 || resource.status >= 300) reasons.add('CONTENT_BODY_UNCONFIRMED');
  }
  for (const failed of evidence.failedRequests) {
    if(inScope(identity(failed),scope)) reasons.add('IN_SCOPE_REQUEST_FAILED');
  }
  const roots = evidence.roots.map(root => identity(root).key);
  for(const key of roots) if(!all.has(key)) missing.add(key);
  if(!roots.includes(identity({method:'GET',url:sourceUrl}).key)) reasons.add('NAVIGATION_ROOT_MISMATCH');
  const adjacency = new Map();
  for(const edge of evidence.edges) {
    const from = identity(edge.from).key, to = identity(edge.to).key;
    if(!nodes.has(from) || !nodes.has(to)) reasons.add('GRAPH_ENDPOINT_MISSING');
    if(!adjacency.has(from)) adjacency.set(from,[]);
    adjacency.get(from).push(to);
  }
  const reached = new Set(),queue = [...roots];
  for(let index=0;index<queue.length;index++) {
    const key = queue[index];
    if(reached.has(key)) continue;
    reached.add(key);
    if(!nodes.has(key)) {reasons.add('GRAPH_ENDPOINT_MISSING');continue;}
    const node = nodes.get(key);
    if(inScope(node,scope) && !scope.excludedResourceTypes.includes(node.resourceType) && !all.has(key)) missing.add(key);
    for(const next of adjacency.get(key) ?? []) if(!reached.has(next)) queue.push(next);
  }
  for(const resource of resources.values()) if(!reached.has(resource.key)) unreachable.add(resource.key);
  if(missing.size) reasons.add('RESOURCE_COVERAGE_MISSING');
  if(unreachable.size) reasons.add('RESOURCE_GRAPH_INCOMPLETE');
  if(resources.size === 0) reasons.add('EMPTY_SCOPED_INVENTORY');
  return finish();
}

function diffInventories(baseline,candidate) {
  const old = new Map(baseline.resources.map(resource => [resource.identity,resource]));
  const current = new Map(candidate.resources.map(resource => [resource.identity,resource]));
  const changes = [];
  const summary = {added:0,removed:0,modified:0};
  for(const key of sorted(new Set([...old.keys(),...current.keys()]))) {
    const a = old.get(key),b = current.get(key);
    const change = !a ? 'ADDED' : !b ? 'REMOVED' : a.sha256 !== b.sha256 ? 'MODIFIED' : null;
    if(!change) continue;
    summary[change.toLowerCase()]++;
    changes.push({change,identity:key,method:(b??a).method,url:(b??a).url,
      oldSha256:a?.sha256 ?? null,newSha256:b?.sha256 ?? null});
  }
  return {summary,resources:changes};
}

async function compareSnapshots(storeRoot,params) {
  fail(validateParams(params),'CONTENT_COMPARE_SCHEMA_INVALID');
  const store = new FileSystemSnapshotStore({rootDir:storeRoot});
  const baseline = await buildScopedInventory(store,params.baseline);
  const candidate = await buildScopedInventory(store,params.candidate);
  const comparable = baseline.scopeFingerprint === candidate.scopeFingerprint;
  const complete = baseline.coverage.state === 'COMPLETE' && candidate.coverage.state === 'COMPLETE';
  const result = {protocolVersion:'d4-rulekit-snapshots/v1',contentVersionContract:CONTRACT,
    status:'UNVERIFIED',reason:!comparable ? 'SCOPE_POLICY_MISMATCH':'COVERAGE_UNVERIFIED',
    baselineFingerprint:baseline.contentFingerprint,candidateFingerprint:candidate.contentFingerprint,
    fingerprintKind:comparable && complete ? 'COMPLETE_SCOPED_CONTENT':'OBSERVED_SCOPED_CONTENT',
    baseline:{snapshotId:baseline.snapshotId,manifestSha256:baseline.manifestSha256,scopeFingerprint:baseline.scopeFingerprint},
    candidate:{snapshotId:candidate.snapshotId,manifestSha256:candidate.manifestSha256,scopeFingerprint:candidate.scopeFingerprint},
    coverage:{baseline:baseline.coverage,candidate:candidate.coverage},scopeComparable:comparable,diff:null,observations:null};
  if(comparable && !complete) {
    const observed = diffInventories(baseline,candidate).resources;
    // Presence in a partial capture is not proof of addition/removal in the
    // complete graph. These are observations, never confirmed diff changes.
    result.observations = {
      basis:'VERIFIED_CAPTURED_SETS_ONLY',
      baselineOnly:observed.filter(row => row.change === 'REMOVED').map(({identity,url,oldSha256}) => ({identity,url,sha256:oldSha256})),
      candidateOnly:observed.filter(row => row.change === 'ADDED').map(({identity,url,newSha256}) => ({identity,url,sha256:newSha256})),
      differentBytes:observed.filter(row => row.change === 'MODIFIED').map(({identity,url,oldSha256,newSha256}) => ({identity,url,oldSha256,newSha256})),
    };
  }
  if(comparable && complete) {
    result.diff = diffInventories(baseline,candidate);
    result.status = result.diff.resources.length ? 'NEW_VERSION_FOUND':'UNCHANGED';
    result.reason = result.diff.resources.length ? 'SCOPED_CONTENT_CHANGED':'SCOPED_CONTENT_IDENTICAL';
  }
  return freeze(result);
}
module.exports={CONTRACT,normalizeScope,scopeFingerprint,buildScopedInventory,compareSnapshots};
