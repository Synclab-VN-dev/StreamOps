"""Boundary/package checks; Linux subprocess evidence, no production snapshots."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

from d4planner.rulekit import RuleKitRuntimeService
from d4planner.rulekit.protocol import APPROVED_METHODS, SNAPSHOT_METHODS

ROOT = Path(__file__).resolve().parents[3]
WORKER = ROOT / 'utility/d4planner/src/d4planner/rulekit/worker.js'
BOOTSTRAP = ROOT / 'utility/d4-rulekit/application/src/runtime/bootstrap.js'
FIXTURE = ROOT / 'utility/d4planner/tests/fixtures/rulekit-test-composition.js'


def test_adapter_has_no_rulekit_implementation_imports():
    source = WORKER.read_text()
    for internal in ('registry', 'resolver', 'MaxrollProvider', 'MaxrollPatchProfile',
                     'BrowserInfrastructure', 'manager.', 'production-composition', '/src'):
        assert internal not in source
    assert not (ROOT / 'utility/d4planner/rulekit-worker').exists()
    # Test contract parity independently of manager's exported method list.
    schema = json.loads((ROOT / 'utility/d4-rulekit/snapshot-management/schemas/call.schema.json').read_text())
    assert {row['properties']['method']['const'] for row in schema['oneOf']} == SNAPSHOT_METHODS
    for method in APPROVED_METHODS | SNAPSHOT_METHODS:
        assert repr(method) in source


@pytest.mark.parametrize('generation', ['0', 'wrong'])
def test_bootstrap_invalid_generation_never_ready(tmp_path, generation):
    result = subprocess.run(['node', str(BOOTSTRAP), str(WORKER)], cwd=tmp_path,
        env={**os.environ, 'D4_RULEKIT_WORKER_INSTANCE_ID': 'isolated',
             'D4_RULEKIT_WORKER_GENERATION': generation}, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0 and 'READY' not in result.stdout
    assert 'managed worker identity is required' in result.stderr


def test_bootstrap_missing_profile_never_ready(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith('D4_RULEKIT_')}
    env.update(D4_RULEKIT_WORKER_INSTANCE_ID='isolated', D4_RULEKIT_WORKER_GENERATION='1',
               D4_RULEKIT_PROFILE_JSON=str(tmp_path / 'missing.json'),
               D4_RULEKIT_SNAPSHOT_ROOT=str(tmp_path / 'missing-snapshots'))
    result = subprocess.run(['node', str(BOOTSTRAP), str(WORKER)], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0 and 'READY' not in result.stdout
    assert 'ENOENT' in result.stderr


@pytest.mark.parametrize('override,label', [
    ('D4PLANNER_RULEKIT_BOOTSTRAP', 'bootstrap'),
    ('D4PLANNER_RULEKIT_WORKER', 'worker'),
])
def test_missing_installed_runtime_fails_before_spawn(tmp_path, override, label):
    values = {'D4PLANNER_RULEKIT_EXECUTABLE': shutil.which('node'),
              'D4PLANNER_RULEKIT_WORKING_DIR': str(tmp_path),
              'D4_RULEKIT_PROFILE_JSON': str(tmp_path / 'profile.json'),
              'D4_RULEKIT_SNAPSHOT_ROOT': str(tmp_path / 'snapshots'),
              override: str(tmp_path / 'missing.js')}
    with pytest.raises(ValueError, match=label):
        RuleKitRuntimeService.from_environment(values)


def test_real_ipc_rejects_unsupported_method_and_bounds_queue(tmp_path):
    async def scenario():
        env = {**os.environ, 'D4_RULEKIT_COMPOSITION_MODULE': str(FIXTURE),
               'D4_RULEKIT_WORKER_INSTANCE_ID': 'isolated', 'D4_RULEKIT_WORKER_GENERATION': '1',
               'D4_RULEKIT_MAX_CONCURRENT': '1', 'D4_RULEKIT_MAX_QUEUE': '1'}
        child = await asyncio.create_subprocess_exec('node', str(WORKER), cwd=tmp_path, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        async def read():
            return json.loads(await asyncio.wait_for(child.stdout.readline(), 5))
        def send(id, method, params=None):
            child.stdin.write((json.dumps({'protocolVersion': 'd4-rulekit-ipc/v1',
                'type': 'request', 'id': id, 'method': method, 'params': params or {}}) + '\n').encode())
        try:
            ready = await read()
            assert set(ready['apis']) == APPROVED_METHODS
            send('unsupported', 'ninthAPI')
            await child.stdin.drain()
            assert (await read())['error']['code'] == 'INVALID_MESSAGE'
            send('create', 'createSession', {
                'contractVersion': 'd4-rulekit-application/v1', 'providerId': 'test.synthetic',
                'providerVersion': '1.0.0', 'buildSchemaVersion': 'synthetic-build/v1',
                'build': {'class': 'Rogue', 'equipment': {}, 'skills': {}, 'paragon': {},
                          'effects': {}, 'testDelayMs': 500}})
            await child.stdin.drain()
            session = (await read())['result']['sessionId']
            # Hold an actual operation pending, independent of pipe chunking.
            send('0', 'evaluate', {'sessionId': session})
            send('1', 'listProviders')
            send('2', 'listProviders')
            await child.stdin.drain()
            responses = [await read() for _ in range(3)]
            assert {r['correlationId'] for r in responses} == {'0', '1', '2'}
            assert sum(r.get('error', {}).get('code') == 'QUEUE_FULL' for r in responses) == 1
            send('3', 'evaluate', {'sessionId': session, 'options': {'bypassCache': True}})
            send('4', 'listProviders')
            child.stdin.write((json.dumps({'protocolVersion': 'd4-rulekit-ipc/v1',
                'type': 'cancel', 'correlationId': '4'}) + '\n').encode())
            send('5', 'listProviders')
            await child.stdin.drain()
            resumed = [await read() for _ in range(2)]
            assert {r['correlationId'] for r in resumed} == {'3', '5'}
            assert all(r['type'] == 'result' for r in resumed)
        finally:
            child.stdin.close()
            await asyncio.wait_for(child.wait(), 5)
        assert child.returncode == 0
    asyncio.run(scenario())


def test_wheel_installs_adapter_and_resolves_external_runtime_without_cwd(tmp_path):
    build = subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-build-isolation',
                    '-w', str(tmp_path), str(ROOT / 'utility/d4planner')],
                   capture_output=True, text=True, timeout=60)
    assert build.returncode == 0, f"Wheel build failed ({build.returncode}):\n{build.stdout}\n{build.stderr}"
    wheel = next(tmp_path.glob('*.whl'))
    with zipfile.ZipFile(wheel) as archive:
        assert archive.read('d4planner/rulekit/worker.js') == WORKER.read_bytes()
    target = tmp_path / 'site-packages'
    install_result = subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps', '--target', str(target), str(wheel)],
                   capture_output=True, text=True, timeout=60)
    assert install_result.returncode == 0, (
        f"Wheel install failed ({install_result.returncode}):\n{install_result.stdout}\n{install_result.stderr}"
    )
    install = tmp_path / 'installation'
    (install / 'utility').mkdir(parents=True)
    # A separately provisioned Rule Kit tree, like #150; never embedded in the wheel.
    shutil.copytree(ROOT / 'utility/d4-rulekit', install / 'utility/d4-rulekit',
                    ignore=shutil.ignore_patterns('artifacts', '__pycache__', '.pytest_cache'))
    code = '''
import sys, json
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from d4planner.rulekit import RuleKitRuntimeService
service = RuleKitRuntimeService.from_environment(json.loads(sys.argv[2]))
spec = service.wrapper.specification
assert Path(spec.args[1]) == Path(sys.argv[1]) / 'd4planner/rulekit/worker.js'
assert Path(spec.args[0]).is_file()
if 'D4_RULEKIT_CHROMIUM_EXECUTABLE' in spec.environment_allow_list:
    import asyncio
    async def verify():
        try:
            health = await service.start()
            assert health['ready'] and health['calculationAvailability'] == 'UNAVAILABLE'
        finally:
            await service.stop()
    asyncio.run(verify())
print(json.dumps(list(spec.args)))
'''
    env = {'D4PLANNER_RULEKIT_EXECUTABLE': shutil.which('node'),
           'D4PLANNER_RULEKIT_WORKING_DIR': str(tmp_path),
           'D4_RULEKIT_INSTALLATION_ROOT': str(install), 'D4_RULEKIT_DATA_ROOT': str(tmp_path / 'data')}
    if os.environ.get('F2_TEST_CHROMIUM'):
        env['D4_RULEKIT_CHROMIUM_EXECUTABLE'] = os.environ['F2_TEST_CHROMIUM']
    result = subprocess.run([sys.executable, '-I', '-c', code, str(target), json.dumps(env)],
                            cwd=tmp_path, check=True, capture_output=True, text=True, timeout=10)
    bootstrap, worker = json.loads(result.stdout)
    # Actual relocated Node module loading, even without a provisioned snapshot.
    result = subprocess.run(['node', bootstrap, worker], cwd=tmp_path,
        env={**os.environ, 'D4_RULEKIT_WORKER_INSTANCE_ID': 'installed', 'D4_RULEKIT_WORKER_GENERATION': '0'},
        capture_output=True, text=True, timeout=10)
    assert 'managed worker identity is required' in result.stderr
    assert 'Cannot find module' not in result.stderr


def test_real_production_bootstrap_no_snapshot_and_owned_shutdown(tmp_path):
    chromium = os.environ.get('F2_TEST_CHROMIUM')
    if not chromium:
        pytest.skip('explicit isolated Chromium required; not a synthetic production PASS')
    async def scenario():
        service = RuleKitRuntimeService.from_environment({
            'D4PLANNER_RULEKIT_EXECUTABLE': shutil.which('node'),
            'D4PLANNER_RULEKIT_WORKING_DIR': str(tmp_path),
            'D4_RULEKIT_INSTALLATION_ROOT': str(ROOT),
            'D4_RULEKIT_DATA_ROOT': str(tmp_path / 'data'),
            'D4_RULEKIT_CHROMIUM_EXECUTABLE': chromium,
        })
        try:
            health = await service.start()
            assert health['ready'] and health['calculationAvailability'] == 'UNAVAILABLE'
            assert health['providers'][0]['id'] == 'maxroll'
            assert service.wrapper.specification.args == (str(BOOTSTRAP), str(WORKER))
            capabilities = await service.client.snapshot_call('getCapabilities')
            assert capabilities['reason'] == 'SNAPSHOT_NOT_SELECTED'
            assert capabilities['active'] is None
            assert capabilities['restartRequired'] is False
            child = service.wrapper._child
        finally:
            await service.stop()
        assert child.process.returncode == 0
        assert not (tmp_path / 'data/.manager.lock').exists()
    asyncio.run(scenario())
