"""Planner uses real owned Node IPC/HTTP. Fixture data is explicitly synthetic."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import urllib.request

import pytest

from d4planner.control import dispatch, validate_request
from d4planner.rulekit import RuleKitRuntimeService, RuleKitRemoteError
from d4planner.rulekit import LaunchSpecification, RuleKitProcessWrapper

ROOT = Path(__file__).resolve().parents[4]
PROVIDER = ROOT / 'utility/d4planner/d4planner-rulekit/providers/maxroll'


def provision(root):
    config = json.loads(subprocess.check_output(['node', str(PROVIDER/'tooling/web/activation-fixture.js'), str(root/'ui')], text=True))[0]
    package = {'kind': 'ui', 'snapshotId': config['snapshotId'], 'validationStatus': 'VALIDATED', 'runId': 'synthetic',
               'manifestSha256': config['manifestSha256'], 'coverageSha256': config['uiTrust']['coverageSha256'],
               'validationSha256': config['uiTrust']['validationSha256'], 'config': config}
    payload = {'schemaVersion': 'maxroll-capture-state/v1', 'revision': 1, 'activeUi': config['snapshotId'],
               'packages': {config['snapshotId']: package}, 'runs': {'synthetic': {'status': 'COMPLETE'}}}
    state = root/'state'; state.mkdir()
    # This is the existing Python capture_state canonical representation, including non-ASCII metadata.
    payload['note'] = 'Kiểm chứng 🧪'
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    (state/'capture-state.json').write_text(json.dumps({'payload': payload, 'sha256': digest}))
    return state


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def request(id='planner-1'):
    return {'protocolVersion': 'd4planner-control/v1', 'type': 'request', 'requestId': id,
            'ownerInstanceId': 'owner', 'childInstanceId': 'child', 'generation': 1,
            'method': 'planner.ensureReady', 'params': {}}


def test_control_contract_and_redacted_errors():
    validate_request(request())
    for params in ({'url': 'https://maxroll.gg/'}, [], None):
        with pytest.raises(ValueError): validate_request({**request(), 'params': params})
    class Runtime:
        async def handle_control(self, command):
            raise RuleKitRemoteError('PLANNER_SNAPSHOT_UNTRUSTED', '/private/secret')
    result = asyncio.run(dispatch(Runtime(), request(), request()))
    assert result['error']['code'] == 'PLANNER_SNAPSHOT_UNTRUSTED'
    assert '/private' not in json.dumps(result)


def test_production_worker_planner_independent_of_calculation_and_owned_cleanup(tmp_path):
    chromium = os.environ.get('F2_TEST_CHROMIUM')
    if not chromium:
        pytest.skip('Explicit installed Chromium for unchanged production bootstrap required')
    state = provision(tmp_path); port = free_port()
    async def scenario():
        service = RuleKitRuntimeService.from_environment({
            'D4PLANNER_RULEKIT_EXECUTABLE': shutil.which('node'),
            'D4PLANNER_RULEKIT_WORKING_DIR': str(tmp_path),
            'D4_RULEKIT_INSTALLATION_ROOT': str(ROOT), 'D4_RULEKIT_DATA_ROOT': str(tmp_path/'calculation'),
            'D4_RULEKIT_CHROMIUM_EXECUTABLE': chromium, 'D4_RULEKIT_PLANNER_STATE_ROOT': str(state),
            'D4_RULEKIT_PLANNER_PORT': str(port),
        })
        from d4planner.production import ProductionBackendRuntime
        # Actual production forwarding boundary; no capture/Target repository needed to issue the command.
        backend = object.__new__(ProductionBackendRuntime); backend.rulekit = service
        try:
            health = await service.start()
            assert health['calculationAvailability'] == 'UNAVAILABLE'
            worker_pid = service.wrapper._child.pid
            replies = await asyncio.gather(*(dispatch(backend, request(str(i)), request()) for i in range(8)))
            assert all(r['error'] is None and r['result']['status'] == 'READY' for r in replies)
            assert service.wrapper._child.pid == worker_pid
            again = await backend.handle_control(request())
            assert again['reused'] and again['url'] == f'http://127.0.0.1:{port}/'
            with urllib.request.urlopen(again['url']) as response: assert response.status == 200
            assert (await service.client.snapshot_call('getActive'))['active'] is None
            assert len(await service.client.list_providers()) == 1
            assert service.client.pending_count == 0
        finally:
            await service.stop()
        with socket.socket() as sock: assert sock.connect_ex(('127.0.0.1', port)) != 0
        assert service.wrapper._child is None
        with pytest.raises(RuleKitRemoteError) as error: await service.ensure_planner_ready()
        assert error.value.code == 'PLANNER_UNAVAILABLE'
    asyncio.run(scenario())


def test_public_package_contains_runtime_only_and_no_capture_assets():
    policy = json.loads((ROOT/'utility/d4planner/d4planner-be/release1/public-content-policy.json').read_text())
    names = policy['sourceAllowlist']
    prefix = 'utility/d4planner/d4planner-rulekit/providers/maxroll/tooling/'
    required = ['planner/worker-adapter.js', 'planner/manager.js', 'planner/selection.js',
                'web/server.js', 'web/client.js', 'web/shell.js', 'web/native-transfer.js', 'web/ui-package.js']
    for name in required:
        assert prefix+name in names and (ROOT/(prefix+name)).is_file()
    assert not any(name.endswith(('capture-state.json', 'manifest.json', 'cli.py', 'capture-ui.js')) for name in names)


def test_planner_ipc_does_not_interrupt_calculation_sessions(tmp_path):
    state = provision(tmp_path)
    async def scenario():
        wrapper = RuleKitProcessWrapper(LaunchSpecification(executable='node',
            args=(str(ROOT/'utility/d4planner/d4planner-be/src/d4planner/rulekit/worker.js'),), working_directory=ROOT,
            environment_allow_list={'D4_RULEKIT_COMPOSITION_MODULE': str(Path(__file__).with_name('fixtures')/'planner-test-composition.js'),
                'D4_RULEKIT_PLANNER_STATE_ROOT': str(state), 'D4_RULEKIT_PLANNER_PORT': str(free_port())}, operation_timeout=3))
        try:
            client = await wrapper.start()
            session = await client.create_session({'contractVersion': 'd4-rulekit-application/v1',
                'providerId': 'test.synthetic', 'providerVersion': '1.0.0', 'buildSchemaVersion': 'synthetic-build/v1',
                'build': {'class': 'Rogue', 'equipment': {}, 'skills': {}, 'paragon': {}, 'effects': {}, 'testDelayMs': 150}})
            before = await client.get_session(session)
            calculated, planner = await asyncio.gather(client.evaluate(session), client.ensure_planner_ready())
            assert calculated['metrics'][0]['rawValue'] == 0 and planner['status'] == 'READY'
            after = await client.get_session(session)
            assert {k: v for k, v in after.items() if k not in {'touchedAt', 'diagnostics'}} == {k: v for k, v in before.items() if k not in {'touchedAt', 'diagnostics'}}
            assert after['diagnostics']['evaluations'] == before['diagnostics']['evaluations'] + 1
            await client.close_session(session)
        finally:
            await wrapper.stop()
    asyncio.run(scenario())


def test_managed_stdin_planner_requests_target_and_shutdown(tmp_path):
    chromium = os.environ.get('F2_TEST_CHROMIUM')
    if not chromium:
        pytest.skip('Explicit installed Chromium required for production managed process')
    state = provision(tmp_path); port = free_port()
    bootstrap = {'protocol': 'd4planner-managed/v1', 'contractVersion': 'd4planner-r1-contract/1.0.0-candidate.6',
                 **{k: request()[k] for k in ('ownerInstanceId', 'childInstanceId', 'generation')},
                 'dataDir': str(tmp_path/'state'), 'targetFolder': str(tmp_path/'targets'),
                 'wsEndpoint': {'host': '127.0.0.1', 'port': 0}, 'credential': 'a'*32}
    file = tmp_path/'bootstrap.json'; file.write_text(json.dumps(bootstrap)); file.chmod(0o600)
    env = {**os.environ, 'PYTHONPATH': str(ROOT/'utility/d4planner/d4planner-be/src'),
           'D4PLANNER_BOOTSTRAP_FILE': str(file), 'D4PLANNER_RUNTIME_FACTORY': 'd4planner.production:create_runtime',
           'D4PLANNER_REPOSITORY_ROOT': str(ROOT), 'D4PLANNER_RULEKIT_EXECUTABLE': shutil.which('node'),
           'D4PLANNER_RULEKIT_WORKING_DIR': str(tmp_path), 'D4_RULEKIT_INSTALLATION_ROOT': str(ROOT),
           'D4_RULEKIT_CHROMIUM_EXECUTABLE': chromium, 'D4_RULEKIT_PLANNER_STATE_ROOT': str(state), 'D4_RULEKIT_PLANNER_PORT': str(port)}
    async def scenario():
        proc = await asyncio.create_subprocess_exec(sys.executable, '-m', 'd4planner.managed_backend', env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        async def read(): return json.loads(await asyncio.wait_for(proc.stdout.readline(), 20))
        def send(message): proc.stdin.write((json.dumps(message)+'\n').encode())
        try:
            ready = await read(); assert ready['event'] == 'READY'
            for i in range(3): send(request(str(i)))
            send({**request('targets'), 'method': 'target.list'})
            replies = [await read() for _ in range(4)]
            assert {r['requestId'] for r in replies} == {'0', '1', '2', 'targets'}
            assert all(r['error'] is None for r in replies)
            send(request('reused')); assert (await read())['result']['reused']
            send({**request('cancelled'), 'type': 'cancel'}) # harmless unknown cancellation
            send({'type': 'shutdown', **{k: bootstrap[k] for k in ('ownerInstanceId', 'childInstanceId', 'generation')}})
            assert (await read())['event'] == 'EXIT'
            assert await asyncio.wait_for(proc.wait(), 12) == 0
        finally:
            if proc.returncode is None:
                proc.stdin.close(); await asyncio.wait_for(proc.wait(), 15)
        with socket.socket() as sock: assert sock.connect_ex(('127.0.0.1', port)) != 0
    asyncio.run(scenario())


def test_caller_cancellation_propagates_to_worker_without_late_listener(tmp_path):
    state = provision(tmp_path); port = free_port()
    async def scenario():
        wrapper = RuleKitProcessWrapper(LaunchSpecification(executable='node',
            args=(str(ROOT/'utility/d4planner/d4planner-be/src/d4planner/rulekit/worker.js'),), working_directory=ROOT,
            environment_allow_list={'D4_RULEKIT_COMPOSITION_MODULE': str(Path(__file__).with_name('fixtures')/'planner-test-composition.js'),
                'D4_RULEKIT_PLANNER_STATE_ROOT': str(state), 'D4_RULEKIT_PLANNER_PORT': str(port), 'TEST_PLANNER_DELAY_MS': '350'}))
        try:
            client = await wrapper.start()
            task = asyncio.create_task(client.ensure_planner_ready())
            await asyncio.sleep(.05); task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            await asyncio.sleep(.5)
            with socket.socket() as sock: assert sock.connect_ex(('127.0.0.1', port)) != 0
            assert client.pending_count == 0
            assert await client.list_providers()
            assert (await client.ensure_planner_ready())['status'] == 'READY'
        finally:
            await wrapper.stop()
    asyncio.run(scenario())
