"""Process identity policy: unrelated runtimes pass, D4Planner/uncertainty block."""
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from d4planner.runtime import migration


def row(pid=100, name='python.exe', argv=None, executable=None, parent=1):
    if executable is None:
        import ntpath
        executable = argv[0] if argv and ntpath.isabs(argv[0]) else 'C:\\Runtime\\' + name
    return {'pid': pid, 'name': name, 'parentPid': parent, 'executable': executable,
            'commandLine': json.dumps(argv or [executable, '-m', 'http.server']),
            'startedAt': '2026-11-08T00:00:00+00:00'}


def check(rows, monkeypatch, roots=()):
    # JSON transports exact argv in portable fixtures. The native runner also
    # exercises CommandLineToArgvW against actual Windows process command lines.
    try:
        from d4planner.runtime import process_identity
        monkeypatch.setattr(process_identity, 'windows_argv', json.loads)
    except ImportError:
        pass  # Baseline still runs so the unrelated-process regression is red.
    data = {'processes': rows, 'tasks': [], 'processDiscovery': 'OK', 'taskDiscovery': 'OK',
            'installRoots': list(roots)}
    with patch.object(migration.os, 'name', 'nt'), patch.object(migration.subprocess, 'run',
            return_value=SimpleNamespace(returncode=0, stdout=json.dumps(data), stderr='')):
        migration.quiescence()


@pytest.mark.parametrize('argv,name', [
    ([r'C:\StreamOps\.venv\Scripts\python.exe', '-m', 'streamops.cli', 'runserver', '--data-dir', r'C:\StreamOps\.streamops\node'], 'python.exe'),
    ([r'C:\Python\python.exe', '-I', '-X', 'utf8', '-m', 'http.server'], 'python.exe'),
    ([r'C:\Python\python.exe', r'C:\Other App\server.py'], 'python.exe'),
    ([r'C:\node\node.exe', r'C:\Other App\server.js'], 'node.exe'),
    ([r'C:\Python\python.exe', '-m', 'not_d4planner.cli'], 'python.exe'),
    ([r'C:\Python\python.exe', '-m', 'http.server', '--label', 'd4planner'], 'python.exe'),
])
def test_unrelated_interpreter_not_a_writer_by_name(monkeypatch, argv, name):
    check([row(name=name, argv=argv)], monkeypatch)


@pytest.mark.parametrize('argv', [
    ['python.exe', '-m', 'd4planner.daemon'], ['python.exe', '-md4planner.managed_backend'],
    ['python.exe', '-X', 'utf8', '-m', 'd4planner.cli', 'start'],
    ['python.exe', r'C:\checkout\d4planner-be\src\d4planner\daemon.py'],
    ['python.exe', '-m', 'another.module', '--data-dir', r'C:\Data\D4Planner\state'],
    ['node.exe', r'C:\checkout\d4planner-rulekit\worker.js'],
    ['node.exe', r'C:\package\utility\d4-rulekit\snapshot-management\manage.js'],
    ['python.exe', '-c', 'opaque dynamic code'],
])
def test_d4planner_or_opaque_invocation_still_blocks(monkeypatch, argv):
    with pytest.raises(migration.StorageError, match='PID 100'):
        check([row(argv=argv)], monkeypatch)


def test_packaged_interpreter_blocks_even_for_other_module(monkeypatch):
    with pytest.raises(migration.StorageError, match='PID 100'):
        check([row(executable=r'C:\Applications\Planner\runtime\python.exe')], monkeypatch,
              roots=[r'C:\Applications\Planner'])


def test_path_prefix_is_not_package_containment(monkeypatch):
    check([row(executable=r'C:\Applications\Planner-other\python.exe')], monkeypatch,
          roots=[r'C:\Applications\Planner'])


@pytest.mark.parametrize('field', ['executable', 'commandLine', 'startedAt'])
def test_inaccessible_interpreter_identity_blocks(monkeypatch, field):
    p = row(); p[field] = None
    with pytest.raises(migration.StorageError, match='PID 100'):
        check([p], monkeypatch)


def test_d4planner_child_is_not_allowed_by_unrelated_module(monkeypatch):
    parent = row(pid=200, argv=['python.exe', '-m', 'd4planner.cli'])
    child = row(pid=201, parent=200)
    with pytest.raises(migration.StorageError) as error:
        check([parent, child], monkeypatch)
    assert {p['pid'] for p in error.value.quiescence['processes']} == {200, 201}


def test_reused_parent_pid_does_not_claim_old_child(monkeypatch):
    parent = row(pid=200, argv=['python.exe', '-m', 'd4planner.cli'])
    parent['startedAt'] = '2026-11-09T00:00:00+00:00'
    child = row(pid=201, parent=200)
    with pytest.raises(migration.StorageError) as error:
        check([parent, child], monkeypatch)
    assert {p['pid'] for p in error.value.quiescence['processes']} == {200}


def test_current_setup_python_is_excluded_by_pid(monkeypatch):
    check([row(pid=os.getpid(), argv=['python.exe', '-c', 'setup host'])], monkeypatch)


def test_interpreter_image_mismatch_is_not_exempted(monkeypatch):
    with pytest.raises(migration.StorageError, match='PID 100'):
        check([row(executable=r'C:\Python\python.exe', argv=[r'C:\Other\python.exe', '-m', 'http.server'])], monkeypatch)


def test_relative_script_without_cwd_is_unverified(monkeypatch):
    with pytest.raises(migration.StorageError, match='PID 100'):
        check([row(argv=['python.exe', 'worker.py'])], monkeypatch)


def test_python_versioned_executable_running_d4planner_blocks(monkeypatch):
    with pytest.raises(migration.StorageError, match='PID 100'):
        check([row(name='python3.12.exe', argv=['python3.12.exe', '-m', 'd4planner.daemon'])], monkeypatch)


def test_setup_parent_arguments_do_not_make_it_a_runtime_writer(monkeypatch):
    check([row(name='D4Planner-Setup.exe', executable=r'C:\Downloads\D4Planner-Setup.exe',
               argv=[r'C:\Downloads\D4Planner-Setup.exe', '/DATAROOT=C:\\Data\\D4Planner'])], monkeypatch)
