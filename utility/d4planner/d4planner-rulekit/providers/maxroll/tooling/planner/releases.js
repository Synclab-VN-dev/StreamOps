'use strict';
// UI-only release transport. Calculation selection and registries are never changed.
const fs = require('node:fs/promises');
const path = require('node:path');
const {createHash, randomUUID} = require('node:crypto');
const {spawn} = require('node:child_process');
const {canonical, failure, readSelection} = require('./selection');
const REPO = 'Synclab-VN-dev/StreamOps';
const API = `https://api.github.com/repos/${REPO}`;
const HASH = /^[a-f0-9]{64}$/;
const VERSION = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
const PROTOCOL = 'd4planner-local-planner/v1';
const digest = bytes => createHash('sha256').update(bytes).digest('hex');

async function safePath(file) {
  for (let p = path.resolve(file);; p = path.dirname(p)) {
    try { if ((await fs.lstat(p)).isSymbolicLink()) throw failure('PLANNER_SNAPSHOT_UNTRUSTED'); }
    catch (e) { if (e.code !== 'ENOENT') throw e; }
    if (path.dirname(p) === p) break;
  }
}
async function download(url, limit, signal, token = '', accept = 'application/octet-stream') {
  for (let redirects = 0; redirects < 4; redirects++) {
    const u = new URL(url);
    if (u.protocol !== 'https:' || u.username || u.password || !['api.github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'].includes(u.hostname)) throw failure('PLANNER_RELEASE_UNTRUSTED');
    const headers = {'Accept': accept, 'User-Agent': 'D4Planner-Local-Planner', 'X-GitHub-Api-Version': '2022-11-28'};
    if (u.hostname === 'api.github.com' && token) headers.Authorization = `Bearer ${token}`;
    let response;
    try { response = await fetch(u, {headers, signal, redirect: 'manual'}); }
    catch (e) { signal?.throwIfAborted(); throw failure('PLANNER_DOWNLOAD_FAILED'); }
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      const next = response.headers.get('location'); await response.body?.cancel();
      if (!next) throw failure('PLANNER_DOWNLOAD_FAILED');
      url = new URL(next, u).href; continue;
    }
    if (!response.ok) {
      await response.body?.cancel();
      throw failure([401, 403, 404].includes(response.status) ? 'PLANNER_RELEASE_ACCESS_DENIED' : 'PLANNER_DOWNLOAD_FAILED');
    }
    if (Number(response.headers.get('content-length')) > limit) { await response.body?.cancel(); throw failure('PLANNER_RELEASE_UNTRUSTED'); }
    const chunks = []; let bytes = 0;
    try {
      for await (const chunk of response.body) {
        bytes += chunk.length;
        if (bytes > limit) throw failure('PLANNER_RELEASE_UNTRUSTED');
        chunks.push(chunk);
      }
    } catch (error) {
      signal?.throwIfAborted();
      throw error.code === 'PLANNER_RELEASE_UNTRUSTED' ? error : failure('PLANNER_DOWNLOAD_FAILED');
    }
    return Buffer.concat(chunks);
  }
  throw failure('PLANNER_DOWNLOAD_FAILED');
}
function json(bytes) { try { return JSON.parse(bytes); } catch { throw failure('PLANNER_RELEASE_UNTRUSTED'); } }
function select(releases) {
  return releases.filter(r => !r.draft && !r.prerelease && /^d4planner-snapshots\/v\d+\.\d+\.\d+$/.test(r.tag_name || '') &&
    VERSION.test(r.tag_name.split('/v')[1]) && r.assets?.some(a => a.name === 'snapshot-pair.json'))
    .sort((a, b) => {
      const x=a.tag_name.split('/v')[1].split('.').map(Number), y=b.tag_name.split('/v')[1].split('.').map(Number);
      return y[0]-x[0] || y[1]-x[1] || y[2]-x[2];
    });
}
function asset(release, name) {
  const matches = release.assets.filter(a => a.name === name);
  if (matches.length !== 1 || !Number.isSafeInteger(matches[0].id) || matches[0].id <= 0) throw failure('PLANNER_RELEASE_UNTRUSTED');
  return matches[0];
}
function unpack(executable, archive, identity, destination, signal) {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, ['--planner-unpack', archive, identity, destination], {windowsHide: true, stdio: 'ignore'});
    const abort = () => child.kill(); signal?.addEventListener('abort', abort, {once:true});
    if (signal?.aborted) abort();
    child.on('error', () => { signal?.removeEventListener('abort',abort); reject(failure('PLANNER_DECRYPTION_FAILED')); });
    child.on('close', code => {
      signal?.removeEventListener('abort',abort);
      if (signal?.aborted) reject(signal.reason);
      else if (code !== 0) reject(failure('PLANNER_DECRYPTION_FAILED')); else resolve();
    });
  });
}
class ReleaseProvisioner {
  constructor({stateRoot, dataRoot, installationRoot, load, read = download, decrypt = unpack}) {
    Object.assign(this, {stateRoot, dataRoot, installationRoot, load, read, decrypt});
  }
  async ensure(signal) {
    if (!path.isAbsolute(this.stateRoot || '') || !path.isAbsolute(this.dataRoot || '')) throw failure('PLANNER_RELEASE_NOT_FOUND');
    const privateRoot = path.join(path.dirname(this.dataRoot), 'private');
    const configFile = path.join(privateRoot, 'report-config.json');
    await safePath(configFile);
    let token = '';
    try {
      const stat = await fs.stat(configFile); if (stat.size > 8192) throw failure('PLANNER_RELEASE_ACCESS_DENIED');
      token = json(await fs.readFile(configFile)).githubToken || '';
      if (typeof token !== 'string' || token.length > 4096 || /\s/.test(token)) throw failure('PLANNER_RELEASE_ACCESS_DENIED');
    } catch (e) { if (e.code !== 'ENOENT') throw failure('PLANNER_RELEASE_ACCESS_DENIED'); }
    const read = async (url, limit, accept) => { signal?.throwIfAborted(); return this.read(url, limit, signal, token, accept); };
    const releases=[];
    for (let page=1; page<=5; page++) {
      const rows=json(await read(`${API}/releases?per_page=100&page=${page}`,4*1024*1024,'application/vnd.github+json'));
      if (!Array.isArray(rows)) throw failure('PLANNER_RELEASE_UNTRUSTED');
      releases.push(...rows); if(rows.length<100) break;
      if(page===5) throw failure('PLANNER_RELEASE_ENUMERATION_LIMIT');
    }
    let chosen;
    for (const release of select(releases)) {
      const metadataAsset=asset(release,'snapshot-pair.json');
      const bytes=await read(`${API}/releases/assets/${metadataAsset.id}`,1024*1024);
      if (metadataAsset.digest && metadataAsset.digest !== `sha256:${digest(bytes)}`) throw failure('PLANNER_RELEASE_UNTRUSTED');
      const meta=json(bytes), version=release.tag_name.split('/v')[1];
      if(meta.schemaVersion !== 'd4planner-snapshot-pair/v1' || meta.version !== version) throw failure('PLANNER_RELEASE_UNTRUSTED');
      const name=`ui-snapshot-${version}.zip.age`, entry=meta.assets?.[name];
      if(!entry || (entry.plannerProtocolVersion !== undefined && entry.plannerProtocolVersion !== PROTOCOL)) continue;
      if(!HASH.test(entry.sha256 || '') || !HASH.test(entry.manifestSha256 || '') ||
        !Number.isSafeInteger(entry.bytes) || entry.bytes<1 || entry.bytes>128*1024*1024 ||
        !/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,159}$/.test(entry.snapshotId || '') ||
        (entry.uiTrust !== undefined && (!HASH.test(entry.uiTrust?.coverageSha256 || '') ||
        !HASH.test(entry.uiTrust?.validationSha256 || '') || entry.uiTrust?.schemaVersion !== 'maxroll-ui-trust/v1'))) throw failure('PLANNER_RELEASE_UNTRUSTED');
      const binary=asset(release,name);
      if(binary.size !== entry.bytes || (binary.digest && binary.digest !== `sha256:${entry.sha256}`)) throw failure('PLANNER_RELEASE_UNTRUSTED');
      chosen={release,entry,binary}; break;
    }
    if(!chosen) throw failure('PLANNER_RELEASE_NOT_FOUND');
    const identity=path.join(privateRoot,'snapshot-age-identity.txt'); await safePath(identity);
    try { if(!(await fs.stat(identity)).isFile()) throw Error(); } catch { throw failure('PLANNER_DECRYPTION_KEY_REQUIRED'); }
    const parent=path.dirname(this.stateRoot); await safePath(parent); await fs.mkdir(parent,{recursive:true});
    const lockFile=path.join(parent,'.provision.lock');
    let lock; try {lock=await fs.open(lockFile,'wx',0o600);} catch {throw failure('PLANNER_BUSY');}
    let stage, destination, published = false;
    try {
      // A second process may have completed while this one downloaded metadata.
      try { await readSelection(this.stateRoot,6085); return; } catch(e) { if(e.code!=='PLANNER_SNAPSHOT_UNAVAILABLE') throw e; }
      // A pre-existing capture registry belongs to the capture/activation workflow.
      // Never overwrite its history, including a registry without an active UI.
      try { await fs.lstat(path.join(this.stateRoot,'capture-state.json')); throw failure('PLANNER_SNAPSHOT_UNTRUSTED'); }
      catch(e) { if(e.code !== 'ENOENT') throw e; }
      stage=await fs.mkdtemp(path.join(parent,'.download-'));
      const bytes=await read(`${API}/releases/assets/${chosen.binary.id}`,chosen.entry.bytes);
      if(bytes.length!==chosen.entry.bytes || digest(bytes)!==chosen.entry.sha256) throw failure('PLANNER_RELEASE_UNTRUSTED');
      const archive=path.join(stage,'ui.zip.age'); await fs.writeFile(archive,bytes,{mode:0o600});
      const unpacked=path.join(stage,'unpacked');
      if (!path.isAbsolute(this.installationRoot || '')) throw failure('PLANNER_UNAVAILABLE');
      await this.decrypt(path.join(this.installationRoot,'app','d4planner-fe.exe'),archive,identity,unpacked,signal);
      const config={snapshotRoot:unpacked,snapshotId:chosen.entry.snapshotId,manifestSha256:chosen.entry.manifestSha256,uiTrust:chosen.entry.uiTrust};
      try {
        // These receipts are authenticated as part of the already SHA-256-verified
        // archive. Older releases need no extra outer metadata to supply pins.
        const pins={schemaVersion:'maxroll-ui-trust/v1'};
        for(const [name,field] of [['ui-coverage.json','coverageSha256'],['ui-validation.json','validationSha256']]) {
          const file=path.join(unpacked,config.snapshotId,name),stat=await fs.lstat(file);
          if(!stat.isFile() || stat.isSymbolicLink() || stat.size>32*1024*1024) throw Error('receipt');
          pins[field]=digest(await fs.readFile(file));
        }
        if(config.uiTrust && (config.uiTrust.coverageSha256!==pins.coverageSha256 ||
          config.uiTrust.validationSha256!==pins.validationSha256)) throw Error('receipt pins');
        config.uiTrust=pins;
        // Verify receipt schemas, validation status and manifest/resource links;
        // deriving hashes alone never declares a package validated.
        const snapshot=await this.load(config);
        if(snapshot.uiVerification.status!=='AUTOMATED_VALIDATED') throw Error();
      } catch { throw failure('PLANNER_SNAPSHOT_UNTRUSTED'); }
      signal?.throwIfAborted();
      const store=path.join(parent,'releases');await safePath(store);await fs.mkdir(store,{recursive:true});
      destination=path.join(store,randomUUID());await fs.rename(unpacked,destination);
      config.snapshotRoot=destination;
      await safePath(this.stateRoot);await fs.mkdir(this.stateRoot,{recursive:true});
      const file=path.join(this.stateRoot,'capture-state.json');
      // Do not overwrite existing active/history state or a concurrent selection.
      try {await fs.access(file); throw failure('PLANNER_SNAPSHOT_UNTRUSTED');} catch(e) {if(e.code!=='ENOENT')throw e;}
      const entry=chosen.entry;
      const payload={schemaVersion:'maxroll-capture-state/v1',revision:1,activeUi:entry.snapshotId,
        previousActiveUi:null,runs:{},history:[{operation:'RELEASE_PROVISION',tag:chosen.release.tag_name}],transition:null,
        packages:{[entry.snapshotId]:{kind:'ui',snapshotId:entry.snapshotId,validationStatus:'VALIDATED',
          manifestSha256:entry.manifestSha256,coverageSha256:config.uiTrust.coverageSha256,validationSha256:config.uiTrust.validationSha256,config}}};
      const pending=path.join(stage,'capture-state.json');
      await fs.writeFile(pending,JSON.stringify({payload,sha256:digest(canonical(payload))}),{mode:0o600});
      signal?.throwIfAborted();await fs.link(pending,file); published = true; // atomic no-clobber publication
    } finally {
      try {
        if(destination && !published) await fs.rm(destination,{recursive:true,force:true});
        if(stage) await fs.rm(stage,{recursive:true,force:true});
      } finally { await lock.close();await fs.unlink(lockFile); }
    }
  }
}
module.exports={ReleaseProvisioner,download,select,PROTOCOL};
