"""Host wrapper tests: real Git snapshots, simulated SSH only, no release writes."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import build_setup_vm as vm


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / 'repo'
    subprocess.run(['git','init','-q',str(repo)],check=True)
    plan = repo / 'utility/d4planner/d4planner-be/release1/package-plan.json'
    plan.parent.mkdir(parents=True)
    plan.write_text('{"version":"1.2.8"}')
    (repo/'tracked.txt').write_text('committed\n')
    subprocess.run(['git','-C',str(repo),'add','.'],check=True)
    subprocess.run(['git','-C',str(repo),'-c','user.name=test','-c','user.email=test@example.invalid',
                    'commit','-qm','fixture'],check=True)
    return repo


def test_snapshot_preserves_head_and_lf_excludes_local_changes(repository,tmp_path):
    head=subprocess.check_output(['git','-C',str(repository),'rev-parse','HEAD'],text=True).strip()
    (repository/'tracked.txt').write_text('uncommitted\n')
    (repository/'private.key').write_text('must not transfer')
    archive=tmp_path/'source.zip'
    assert vm.source_snapshot(repository,'HEAD',archive)==(head,'1.2.8')
    extract=tmp_path/'extract'
    with zipfile.ZipFile(archive) as z:
        assert 'private.key' not in z.namelist()
        assert z.read('tracked.txt')==b'committed\n'
        z.extractall(extract)
    assert subprocess.check_output(['git','-C',str(extract),'rev-parse','HEAD'],text=True).strip()==head
    assert subprocess.check_output(['git','-C',str(extract),'status','--porcelain'],text=True)==''
    assert (repository/'tracked.txt').read_text()=='uncommitted\n'


def artifact_files(head):
    setup='D4Planner-Setup-1.2.8.exe'
    binary=b'synthetic installer bytes, not Windows build evidence'
    sha=hashlib.sha256(binary).hexdigest()
    metadata={'sourceHead':head,'version':'1.2.8','artifact':setup,'sha256':sha,'bytes':len(binary),
              'snapshotIncluded':False,'artifactClass':'D4PLANNER_APPLICATION_NO_SNAPSHOT','runtimeHealth':'PASS'}
    files={setup:binary,'release-metadata.json':json.dumps(metadata).encode(),
           'SHA256SUMS':f'{sha}  {setup}\n'.encode(),'UAT.md':b'Synthetic fixture'}
    result={'exitCode':0,'sourceHead':head,'version':'1.2.8',
            'files':{name:hashlib.sha256(data).hexdigest() for name,data in files.items()}}
    return files,result


@pytest.mark.parametrize('mode',['success','failed','tampered','wrong_head','extra_asset','timeout','disconnect','check'])
def test_orchestration_downloads_only_verified_artifacts(repository,tmp_path,monkeypatch,mode):
    head=subprocess.check_output(['git','-C',str(repository),'rev-parse','HEAD'],text=True).strip()
    files,result=artifact_files(head)
    if mode=='failed': result['exitCode']=2
    if mode=='wrong_head': result['sourceHead']='0'*40
    if mode=='extra_asset': result['files']['../private.key']='0'*64
    remote_files={**files,'result.json':json.dumps(result).encode(),'build.log':b'fixture build log'}
    if mode=='tampered': remote_files['D4Planner-Setup-1.2.8.exe']=b'tampered'
    calls=[]; downloaded=[]
    class FakeSSH:
        def __init__(self,host): assert host=='builder'
        def powershell(self,code,**kw):
            calls.append(code)
            if 'New-Item' in code:
                import re
                run_id=re.search(r'd4planner-build-([0-9a-f]{32})',code)[1]
                return SimpleNamespace(returncode=0,stdout='C:/Temp/d4planner-build-'+run_id+'\n')
            if '-CheckOnly' in code: return SimpleNamespace(returncode=0,stdout='{"ready":true}')
            if 'taskkill.exe' in code: return SimpleNamespace(returncode=0,stdout='owned cleanup')
            assert '-SourceHead '+head in code and '-Version 1.2.8' in code
            if mode=='timeout': raise subprocess.TimeoutExpired('ssh',1)
            return SimpleNamespace(returncode=255 if mode=='disconnect' else 2 if mode=='failed' else 0)
        def upload(self,local,remote): assert Path(local).is_file()
        def download(self,remote,local):
            name=remote.rsplit('/',1)[1]; downloaded.append(name)
            Path(local).write_bytes(remote_files[name])
    monkeypatch.setattr(vm,'WindowsSSH',FakeSSH)
    out=tmp_path/'out'
    args=['--vm','builder','--repo',str(repository),'--output',str(out)]
    if mode=='check': args+=['--check']
    assert vm.main(args)==(0 if mode in {'success','check'} else 1)
    assert (out/'D4Planner-Setup-1.2.8.exe').exists()==(mode=='success')
    assert any('taskkill.exe' in code for code in calls)==(mode in {'timeout','disconnect'})
    if mode in {'failed','extra_asset'}: assert downloaded==['result.json','build.log']
    if mode=='check': assert not downloaded and len(calls)==2
    assert not any(name.endswith('.key') for name in downloaded)


def test_ssh_uses_key_verification_and_encoded_powershell(monkeypatch):
    calls=[]
    monkeypatch.setattr(vm.subprocess,'run',lambda args,**kw:calls.append(args) or SimpleNamespace(returncode=0))
    code="Write-Output 'path with spaces & $value'"
    vm.WindowsSSH('windows-builder').powershell(code)
    command=calls[0]
    assert 'BatchMode=yes' in command and 'StrictHostKeyChecking=yes' in command
    assert base64.b64decode(command[-1]).decode('utf-16-le')==code
    for invalid in ['-oProxyCommand=bad','host;touch bad','user@host:22','host\nother']:
        with pytest.raises(ValueError):vm.WindowsSSH(invalid)


def test_existing_output_is_never_overwritten(tmp_path):
    (tmp_path/'keep').write_text('retained')
    with pytest.raises(FileExistsError): vm.main(['--vm','builder','--output',str(tmp_path),'--check'])
    assert (tmp_path/'keep').read_text()=='retained'
