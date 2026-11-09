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
