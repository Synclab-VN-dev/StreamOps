"""Run issue-165 native tests in the enrolled, exclusively locked Windows builder.

No machine A access. No Actions. Only per-run source/venv/sandbox is written.
Failed or disconnected runs are retained for inspection; never guessed-cleaned.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import uuid

REPO = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('udr_vm_build', REPO/'utility/d4planner/script/build/build_vm.py')
vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vm)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--suite', choices=('full','storage'), default='full')
    parser.add_argument('--setup', type=Path)
    parser.add_argument('--old-setup', type=Path)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    builder = vm.ManagedBuilder('d4planner-builder')
    ssh = vm.WindowsSSH('d4planner-builder', builder.ssh_config)
    remote = 'C:/D4Builder/runs/udr165-' + uuid.uuid4().hex
    report = {'remote':remote, 'status':'RUNNING', 'ci':'CI_NOT_CHECKED', 'suite':args.suite}
    builder.acquire()
    try:
        builder.ensure_running(ssh)
        with tempfile.TemporaryDirectory(prefix='udr165-source-') as directory:
            archive = Path(directory)/'source.zip'
            head, _ = vm.source_snapshot(REPO, None, archive)
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
Native $python @('-m','pytest',__TESTS__,'-q','--tb=short')
Native $python @('utility/d4planner/d4planner-be/tools/storage_native_smoke.py','--sandbox',($root+'/migration'))
foreach($project in @('d4planner-launcher','d4planner-hud/runtime-logging','d4planner-hud/report-issue')) {
 Native 'cargo' @('test','--release','--locked','--manifest-path',('utility/d4planner/'+$project+'/Cargo.toml'))
}
'''.replace('__ROOT__', vm.ps_quote(remote)).replace('__SHA__', vm.digest(archive)).replace('__TESTS__', ','.join(vm.ps_quote('utility/d4planner/d4planner-be/'+name) for name in (['tests'] if args.suite == 'full' else ['tests/test_unified_storage.py','tests/test_runtime_store.py','tests/test_production_backend.py','tests/test_windows_runtime_pure.py'])))
            if args.setup:
                code += "\nNative $python @('utility/d4planner/d4planner-be/tools/storage_setup_smoke.py','--setup',($root+'/setup.exe'),'--source-head','"+head+"','--sandbox',($root+'/setup-smoke')" + (",'--old-setup',($root+'/old-setup.exe')" if args.old_setup else "") + ")\n"
            with (args.output/'native.log').open('w') as log:
                result = ssh.powershell(code, timeout=2400, stdout=log)
            report['subprocessExit'] = result.returncode
            if result.returncode:
                raise RuntimeError('native test failed; retained VM run at '+remote)
            ssh.download(remote+'/migration/report.json', args.output/'migration.json')
            if args.setup:
                ssh.download(remote+'/setup-smoke/report.json', args.output/'setup.json')
            report['status'] = 'PASS'
    except Exception as error:
        report.update(status='FAIL', error=str(error))
        raise
    finally:
        (args.output/'report.json').write_text(json.dumps(report, indent=2))
        # Evidence/source retained on VM for manual inspection. The builder API
        # shuts down only a VM started by this run and releases its host lock.
        builder.close(ssh, leave_running=report['status'] != 'PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
