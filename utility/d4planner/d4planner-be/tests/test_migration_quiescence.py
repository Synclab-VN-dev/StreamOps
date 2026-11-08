"""Quiescence diagnostics must explain blockers without relaxing offline safety."""
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from d4planner.runtime import migration


def snapshot(processes=(), tasks=()):
    return {'processes': list(processes), 'tasks': list(tasks),
            'processDiscovery': 'OK', 'taskDiscovery': 'OK'}


def process(name, pid=123):
    return {'pid': pid, 'name': name}


def probe(data, *, returncode=0):
    with patch.object(migration.os, 'name', 'nt'), patch.object(
        migration.subprocess, 'run', return_value=SimpleNamespace(
            returncode=returncode, stdout=json.dumps(data), stderr='private query output')):
        migration.quiescence()


def test_setup_owned_python_is_excluded_only_by_current_pid():
    probe(snapshot([process('python.exe', os.getpid())]))


@pytest.mark.parametrize('name', ['python.exe', 'pythonw.exe', 'node.exe', 'nvda.exe',
                                 'nvda_noUIAccess.exe', 'D4Planner.exe', 'd4planner-fe.exe'])
def test_potential_writer_is_blocked_with_pid(name):
    # Includes unrelated Python/Node: command-line appearance alone cannot prove
    # they cannot write these roots. Preserve the existing conservative contract.
    with pytest.raises(migration.StorageError, match='PID 123') as error:
        probe(snapshot([process(name)]))
    assert error.value.quiescence['processes'] == [process(name)]
    assert 'private query output' not in str(error.value)


def test_setup_python_parent_is_not_implicitly_trusted():
    with pytest.raises(migration.StorageError, match='PID 123'):
        probe(snapshot([process('python.exe', os.getpid()), process('python.exe')]))


@pytest.mark.parametrize('state', ['Ready', 'Running', 'Queued', 'Unknown'])
def test_enabled_task_blocks_even_when_not_running(state):
    task = {'name': 'D4Planner-Supervisor', 'path': '\\', 'state': state}
    with pytest.raises(migration.StorageError, match='D4Planner-Supervisor') as error:
        probe(snapshot(tasks=[task]))
    assert error.value.quiescence['tasks'] == [task]


def test_disabled_task_and_no_other_writers_pass():
    probe(snapshot(tasks=[{'name': 'D4Planner-Supervisor', 'path': '\\', 'state': 'Disabled'}]))


@pytest.mark.parametrize('stage', ['processDiscovery', 'taskDiscovery'])
def test_discovery_failure_is_distinct_and_fail_closed(stage):
    data = snapshot(); data[stage] = 'FAILED'
    with pytest.raises(migration.StorageError, match='DISCOVERY_FAILED') as error:
        probe(data)
    assert error.value.quiescence[stage] == 'FAILED'


@pytest.mark.parametrize('data', [{}, {'processes': None}, snapshot([{'name': 'python.exe'}])])
def test_incomplete_discovery_is_blocked(data):
    with pytest.raises(migration.StorageError, match='DISCOVERY_FAILED'):
        probe(data)


def test_nonzero_query_exit_is_blocked_even_with_valid_json():
    with pytest.raises(migration.StorageError, match='DISCOVERY_FAILED'):
        probe(snapshot(), returncode=1)


@pytest.mark.parametrize('exception', [OSError('no powershell'),
    migration.subprocess.TimeoutExpired('powershell.exe', 30)])
def test_unavailable_or_timeout_discovery_is_blocked(exception):
    with patch.object(migration.os, 'name', 'nt'), patch.object(
        migration.subprocess, 'run', side_effect=exception):
        with pytest.raises(migration.StorageError, match='DISCOVERY_FAILED'):
            migration.quiescence()


@pytest.mark.skipif(os.name != 'nt', reason='real Windows process/task discovery')
def test_native_unrelated_python_blocks_with_real_pid(tmp_path):
    import subprocess
    import sys
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        with pytest.raises(migration.StorageError, match=f'PID {child.pid}') as error:
            migration.quiescence()
        assert error.value.quiescence['processDiscovery'] == 'OK'
        assert error.value.quiescence['taskDiscovery'] == 'OK'
    finally:
        child.terminate(); child.wait(timeout=10)  # only this test's own child


@pytest.mark.parametrize('stage,classification', [('OK', 'MIGRATION_BUSY'),
                                                 ('FAILED', 'MIGRATION_DISCOVERY_FAILED')])
def test_setup_report_preserves_quiescence_reason(tmp_path, monkeypatch, stage, classification):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
    import windows_install as engine
    data = snapshot([process('python.exe')]); data['taskDiscovery'] = stage
    def blocked(*args, **kwargs):
        probe(data)
    monkeypatch.setattr(engine, 'install', blocked)
    report = tmp_path / 'report.json'
    assert engine.main(['install', '--root', str(tmp_path / 'app'), '--data', str(tmp_path / 'data'),
                        '--package', str(tmp_path / 'package.zip'), '--sha256', 'fixture',
                        '--report', str(report)]) == 1
    result = json.loads(report.read_text())
    assert result['classification'] == classification
    assert result['quiescence']['processes'] == [process('python.exe')]
    assert not (tmp_path / 'data').exists()


@pytest.mark.parametrize('name', [
    'D4Planner-Controller-Probe', 'D4Planner-Controller-Probe-V2',
    'D4Planner-Unrelated', 'Other-D4Planner-Supervisor', 'D4Planner-Supervisor-old',
    'D4Planner-Isolated-invalid-Supervisor',
    'D4Planner-Isolated-123456789abc-Controller-Probe',
    'D4Planner-F11-Diagnostic-not-a-request-id',
])
def test_obsolete_or_similarly_named_tasks_do_not_block(name):
    probe(snapshot(tasks=[{'name': name, 'path': '\\', 'state': 'Ready'}]))


@pytest.mark.parametrize('name', [
    'D4Planner-Supervisor', 'D4Planner-NVDA', 'D4Planner-NVDA-Restart',
    'D4Planner-NVDA-Stop', 'D4Planner-D4', 'D4Planner-Tolk-Probe',
    'D4Planner-Input-Marker-Probe', 'd4planner-supervisor',
    'D4Planner-Isolated-123456789abc-Supervisor',
    'D4Planner-Isolated-123456789abc-Input-Marker-Probe',
    'D4Planner-F11-Diagnostic-0123456789abcdef',
])
def test_source_defined_task_names_remain_blocked(name):
    with pytest.raises(migration.StorageError, match='enabled D4Planner tasks'):
        probe(snapshot(tasks=[{'name': name, 'path': '\\', 'state': 'Ready'}]))


def test_obsolete_tasks_do_not_hide_discovery_failure():
    data = snapshot(tasks=[{'name': 'D4Planner-Controller-Probe', 'path': '\\', 'state': 'Ready'}])
    data['taskDiscovery'] = 'FAILED'
    with pytest.raises(migration.StorageError, match='DISCOVERY_FAILED'):
        probe(data)


def test_task_catalog_covers_actual_runtime_call_sites(tmp_path):
    # Guard against producer/classifier drift when a runtime task is added.
    import ast
    import inspect
    from d4planner.runtime.windows import WindowsRuntime
    from d4planner.runtime.store import RuntimePaths
    from d4planner.runtime.task_names import RUNTIME_TASK_NAMES, is_current_task_name
    tree = ast.parse(inspect.getsource(WindowsRuntime))
    names = {node.args[0].value for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr in ('task_name', 'run_task') and node.args
             and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
             and node.args[0].value.startswith('D4Planner-')}
    assert names == RUNTIME_TASK_NAMES
    runtime = WindowsRuntime(RuntimePaths(tmp_path))
    for name in names:
        assert is_current_task_name(runtime.task_name(name))
        assert is_current_task_name(runtime.task_name(name, isolated=True))
