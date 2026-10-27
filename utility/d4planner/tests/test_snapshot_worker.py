"""Real Node-process management IPC with synthetic data/test trust only."""
import asyncio
import json
from pathlib import Path
import subprocess

import pytest

from d4planner.rulekit import LaunchSpecification,RuleKitProcessWrapper,RuleKitRuntimeService,RuleKitRemoteError
ROOT=Path(__file__).resolve().parents[3]
WORKER=ROOT/'utility/d4planner/rulekit-worker/worker.js'


def test_snapshot_management_switch_restart_and_old_session_invalidation(tmp_path):
    helper=ROOT/'utility/d4-rulekit/snapshot-management/tests/helpers.js'
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
            environment_allow_list={'D4_RULEKIT_COMPOSITION_MODULE':str(ROOT/'utility/d4planner/tests/fixtures/snapshot-test-composition.js'),'TEST_SNAPSHOT_CONFIG':str(tmp_path/'test-config.json')},
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
            switched=await runtime.snapshot_api('switchSnapshot',{'entryId':inputs['b']['entry']['entryId']})
            assert switched['afterRestart']['active']['snapshotId']=='SYNTHETIC-B' and wrapper.generation==3
            with pytest.raises(RuleKitRemoteError,match='previous worker'):await runtime.client.get_session(session)
            rolled=await runtime.snapshot_api('rollback');assert rolled['afterRestart']['active']['snapshotId']=='SYNTHETIC-A'
            assert wrapper.generation==4
            assert wrapper._restart_count==0
            with pytest.raises(ValueError):await runtime.client.call('getCapabilities') # still exactly eight Application methods
            assert runtime.client.pending_count==0
        finally:await runtime.stop()
        assert wrapper._child is None
    asyncio.run(scenario())
