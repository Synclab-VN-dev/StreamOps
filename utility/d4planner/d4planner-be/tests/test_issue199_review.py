"""PR #203 F2/F3: packaged dependency and recovery without restarting capture."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from d4planner.runtime.managed_capture import ManagedCaptureRuntime

BE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BE/'tools'))
import public_package as public
LAYOUT = json.loads((BE/'tests/fixtures/equipment/verified_equipment_layouts.json').read_text(encoding='utf-8'))


def test_packaged_rulekit_layout_module_is_loadable(tmp_path):
    for name in public.policy()['sourceAllowlist']:
        dest = tmp_path/name.replace('utility/d4planner/d4planner-rulekit/', 'utility/d4-rulekit/', 1)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(public.ROOT/name, dest)
    module = tmp_path/'utility/d4-rulekit/providers/maxroll/tooling/planner/equipment-layout.js'
    assert module.is_file(), 'Setup omits the lazily required equipment-layout module'
    sources = public.ROOT/'utility/d4planner/d4planner-rulekit'
    env = {**os.environ, 'NODE_PATH': os.pathsep.join(str(sources/p/'node_modules') for p in ('browser-infra','providers/maxroll','snapshot-management'))}
    subprocess.run(['node','-e',"if(typeof require(process.argv[1]).getEquipmentLayouts !== 'function')process.exit(2)",str(module)], env=env, check=True, capture_output=True)


class Child:
    pid = 123
    returncode = None
    def __init__(self): self.stdin=self; self.frames=[]
    def write(self, value): self.frames.append(json.loads(value))
    async def drain(self): pass
    def close(self): self.returncode=0
    async def wait(self): return self.returncode


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate(): await asyncio.sleep(.005)


def test_slow_layout_does_not_delay_capture_and_reaches_same_child(tmp_path):
    async def scenario():
        gate=asyncio.Event(); child=Child(); calls=[]
        async def provider(): await gate.wait(); return LAYOUT
        async def spawn(*a,**kw): calls.append(kw); return child
        async def health(*a): pass
        runtime=ManagedCaptureRuntime(tmp_path,health,spawn=spawn,equipment_layout_provider=provider)
        try:
            await asyncio.wait_for(runtime.start(),.1)
            assert runtime.process is child and not child.frames
            gate.set(); await until(lambda: child.frames)
            assert child.frames[0]['layouts']==LAYOUT
            assert child.frames[0]['ownerToken']==runtime.owner_token
            assert len(calls)==1
        finally: await runtime.stop()
    asyncio.run(scenario())


def test_layout_transient_error_retries_in_same_capture_session(tmp_path):
    async def scenario():
        attempts=[]; child=Child(); calls=[]
        async def provider():
            attempts.append(1)
            if len(attempts)==1: raise RuntimeError('snapshot temporarily unavailable')
            return LAYOUT
        async def spawn(*a,**kw): calls.append(1); return child
        async def health(*a): pass
        runtime=ManagedCaptureRuntime(tmp_path,health,spawn=spawn,equipment_layout_provider=provider)
        runtime.layout_retry_initial=.01
        try:
            await runtime.start(); await until(lambda: child.frames)
            assert len(attempts)==2 and len(calls)==1
            assert child.frames[0]['layouts']==LAYOUT
        finally: await runtime.stop()
    asyncio.run(scenario())


def test_layout_retry_after_rpc_deadline_and_invalid_result(tmp_path, monkeypatch):
    import d4planner.runtime.managed_capture as managed
    monkeypatch.setattr(managed, 'EQUIPMENT_LAYOUT_TIMEOUT', .02)
    async def scenario():
        child=Child(); attempts=[]
        async def provider():
            attempts.append(1)
            if len(attempts)==1: await asyncio.sleep(1)
            if len(attempts)==2: return {'status':'READY'}
            return LAYOUT
        async def spawn(*a,**kw): return child
        async def health(*a): pass
        runtime=ManagedCaptureRuntime(tmp_path,health,spawn=spawn,equipment_layout_provider=provider)
        runtime.layout_retry_initial=.01
        try:
            await runtime.start(); await until(lambda: child.frames)
            assert len(attempts)==3 and len(child.frames)==1
            assert runtime.status()['equipmentLayout']['state']!='READY'
            # An ack for another layout cannot promote readiness.
            runtime._payload={'extras':{'equipmentLayout':{'state':'READY','digest':'foreign'}}}
            await asyncio.sleep(.06)
            assert runtime.status()['equipmentLayout']['state']!='READY'
            runtime._payload={'extras':{'equipmentLayout':{'state':'READY','digest':child.frames[0]['digest']}}}
            await until(lambda: runtime.status()['equipmentLayout']['state']=='READY')
        finally: await runtime.stop()
    asyncio.run(scenario())


def test_stop_discards_late_provider_result_and_restart_rotates_owner(tmp_path):
    async def scenario():
        started=asyncio.Event(); children=[]; attempts=[]
        async def provider():
            attempts.append(1)
            if len(attempts)==1:
                started.set()
                try: await asyncio.Event().wait()
                except asyncio.CancelledError: return LAYOUT
            return LAYOUT
        async def spawn(*a,**kw):
            child=Child(); children.append(child); return child
        async def health(*a): pass
        runtime=ManagedCaptureRuntime(tmp_path,health,spawn=spawn,equipment_layout_provider=provider)
        await runtime.start(); await started.wait(); owner=runtime.owner_token
        await runtime.command('restart')
        try:
            await until(lambda: children[1].frames)
            assert not children[0].frames
            assert children[1].frames[0]['ownerToken']!=owner
        finally: await runtime.stop()
    asyncio.run(scenario())


def test_owner_pipe_accepts_bounded_verified_frame_and_applies_on_supervisor_thread(tmp_path):
    from d4planner.runtime.equipment_layout_channel import LayoutInbox, encode_layout, MAX_FRAME
    from d4planner.runtime.supervisor import Supervisor
    from d4planner.runtime.store import RuntimePaths
    inbox=LayoutInbox('owner')
    paths=RuntimePaths(tmp_path)
    supervisor=Supervisor(paths=paths,runtime=object(),path_manager=None,equipment_layout_inbox=inbox)
    bad,_=encode_layout('foreign',LAYOUT)
    inbox.feed(bad)
    inbox.feed(b'x'*(MAX_FRAME+1)+b'\n')
    supervisor._apply_equipment_layout()
    assert supervisor.equipment_projector.equipment_layouts is None
    frame,digest=encode_layout('owner',LAYOUT)
    tampered=json.loads(frame); tampered['layouts']['provenance']['snapshotId']='tampered'
    inbox.feed(json.dumps(tampered).encode()+b'\n')
    assert inbox.take() is None
    for offset in range(0,len(frame),57): inbox.feed(frame[offset:offset+57])
    assert supervisor.equipment_projector.equipment_layouts is None
    supervisor._apply_equipment_layout()
    assert supervisor.equipment_projector.equipment_layouts==LAYOUT
    assert supervisor.status.extras['equipmentLayout']['digest']==digest


def test_layout_slower_than_previous_ten_second_cutoff_still_delivered(tmp_path):
    async def scenario():
        child=Child()
        async def provider(): await asyncio.sleep(10.1); return LAYOUT
        async def spawn(*a,**kw): return child
        async def health(*a): pass
        runtime=ManagedCaptureRuntime(tmp_path,health,spawn=spawn,equipment_layout_provider=provider)
        try:
            await asyncio.wait_for(runtime.start(),.1)
            async with asyncio.timeout(12):
                while not child.frames: await asyncio.sleep(.02)
            assert child.frames[0]['layouts']==LAYOUT
        finally: await runtime.stop()
    asyncio.run(scenario())
