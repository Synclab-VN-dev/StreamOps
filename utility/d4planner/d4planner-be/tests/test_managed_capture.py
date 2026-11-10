"""Issue #193: ownership and lifecycle at the managed capture boundary."""
import asyncio
import json
from pathlib import Path

from d4planner.runtime.managed_capture import ManagedCaptureRuntime


class Child:
    pid = 123
    returncode = None
    def __init__(self):
        self.stdin = self
        self.closed = False
        self.killed = False
    def close(self):
        self.closed = True
    async def wait(self):
        self.returncode = 0
        return 0
    def terminate(self):
        self.killed = True


def test_managed_child_uses_block_xbox16_and_stops_only_owned_handle(tmp_path):
    async def scenario():
        calls, health = [], []
        child = Child()
        async def spawn(*args, **kwargs):
            calls.append((args, kwargs)); return child
        async def changed(value):
            health.append(value)
        runtime = ManagedCaptureRuntime(tmp_path, changed, spawn=spawn)
        await runtime.start()
        await runtime.start()
        assert len(calls) == 1
        args, kwargs = calls[0]
        assert args[args.index('--controller-profile') + 1] == 'xbox16'
        assert '--block' in args and '--managed-by-hud' in args
        assert args[args.index('--home') + 1] == str(tmp_path)
        assert 'D4PLANNER_BOOTSTRAP_FILE' not in kwargs['env']
        await runtime.stop()
        await runtime.stop()
        assert child.closed and not child.killed
        assert not (tmp_path / 'state/stop.request').exists()
    asyncio.run(scenario())


def test_foreign_runtime_status_cannot_mark_owned_capture_running(tmp_path):
    async def scenario():
        child = Child()
        async def spawn(*args, **kwargs): return child
        async def changed(value): pass
        state = tmp_path / 'state'; state.mkdir()
        (state / 'runtime.json').write_text(json.dumps({'supervisorPid': 999, 'state': 'RUNNING'}))
        runtime = ManagedCaptureRuntime(tmp_path, changed, spawn=spawn)
        await runtime.start()
        await runtime._refresh()
        assert runtime.state == 'STARTING'
        child.returncode = 5
        await runtime._refresh()
        assert runtime.state == 'BLOCKED'
        assert 'Another capture runtime' in runtime.detail
        await runtime.stop()
        assert not child.closed and not child.killed
        assert json.loads((state / 'runtime.json').read_text())['supervisorPid'] == 999
    asyncio.run(scenario())


def test_spawn_failure_is_visible_and_stop_is_safe(tmp_path):
    async def scenario():
        health = []
        async def spawn(*args, **kwargs): raise OSError('cannot spawn')
        async def changed(value): health.append(value)
        runtime = ManagedCaptureRuntime(tmp_path, changed, spawn=spawn)
        await runtime.start()
        assert runtime.state == 'BLOCKED'
        assert health == ['ERROR']
        await runtime.stop()
    asyncio.run(scenario())


def test_owned_status_preserves_dependency_failure_and_waiting(tmp_path):
    async def scenario():
        child, health = Child(), []
        async def spawn(*args, **kwargs): return child
        async def changed(value): health.append(value)
        runtime = ManagedCaptureRuntime(tmp_path, changed, spawn=spawn)
        state = tmp_path / 'state'; state.mkdir()
        await runtime.start()
        for status, detail in [('WAITING_FOR_GAME', 'waiting for user'), ('BLOCKED', 'NVDA missing')]:
            (state / 'runtime.json').write_text(json.dumps({
                'supervisorPid': child.pid, 'extras': {'runtime': {'ownerToken': runtime.owner_token}}, 'state': status, 'detail': detail}))
            await runtime._refresh()
            assert runtime.state == status and runtime.detail == detail
        assert health == ['DEGRADED', 'ERROR']
        await runtime.stop()
    asyncio.run(scenario())


def test_hud_nvda_start_does_not_require_legacy_scheduled_tasks(tmp_path, monkeypatch):
    from d4planner.runtime.windows import WindowsRuntime
    from d4planner.runtime.store import RuntimePaths
    from d4planner.runtime.model import ProcessInfo
    runtime = WindowsRuntime(RuntimePaths(tmp_path))
    runtime.managed_by_hud = True
    process = ProcessInfo('nvda', 456, session_id=1)
    calls = []
    monkeypatch.setattr(runtime, 'nvda_process', lambda: process if calls else None)
    monkeypatch.setattr(runtime, 'current_process_session_id', lambda: 1)
    monkeypatch.setattr(runtime, 'active_console_session_id', lambda: 1)
    monkeypatch.setattr(runtime, 'locate_nvda_executable', lambda: tmp_path / 'nvda.exe')
    def forbidden(): raise AssertionError('HUD must not depend on legacy Scheduled Tasks')
    monkeypatch.setattr(runtime, 'ensure_interactive_tasks', forbidden)
    monkeypatch.setattr('subprocess.Popen', lambda *a, **kw: calls.append((a, kw)))
    assert runtime.ensure_nvda_running(timeout=.1) == process
    assert len(calls) == 1
    assert calls[0][1]['env']['D4PLANNER_DATA_ROOT'] == str(tmp_path)


def test_hud_nvda_wrong_session_blocks_before_spawn(tmp_path, monkeypatch):
    import pytest
    from d4planner.runtime.windows import WindowsRuntime, RuntimeBlocked
    from d4planner.runtime.store import RuntimePaths
    runtime = WindowsRuntime(RuntimePaths(tmp_path))
    runtime.managed_by_hud = True
    monkeypatch.setattr(runtime, 'nvda_process', lambda: None)
    monkeypatch.setattr(runtime, 'current_process_session_id', lambda: 0)
    monkeypatch.setattr(runtime, 'active_console_session_id', lambda: 1)
    def forbidden(*a, **kw): raise AssertionError('wrong session must not launch NVDA')
    monkeypatch.setattr('subprocess.Popen', forbidden)
    with pytest.raises(RuntimeBlocked, match='active desktop session'):
        runtime.ensure_nvda_running()


def test_v16_stop_pause_survives_backend_restart_and_explicit_start_resumes(tmp_path):
    async def scenario():
        children = []
        async def spawn(*args, **kwargs):
            child = Child(); children.append(child); return child
        async def changed(value): pass
        first = ManagedCaptureRuntime(tmp_path, changed, spawn=spawn)
        await first.start()
        await first.command('stop')
        assert first.status()['manualPause'] is True
        await first.stop()  # Backend shutdown must not clear the user's pause.
        second = ManagedCaptureRuntime(tmp_path, changed, spawn=spawn)
        await second.start()
        assert len(children) == 1
        assert second.status()['state'] == 'STOPPED'
        await second.command('start')
        assert len(children) == 2 and not second.status()['manualPause']
        await second.stop()
    asyncio.run(scenario())


def test_v16_dead_child_cannot_be_hidden_by_stale_running_status_and_retry_rotates_owner(tmp_path):
    async def scenario():
        children = []
        async def spawn(*args, **kwargs):
            child = Child(); children.append(child); return child
        async def changed(value): pass
        runtime = ManagedCaptureRuntime(tmp_path, changed, spawn=spawn)
        await runtime.start()
        token = runtime.owner_token
        state = tmp_path / 'state'; state.mkdir(exist_ok=True)
        (state / 'runtime.json').write_text(json.dumps({'supervisorPid':123, 'state':'RUNNING',
            'detail':'Ready', 'nvda':{'pid':456}, 'extras':{'runtime':{'ownerToken':token}}}))
        children[0].returncode = 1
        await runtime._refresh()
        assert 'exited (1)' in runtime.detail
        assert runtime.status()['dependencies'] == {}
        await runtime.command('restart')
        assert runtime.owner_token != token and len(children) == 2
        await runtime._refresh()
        assert runtime.state == 'STARTING'
        await runtime.stop()
    asyncio.run(scenario())


def test_v16_concurrent_starts_spawn_once_and_invalid_pause_blocks(tmp_path):
    async def scenario():
        calls = []
        async def spawn(*args, **kwargs):
            await asyncio.sleep(.01); calls.append(1); return Child()
        async def changed(value): pass
        runtime = ManagedCaptureRuntime(tmp_path, changed, spawn=spawn)
        await asyncio.gather(runtime.command('start'), runtime.command('start'))
        assert calls == [1]
        await runtime.stop()
        (tmp_path / 'state/capture-preferences.json').write_text('{broken')
        blocked = ManagedCaptureRuntime(tmp_path, changed, spawn=spawn)
        await blocked.start()
        assert blocked.state == 'BLOCKED' and calls == [1]
        await blocked.command('start')  # Explicit operator intent repairs preference.
        assert calls == [1, 1]
        await blocked.stop()
    asyncio.run(scenario())


def test_v16_runtime_controls_require_owner_and_empty_parameters(tmp_path):
    import pytest
    from d4planner.control import dispatch, validate_request
    from d4planner.production import ProductionBackendRuntime
    async def scenario():
        async def changed(value): pass
        async def spawn(*args, **kwargs): return Child()
        capture = ManagedCaptureRuntime(tmp_path, changed, spawn=spawn)
        # Exercise actual production dispatch without starting unrelated services.
        runtime = object.__new__(ProductionBackendRuntime)
        runtime.capture_runtime = capture
        bootstrap = {'ownerInstanceId':'owner', 'childInstanceId':'child', 'generation':1}
        command = {'protocolVersion':'d4planner-control/v1', 'type':'request', 'requestId':'test',
                   **bootstrap, 'method':'capture.start', 'params':{}}
        for method in ('runtime.status','capture.start','capture.stop','capture.restart'):
            validate_request({**command,'method':method})
            for invalid in ({'pid':123}, [], None):
                with pytest.raises(ValueError): validate_request({**command,'method':method,'params':invalid})
        denied = await dispatch(runtime, {**command,'ownerInstanceId':'foreign'}, bootstrap)
        assert denied['error']['code'] == 'OWNERSHIP_MISMATCH' and capture.process is None
        result = await dispatch(runtime, command, bootstrap)
        assert result['error'] is None and result['result']['pid'] == 123
        stopped = await dispatch(runtime, {**command,'method':'capture.stop'}, bootstrap)
        assert stopped['result']['manualPause'] and stopped['result']['state'] == 'STOPPED'
    asyncio.run(scenario())


def test_v16_receipt_and_metrics_are_only_from_owned_live_capture(tmp_path):
    from datetime import datetime, timezone
    import time
    async def scenario():
        async def changed(value): pass
        child = Child()
        async def spawn(*a, **kw): return child
        runtime = ManagedCaptureRuntime(tmp_path, changed, spawn=spawn)
        await runtime.start()
        (tmp_path/'state').mkdir(exist_ok=True); (tmp_path/'private').mkdir()
        payload = {'supervisorPid':123, 'state':'RUNNING', 'nvda':{'pid':456,
            'started_at':datetime.fromtimestamp(time.time()-10, timezone.utc).isoformat()},
            'extras':{'runtime':{'ownerToken':runtime.owner_token},'speechEventCount':7}}
        (tmp_path/'state/runtime.json').write_text(json.dumps(payload))
        receipt = tmp_path/'private/nvda-capture-consumer.json'
        receipt.write_text(json.dumps({'pid':456,'dataRoot':str(tmp_path),'writtenAtUnix':time.time()}))
        await runtime._refresh()
        assert runtime.status()['speechEvents'] == 7
        assert runtime.status()['dataRootReceipt'] == 'VALIDATED'
        receipt.write_text(json.dumps({'pid':999,'dataRoot':str(tmp_path),'writtenAtUnix':time.time()}))
        assert runtime.status()['dataRootReceipt'] == 'MISMATCH'
        receipt.write_text('null')
        assert runtime.status()['dataRootReceipt'] == 'UNAVAILABLE'
        child.returncode = 1
        await runtime._refresh()
        assert runtime.status()['speechEvents'] is None
        assert runtime.status()['dataRootReceipt'] == 'UNAVAILABLE'
        await runtime.stop()
    asyncio.run(scenario())


def test_v16_failed_owned_cleanup_never_loses_handle_or_spawns_replacement(tmp_path, monkeypatch):
    import pytest
    async def scenario():
        child = Child()
        async def spawn(*a, **kw): return child
        async def changed(value): pass
        runtime = ManagedCaptureRuntime(tmp_path, changed, spawn=spawn)
        await runtime.start()
        original_wait = asyncio.wait_for
        async def timeout_wait(coro, timeout):
            coro.close()
            raise asyncio.TimeoutError()
        monkeypatch.setattr(asyncio, 'wait_for', timeout_wait)
        with pytest.raises(asyncio.TimeoutError): await runtime.command('restart')
        assert runtime.process is child
        monkeypatch.setattr(asyncio, 'wait_for', original_wait)
        await runtime.stop()
    asyncio.run(scenario())
