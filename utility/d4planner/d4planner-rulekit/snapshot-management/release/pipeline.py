"""Private snapshot release orchestration. No code here grants compatibility."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import tarfile
import urllib.request
import zipfile

RECIPIENT = 'age1q9x3chgd0ycxe6y692cme82906a7qvcm08a02mwp9scdrtyupgzqhhwfrj'
MAX_BYTES = 2 * 1024**3
MAX_FILES = 10000
VERSION = re.compile(r'^[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?$')
HASH = re.compile(r'^[a-f0-9]{64}$')

class ReleaseBlocked(RuntimeError): pass

def require(ok, code):
    if not ok: raise ReleaseBlocked(code)

def sha(data): return hashlib.sha256(data).hexdigest()
def file_sha(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()
def read(path): return json.loads(Path(path).read_text())
def write(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2)+'\n')
    Path(path).chmod(0o600)

def command(args, *, cwd=None, env=None, timeout=1200):
    # Never forward provider stdout/stderr or raw exception text to public CI logs.
    try:
        result = subprocess.run(list(map(str,args)), cwd=cwd, env=env, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReleaseBlocked('BLOCKED_TOOL_'+Path(str(args[0])).name.upper()) from None
    if result.returncode != 0:
        text=result.stderr.decode('utf-8',errors='replace')
        for code in ('BLOCKED_PAIR_MISMATCH','BLOCKED_CAPTURE','BLOCKED_UI_VALIDATION'):
            if code in text: raise ReleaseBlocked(code)
        raise ReleaseBlocked('BLOCKED_COMMAND_'+Path(str(args[0])).name.upper())
    return result.stdout

def safe_name(name):
    require(isinstance(name,str) and name and '\\' not in name and ':' not in name and '\x00' not in name
            and not PurePosixPath(name).is_absolute() and all(p not in ('','.','..') for p in name.split('/')),
            'BLOCKED_ARCHIVE_PATH')
    return name

def inventory(root):
    root=Path(root)
    require(root.is_dir() and not root.is_symlink(), 'BLOCKED_PACKAGE_ROOT')
    result={}
    for p in sorted(root.rglob('*')):
        require(not p.is_symlink(), 'BLOCKED_PACKAGE_SYMLINK')
        if p.is_dir(): continue
        require(p.is_file(), 'BLOCKED_PACKAGE_SPECIAL_FILE')
        name=safe_name(p.relative_to(root).as_posix())
        result[name]={'bytes':p.stat().st_size,'sha256':file_sha(p)}
    require(0 < len(result) <= MAX_FILES and sum(v['bytes'] for v in result.values()) <= MAX_BYTES, 'BLOCKED_PACKAGE_LIMIT')
    return result

def pack(root, target):
    files=inventory(root)
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            info=zipfile.ZipInfo(name, (1980,1,1,0,0,0))
            info.external_attr=(stat.S_IFREG|0o600)<<16
            info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,(Path(root)/name).read_bytes())
    return files

def unpack(archive, output, expected):
    output=Path(output); output.mkdir(mode=0o700, exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        rows=z.infolist()
        names=[safe_name(row.filename) for row in rows]
        require(len(names)==len(set(names)) and set(names)==set(expected), 'BLOCKED_ARCHIVE_INVENTORY')
        require(len(rows)<=MAX_FILES and sum(r.file_size for r in rows)<=MAX_BYTES, 'BLOCKED_ARCHIVE_LIMIT')
        for row in rows:
            mode=row.external_attr>>16
            require(not row.is_dir() and stat.S_IFMT(mode) in (0,stat.S_IFREG), 'BLOCKED_ARCHIVE_TYPE')
            wanted=expected[row.filename]
            require(row.file_size==wanted['bytes'], 'BLOCKED_ARCHIVE_SIZE')
            content=z.read(row)
            require(sha(content)==wanted['sha256'], 'BLOCKED_ARCHIVE_HASH')
            target=output/row.filename;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            target.write_bytes(content);target.chmod(0o600)
    return output

def fetch(descriptor, target):
    require(isinstance(descriptor,dict) and HASH.fullmatch(descriptor.get('sha256','')), 'BLOCKED_PINNED_INPUT')
    url=descriptor.get('url','')
    from urllib.parse import urlsplit
    parsed=urlsplit(url)
    require(parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password,
            'BLOCKED_INPUT_URL')
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            require(response.url.startswith('https://'), 'BLOCKED_INPUT_REDIRECT')
            content=response.read(16*1024*1024+1)
    except (OSError,ValueError): raise ReleaseBlocked('BLOCKED_INPUT_ACCESS') from None
    require(len(content)<=16*1024*1024 and sha(content)==descriptor['sha256'], 'BLOCKED_INPUT_HASH')
    target.write_bytes(content);target.chmod(0o600)

def load_config(ctx, here):
    override=ctx.env.get('SNAPSHOT_RELEASE_CONFIG')
    require(not override or ctx.env.get('GITHUB_ACTIONS')!='true', 'BLOCKED_CI_LOCAL_CONFIG')
    c=read(override or here/'config.json')
    require(isinstance(c.get('authorizationRef'),str) and c['authorizationRef'].strip(), 'BLOCKED_CAPTURE_AUTHORIZATION')
    require(re.fullmatch(r'https://maxroll\.gg/d4/planner/[A-Za-z0-9]+(?:#[^?]*)?',c.get('sourceUrl') or ''), 'BLOCKED_CAPTURE_SOURCE')
    return c

def allowed_snapshot(source, destination, *, ui=False):
    # Copy only declared content. Exclude capture logs, paths and F capture state.
    source=Path(source);require(not source.is_symlink(), 'BLOCKED_PACKAGE_SYMLINK')
    manifest=read(source/'manifest.json')
    names={'manifest.json','manifest.sha256'}
    from urllib.parse import urlsplit, parse_qsl
    for row in manifest['resources']:
        url=urlsplit(row['url'])
        require(not url.username and not url.password and not any(
            re.fullmatch(r'access_?token|auth(?:orization)?|api_?key|session|secret', key, re.I)
            for key,_ in parse_qsl(url.query)), 'BLOCKED_RESOURCE_CREDENTIAL')
        require(not {'authorization','cookie','proxy-authorization','set-cookie'} &
                {key.lower() for key in row.get('headers',{})}, 'BLOCKED_RESOURCE_CREDENTIAL')
        name=row['blob'];require(re.fullmatch(r'blobs/[a-f0-9]{64}\.bin',name), 'BLOCKED_BLOB_PATH');names.add(name)
    if ui:names.update({'ui-coverage.json','ui-validation.json'})
    for name in sorted(names):
        p=source/name
        require(p.is_file() and not p.is_symlink() and not p.parent.is_symlink(), 'BLOCKED_PACKAGE_FILE')
        data=p.read_bytes()
        require(b'AGE-SECRET-KEY-' not in data and b'-----BEGIN PRIVATE KEY-----' not in data, 'BLOCKED_PRIVATE_KEY_LEAK')
        target=Path(destination)/name;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        target.write_bytes(data);target.chmod(0o600)

def safe_env(ctx):
    return {k:v for k,v in ctx.env.items() if not any(w in k.upper() for w in ('SECRET','TOKEN','PASSWORD','CREDENTIAL','IDENTITY'))}

def build(ctx, here, c):
    require(ctx.version and VERSION.fullmatch(ctx.version), 'BLOCKED_VERSION')
    identity_secret=ctx.env.get('AGE_IDENTITY_SECRET')
    require(identity_secret, 'BLOCKED_AGE_IDENTITY')
    for tool in ('node','npm','python3'):
        require(shutil.which(tool, path=ctx.env.get('PATH')), 'BLOCKED_TOOL_'+tool.upper())
    rulekit=here.parent.parent;provider=rulekit/'providers/maxroll'
    env=safe_env(ctx)
    private=ctx.temp/'snapshot-private';private.mkdir(mode=0o700)
    try:
        if not shutil.which('age', path=env.get('PATH')) or not shutil.which('age-keygen', path=env.get('PATH')):
            archive=private/'age.tar.gz'
            fetch({'url':'https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-linux-amd64.tar.gz',
                   'sha256':'cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10'},archive)
            with tarfile.open(archive) as tar:tar.extractall(private,filter='data')
            env['PATH']=str(private/'age')+os.pathsep+env.get('PATH','')
        identity=private/'age-identity';identity.write_text(identity_secret+'\n');identity.chmod(0o600)
        require(command(['age-keygen','-y',identity],env=env).decode().strip()==RECIPIENT, 'BLOCKED_AGE_RECIPIENT')
        # Install the existing pinned browser infrastructure, not a second capture framework.
        for module in ('browser-infra','providers/maxroll'):
            command(['npm','ci','--ignore-scripts','--no-audit','--no-fund'],cwd=rulekit/module,env=env)
        chromium=env.get('BROWSER_INFRA_CHROMIUM_PATH') or env.get('CHROMIUM_EXECUTABLE')
        if not chromium:
            cli=provider/'node_modules/playwright-core/cli.js'
            command(['node',cli,'install','chromium'],env=env)
            script="process.stdout.write(require(process.argv[1]).chromium.executablePath())"
            chromium=command(['node','-e',script,provider/'node_modules/playwright-core'],env=env).decode()
        require(Path(chromium).is_file(), 'BLOCKED_BROWSER')
        env.update(BROWSER_INFRA_CHROMIUM_PATH=chromium, CHROMIUM_EXECUTABLE=chromium)
        # Existing UI visual comparison requires Pillow; isolate it from system Python.
        command(['python3','-m','venv',private/'python'],env=env)
        command([private/'python/bin/python','-m','pip','install','Pillow==12.3.0'],env=env)
        env['PATH']=str(private/'python/bin')+os.pathsep+env.get('PATH','')
        roots={name:str(private/name) for name in ('stateRoot','calculationRoot','uiRoot')}
        capture_config={**roots,'schemaVersion':'maxroll-capture-config/v1','sourceUrl':c['sourceUrl'],
                        'authorizationRef':c['authorizationRef'],'chromium':chromium}
        config_file=private/'capture-config.json';write(config_file,capture_config)
        report_file=private/'capture-report.json'
        try:
            command(['node',here/'capture.js',config_file,report_file],env=env,timeout=3600)
        finally:
            if report_file.is_file():
                observed=read(report_file)
                receipt=private/'capture-receipt.json'
                write(receipt,{'sourceSha':ctx.source['head'],'ciRunId':ctx.env.get('GITHUB_RUN_ID'),
                  'captureRunId':observed.get('runId'),'status':observed.get('status'),
                  'consistency':observed.get('consistency'),'error':observed.get('error'),
                  'packages':[{key:row.get(key) for key in ('kind','snapshotId','manifestSha256','validationStatus','compatibility')}
                              for row in observed.get('packages',[])]})
                ctx.artifact(receipt,'capture-receipt.json')
        report=read(report_file)
        ctx.log('snapshot capture and UI validation: completed; pair integrity verification pending')
        # Match this run, independently of the older Rule Kit reference pins.
        command(['node','-e',"require(process.argv[1]).matchCapture(require(process.argv[2]))",here/'pair.js',report_file],env=env)
        verify_config={'authorizationRef':c['authorizationRef'],'report':str(report_file),
          'uiAcceptance':str(Path(roots['stateRoot'])/'runs'/report['runId']/'acceptance/acceptance.json'),
          'source':ctx.source['head']}
        config_file=private/'verify-config.json';write(config_file,verify_config)
        verified_file=private/'verified.json'
        command(['node',here/'verify.js',config_file,verified_file],env=env)
        verified=read(verified_file)
        ctx.log('snapshot integrity and pair match: PASS; Rule Kit readiness not assessed')
        calculation=next(p for p in report['packages'] if p['kind']=='calculation')
        ui=next(p for p in report['packages'] if p['kind']=='ui')
        staged=private/'packages';staged.mkdir()
        calc=staged/'calculation';calc.mkdir()
        allowed_snapshot(Path(calculation['snapshotRoot'])/calculation['snapshotId'],calc/calculation['snapshotId'])
        ui_package=staged/'ui';ui_package.mkdir()
        allowed_snapshot(Path(ui['snapshotRoot'])/ui['snapshotId'],ui_package/ui['snapshotId'],ui=True)
        candidate=private/'candidate';candidate.mkdir()
        assets={};roundtrips={}
        for kind in ('calculation','ui'):
            plain=private/(kind+'.zip');files=pack(staged/kind,plain)
            name=f'{kind}-snapshot-{ctx.version}.zip.age';encrypted=candidate/name
            command(['age','--encrypt','--recipient',RECIPIENT,'--output',encrypted,plain],env=env)
            decrypted=private/(kind+'-verify.zip')
            command(['age','--decrypt','--identity',identity,'--output',decrypted,encrypted],env=env)
            require(file_sha(plain)==file_sha(decrypted),'BLOCKED_ROUNDTRIP_HASH')
            roundtrips[kind]=unpack(decrypted,private/(kind+'-verified'),files)
            assets[name]={'sha256':file_sha(encrypted),'bytes':encrypted.stat().st_size,'plaintextSha256':file_sha(plain)}
        # Re-read the native captures after decrypt/extract; do not import or activate Rule Kit.
        for p in report['packages']:
            p['snapshotRoot']=str(roundtrips[p['kind']])
        write(report_file,report);write(config_file,verify_config)
        command(['node',here/'verify.js',config_file,private/'roundtrip-verification.json'],env=env)
        ui_replay={
          'scope':'ui','snapshotRoot':str(roundtrips['ui']),'snapshotId':ui['snapshotId'],
          'manifestSha256':ui['manifestSha256'],'chromium':chromium,
          'uiTrust':{'schemaVersion':'maxroll-ui-trust/v1','coverageSha256':verified['coverageSha256'],
            'validationSha256':verified['validationSha256'],'authorizationRef':c['authorizationRef']},
          'referenceDir':str(Path(roots['stateRoot'])/'runs'/report['runId']/'reference'),
          'referenceReportSha256':read(Path(ui['snapshotRoot'])/ui['snapshotId']/'ui-validation.json')['referenceReportSha256'],
          'output':str(private/'roundtrip-ui-acceptance')}
        ui_replay_config=private/'ui-replay.json';write(ui_replay_config,ui_replay)
        command(['node',provider/'tooling/web/full-acceptance.js',ui_replay_config],env=env)
        require(read(private/'roundtrip-ui-acceptance/acceptance.json').get('status')=='AUTOMATED_PASS','BLOCKED_UI_REPLAY')
        ctx.log('snapshot ZIP/age/decrypt/integrity/offline UI replay: PASS')
        metadata={**verified,'schemaVersion':'d4planner-snapshot-pair/v1','version':ctx.version,
          'sourceSha':ctx.source['head'],'ciRunId':ctx.env.get('GITHUB_RUN_ID'),'assets':assets,
          'uiReplaySha256':file_sha(private/'roundtrip-ui-acceptance/acceptance.json')}
        write(candidate/'snapshot-pair.json',metadata)
        (candidate/'SHA256SUMS').write_text(''.join(f'{file_sha(p)}  {p.name}\n' for p in sorted(candidate.iterdir()) if p.name!='SHA256SUMS'))
        verify_candidate(candidate,ctx.version,ctx.source['head'])
        ctx.artifact(candidate,'snapshots')
    finally:
        shutil.rmtree(private)

def verify_candidate(directory, version, source):
    directory=Path(directory)
    require(not directory.is_symlink(), 'BLOCKED_CANDIDATE_SYMLINK')
    names={'snapshot-pair.json','SHA256SUMS',f'calculation-snapshot-{version}.zip.age',f'ui-snapshot-{version}.zip.age'}
    require({p.name for p in directory.iterdir()}==names and all(p.is_file() and not p.is_symlink() for p in directory.iterdir()),'BLOCKED_CANDIDATE_INVENTORY')
    metadata=read(directory/'snapshot-pair.json')
    require(metadata.get('version')==version and metadata.get('sourceSha')==source,'BLOCKED_CANDIDATE_PROVENANCE')
    require(metadata.get('schemaVersion')=='d4planner-snapshot-pair/v1' and
            metadata.get('ruleKitReadiness')=='NOT_ASSESSED' and
            isinstance(metadata.get('calculationReferenceStatus'),str) and metadata['calculationReferenceStatus'] and
            all(isinstance(metadata.get(key),str) and metadata[key] for key in
                ('captureRunId','calculationSnapshotId','uiSnapshotId')) and
            metadata['calculationSnapshotId']!=metadata['uiSnapshotId'] and
            all(HASH.fullmatch(metadata.get(key,'')) for key in
                ('calculationManifestSha256','uiManifestSha256','runtimeIdentitySha256')),
            'BLOCKED_PAIR_METADATA')
    assets=metadata.get('assets',{})
    require(set(assets)==names-{'snapshot-pair.json','SHA256SUMS'},'BLOCKED_ASSET_INVENTORY')
    for name,record in assets.items():
        with (directory/name).open('rb') as stream:
            require(stream.read(len(b'age-encryption.org/v1\n'))==b'age-encryption.org/v1\n', 'BLOCKED_PLAINTEXT_ASSET')
        require(record.get('sha256')==file_sha(directory/name) and record.get('bytes')==(directory/name).stat().st_size,'BLOCKED_ASSET_HASH')
    expected=''.join(f'{file_sha(directory/name)}  {name}\n' for name in sorted(names-{'SHA256SUMS'}))
    require((directory/'SHA256SUMS').read_text()==expected,'BLOCKED_CHECKSUM')
    return metadata

def publish(ctx, here, c):
    require(ctx.version and VERSION.fullmatch(ctx.version), 'BLOCKED_VERSION')
    candidate=ctx.build_artifact('snapshots')
    metadata=verify_candidate(candidate,ctx.version,ctx.source['head'])
    approval=c.get('distribution') or {}
    require(approval.get('permission')=='PUBLIC_APPROVED' and approval.get('version')==ctx.version and
            isinstance(approval.get('reference'),str) and approval['reference'].strip(), 'BLOCKED_DISTRIBUTION_APPROVAL')
    require(ctx.env.get('GITHUB_ACTIONS')=='true' and ctx.env.get('GITHUB_EVENT_NAME')=='workflow_dispatch'
            and ctx.env.get('GITHUB_REF')=='refs/heads/master' and ctx.intent=='publish','BLOCKED_OWNER_PUBLISH_APPROVAL')
    repo=ctx.env.get('GITHUB_REPOSITORY');require(repo,'BLOCKED_RELEASE_REPOSITORY')
    tag='d4planner-snapshots/v'+ctx.version
    env=ctx.env
    # Query lists successfully before deciding absence: authentication/network errors never mean "not found".
    releases=json.loads(command(['gh','api',f'repos/{repo}/releases','--paginate','--slurp'],env=env))
    require(not any(r['tag_name']==tag for page in releases for r in page),'BLOCKED_RELEASE_EXISTS')
    refs=json.loads(command(['gh','api',f'repos/{repo}/git/matching-refs/tags/{tag}'],env=env))
    require(not any(r['ref']=='refs/tags/'+tag for r in refs),'BLOCKED_TAG_EXISTS')
    # Leave an incomplete draft for inspection on failure; never clobber or delete it automatically.
    command(['gh','release','create',tag,'--repo',repo,'--target',ctx.source['head'],'--draft',
             '--title',f'D4Planner Snapshots {ctx.version}','--notes','Encrypted Calculation + UI snapshot pair.'],env=env)
    command(['gh','release','upload',tag,*sorted(Path(candidate).iterdir()),'--repo',repo],env=env)
    download=ctx.temp/'download';download.mkdir()
    command(['gh','release','download',tag,'--repo',repo,'--dir',download],env=env)
    verify_candidate(download,ctx.version,ctx.source['head'])
    require(inventory(download)==inventory(candidate),'BLOCKED_RELEASE_DOWNLOAD')
    target=json.loads(command(['gh','api',f'repos/{repo}/git/ref/tags/{tag}'],env=env))['object']
    for _ in range(8):
        if target['type']=='commit': break
        require(target['type']=='tag','BLOCKED_RELEASE_TAG_TARGET')
        target=json.loads(command(['gh','api',f'repos/{repo}/git/tags/{target["sha"]}'],env=env))['object']
    require(target['type']=='commit' and target['sha']==ctx.source['head'],'BLOCKED_RELEASE_TAG_TARGET')
    command(['gh','release','edit',tag,'--repo',repo,'--draft=false'],env=env)
    receipt=ctx.temp/'publish.json';write(receipt,{'status':'PASS','tag':tag,'sourceSha':ctx.source['head'],'assets':inventory(download)})
    ctx.artifact(receipt,'publish.json')

def run(ctx):
    here=Path(__file__).resolve().parent
    try:
        c=load_config(ctx,here)
        if ctx.job['operation']=='build':build(ctx,here,c)
        else:publish(ctx,here,c)
    except ReleaseBlocked as error:
        receipt=ctx.temp/'snapshot-blocked.json'
        write(receipt,{'status':'BLOCKED','reason':str(error),'sourceSha':ctx.source['head'],
                      'operation':ctx.job['operation'],'ciRunId':ctx.env.get('GITHUB_RUN_ID')})
        ctx.artifact(receipt,'snapshot-blocked.json')
        raise
