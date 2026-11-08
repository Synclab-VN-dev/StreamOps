"""Explicit isolated-VM regression for #184 quiescence diagnostics.

Run with a base Python directly from PowerShell (no Python supervisor). Creates
only owned process/task fixtures; does not stop or modify existing writers/tasks.
Not added to CI: the lightweight tests cover the same decision table there.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import uuid

from d4planner.runtime import migration
from storage_native_smoke import secure_new_sandbox


def powershell(code):
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                             "$ErrorActionPreference='Stop'; " + code], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sandbox', required=True, type=Path)
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Windows required')
    root = args.sandbox.resolve(); root.mkdir(parents=True, exist_ok=False)
    secure_new_sandbox(root)
    source = root / 'legacy'; source.mkdir()
    for name in ('state', 'targets', 'rulekit'):
        (source / name).mkdir()
        (source / name / 'preserve.bin').write_bytes(b'unchanged fixture')
    db = sqlite3.connect(source / 'state/hud.sqlite3')
    db.execute('CREATE TABLE revision(value INTEGER)'); db.execute('INSERT INTO revision VALUES(42)')
    db.commit(); db.close()
    def inventory():
        return {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in source.rglob('*') if p.is_file()}
    report = {'status': 'RUNNING', 'cases': [], 'before': inventory()}
    def case(name, run):
        try:
            run(); report['cases'].append({'id': name, 'status': 'PASS'})
        except Exception as error:
            report['cases'].append({'id': name, 'status': 'FAIL', 'error': str(error)})
    def blocked(pid=None, task=None):
        try:
            migration.plan(source, root / 'target')
        except migration.StorageError as error:
            evidence = getattr(error, 'quiescence', {})
            if pid is not None:
                assert any(p['pid'] == pid for p in evidence.get('processes', [])), str(error)
            if task is not None:
                assert any(t['name'] == task for t in evidence.get('tasks', [])), str(error)
            assert evidence.get('processDiscovery') == evidence.get('taskDiscovery') == 'OK', str(error)
            assert not (root / 'target').exists()
        else:
            raise AssertionError('unsafe migration was not blocked')
    # This interpreter is the migration host, matching Setup's direct Python
    # invocation. Its parent PowerShell is not granted a Python exception.
    case('setup-host-python-self-excluded', migration.quiescence)
    # Reproduce Windows venv redirector + interpreter, as on A. An unrelated
    # module with its own data directory must not be blocked by python.exe.
    import venv
    venv.EnvBuilder(with_pip=False).create(root / 'server-venv')
    package = root / 'server-code' / 'streamops'; package.mkdir(parents=True)
    (package / '__init__.py').write_text('')
    (package / 'cli.py').write_text('import os,sys; print(os.getpid(),flush=True); sys.stdin.read()')
    environment = dict(os.environ); environment.pop('PYTHONPATH', None)
    child = subprocess.Popen([str(root / 'server-venv/Scripts/python.exe'), '-m', 'streamops.cli',
                              'runserver', '--data-dir', str(root / 'server-data')],
                             cwd=package.parent, env=environment, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
    try:
        actual_pid = int(child.stdout.readline().strip())
        report['unrelatedServerPids'] = [child.pid, actual_pid]
        case('unrelated-server-venv-and-interpreter-allowed', migration.quiescence)
    finally:
        child.communicate(timeout=10)  # EOF ends our child and its venv wrapper.
    package = root / 'writer-code' / 'd4planner'; package.mkdir(parents=True)
    (package / '__init__.py').write_text('')
    (package / 'fixture_worker.py').write_text('import os,sys; print(os.getpid(),flush=True); sys.stdin.read()')
    child = subprocess.Popen([sys.executable, '-m', 'd4planner.fixture_worker'], cwd=package.parent,
                             env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        actual_pid = int(child.stdout.readline().strip())
        case('actual-d4planner-module-blocked', lambda: blocked(pid=actual_pid))
    finally:
        child.communicate(timeout=10)
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(90)'])
    try:
        case('opaque-inline-python-stays-blocked', lambda: blocked(pid=child.pid))
    finally:
        child.terminate(); child.wait(timeout=10)
    # Actual SQLite connection holds a write reservation without changing bytes.
    code = "import sqlite3,time,sys; c=sqlite3.connect(sys.argv[1]); c.execute('BEGIN IMMEDIATE'); print('READY',flush=True); time.sleep(90)"
    child = subprocess.Popen([sys.executable, '-c', code, str(source / 'state/hud.sqlite3')], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'READY'
        case('sqlite-writer-stays-blocked', lambda: blocked(pid=child.pid))
    finally:
        child.terminate(); child.wait(timeout=10); child.stdout.close()
    # Harmless native image-name fixtures exercise the actual CIM classifier;
    # they do not install Node/NVDA or claim to exercise their application logic.
    exe = root / 'sleeper.exe'
    quoted = str(exe).replace("'", "''")
    powershell("Add-Type -TypeDefinition 'public class Fixture { public static void Main() { System.Threading.Thread.Sleep(90000); } }' -OutputAssembly '" + quoted + "' -OutputType ConsoleApplication")
    for name in ('node.exe', 'nvda.exe', 'D4Planner.exe'):
        image = root / name; shutil.copyfile(exe, image)
        child = subprocess.Popen([str(image)])
        try:
            case(name + '-stays-blocked', lambda: blocked(pid=child.pid))
        finally:
            child.terminate(); child.wait(timeout=10)
    # Unknown names sharing the prefix must not block. Use a real generated
    # runtime name for the positive case, never a production fixed task name.
    node = root / 'node.exe'
    script = root / 'unrelated-server.js'; script.write_text('// unrelated application fixture')
    child = subprocess.Popen([str(node), str(script)])
    try:
        case('unrelated-node-script-allowed', migration.quiescence)
    finally:
        child.terminate(); child.wait(timeout=10)
    suffix = uuid.uuid4().hex
    for task, relevant in [
        ('D4Planner-Quiescence-Regression-' + suffix, False),
        ('D4Planner-Isolated-' + suffix[:12] + '-Supervisor', True),
    ]:
        created = False
        try:
            powershell("$a=New-ScheduledTaskAction -Execute '" + quoted + "'; Register-ScheduledTask -TaskName '" + task + "' -Action $a | Out-Null")
            created = True
            if relevant:
                case('ready-source-task-stays-blocked', lambda: blocked(task=task))
                powershell("Disable-ScheduledTask -TaskName '" + task + "' | Out-Null")
                case('disabled-owned-task-allows-offline', migration.quiescence)
            else:
                case('unrelated-prefix-task-allows-offline', migration.quiescence)
        finally:
            if created:
                powershell("Unregister-ScheduledTask -TaskName '" + task + "' -Confirm:$false")
    for command, stage in [('Get-CimInstance', 'processDiscovery'), ('Get-ScheduledTask', 'taskDiscovery')]:
        original = migration.subprocess.run
        def injected(argv, **kwargs):
            argv = list(argv); argv[-1] = 'function ' + command + " { throw 'Access denied fixture' }; " + argv[-1]
            return original(argv, **kwargs)
        def discovery_failure():
            from unittest.mock import patch
            with patch.object(migration.subprocess, 'run', side_effect=injected):
                try:
                    migration.quiescence()
                except migration.StorageError as error:
                    assert getattr(error, 'quiescence', {}).get(stage) == 'FAILED', str(error)
                    assert 'DISCOVERY_FAILED' in str(error)
                else:
                    raise AssertionError('discovery failure allowed migration')
        case(stage + '-permission-failure-blocked', discovery_failure)
    report['after'] = inventory()
    db = sqlite3.connect(source / 'state/hud.sqlite3')
    report['sqlite'] = {'integrity': db.execute('PRAGMA integrity_check').fetchone()[0],
                        'revision': db.execute('SELECT value FROM revision').fetchone()[0]}
    db.close()
    report['ownedCleanup'] = True
    report['status'] = ('PASS' if all(c['status'] == 'PASS' for c in report['cases'])
        and report['before'] == report['after'] and report['sqlite'] == {'integrity': 'ok', 'revision': 42} else 'FAIL')
    (root / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
