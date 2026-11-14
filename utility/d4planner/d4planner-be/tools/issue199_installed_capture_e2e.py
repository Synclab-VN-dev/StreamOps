"""Explicit Windows VM #199 package acceptance, never run on a user's machine.

Requires an installed payload, an isolated owner-only DataRoot, an existing
verified UI snapshot plus its selection record, and copied recorded events.
Uses the real production BE, Node worker, managed daemon, lifetime pipe,
projector and Current/HUD publisher. Only OS/game ingress is substituted.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


async def wait_until(predicate, seconds=60):
    async with asyncio.timeout(seconds):
        while not predicate(): await asyncio.sleep(.05)


async def scenario(args):
    payload=args.payload.resolve(); root=args.data.resolve()
    assert root.is_dir() and not (root/'state').exists(), 'Use a fresh, owner-only isolated directory'
    sys.path.insert(0,str(payload/'backend/site-packages'))
    from d4planner.production import ProductionBackendRuntime
    import d4planner.runtime.managed_capture as managed
    original_spawn=asyncio.create_subprocess_exec
    children=[]
    child_fixture=args.child.resolve()
    async def recorded_spawn(executable,*argv,**kw):
        assert argv[:2]==('-m','d4planner.daemon')
        child=await original_spawn(str(payload/'runtime/python/python.exe'),str(child_fixture),*argv[2:],**kw)
        children.append(child)
        return child
    RealCapture=managed.ManagedCaptureRuntime
    class RecordedCapture(RealCapture):
        def __init__(self,*a,**kw):
            super().__init__(*a,spawn=recorded_spawn,**kw)
            self.layout_retry_initial=.5
    managed.ManagedCaptureRuntime=RecordedCapture
    for name in ('D4PLANNER_CAPTURE_PROBE_ONLY','D4PLANNER_EQUIPMENT_EVIDENCE_FILE','D4PLANNER_EQUIPMENT_REPOSITORY_DB','D4_RULEKIT_PROFILE_JSON','D4_RULEKIT_COMPOSITION_MODULE','D4PLANNER_CAPTURE_EQUIPMENT_LAYOUTS'):
        os.environ.pop(name,None)
    os.environ.update({
        'D4PLANNER_STORAGE_ISOLATED':'1','D4PLANNER_DATA_ROOT':str(root),'D4PLANNER_HOME':str(root),
        'D4PLANNER_DATA_DIR':str(root/'state'),'D4PLANNER_REPOSITORY_ROOT':str(payload),
        'D4PLANNER_RULEKIT_EXECUTABLE':str(payload/'runtime/node/node.exe'),
        'D4PLANNER_RULEKIT_WORKER':str(payload/'backend/site-packages/d4planner/rulekit/worker.js'),
        'D4PLANNER_RULEKIT_WORKING_DIR':str(payload/'backend/site-packages/d4planner/rulekit'),
        'D4_RULEKIT_INSTALLATION_ROOT':str(payload),'D4_RULEKIT_DATA_ROOT':str(root/'rulekit'),
        'D4_RULEKIT_PLANNER_STATE_ROOT':str(root/'planner-state'),
        'D4_RULEKIT_CHROMIUM_EXECUTABLE':str(payload/'runtime/chromium/chrome-win64/chrome.exe'),
        'D4_TEST_PACKAGE_PAYLOAD':str(payload),'D4_TEST_CAPTURE_EVENTS':str(args.events.resolve()),
    })
    module=payload/'utility/d4-rulekit/providers/maxroll/tooling/planner/equipment-layout.js'
    assert module.is_file(), 'F2: module missing from installed package'
    original_events=digest(args.events)
    selected=json.loads(args.selection.read_text(encoding='utf-8'))
    snapshot=args.snapshots.resolve()/selected['snapshotId']
    snapshot_hashes={str(f.relative_to(snapshot)):digest(f) for f in snapshot.rglob('*') if f.is_file()}
    (root/'targets').mkdir(); (root/'targets/canary.txt').write_text('preserve target')
    be=ProductionBackendRuntime({'childInstanceId':'issue199-package-e2e','generation':1,
        'dataDir':str(root/'state'),'targetFolder':str(root/'targets'),
        'wsEndpoint':{'host':'127.0.0.1','port':0},'credential':'vm-recorded-only-'+'x'*32})
    observations=[]; starting=time.monotonic()
    try:
        await be.start()
        capture=be.capture_runtime
        assert isinstance(capture,RealCapture) and capture.process
        await wait_until(lambda: capture.layout_state['state']=='RETRYING')
        pid=capture.process.pid; owner=capture.owner_token
        (root/'before.request').touch()
        await wait_until(lambda: (root/'before-done.json').exists())
        before=json.loads((root/'before-done.json').read_text())
        assert before['events']==1350 and before['layout'] is None
        assert not any(r['name']=='STAFF OF LAM ESEN' for r in before['rows'])
        # Test provisioning happens after raw capture proved it can run without layout.
        # Copy only selection metadata into this disposable profile, preserving the
        # existing snapshot/manifest/coverage/validation bytes and trusted hashes.
        selected['config']['snapshotRoot']=str(args.snapshots.resolve())
        state={'schemaVersion':'maxroll-capture-state/v1','revision':1,'activeUi':selected['snapshotId'],
               'packages':{selected['snapshotId']:selected},'runs':{selected['runId']:{'status':'COMPLETE'}}}
        encoded=json.dumps(state,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
        folder=root/'planner-state';folder.mkdir(exist_ok=True)
        (folder/'capture-state.json').write_text(json.dumps({'payload':state,'sha256':hashlib.sha256(encoded).hexdigest()}),encoding='utf-8')
        selection_hash=digest(folder/'capture-state.json')
        await wait_until(lambda: capture.status()['equipmentLayout']['state']=='READY')
        assert capture.process.pid==pid and capture.owner_token==owner and len(children)==1
        applied=capture.status()['equipmentLayout']
        # This independent call also proves the installed worker can load its module.
        layouts=await be.rulekit.client.get_equipment_layouts()
        assert applied['snapshotId']==layouts['provenance']['snapshotId']
        (root/'after.request').touch()
        while not (root/'after-done.json').exists():
            current=be.store.latest_authoritative()
            if any(i['name']=='STAFF OF LAM ESEN' for i in current['currentEquipment']['items']):
                observations.append({'hudRevision':current['hudRevision'],'beforeReplayCompleted':True})
            await asyncio.sleep(.05)
        await be.refresh_current_equipment()
        after=json.loads((root/'after-done.json').read_text())
        hud=be.store.latest_authoritative()
        assert after['events']==1350 and len(after['rows'])==9 and after['error'] is None
        staff=next(r for r in after['rows'] if r['name']=='STAFF OF LAM ESEN')
        assert staff['slotFamily']=='main_hand' and staff['itemPower']==850
        assert not any(r['slotFamily']=='off_hand' for r in after['rows'])
        assert len(hud['currentEquipment']['items'])==9 and hud['context']['target'] is None
        assert observations, 'HUD must show Staff before replay ends'
        assert digest(args.events)==original_events
        assert digest(folder/'capture-state.json')==selection_hash
        assert (root/'targets/canary.txt').read_text()=='preserve target'
        assert snapshot_hashes=={str(f.relative_to(snapshot)):digest(f) for f in snapshot.rglob('*') if f.is_file()}
        result={'status':'PASS','classification':'INSTALLED_PACKAGE_RECORDED_OS_INGRESS',
                'sourceHead':json.loads((payload/'release-manifest.json').read_text())['sourceHead'],
                'moduleSha256':digest(module),'sameCapturePid':pid,'spawnCount':len(children),
                'beforeRawEvents':before['events'],'beforeStaffResolved':False,
                'appliedLayout':applied,'afterRawEvents':after['events'],'afterItems':len(after['rows']),
                'hudLiveObservations':observations,'inputSnapshotTargetsPreserved':True,
                'seconds':round(time.monotonic()-starting,2)}
        args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
        (root/'hud-after.json').write_text(json.dumps(hud,indent=2),encoding='utf-8')
        print(json.dumps(result),flush=True)
    finally:
        await be.stop()
        assert all(c.returncode is not None for c in children)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ('payload','data','child','events','selection','snapshots','output'):
        parser.add_argument('--'+flag,type=Path,required=True)
    asyncio.run(scenario(parser.parse_args()))
