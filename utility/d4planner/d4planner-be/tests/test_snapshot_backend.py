"""BE forwarding over genuine Node IPC, synthetic snapshots, isolated DB."""
import asyncio,json,subprocess,shutil
from pathlib import Path
from d4planner.production import ProductionBackendRuntime
from d4planner.rulekit import LaunchSpecification,RuleKitProcessWrapper,RuleKitRuntimeService
from test_production_backend import _evidence
ROOT=Path(__file__).resolve().parents[4]


def test_backend_forwards_rulekit_health_without_owning_snapshot_compatibility(tmp_path):
    helper=ROOT/'utility/d4planner/d4planner-rulekit/snapshot-management/tests/helpers.js'
    script="""const fs=require('node:fs/promises');const path=require('node:path');const {createPackage,trust}=require(process.argv[1]);(async()=>{const root=process.argv[2],a=await createPackage(root),b=await createPackage(root,'SYNTHETIC-B'),t=trust([a.entry,b.entry]);await fs.writeFile(path.join(root,'test-config.json'),JSON.stringify({anchors:t.registry.anchors,dataRoot:path.join(root,'rulekit-data')}));await fs.writeFile(path.join(root,'inputs.json'),JSON.stringify({a,b,envelope:t.envelope}));})();"""
    subprocess.run(['node','-e',script,str(helper),str(tmp_path)],check=True,timeout=10)
    inputs=json.loads((tmp_path/'inputs.json').read_text())
    async def scenario():
        worker=RuleKitProcessWrapper(LaunchSpecification(executable='node',args=(str(ROOT/'utility/d4planner/d4planner-be/src/d4planner/rulekit/worker.js'),),working_directory=ROOT,
            environment_allow_list={'D4_RULEKIT_COMPOSITION_MODULE':str(ROOT/'utility/d4planner/d4planner-be/tests/fixtures/snapshot-test-composition.js'),'TEST_SNAPSHOT_CONFIG':str(tmp_path/'test-config.json'),'D4_RULEKIT_DATA_ROOT':str(tmp_path/'rulekit-data')},operation_timeout=3,readiness_timeout=3))
        targets=tmp_path/'targets';targets.mkdir();shutil.copy2(ROOT/'utility/d4planner/d4planner-be/contracts/release1/v1/fixtures/target.valid.synthetic.json',targets/'target.json')
        backend=ProductionBackendRuntime({'ownerInstanceId':'owner-synthetic','childInstanceId':'backend-synthetic','generation':9,'dataDir':str(tmp_path/'data'),'targetFolder':str(targets),'wsEndpoint':{'host':'127.0.0.1','port':0},'credential':'snapshot-test-credential-01234567890123'},rulekit=RuleKitRuntimeService(worker))
        try:
            ready=await backend.start();assert ready['health']['ruleKitWorker']=='UNAVAILABLE'
            listed=backend.targets.list();target=next(row for row in listed.entries if row.validation=='VALID')
            await backend.activate_target(target.target_id,target.content_sha256,listed.revision)
            scored=await backend.ingest(_evidence());assert scored['score']['value']==100.0
            assert scored['health']['ruleKit']=='UNAVAILABLE' and scored['health']['scoreFreshness']=='CURRENT'
            assert scored['backend']['generation']==9
            await backend.snapshot_management('importPackage',{'kind':'REGISTRY','envelope':inputs['envelope']})
            for name in ('a','b'):await backend.snapshot_management('importPackage',{'kind':'SNAPSHOT','packagePath':inputs[name]['directory']})
            await backend.snapshot_management('activate',{'entryId':inputs['a']['entry']['entryId']})
            latest=backend.store.latest_authoritative();assert latest['health']['ruleKit']=='READY'
            assert latest['score']==scored['score'] and latest['context']==scored['context']
            revision=latest['hudRevision'];await backend.snapshot_management('switchSnapshot',{'entryId':inputs['b']['entry']['entryId']})
            after=backend.store.latest_authoritative();assert after['hudRevision']==revision+2
            assert after['health']['ruleKit']=='READY' and after['score']==scored['score']
            assert backend.hub.latest_revision==after['hudRevision']
        finally:await backend.stop()
        assert worker._child is None
    asyncio.run(scenario())
