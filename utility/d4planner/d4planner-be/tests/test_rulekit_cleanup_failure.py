"""Deterministic async ownership faults, not Windows process-group evidence."""
import asyncio
from pathlib import Path
import pytest
from d4planner.rulekit.process import RuleKitProcessWrapper, LaunchSpecification, SpawnedProcess, ProcessState
from d4planner.rulekit.runtime import RuleKitRuntimeService

class Process:
    pid = 987654
    returncode = None
    def __init__(self, failure): self.failure = failure
    async def wait(self):
        if self.returncode is None: await asyncio.Event().wait()
        return self.returncode
    def kill(self):
        if self.failure == 'kill': raise OSError('kill failed')
        if self.failure != 'wait': self.returncode = -9

class Driver:
    async def request_graceful_stop(self, *args): await asyncio.Event().wait()
    async def terminate_owned_child(self, child):
        if child.process.failure == 'terminate': raise OSError('terminate failed')
    async def spawn(self, *args, **kwargs): raise AssertionError('must not spawn over owned child')

@pytest.mark.parametrize('failure', ['kill', 'wait'])
def test_cleanup_deadline_retains_handle_and_retry(failure):
    async def run():
        wrapper = RuleKitProcessWrapper(LaunchSpecification('node', (), Path.cwd(), graceful_stop_timeout=.02, kill_timeout=.02), Driver())
        child = SpawnedProcess(Process(failure), 'owned', 1)
        wrapper._child = child; wrapper.state = ProcessState.READY
        with pytest.raises(Exception): await asyncio.wait_for(wrapper.stop(), .3)
        assert wrapper.state == ProcessState.FAILED
        assert wrapper._child is child
        with pytest.raises(RuntimeError, match='cleanup pending'): await wrapper.start()
        child.process.returncode = 0
        await asyncio.wait_for(wrapper.stop(), .3)
        assert wrapper._child is None
    asyncio.run(run())

def test_terminate_error_still_attempts_kill_and_confirms_exit():
    async def run():
        wrapper = RuleKitProcessWrapper(LaunchSpecification('node', (), Path.cwd(), graceful_stop_timeout=.02, kill_timeout=.02), Driver())
        wrapper._child = SpawnedProcess(Process('terminate'), 'owned', 1); wrapper.state = ProcessState.READY
        await asyncio.wait_for(wrapper.stop(), .3)
        assert wrapper._child is None
    asyncio.run(run())

def test_runtime_post_ready_error_cleans_worker():
    async def run():
        class Client:
            async def list_providers(self): raise RuntimeError('post READY failure')
        class Wrapper:
            stopped = False
            async def start(self): return Client()
            async def stop(self): self.stopped = True
        wrapper = Wrapper(); runtime = RuleKitRuntimeService(wrapper)
        with pytest.raises(RuntimeError): await runtime.start()
        assert wrapper.stopped and runtime.client is None
    asyncio.run(run())


def test_startup_cleanup_failure_blocks_new_spawn_until_exit():
    async def run():
        class StartupDriver(Driver):
            spawns = 0
            async def spawn(self, spec, **identity):
                self.spawns += 1
                process = Process('wait')
                process.stdin = object()
                process.stdout = asyncio.StreamReader()
                process.stdout.feed_data(b'not-json\n')
                return SpawnedProcess(process, identity['instance_id'], identity['generation'])
        driver = StartupDriver()
        wrapper = RuleKitProcessWrapper(LaunchSpecification('node', (), Path.cwd(), kill_timeout=.02, graceful_stop_timeout=.02), driver)
        with pytest.raises(RuntimeError, match='cleanup pending'): await wrapper.start()
        child = wrapper._child
        assert child is not None and wrapper.state == ProcessState.FAILED
        with pytest.raises(RuntimeError, match='cleanup pending'): await wrapper.restart()
        assert driver.spawns == 1
        child.process.returncode = 0
        await wrapper.stop()
        assert wrapper._child is None
    asyncio.run(run())


def test_real_worker_post_ready_failure_reaps_owned_process(monkeypatch):
    from test_rulekit_worker import specification
    async def run():
        wrapper = RuleKitProcessWrapper(specification())
        client = await wrapper.start()
        child = wrapper._child
        async def broken(): raise RuntimeError('post READY provider failure')
        monkeypatch.setattr(client, 'list_providers', broken)
        runtime = RuleKitRuntimeService(wrapper)
        with pytest.raises(RuntimeError, match='post READY'): await runtime.start()
        assert runtime.client is None and wrapper._child is None
        assert child.process.returncode is not None
    asyncio.run(run())
