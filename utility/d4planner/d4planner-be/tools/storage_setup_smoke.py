"""UDR-08 packaged lifecycle on an explicitly isolated Windows VM.

Only a new sandbox and the dedicated installer UAT identity are used. Production
registration is read for preservation evidence, never written. This is not a
clean-OS or live-game claim.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from contextlib import closing


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_file():
            with path.open('rb') as stream:
                result[path.relative_to(root).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', type=Path, required=True)
    parser.add_argument('--old-setup', type=Path)
    parser.add_argument('--source-head', required=True)
    parser.add_argument('--sandbox', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('isolated Windows required')
    import winreg
    from windows_setup_e2e import owned_tree
    keys = [r'Software\Synclab\D4Planner-UAT', r'Software\Microsoft\Windows\CurrentVersion\Uninstall\SynclabD4PlannerUAT']
    production = [r'Software\Synclab\D4Planner', r'Software\Microsoft\Windows\CurrentVersion\Uninstall\SynclabD4Planner']
    def registry(name):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, name, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                values = {}; index = 0
                while True:
                    try:
                        field, value, kind = winreg.EnumValue(key, index)
                    except OSError:
                        return values
                    values[field] = [value, kind]; index += 1
        except FileNotFoundError:
            return None
    if any(registry(key) is not None for key in keys):
        raise RuntimeError('BLOCKED: existing UAT registration belongs to another run')
    before_registry = {key:registry(key) for key in production}
    args.sandbox.mkdir(parents=True, exist_ok=False)
    from storage_native_smoke import secure_new_sandbox
    secure_new_sandbox(args.sandbox)
    install, data = args.sandbox/'application', args.sandbox/'data'
    (data/'state').mkdir(parents=True)
    with closing(sqlite3.connect(data/'state/user-data.db')) as db, db:
        db.execute('CREATE TABLE preserve(value TEXT)'); db.execute("INSERT INTO preserve VALUES ('UDR-08')")
    (data/'sessions/recorded').mkdir(parents=True)
    (data/'sessions/recorded/raw-speech.jsonl').write_text('{"fixture":true}\n')
    (data/'rulekit').mkdir(); (data/'rulekit/foreign-canary.bin').write_bytes(b'preserve; do not adopt')
    baseline = inventory(data)
    environment = {k:v for k,v in os.environ.items() if not k.startswith(('D4PLANNER_','D4_RULEKIT_','D4_LOG_','D4_HUD_'))}
    report = {'id':'UDR-08','status':'RUNNING','sourceHead':args.source_head,
              'classification':'WINDOWS_VM_PACKAGED_LIFECYCLE','cases':[], 'limits':['not a clean-OS test','no live game','installer interruption covered separately']}
    def run(command):
        value = subprocess.run(list(map(str, command)), env=environment, capture_output=True, text=True, timeout=240)
        report['cases'].append({'command':list(map(str,command)), 'exit':value.returncode})
        if value.returncode:
            raise RuntimeError(f'command failed: {command[0]} exit={value.returncode}')
        return value
    def preserved(expected):
        actual = inventory(data)
        assert all(actual.get(name) == digest for name,digest in expected.items()), 'persisted bytes changed'
    def setup(path):
        run([path, '/S', '/ISOLATED=1', '/DATADIR='+str(data), '/INSTALLROOT='+str(install)])
        active = json.loads((install/'active.json').read_text())
        assert Path(active['dataDir']) == data
        return active
    def stop(child):
        run([install/'D4Planner.exe','--stop']); child.wait(timeout=30)
        assert child.returncode == 0
    child = None
    try:
        if args.old_setup:
            setup(args.old_setup); preserved(baseline)
        active = setup(args.setup); preserved(baseline)
        manifest = json.loads((install/active['payload']/'release-manifest.json').read_text())
        assert manifest['sourceHead'] == args.source_head
        run([install/'D4Planner.exe','--runtime-health','--health-report',args.sandbox/'health.json'])
        assert json.loads((args.sandbox/'health.json').read_text())['runtimeReady'] is True
        child = subprocess.Popen([str(install/'D4Planner.exe'),'--viewer'],env=environment)
        time.sleep(5)
        assert child.poll() is None, 'viewer exited'
        tree = owned_tree(child.pid)
        assert any(row['name'].lower() == 'd4planner-fe.exe' for row in tree)
        assert not any(row['name'].lower() in {'python.exe','node.exe'} for row in tree)
        stop(child); child = None
        report['viewerTree'] = tree
        preserved(baseline)
        retained = inventory(data)
        setup(args.setup); preserved(retained)
        report['beforeUninstall'] = retained
        report['status'] = 'PASS'
    except Exception as error:
        report.update(status='FAIL',error=repr(error))
    finally:
        try:
            if child is not None and child.poll() is None:
                stop(child)
            if (install/'Uninstall.exe').exists():
                run([install/'Uninstall.exe','/S'])
                deadline = time.monotonic()+90
                while (install/'Uninstall.exe').exists() and time.monotonic()<deadline:
                    time.sleep(.2)
                assert not (install/'Uninstall.exe').exists() and not (install/'D4Planner.exe').exists()
            preserved(report.get('beforeUninstall',baseline))
            assert all(registry(key) is None for key in keys)
            assert {key:registry(key) for key in production} == before_registry
            report['afterUninstall'] = inventory(data)
        except Exception as error:
            report.update(status='FAIL', cleanupError=repr(error))
        (args.sandbox/'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if report['status']=='PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
