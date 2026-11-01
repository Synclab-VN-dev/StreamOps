#!/usr/bin/env python3
"""Versioned component CI contracts. Planning never imports component code."""
from __future__ import annotations
import argparse
import ast
from datetime import datetime, timezone
import fnmatch
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
VERSION = 'streamops-ci/v1'
PROFILES = {'linux': ('linux', 'ubuntu-24.04'), 'windows': ('win32', 'windows-2022')}
CAPABILITIES = {'read': [], 'fixture': ['fixture'], 'public-inputs': ['public-inputs'], 'publish': ['publish'], 'external-publish': ['publish']}
SECRET_BINDINGS = {'read':{}, 'publish':{}, 'fixture':{'AGE_IDENTITY_SECRET':'MAXROLL_FIXTURE_AGE_IDENTITY'},
    'external-publish':{'GH_TOKEN':'SYNCLAB_OBS_RELEASE_TOKEN'},
    'public-inputs':{'D4_PUBLIC_RUNTIME_INPUT_URL':'D4PLANNER_PUBLIC_RUNTIME_INPUTS_URL','D4_PUBLIC_RUNTIME_INPUT_SHA256':'D4PLANNER_PUBLIC_RUNTIME_INPUTS_SHA256'}}
NAME = re.compile(r'^[a-z][a-z0-9-]{0,63}$')
ENV_NAME = re.compile(r'^[A-Z][A-Z0-9_]*$')

class ContractError(ValueError): pass
class Blocked(RuntimeError): pass

def require(ok, message):
    if not ok: raise ContractError(message)

def stamp(): return datetime.now(timezone.utc).isoformat(timespec='milliseconds')
def canonical(value): return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
def digest(value): return hashlib.sha256(value).hexdigest()
def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    temporary.replace(path)

def git(root, *args, binary=False, allowed=(0,)):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, timeout=60)
    require(result.returncode in allowed, 'GIT_HISTORY_OR_DIFF_UNAVAILABLE: '+ ' '.join(args[:2]))
    return result.stdout if binary else result.stdout.decode('utf-8', errors='strict').strip()

def safe_path(value, *, pattern=False):
    require(isinstance(value, str) and value and '\\' not in value, 'INVALID_PATH')
    p = PurePosixPath(value)
    require(not p.is_absolute() and '..' not in p.parts and ':' not in value and '\x00' not in value, 'UNSAFE_PATH: '+value)
    if not pattern: require(not any(c in value for c in '*?['), 'PATTERN_NOT_PATH')
    return value

def metadata(text, path):
    try: tree = ast.parse(text, filename=path)
    except SyntaxError as error: raise ContractError('INVALID_CONTRACT_SYNTAX: '+path) from error
    declarations = [node for node in tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'CI_SPEC' for t in node.targets)]
    require(len(declarations) == 1, 'ONE_LITERAL_CI_SPEC_REQUIRED: '+path)
    try: spec = ast.literal_eval(declarations[0].value)
    except (ValueError, TypeError) as error: raise ContractError('NON_LITERAL_METADATA: '+path) from error
    require(type(spec) is dict and spec.get('version') == 1, 'UNSUPPORTED_SPEC_VERSION: '+path)
    require(set(spec) <= {'version','id','watch','depends_on','jobs','ignore','release_tags'}, 'UNKNOWN_SPEC_FIELD: '+path)
    require(isinstance(spec.get('id'), str) and NAME.fullmatch(spec['id']), 'INVALID_ID: '+path)
    for field in ('watch','ignore'):
        require(isinstance(spec.get(field, []), list), 'INVALID_'+field.upper())
        for item in spec.get(field, []): safe_path(item, pattern=True)
    require(isinstance(spec.get('depends_on', []), list), 'INVALID_DEPENDENCIES')
    require(all(isinstance(x,str) and NAME.fullmatch(x) for x in spec.get('depends_on', [])), 'INVALID_DEPENDENCY_ID')
    kind = 'release' if path.endswith('ci.release.py') else 'test'
    require(isinstance(spec.get('jobs'), list) and spec['jobs'], 'JOBS_REQUIRED: '+path)
    ids = set()
    for job in spec['jobs']:
        require(type(job) is dict, 'INVALID_JOB')
        require(set(job) <= {'id','profile','timeout','operation','capability','secrets','tools','artifacts','required','manual'}, 'UNKNOWN_JOB_FIELD')
        require(isinstance(job.get('id'),str) and NAME.fullmatch(job['id']) and job['id'] not in ids, 'INVALID_OR_DUPLICATE_JOB')
        ids.add(job['id'])
        require(job.get('profile') in PROFILES, 'UNAPPROVED_RUNNER_PROFILE')
        require(type(job.get('timeout')) is int and 1 <= job['timeout'] <= 7200, 'INVALID_TIMEOUT')
        operation = job.get('operation','test')
        require(operation in ({'test'} if kind == 'test' else {'build','publish'}), 'INVALID_OPERATION')
        capability = job.get('capability','read')
        require(capability in CAPABILITIES, 'UNAPPROVED_CAPABILITY')
        require(capability not in {'publish','external-publish'} or operation == 'publish', 'WRITE_CAPABILITY_OUTSIDE_PUBLISH')
        require(operation != 'publish' or capability in {'publish','external-publish'}, 'PUBLISH_CAPABILITY_REQUIRED')
        secrets = job.get('secrets', {})
        require(type(secrets) is dict and len(secrets) <= 2, 'INVALID_SECRET_BINDINGS')
        require(all(isinstance(k,str) and ENV_NAME.fullmatch(k) and isinstance(v,str) and ENV_NAME.fullmatch(v) for k,v in secrets.items()), 'INVALID_SECRET_ALIAS')
        require(all(SECRET_BINDINGS[capability].get(k)==v for k,v in secrets.items()), 'UNAPPROVED_SECRET_BINDING')
        require(capability!='public-inputs' or operation=='build','BUILD_CAPABILITY_REQUIRED')
        require(capability!='fixture' or (operation=='test' and job.get('manual') is True),'FIXTURE_MANUAL_ONLY')
        require(type(job.get('required', True)) is bool and type(job.get('manual',False)) is bool, 'INVALID_JOB_FLAGS')
        require(isinstance(job.get('artifacts', []), list), 'INVALID_ARTIFACTS')
        for artifact in job.get('artifacts', []): safe_path(artifact, pattern=True)
        require(type(job.get('tools', {})) is dict and set(job.get('tools', {})) <= {'node','rust'}, 'INVALID_TOOLS')
        require(all(isinstance(v,str) and re.fullmatch(r'[A-Za-z0-9.+-]{1,50}',v) for v in job.get('tools', {}).values()), 'INVALID_TOOL_VERSION')
    require(any(isinstance(n, ast.FunctionDef) and n.name == 'run' for n in tree.body), 'RUN_FUNCTION_REQUIRED')
    require(kind == 'release' or not spec.get('release_tags'), 'RELEASE_TAGS_ON_TEST')
    require(isinstance(spec.get('release_tags', []), list), 'INVALID_RELEASE_TAGS')
    for tag in spec.get('release_tags', []): safe_path(tag, pattern=True)
    return {**spec, 'kind':kind, 'path':path, 'root':str(PurePosixPath(path).parent), 'sha256':digest(text.encode())}

def tracked_paths(root, ref=None):
    args = ['ls-tree','-rz','--name-only',ref] if ref else ['ls-files','-z','--cached','--others','--exclude-standard']
    return sorted(set(x.decode('utf-8') for x in git(root,*args,binary=True).split(b'\0') if x))

def discover(root, ref=None):
    specs = {}
    for path in tracked_paths(root, ref):
        if PurePosixPath(path).name not in {'ci.test.py','ci.release.py'}: continue
        if ref: text = git(root, 'show', f'{ref}:{path}', binary=True).decode('utf-8')
        else:
            target = root/path
            if not target.exists(): continue
            require(not target.is_symlink(), 'SYMLINK_CONTRACT: '+path)
            text = target.read_text(encoding='utf-8')
        spec = metadata(text, path)
        require(spec['id'] not in specs, 'DUPLICATE_COMPONENT_ID: '+spec['id'])
        specs[spec['id']] = spec
    validate_graph(specs)
    return specs

def validate_graph(specs):
    visited, visiting = set(), set()
    def visit(name):
        require(name in specs, 'MISSING_DEPENDENCY: '+str(name))
        require(name not in visiting, 'CYCLIC_DEPENDENCY: '+name)
        if name in visited: return
        visiting.add(name)
        for dep in specs[name].get('depends_on',[]): visit(dep)
        visiting.remove(name); visited.add(name)
    for name in specs: visit(name)

def snapshot(root, ref=None):
    head = git(root,'rev-parse','--verify',ref or 'HEAD')
    if ref: return {'head':head, 'tree':git(root,'rev-parse',head+'^{tree}'), 'dirty':False}
    # File bytes (including dirty/untracked), modes and paths bind the tested source.
    records = []
    for name in tracked_paths(root):
        path = root/name
        if not path.exists() and not path.is_symlink(): continue
        require(not path.is_dir(), 'SUBMODULE_REQUIRES_CONTRACT: '+name)
        data = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
        records.append((name, 'symlink' if path.is_symlink() else bool(path.stat().st_mode & 0o111), digest(data)))
    return {'head':head, 'tree':digest(canonical(records)), 'dirty':bool(git(root,'status','--porcelain','--untracked-files=all'))}

def changed_paths(root, base, head, dirty=False, push=False):
    require(base and head and not re.fullmatch('0+',base), 'BASE_AND_HEAD_HISTORY_REQUIRED')
    resolved = git(root,'rev-parse','--verify',base+'^{commit}')
    target = git(root,'rev-parse','--verify',head+'^{commit}')
    ancestor = resolved if push else git(root,'merge-base',resolved,target)
    # --no-renames yields both the removed old path and added new path.
    paths = set(x.decode() for x in git(root,'diff','--name-only','--no-renames','-z',ancestor,target,binary=True).split(b'\0') if x)
    if dirty:
        for args in [('diff','--name-only','--no-renames','-z','HEAD'), ('ls-files','--others','--exclude-standard','-z')]:
            paths.update(x.decode() for x in git(root,*args,binary=True).split(b'\0') if x)
    return sorted(paths), ancestor

def matches(path, patterns): return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)
def ownership(path, specs):
    candidates = [s for s in specs.values() if s['kind']=='test' and (s['root']=='.' or path.startswith(s['root']+'/'))]
    if not candidates: return []
    depth = max(len(PurePosixPath(s['root']).parts) for s in candidates)
    return [s['id'] for s in candidates if len(PurePosixPath(s['root']).parts)==depth]

def plan(root, *, base=None, head='HEAD', dirty=False, push=False, component=None, product=None, operation='test', all_jobs=False, tag=None, all_reason='explicit all tests'):
    specs = discover(root, None if dirty else head)
    identity = snapshot(root, None if dirty else head)
    reasons, changes = {}, []
    if component or product:
        name = component or product
        require(name in specs, 'UNKNOWN_COMPONENT_OR_PRODUCT: '+name)
        require(specs[name]['kind']==('release' if product else 'test'), 'CONTRACT_KIND_MISMATCH')
        reasons[name] = ['explicit selection']
    elif tag:
        require(operation=='publish', 'TAG_OPERATION_MISMATCH')
        selected = [s['id'] for s in specs.values() if s['kind']=='release' and matches(tag,s.get('release_tags',[]))]
        require(len(selected)==1, 'UNKNOWN_OR_AMBIGUOUS_RELEASE_TAG')
        reasons[selected[0]] = ['approved release tag pattern']
    elif all_jobs:
        require(operation=='test', 'EXPLICIT_PRODUCT_REQUIRED')
        reasons = {n:[all_reason] for n,s in specs.items() if s['kind']=='test'}
    else:
        require(operation=='test', 'EXPLICIT_PRODUCT_REQUIRED')
        changes, ancestor = changed_paths(root,base,head,dirty,push)
        old = discover(root, ancestor)
        for path in changes:
            covered = False
            for source in (old,specs):
                owners = ownership(path,source)
                selected = set(owners) | {n for n,s in source.items() if s['kind']=='test' and matches(path,s.get('watch',[]))}
                for name in selected:
                    require(name in specs, 'REMOVED_CONTRACT_WITHOUT_COVERAGE: '+name)
                    reasons.setdefault(name,[]).append('changed: '+path)
                    covered = True
                if any(matches(path,s.get('ignore',[])) for s in source.values()): covered=True
            require(covered, 'UNCOVERED_CHANGE: '+path)
    if operation=='test':
        expanded=True
        while expanded:
            expanded=False
            for name,spec in specs.items():
                if spec['kind']!='test' or name in reasons: continue
                affected=set(spec.get('depends_on',[])) & reasons.keys()
                if affected:
                    reasons[name]=['dependency: '+n for n in sorted(affected)];expanded=True
    jobs=[]
    for name in sorted(reasons):
        spec=specs[name]
        for job in spec['jobs']:
            # Publish always has a build phase; only its publish job receives credentials.
            if job.get('operation','test') not in ({'build','publish'} if operation=='publish' else {operation}): continue
            if job.get('manual',False) and not (component or product): continue
            capability=job.get('capability','read')
            jobs.append({**job, 'key':name+'--'+job['id'], 'component':name,'contract':spec['path'],
                         'contractSha256':spec['sha256'], 'operation':job.get('operation','test'),
                         'capability':capability, 'runner':PROFILES[job['profile']][1],
                         'reasons':sorted(set(reasons[name]))})
    if reasons: require(jobs, 'NO_JOBS_FOR_SELECTION')
    document={'schemaVersion':VERSION, 'source':identity, 'operation':operation, 'tag':tag,
              'changes':changes, 'jobs':jobs, 'status':'PLANNED' if jobs else 'NO_CHANGE'}
    document['planId']=digest(canonical(document))
    return document

class Context:
    def __init__(self, root, job, output, source, version=None, channel='stable', inputs=None):
        self.root=root; self.job=job; self.output=output; self.source=source
        self.version=version; self.channel=channel; self.inputs=inputs
        self.plan_id=None
        self.temp=None
        self.commands=[]; self.test_counts={}; self.artifacts=[]
        self.env={k:v for k,v in os.environ.items() if not any(x in k.upper() for x in ('TOKEN','SECRET','PASSWORD','CREDENTIAL','IDENTITY'))}
        self.env.update({'GITHUB_WORKSPACE':str(root),'PYTHONUTF8':'1', 'PYTHONUNBUFFERED':'1'})
        self.redactions=[]
        self.deadline=time.monotonic()+job['timeout']
        for index,(alias,secret) in enumerate(sorted(job.get('secrets',{}).items()),1):
            value=os.environ.get('CI_BOUND_SECRET_'+str(index)) or (os.environ.get(alias) if not os.environ.get('GITHUB_ACTIONS') else None)
            if not value and job['capability']=='public-inputs':continue
            if not value: raise Blocked('MISSING_REQUIRED_SECRET: '+alias)
            self.env[alias]=value;self.redactions.append(value)
        if job['capability'] in {'fixture','public-inputs'} and os.environ.get('CI_READ_TOKEN'):
            self.env['GH_TOKEN']=os.environ['CI_READ_TOKEN']
            self.redactions.append(os.environ['CI_READ_TOKEN'])
        if job['capability'] in {'publish','external-publish'}:
            token=self.env.get('GH_TOKEN') if job['capability']=='external-publish' else os.environ.get('CI_PUBLISH_TOKEN')
            if not token: raise Blocked('PUBLISH_CREDENTIAL_NOT_PROVIDED')
            self.env['GH_TOKEN']=token;self.env['GITHUB_TOKEN']=token;self.redactions.append(token)
        self.temp=Path(tempfile.mkdtemp(prefix='ci-'+job['key']+'-'))
        self.env['RUNNER_TEMP']=str(self.temp)
        self.env['PIP_CACHE_DIR']=str(self.temp/'pip-cache')
        self.env['CARGO_HOME']=str(self.temp/'cargo-home')
        self.env['NPM_CONFIG_CACHE']=str(self.temp/'npm-cache')
        self.env['PLAYWRIGHT_BROWSERS_PATH']=str(self.temp/'browsers')
        for name in ('GITHUB_ENV','GITHUB_OUTPUT','GITHUB_STEP_SUMMARY'):
            self.env[name]=str(self.temp/name.lower());Path(self.env[name]).touch()
    def prepare_checkout(self):
        # Legacy native harnesses detach HEAD and create local venvs. Give each
        # execution an owned checkout; never run those mutations in the caller's tree.
        checkout=self.temp/'source'
        subprocess.run(['git','-c','core.autocrlf=false','clone','--quiet','--shared','--no-hardlinks','--no-checkout',str(self.root),str(checkout)],check=True)
        subprocess.run(['git','-C',str(checkout),'-c','core.autocrlf=false','checkout','--quiet','--detach',self.source['head']],check=True)
        original=set(tracked_paths(self.root))
        for name in tracked_paths(checkout):
            if name not in original or not (self.root/name).exists():
                target=checkout/name
                if target.is_file() or target.is_symlink():target.unlink()
        for name in original:
            src=self.root/name;dst=checkout/name
            if not src.exists() and not src.is_symlink():continue
            dst.parent.mkdir(parents=True,exist_ok=True)
            if dst.is_symlink():dst.unlink()
            if src.is_symlink():
                if dst.exists():dst.unlink()
                dst.symlink_to(os.readlink(src))
            else:shutil.copy2(src,dst)
        self.root=checkout
        self.env['GITHUB_WORKSPACE']=str(checkout)
        self.env['GITHUB_SHA']=self.source['head']
    def redact(self, text):
        for secret in self.redactions: text=text.replace(secret,'***')
        return text
    def log(self, text):
        for secret in self.redactions: text=text.replace(secret,'***')
        with (self.output/'commands.log').open('a',encoding='utf-8') as out:out.write(text+'\n')
        # Preserve full UTF-8 evidence; legacy Windows consoles may be cp1252.
        encoding=getattr(sys.stdout,'encoding',None) or 'utf-8'
        console_text=text.encode(encoding,errors='backslashreplace').decode(encoding)
        print(console_text,flush=True)
    def run(self, args, *, cwd=None, env=None, expected=(0,)):
        cwd=Path(cwd or self.root)
        if not cwd.is_absolute():cwd=self.root/cwd
        command=[str(a) for a in args]
        if os.name=='nt' and command[0] in {'npm','npx'}:command[0]+='.cmd'
        if not shutil.which(command[0], path=self.env.get('PATH')):
            raise Blocked('MISSING_TOOL: '+command[0])
        self.log('$ '+json.dumps(command))
        started=time.monotonic()
        with tempfile.TemporaryFile() as stream:
            p=subprocess.Popen(command,cwd=cwd,env={**self.env,**(env or {})},stdout=stream,stderr=subprocess.STDOUT,
                               start_new_session=os.name!='nt')
            try:p.wait(timeout=max(.01,self.deadline-time.monotonic()))
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
                if os.name=='nt':subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True)
                else:os.killpg(p.pid,signal.SIGKILL)
                p.wait()
                if isinstance(error,KeyboardInterrupt):raise
                raise TimeoutError('OPERATION_TIMEOUT')
            finally:
                stream.seek(0);text=stream.read().decode('utf-8',errors='replace');self.log(text)
                self.commands.append({'argv':[self.redact(x) for x in command],'cwd':str(cwd),'seconds':round(time.monotonic()-started,3),'exitCode':p.returncode})
                plain=re.sub(r'\x1b\[[0-9;]*m','',text)
                unit=re.search(r'Ran (\d+) tests? in .*?\n\s*OK',plain,re.S)
                if unit:
                    pairs=[(unit.group(1),'passed')]
                else:
                    pairs=[]
                    for line in plain.splitlines():
                        node=re.fullmatch(r'(?:ℹ|#) (pass|fail|skipped|cancelled) (\d+)',line)
                        if node:
                            pairs.append((node.group(2),{'pass':'passed','fail':'failed'}.get(node.group(1),node.group(1))))
                        elif re.search(r'\bin \d+(?:\.\d+)?s\b',line):
                            pairs.extend(re.findall(r'(\d+) (passed|failed|skipped|errors?)',line))
                for count,label in pairs:
                    self.test_counts[label]=self.test_counts.get(label,0)+int(count)
        if p.returncode not in expected:raise RuntimeError('COMMAND_FAILED: '+command[0]+' exit '+str(p.returncode))
        self._environment_updates()
        return text
    def _environment_updates(self):
        path=Path(self.env['GITHUB_ENV'])
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line:
                k,v=line.split('=',1)
                require(ENV_NAME.fullmatch(k) and not any(s in k for s in ('TOKEN','SECRET','PASSWORD')), 'UNSAFE_ENV_EXPORT')
                self.env[k]=v
        path.write_text('')
    def shell(self, script, *, shell=None, cwd=None, env=None):
        shell=shell or ('pwsh' if os.name=='nt' else 'bash')
        executable=shutil.which(shell)
        if not executable:raise Blocked('MISSING_TOOL: '+shell)
        path=self.temp/(uuid.uuid4().hex+('.ps1' if shell=='pwsh' else '.sh'))
        if shell=='pwsh':
            script="$ErrorActionPreference='Stop'\n"+script+"\nif ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n"
            args=[executable,'-NoProfile','-File',path]
        else:script='set -euo pipefail\n'+script;args=[executable,path]
        path.write_text(script,encoding='utf-8')
        before=len(self.commands)
        try:return self.run(args,cwd=cwd,env=env)
        finally:
            if len(self.commands)>before:self.commands[-1]['script']=self.redact(script)
    def isolated_python(self):
        import venv
        target=self.temp/'python'
        venv.EnvBuilder(with_pip=True).create(target)
        folder=target/('Scripts' if os.name=='nt' else 'bin')
        self.python_executable=str(folder/('python.exe' if os.name=='nt' else 'python'))
        self.env['PATH']=str(folder)+os.pathsep+self.env.get('PATH','')
        self.env['VIRTUAL_ENV']=str(target)
        self.env.pop('PYTHONPATH',None)
    def python(self, *args, **kw):return self.run([getattr(self,'python_executable',sys.executable),*args],**kw)
    def tool(self, name, version=None):
        if not shutil.which(name): raise Blocked('MISSING_TOOL: '+name)
        try:value=self.run([name,'--version'])
        except RuntimeError as error:raise Blocked('TOOLCHAIN_UNAVAILABLE: '+name) from error
        if version and not re.search(r'(?<![0-9])'+re.escape(version)+r'(?:\.|\s|$)',value):raise Blocked('TOOL_VERSION_MISMATCH: '+name+' expected '+version)
    def artifact(self, path, name=None):
        path=Path(path);path=path if path.is_absolute() else self.root/path
        if not path.exists():raise RuntimeError('REQUIRED_ARTIFACT_MISSING: '+str(path))
        name=name or path.name;safe_path(name)
        target=self.output/'artifacts'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        candidates=[path] if path.is_file() else [path,*path.rglob('*')]
        require(not any(p.is_symlink() for p in candidates), 'SYMLINK_ARTIFACT')
        if path.is_dir():shutil.copytree(path,target,dirs_exist_ok=True)
        else:shutil.copy2(path,target)
        self.artifacts.append(name)
    def build_artifact(self, name):
        if not self.inputs: raise Blocked('VERIFIED_BUILD_INPUTS_REQUIRED')
        matches=[]
        for path in Path(self.inputs).rglob('result.json'):
            if 'artifacts' in path.relative_to(self.inputs).parts:continue
            report=json.loads(path.read_text())
            if report.get('component')==self.job['component'] and report.get('operation')=='build':
                require(report.get('status')=='PASS' and report.get('source')==self.source and report.get('planId')==self.plan_id, 'BUILD_REPORT_IDENTITY')
                target=path.parent/'artifacts'/name
                actual={str(p.relative_to(path.parent/'artifacts')).replace(os.sep,'/') for p in (path.parent/'artifacts').rglob('*') if p.is_file()}
                require(actual==set(report.get('artifactManifest',{})), 'BUILD_ARTIFACT_INVENTORY')
                for relative,sha in report.get('artifactManifest',{}).items():
                    candidate=path.parent/'artifacts'/safe_path(relative)
                    require(candidate.is_file() and not candidate.is_symlink() and digest(candidate.read_bytes())==sha,'BUILD_ARTIFACT_INTEGRITY')
                require(report.get('artifactManifest') and target.exists(), 'BUILD_ARTIFACT_MISSING')
                matches.append(target)
        require(len(matches)==1,'ONE_VERIFIED_BUILD_REQUIRED')
        return matches[0]
    def close(self):
        def remove_readonly(function, path, error):
            # Git packs on Windows can be read-only. Only mutate our owned copy;
            # prepare_checkout explicitly disables hardlinks to the source repo.
            target=Path(path)
            if (not isinstance(error,PermissionError) or target.is_symlink()
                    or not target.resolve().is_relative_to(self.temp.resolve())
                    or target.stat().st_mode & stat.S_IWRITE):
                raise error
            target.chmod(target.stat().st_mode | stat.S_IWRITE)
            function(path)
        shutil.rmtree(self.temp,onexc=remove_readonly)

def execute(root, document, job, output, *, version=None, channel='stable', inputs=None):
    output=Path(output).resolve()
    require(not output.is_relative_to(root.resolve()), 'OUTPUT_MUST_BE_OUTSIDE_SOURCE')
    output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();ctx=None
    result={'schemaVersion':VERSION, 'planId':document['planId'],'source':document['source'],'key':job['key'],
            'component':job['component'],'operation':job['operation'],'status':'NOT_RUN','startedAt':stamp(),'os':sys.platform,'python':sys.version.split()[0],'commands':[], 'testCounts':{}}
    try:
        current=snapshot(root)
        expected=document['source']
        # Committed plans use the Git tree; local plans use byte-bound snapshot hashes.
        comparable=current if expected.get('dirty') or len(expected['tree'])==64 else snapshot(root,'HEAD')
        require(comparable==expected and (len(expected['tree'])==64 or not current['dirty']), 'SOURCE_CHANGED_SINCE_PLAN')
        require(PROFILES[job['profile']][0]==sys.platform, 'OS_PROFILE_MISMATCH')
        if job['capability']!='read':
            if os.environ.get('CI_TRUSTED_EXECUTION')!='1':raise Blocked('TRUSTED_EXECUTION_REQUIRED')
        spec=metadata((root/job['contract']).read_text(encoding='utf-8'),job['contract'])
        require(spec['sha256']==job['contractSha256'], 'CONTRACT_CHANGED_SINCE_PLAN')
        declared=next((j for j in spec['jobs'] if j['id']==job['id']), None)
        require(job.get('secrets',{})==(declared or {}).get('secrets',{}), 'JOB_SECRET_BINDINGS_MISMATCH')
        require(declared is not None and all(job.get(k)==v for k,v in declared.items()), 'JOB_METADATA_MISMATCH')
        require(job['capability']==declared.get('capability','read') and job['operation']==declared.get('operation','test'), 'JOB_CAPABILITY_MISMATCH')
        if document['operation']=='publish':require(not expected['dirty'],'DIRTY_PUBLISH_SOURCE')
        ctx=Context(root,job,output,expected,version,channel,inputs)
        ctx.plan_id=document['planId']
        ctx.intent=document['operation']
        ctx.prepare_checkout()
        for tool,version in job.get('tools',{}).items():
            if tool=='rust':ctx.env['RUSTUP_TOOLCHAIN']=version
            ctx.tool('rustc' if tool=='rust' else tool, None if version=='stable' else version)
        module_spec=importlib.util.spec_from_file_location('ci_contract_'+job['key'].replace('-','_'),ctx.root/job['contract'])
        module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
        module.run(ctx)
        require(snapshot(root)==current, 'SOURCE_CHANGED_DURING_EXECUTION')
        result['status']='PASS'
    except KeyboardInterrupt:result.update(status='CANCELLED',error='EXECUTION_CANCELLED')
    except Blocked as error:result.update(status='BLOCKED',error=str(error))
    except ContractError as error:result.update(status='BLOCKED',error=str(error))
    except Exception as error:result.update(status='FAIL',error=str(error))
    finally:
        if ctx:
            if 'error' in result: result['error']=ctx.redact(result['error'])
            result['artifactManifest']={str(p.relative_to(output/'artifacts')).replace(os.sep,'/'):digest(p.read_bytes()) for p in (output/'artifacts').rglob('*') if p.is_file()}
            result.update(commands=ctx.commands,testCounts=ctx.test_counts,artifacts=ctx.artifacts)
            try:ctx.close()
            except Exception as error:
                detail='OWNED_CLEANUP_FAILED: '+ctx.redact(str(error))
                result.update(status='FAIL',cleanupError=detail)
                result.setdefault('error',detail)
        result.update(finishedAt=stamp(),seconds=round(time.monotonic()-started,3))
        write_json(output/'result.json',result)
    return result

def aggregate(document, reports):
    saved=dict(document);saved.pop('planId',None)
    require(digest(canonical(saved))==document['planId'], 'PLAN_INTEGRITY')
    expected={j['key']:j for j in document['jobs']};seen={};errors=[]
    for report in reports:
        key=report.get('key')
        if key not in expected or key in seen:errors.append('UNKNOWN_OR_DUPLICATE_REPORT: '+str(key));continue
        seen[key]=report
        if report.get('planId')!=document['planId'] or report.get('source')!=document['source']:errors.append('REPORT_IDENTITY_MISMATCH: '+key)
        if report.get('status')!='PASS' and expected[key].get('required',True):errors.append('REQUIRED_JOB_'+str(report.get('status'))+': '+key)
    errors += ['MISSING_REPORT: '+key for key in expected if key not in seen]
    require(document.get('status')!='NO_CHANGE' or not expected, 'INVALID_NO_CHANGE_PLAN')
    return {'schemaVersion':VERSION,'planId':document['planId'],'status':'FAIL' if errors else ('PASS' if expected else 'NO_CHANGE'),'errors':errors}

def matrices(document):
    def rows(capability, operation):
        return {'include':[{'key':j['key'],'runner':j['runner'],'profile':j['profile'],'timeout':(j['timeout']+59)//60,
                           'node':j.get('tools',{}).get('node',''),'rust':j.get('tools',{}).get('rust',''),
                           'secret_1':[v for k,v in sorted(j.get('secrets',{}).items())][0] if j.get('secrets') else '',
                           'secret_2':[v for k,v in sorted(j.get('secrets',{}).items())][1] if len(j.get('secrets',{}))>1 else ''}
                          for j in document['jobs'] if j['capability']==capability and j['operation'] in operation]}
    return {'read':rows('read',{'test','build'}),'fixture':rows('fixture',{'test'}), 'build':rows('public-inputs',{'build'}),
            'publish':rows('publish',{'publish'}),'external_publish':rows('external-publish',{'publish'})}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['plan','run','aggregate','actions-plan'])
    p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--base');p.add_argument('--head',default='HEAD')
    p.add_argument('--changed',action='store_true');p.add_argument('--push',action='store_true');p.add_argument('--all',action='store_true')
    p.add_argument('--component');p.add_argument('--product');p.add_argument('--operation',choices=['test','build','publish'],default='test')
    p.add_argument('--tag');p.add_argument('--version');p.add_argument('--channel',choices=['stable','uat'],default='stable')
    p.add_argument('--plan',type=Path);p.add_argument('--job');p.add_argument('--inputs',type=Path)
    p.add_argument('--output',type=Path,default=Path(tempfile.gettempdir())/('streamops-ci-'+uuid.uuid4().hex))
    a=p.parse_args(argv);root=a.root.resolve()
    a.output=a.output.resolve()
    all_reason='explicit all tests'
    try:
        require(not a.output.is_relative_to(root),'OUTPUT_MUST_BE_OUTSIDE_SOURCE')
        if a.command=='actions-plan':
            event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
            name=os.environ['GITHUB_EVENT_NAME'];a.head='HEAD'
            if name=='pull_request':
                require(git(root,'rev-parse','HEAD')==event['pull_request']['head']['sha'],'PR_SOURCE_MISMATCH')
                a.base=event['pull_request']['base']['sha']
            elif name=='push':
                if os.environ.get('GITHUB_REF','').startswith('refs/tags/'):
                    a.tag=os.environ['GITHUB_REF_NAME'];a.operation='publish'
                elif event.get('created') is True and event.get('before')=='0'*40:
                    require(git(root,'rev-parse','HEAD')==event.get('after'),'PUSH_SOURCE_MISMATCH')
                    a.all=True
                    all_reason='new branch push: no before SHA; conservative all tests'
                else:a.base=event['before'];a.push=True
            elif name=='workflow_dispatch':
                inputs=event.get('inputs',{})
                a.component=inputs.get('component') or None;a.product=inputs.get('product') or None
                a.operation=inputs.get('operation','test')
                require(a.operation in {'test','build','publish'},'INVALID_OPERATION')
                a.all=not (a.component or a.product) and a.operation=='test'
            else:raise ContractError('UNSUPPORTED_EVENT')
            a.command='plan'
        if a.command=='aggregate':
            require(a.plan,'PLAN_REQUIRED');document=json.loads(a.plan.read_text())
            reports=[json.loads(x.read_text()) for x in a.output.rglob('result.json') if 'artifacts' not in x.relative_to(a.output).parts]
            result=aggregate(document,reports);write_json(a.output/'aggregate.json',result);print(json.dumps(result))
            return 0 if result['status'] in {'PASS','NO_CHANGE'} else 1
        if a.plan:
            document=json.loads(a.plan.read_text());saved=dict(document);saved.pop('planId',None)
            require(digest(canonical(saved))==document['planId'],'PLAN_INTEGRITY')
        else:
            base=a.base
            if a.changed and not base:
                upstream=git(root,'rev-parse','--abbrev-ref','--symbolic-full-name','@{upstream}')
                base=upstream
            document=plan(root,base=base,head=a.head,dirty=a.changed,push=a.push,component=a.component,product=a.product,operation=a.operation,all_jobs=a.all,tag=a.tag,all_reason=all_reason)
            write_json(a.output/'plan.json',document)
        if a.command=='plan':
            matrix=matrices(document);write_json(a.output/'matrix.json',matrix)
            if os.environ.get('GITHUB_OUTPUT'):
                with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as out:
                    for key,value in matrix.items():out.write(key+'='+json.dumps(value,separators=(',',':'))+'\n')
                    out.write('plan_id='+document['planId']+'\n')
            print(json.dumps(document,indent=2));return 0
        jobs=[j for j in document['jobs'] if not a.job or j['key']==a.job]
        require(not a.job or jobs,'UNKNOWN_JOB')
        results=[]
        for job in jobs:
            results.append(execute(root,document,job,a.output/job['key'],version=a.version,channel=a.channel,inputs=a.inputs or (a.output if job['operation']=='publish' else None)))
        if a.job:return 0 if results[0]['status']=='PASS' else 1
        result=aggregate(document,results);write_json(a.output/'aggregate.json',result);print(json.dumps(result))
        return 0 if result['status'] in {'PASS','NO_CHANGE'} else 1
    except (ContractError,Blocked,ValueError) as error:
        write_json(a.output/'error.json',{'status':'BLOCKED','error':str(error)});print(str(error),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
