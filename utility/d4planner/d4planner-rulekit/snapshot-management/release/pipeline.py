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
import tarfile
import urllib.request
import zipfile

RECIPIENT = 'age1q9x3chgd0ycxe6y692cme82906a7qvcm08a02mwp9scdrtyupgzqhhwfrj'
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
        # Raw diagnostics stay in the owned private workspace, never CI artifacts/logs.
        private=Path((env or {}).get('RUNNER_TEMP',''))/'snapshot-private'
        if env and env.get('RUNNER_TEMP') and private.is_dir():
            write(private/'command-failure.json',{'command':list(map(str,args)),
                'exitCode':result.returncode,'stdout':result.stdout.decode('utf-8',errors='replace'),
                'stderr':result.stderr.decode('utf-8',errors='replace')})
        text=result.stderr.decode('utf-8',errors='replace')
        for code in ('BLOCKED_PAIR_MISMATCH','BLOCKED_CAPTURE','BLOCKED_UI_VALIDATION',
                     'BLOCKED_VALIDATION','BLOCKED_INTEGRITY','BLOCKED_UI_PROVENANCE','BLOCKED_RUNTIME_IDENTITY'):
            if code in text: raise ReleaseBlocked(code)
        raise ReleaseBlocked('BLOCKED_COMMAND_'+Path(str(args[0])).name.upper())
    return result.stdout

def safe_name(name):
    require(isinstance(name,str) and name and '\\' not in name and ':' not in name and '\x00' not in name
            and not PurePosixPath(name).is_absolute() and all(p not in ('','.','..') for p in name.split('/')),
            'BLOCKED_ARCHIVE_PATH')
    return name

def pack(package, target):
    # Retain the native snapshot root; omit capture logs and machine-local state.
    snapshot_id=safe_name(package['snapshotId'])
    source=Path(package['snapshotRoot'])/snapshot_id
    names={'manifest.json','manifest.sha256'}
    names.update(safe_name(row['blob']) for row in read(source/'manifest.json')['resources'])
    if package['kind']=='ui':names.update({'ui-coverage.json','ui-validation.json'})
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(names):
            path=source/name
            require(path.is_file() and not any(parent.is_symlink() for parent in (path,*path.parents)),
                    'BLOCKED_PACKAGE_FILE')
            info=zipfile.ZipInfo(snapshot_id+'/'+name, (1980,1,1,0,0,0))
            info.external_attr=(stat.S_IFREG|0o600)<<16
            info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,path.read_bytes())

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
    return c

def safe_env(ctx):
    return {k:v for k,v in ctx.env.items() if not any(w in k.upper() for w in ('SECRET','TOKEN','PASSWORD','CREDENTIAL','IDENTITY'))}

def build(ctx, here, c):
    require(ctx.version and VERSION.fullmatch(ctx.version), 'BLOCKED_VERSION')
    for tool in ('node','npm','python3'):
        require(shutil.which(tool, path=ctx.env.get('PATH')), 'BLOCKED_TOOL_'+tool.upper())
    rulekit=here.parent.parent;provider=rulekit/'providers/maxroll'
    env=safe_env(ctx)
    private=ctx.temp/'snapshot-private';private.mkdir(mode=0o700)
    try:
        if not shutil.which('age', path=env.get('PATH')):
            archive=private/'age.tar.gz'
            fetch({'url':'https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-linux-amd64.tar.gz',
                   'sha256':'cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10'},archive)
            with tarfile.open(archive) as tar:tar.extractall(private,filter='data')
            env['PATH']=str(private/'age')+os.pathsep+env.get('PATH','')
        # Install the existing pinned browser infrastructure, not a second capture framework.
        # Capturer also reuses snapshot-management's content-version parser (AJV).
        for module in ('browser-infra','providers/maxroll','snapshot-management'):
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
        command(['node',here/'capture.js',config_file,report_file],env=env,timeout=3600)
        report=read(report_file)
        candidate=private/'candidate';candidate.mkdir()
        assets={}
        for kind in ('calculation','ui'):
            package=next(row for row in report['packages'] if row['kind']==kind)
            plain=private/(kind+'.zip');pack(package,plain)
            name=f'{kind}-snapshot-{ctx.version}.zip.age';encrypted=candidate/name
            command(['age','--encrypt','--recipient',c.get('ageRecipient',RECIPIENT),
                     '--output',encrypted,plain],env=env)
            assets[name]={'sha256':file_sha(encrypted),'bytes':encrypted.stat().st_size,
                          'snapshotId':package['snapshotId'],'manifestSha256':package['manifestSha256']}
            if kind == 'ui':
                source = Path(package['snapshotRoot']) / package['snapshotId']
                validation = read(source / 'ui-validation.json')
                require(validation.get('status') == 'AUTOMATED_VALIDATED', 'BLOCKED_UI_VALIDATION')
                assets[name].update(plannerProtocolVersion='d4planner-local-planner/v1', uiTrust={
                    'schemaVersion': 'maxroll-ui-trust/v1',
                    'coverageSha256': file_sha(source / 'ui-coverage.json'),
                    'validationSha256': file_sha(source / 'ui-validation.json'),
                    'authorizationRef': c['authorizationRef'],
                })
        write(candidate/'snapshot-pair.json',{
            'schemaVersion':'d4planner-snapshot-pair/v1','version':ctx.version,
            'sourceSha':ctx.source['head'],'captureRunId':report['runId'],'assets':assets})
        (candidate/'SHA256SUMS').write_text(''.join(
            f'{file_sha(p)}  {p.name}\n' for p in sorted(candidate.iterdir())))
        ctx.artifact(candidate,'snapshots')
    finally:
        shutil.rmtree(private)


def publish(ctx):
    # Context verifies the selected build's source, plan and artifact checksums.
    candidate=Path(ctx.build_artifact('snapshots'))
    names=['snapshot-pair.json','SHA256SUMS',
           f'calculation-snapshot-{ctx.version}.zip.age',f'ui-snapshot-{ctx.version}.zip.age']
    repo=ctx.env['GITHUB_REPOSITORY'];tag='d4planner-snapshots/v'+ctx.version
    # Reuse Application Release's existing no-overwrite and exact-source tag logic.
    ctx.python('-c',
        'import sys; sys.path.insert(0,sys.argv[1]); '
        'from release_ci import require_release_absent, ensure_source_tag; '
        'require_release_absent(sys.argv[2],sys.argv[3]); '
        'ensure_source_tag(sys.argv[2],sys.argv[3],sys.argv[4])',
        ctx.root/'utility/d4planner/d4planner-be/tools',repo,tag,ctx.source['head'])
    ctx.run(['gh','release','create',tag,*[str(candidate/name) for name in names],
             '--repo',repo,'--verify-tag','--title',f'D4Planner Snapshots {ctx.version}',
             '--notes','Encrypted Calculation + UI snapshots captured in one release run.'])


def run(ctx):
    here=Path(__file__).resolve().parent
    if ctx.job['operation']=='build':build(ctx,here,load_config(ctx,here))
    else:publish(ctx)
