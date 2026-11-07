"""Run issue-165 native tests in the enrolled, exclusively locked Windows builder.

No machine A access. No Actions. Only per-run source/venv/sandbox is written.
Failed or disconnected runs are retained for inspection; never guessed-cleaned.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import shutil
from pathlib import Path
import sys
import tempfile
import uuid
from storage_evidence import digest, load_verified, PHASE_CASES

REPO = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('udr_vm_build', REPO/'utility/d4planner/script/build/build_vm.py')
vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vm)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--suite', choices=('full','storage'), default='full')
    parser.add_argument('--resume', type=Path, help='Reuse verified PASS phases from this exact source HEAD')
    parser.add_argument('--interactive-user', help='Explicit disposable local account already logged into the VM console; required for Setup UI')
    parser.add_argument('--setup', type=Path)
    parser.add_argument('--old-setup', type=Path)
    args = parser.parse_args(argv)
    if args.interactive_user and not args.setup:
        parser.error('--interactive-user requires --setup')
    args.output.mkdir(parents=True, exist_ok=False)
    builder = vm.ManagedBuilder('d4planner-builder')
    ssh = vm.WindowsSSH('d4planner-builder', builder.ssh_config)
    remote = 'C:/D4Builder/runs/udr165-' + uuid.uuid4().hex
    report = {'remote':remote, 'status':'RUNNING', 'ci':'CI_NOT_CHECKED', 'suite':args.suite, 'interactiveUser':args.interactive_user, 'phases':{}}
    builder.acquire()
    try:
        builder.ensure_running(ssh)
        with tempfile.TemporaryDirectory(prefix='udr165-source-') as directory:
            archive = Path(directory)/'source.zip'
            head, _ = vm.source_snapshot(REPO, None, archive)
            reused = load_verified(args.resume, head) if args.resume else {}
            setup_sha = digest(args.setup) if args.setup else None
            if reused and reused.get('setupSha256') != setup_sha:
                raise ValueError('resume Setup checksum mismatch')
            old_setup_sha = digest(args.old_setup) if args.old_setup else None
            if reused and (reused.get('suite') != args.suite or reused.get('oldSetupSha256') != old_setup_sha or reused.get('interactiveUser') != args.interactive_user):
                raise ValueError('resume suite or old Setup checksum mismatch')
            report['oldSetupSha256'] = old_setup_sha
            report['setupSha256'] = setup_sha
            passed = {name: phase for name, phase in reused.get('phases', {}).items() if name in PHASE_CASES and phase['status'] == 'PASS'}
            for phase in passed.values():
                for artifact in phase['artifacts']:
                    target = args.output / artifact
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(args.resume / artifact, target)
            report['source'] = json.loads(archive.with_suffix('.json').read_text())
            creation = ssh.powershell(f"New-Item -ItemType Directory -Path {vm.ps_quote(remote)} -ErrorAction Stop | Out-Null")
            if creation.returncode:
                raise RuntimeError(creation.stdout)
            ssh.upload(archive, remote+'/source.zip')
            if args.setup:
                metadata = json.loads((args.setup.parent/'release-metadata.json').read_text())
                if metadata['sourceHead'] != head or metadata['sha256'] != vm.digest(args.setup):
                    raise RuntimeError('Setup must match exact source snapshot and checksum')
                ssh.upload(args.setup, remote+'/setup.exe')
                if args.old_setup:
                    ssh.upload(args.old_setup, remote+'/old-setup.exe')
            code = r'''$ErrorActionPreference='Stop'
$root=__ROOT__
if((Get-FileHash ($root+'/source.zip') -Algorithm SHA256).Hash.ToLower() -ne '__SHA__'){throw 'source checksum mismatch'}
Expand-Archive -LiteralPath ($root+'/source.zip') -DestinationPath ($root+'/source')
Set-Location ($root+'/source')
$frameworks='C:\D4Builder\frameworks'
$env:CARGO_HOME=$frameworks+'\cargo'; $env:RUSTUP_HOME=$frameworks+'\rustup'
$env:RUSTUP_TOOLCHAIN='1.90.0-x86_64-pc-windows-msvc'
$env:CARGO_TARGET_DIR='C:\D4Builder\cache\cargo-target'
$env:CARGO_BUILD_JOBS='2'
$env:PATH="$frameworks\python;$frameworks\node\node-v22.22.1-win-x64;$frameworks\git\cmd;$env:CARGO_HOME\bin;"+$env:PATH
$python=$frameworks+'\python\python.exe'
if(-not(Test-Path -LiteralPath $python)) {
 $registered=Get-ItemProperty 'HKCU:\Software\Python\PythonCore\3.12\InstallPath' -ErrorAction Stop
 $python=$registered.ExecutablePath
}
if((& $python --version) -ne 'Python 3.12.10'){throw 'Python version mismatch'}
function Native([string]$Exe,[string[]]$Arguments) { $saved=$ErrorActionPreference; $ErrorActionPreference='Continue'; & $Exe @Arguments; $code=$LASTEXITCODE; $ErrorActionPreference=$saved; if($code -ne 0){throw "Native exit $code : $Exe"} }
Native $python @('-m','venv',($root+'/venv'))
Native ($root+'/venv/Scripts/python.exe') @('-m','pip','install','-e','utility/d4planner/d4planner-be[dev]')
$env:PATH=($root+'/venv/Scripts;')+$env:PATH
$env:PYTHONPATH=($root+'/source/utility/d4planner/d4planner-be/src;'+$root+'/venv/Lib/site-packages')
foreach($name in @('browser-infra','providers/maxroll','snapshot-management')) {
 Native 'npm.cmd' @('ci','--ignore-scripts','--prefix',('utility/d4planner/d4planner-rulekit/'+$name))
}
function Phase([string]$Name,[string]$Exe,[string[]]$Arguments) {
 if($Name -in @(__REUSED__)){return}
 $saved=$ErrorActionPreference; $ErrorActionPreference='Continue'
 $global:LASTEXITCODE=1
 & $Exe @Arguments *> ($root+'/'+$Name+'.log'); $exit=$LASTEXITCODE
 $ErrorActionPreference=$saved
 $status=if($exit -eq 0){'PASS'}else{'FAIL'}
 @{status=$status;command=@($Exe)+$Arguments;subprocessExit=$exit;testOwner='Dev F / Windows VM';scope='isolated native regression'} | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 ($root+'/'+$Name+'.json')
}
Phase 'python' $python @('-m','pytest',__TESTS__,'-q','--tb=short')
Phase 'migration' $python @('utility/d4planner/d4planner-be/tools/storage_native_smoke.py','--sandbox',($root+'/migration'))
Phase 'launcher' 'cargo' @('test','--release','--locked','--manifest-path','utility/d4planner/d4planner-launcher/Cargo.toml')
Phase 'logging' 'cargo' @('test','--release','--locked','--manifest-path','utility/d4planner/d4planner-hud/runtime-logging/Cargo.toml')
Phase 'report-issue' 'cargo' @('test','--release','--locked','--manifest-path','utility/d4planner/d4planner-hud/report-issue/Cargo.toml')
'''.replace('__REUSED__', ','.join(vm.ps_quote(name) for name in passed)).replace('__ROOT__', vm.ps_quote(remote)).replace('__SHA__', vm.digest(archive)).replace('__TESTS__', ','.join(vm.ps_quote('utility/d4planner/d4planner-be/'+name) for name in (['tests'] if args.suite == 'full' else ['tests/test_unified_storage.py','tests/test_runtime_store.py','tests/test_production_backend.py','tests/test_windows_runtime_pure.py'])))
            if args.setup:
                setup_command = "Phase 'setup' $python @('utility/d4planner/d4planner-be/tools/storage_setup_smoke.py','--setup',($root+'/setup.exe'),'--source-head','"+head+"','--sandbox',($root+'/setup-smoke')" + (",'--old-setup',($root+'/old-setup.exe')" if args.old_setup else "") + ")"
                code += r'''
if('setup' -notin @(__REUSED__)) {
 $requestedUser=__USER__
 $consoleUser=(Get-CimInstance Win32_ComputerSystem).UserName
 $expectedUser=$env:COMPUTERNAME+'\'+$requestedUser
 if(-not $requestedUser -or $consoleUser -ine $expectedUser) {
  @{status='BLOCKED';subprocessExit=$null;testOwner='Dev F / Windows VM';scope='interactive Setup';reason='Explicit disposable --interactive-user must already be logged into the VM console; session 0 is not a UI test'} | ConvertTo-Json | Set-Content -Encoding UTF8 ($root+'/setup.json')
  'No interactive Setup launched' | Set-Content ($root+'/setup.log')
 } else {
  $task='UDR165-'+(Split-Path $root -Leaf)
  if(Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue){throw 'Owned task name already exists'}
  $script=@'
$ErrorActionPreference='Stop'
$root=__ROOT__
$python=__PYTHON__
$env:PYTHONPATH=($root+'/source/utility/d4planner/d4planner-be/src;'+$root+'/venv/Lib/site-packages')
$env:PATH='C:/D4Builder/frameworks/node/node-v22.22.1-win-x64;'+$env:PATH
Set-Location ($root+'/source')
'@
  $script=$script.Replace('__PYTHON__',("'"+$python.Replace("'","''")+"'"))
  $script+="`nfunction Phase {"+(Get-Item Function:\Phase).Definition+"}`n"
  $script+=@'
__SETUP_COMMAND__
'@
  Set-Content -LiteralPath ($root+'/setup-interactive.ps1') -Value $script -Encoding UTF8
  $action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -File "'+$root+'/setup-interactive.ps1"')
  $principal=New-ScheduledTaskPrincipal -UserId $expectedUser -LogonType Interactive -RunLevel Highest
  $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  Register-ScheduledTask -TaskName $task -Action $action -Principal $principal -Settings $settings | Out-Null
  Start-ScheduledTask -TaskName $task
  $deadline=(Get-Date).AddMinutes(15)
  do { Start-Sleep -Milliseconds 500 } while(-not(Test-Path ($root+'/setup.json')) -and (Get-Date) -lt $deadline)
  if((Get-ScheduledTask -TaskName $task).State -ne 'Running'){Unregister-ScheduledTask -TaskName $task -Confirm:$false}
 }
}
'''.replace('__REUSED__', ','.join(vm.ps_quote(name) for name in passed)).replace('__USER__', vm.ps_quote(args.interactive_user or '')).replace('__ROOT__', vm.ps_quote(remote)).replace('__SETUP_COMMAND__',setup_command)
            script = Path(directory)/'acceptance.ps1'
            script.write_text(code, encoding='utf-8')
            ssh.upload(script, remote+'/acceptance.ps1')
            try:
                with (args.output/'native.log').open('w') as log:
                    result = ssh.powershell('& '+vm.ps_quote(remote+'/acceptance.ps1'), timeout=2400, stdout=log)
                report['subprocessExit'] = result.returncode
            except Exception as error:
                report.update(subprocessExit=-1, transportError=str(error))
            for name in ['python', 'migration', 'launcher', 'logging', 'report-issue'] + (['setup'] if args.setup else []):
                if name in passed:
                    report['phases'][name] = {**passed[name], 'reusedFrom':str(args.resume.resolve())}
                    continue
                phase = {'status':'NOT_RUN', 'reason':'phase was not reached or evidence unavailable'}
                try:
                    ssh.download(remote+'/'+name+'.json', args.output/(name+'-phase.json'))
                    phase = json.loads((args.output/(name+'-phase.json')).read_text(encoding='utf-8-sig'))
                    ssh.download(remote+'/'+name+'.log', args.output/(name+'.log'))
                    phase['artifacts'] = {name+'-phase.json': digest(args.output/(name+'-phase.json')), name+'.log': digest(args.output/(name+'.log'))}
                    if name in ('migration', 'setup'):
                        guest = 'migration' if name == 'migration' else 'setup-smoke'
                        ssh.download(remote+'/'+guest+'/report.json', args.output/(name+'.json'))
                        phase['artifacts'][name+'.json'] = digest(args.output/(name+'.json'))
                except Exception as error:
                    phase['evidenceError'] = str(error)
                    if phase['status'] == 'PASS':
                        phase['status'] = 'FAIL'
                report['phases'][name] = phase
            report['status'] = 'PASS' if report['subprocessExit'] == 0 and all(p['status'] == 'PASS' for p in report['phases'].values()) else 'FAIL'
    except Exception as error:
        report.update(status='FAIL', error=str(error))
    finally:
        (args.output/'report.json').write_text(json.dumps(report, indent=2))
        # Evidence/source retained on VM for manual inspection. The builder API
        # shuts down only a VM started by this run and releases its host lock.
        builder.close(ssh, leave_running=report['status'] != 'PASS')
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
