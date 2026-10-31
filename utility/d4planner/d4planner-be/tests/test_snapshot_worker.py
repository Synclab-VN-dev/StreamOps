"""Real Node-process management IPC with synthetic data/test trust only."""
import asyncio
import json
from pathlib import Path
import subprocess

import pytest

from d4planner.rulekit import LaunchSpecification,RuleKitProcessWrapper,RuleKitRuntimeService,RuleKitRemoteError
ROOT=Path(__file__).resolve().parents[4]
WORKER=ROOT/'utility/d4planner/d4planner-be/src/d4planner/rulekit/worker.js'


@pytest.mark.parametrize("fault", ["none", "before_health", "start_failure", "stop_failure", "after_health", "rollback_failure"])
def test_snapshot_management_switch_restart_and_old_session_invalidation(tmp_path, fault):
    helper=ROOT/'utility/d4planner/d4planner-rulekit/snapshot-management/tests/helpers.js'
    code="""
const fs=require('node:fs/promises');const path=require('node:path');
const {createPackage,trust}=require(process.argv[1]);
(async()=>{const root=process.argv[2];const a=await createPackage(root),b=await createPackage(root,'SYNTHETIC-B');const credentials=trust([a.entry,b.entry]);
await fs.writeFile(path.join(root,'test-config.json'),JSON.stringify({anchors:credentials.registry.anchors,dataRoot:path.join(root,'data')}));
await fs.writeFile(path.join(root,'inputs.json'),JSON.stringify({envelope:credentials.envelope,a,b}));})();
"""
    subprocess.run(['node','-e',code,str(helper),str(tmp_path)],check=True,timeout=10)
    inputs=json.loads((tmp_path/'inputs.json').read_text())
    async def scenario():
        wrapper=RuleKitProcessWrapper(LaunchSpecification(executable='node',args=(str(WORKER),),working_directory=ROOT,
            environment_allow_list={'D4_RULEKIT_COMPOSITION_MODULE':str(ROOT/'utility/d4planner/d4planner-be/tests/fixtures/snapshot-test-composition.js'),'TEST_SNAPSHOT_CONFIG':str(tmp_path/'test-config.json')},
            max_restarts=1,operation_timeout=2,readiness_timeout=3))
        runtime=RuleKitRuntimeService(wrapper);runtime.client=await wrapper.start()
        try:
            caps=await runtime.snapshot_api('getCapabilities');assert caps['calculationAvailability']=='UNAVAILABLE'
            await runtime.snapshot_api('importPackage',{'kind':'REGISTRY','envelope':inputs['envelope']})
            for entry in ('a','b'):await runtime.snapshot_api('importPackage',{'kind':'SNAPSHOT','packagePath':inputs[entry]['directory']})
            listed=await runtime.snapshot_api('listInstalled');assert len(listed)==2
            first=await runtime.snapshot_api('activate',{'entryId':inputs['a']['entry']['entryId']})
            assert first['afterRestart']['active']['snapshotId']=='SYNTHETIC-A'
            assert wrapper.generation==2
            session=await runtime.client.create_session({'contractVersion':'d4-rulekit-application/v1','providerId':'test.synthetic','providerVersion':'1.0.0','buildSchemaVersion':'synthetic-build/v1',
                'snapshotId':inputs['a']['entry']['snapshotId'],'snapshotManifestSha256':inputs['a']['entry']['snapshotManifestSha256'],
                'build':{'class':'Rogue','equipment':{},'skills':{},'paragon':{},'effects':{}}})
            result=await runtime.client.evaluate(session);assert result['metrics'][0]['rawValue']==0
            assert result['provenance']['snapshotId']=='SYNTHETIC-A'
            async def transition(method, request=None, *, inject=False):
                calls = 0
                async def notification(health):
                    nonlocal calls
                    calls += 1
                    if inject and ((fault in ('before_health', 'rollback_failure') and calls == 1) or (fault == 'after_health' and calls == 2)):
                        raise RuntimeError('injected observer failure')
                old_spec = wrapper.specification
                old_stop = wrapper.stop
                if inject and fault == "stop_failure":
                    async def broken_stop(*args): raise RuntimeError("injected stop failure")
                    wrapper.stop = broken_stop
                if inject and fault == 'start_failure':
                    from dataclasses import replace
                    wrapper.specification = replace(old_spec, args=('-e', 'process.exit(42)'))
                if inject:
                    with pytest.raises(Exception): await runtime.snapshot_api(method, request, on_health=notification)
                    assert runtime.client is None
                    selection_path = tmp_path/'data'/'selection.json'
                    intent = selection_path.read_bytes()
                    wrapper.specification = old_spec
                    wrapper.stop = old_stop
                    result = await runtime.snapshot_api(method, request)
                    assert selection_path.read_bytes() == intent  # no second rollback/selection
                    return result
                return await runtime.snapshot_api(method, request)
            switched=await transition('switchSnapshot',{'entryId':inputs['b']['entry']['entryId']}, inject=fault not in ('none','rollback_failure'))
            assert switched['afterRestart']['active']['snapshotId']=='SYNTHETIC-B' and wrapper.generation>=3
            with pytest.raises(RuleKitRemoteError,match='previous worker'):await runtime.client.get_session(session)
            rolled=await transition('rollback', inject=fault=='rollback_failure');assert rolled['afterRestart']['active']['snapshotId']=='SYNTHETIC-A'
            assert wrapper.generation>=4
            assert wrapper._restart_count==0
            with pytest.raises(ValueError):await runtime.client.call('getCapabilities') # still exactly eight Application methods
            assert runtime.client.pending_count==0
        finally:await runtime.stop()
        assert wrapper._child is None
    asyncio.run(scenario())

@pytest.mark.parametrize('fault', ['before_health', 'reconfigure', 'null_active', 'wrong_binding', 'after_health'])
def test_transition_failure_is_not_success_and_exact_retry_recovers(fault):
    """Deterministic orchestration faults; real signed Node path is tested above."""
    async def scenario():
        class Client:
            async def snapshot_call(self, method, request=None):
                if method == 'switchSnapshot': return {'restartRequired': True, 'entryId': 'B', 'selectionRevision': 2}
                if method == 'getActive':
                    return {'active': None if fault == 'null_active' and not wrapper.recovered else {'entryId': 'WRONG' if fault == 'wrong_binding' and not wrapper.recovered else 'B', 'selectionRevision': 2}, 'workerGeneration': wrapper.generation, 'calculationAvailability': 'READY', 'restartRequired': False}
                if method == 'getCapabilities': return await self.snapshot_call('getActive')
                raise AssertionError(method)
        class Wrapper:
            generation = 1
            recovered = False
            stopped = False
            async def reconfigure(self):
                if fault == 'reconfigure' and not self.recovered: raise RuntimeError('injected reconfigure')
                self.generation += 1; return Client()
            async def stop(self): self.stopped = True
        wrapper = Wrapper(); runtime = RuleKitRuntimeService(wrapper); runtime.client = Client()
        notifications = 0
        async def notify(health):
            nonlocal notifications
            notifications += 1
            if not wrapper.recovered and ((fault == 'before_health' and notifications == 1) or (fault == 'after_health' and notifications == 2)):
                raise RuntimeError('injected callback')
        with pytest.raises(RuntimeError):
            await runtime.snapshot_api('switchSnapshot', {'entryId': 'B'}, on_health=notify)
        assert runtime.client is None and wrapper.stopped
        wrapper.recovered = True
        result = await runtime.snapshot_api('switchSnapshot', {'entryId': 'B'}, on_health=notify)
        assert result['afterRestart']['active'] == {'entryId': 'B', 'selectionRevision': 2}
    asyncio.run(scenario())
