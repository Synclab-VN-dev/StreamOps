"""Real managed process + Node IPC + DB + notification; synthetic input only."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[4]

def test_managed_target_ipc_commits_before_notification_and_offline_read(tmp_path):
    chromium=os.environ.get('F2_TEST_CHROMIUM')
    if not chromium: pytest.skip('explicit isolated Chromium required for real bootstrap')
    spec=importlib.util.spec_from_file_location('d5_e2e',ROOT/'utility/d4planner/d4planner-be/tools/production_e2e.py')
    tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)
    install=tmp_path/'install';examples=install/'examples';examples.mkdir(parents=True)
    shutil.copyfile(ROOT/'utility/d4planner/d4planner-be/contracts/release1/v1/fixtures/target.valid.synthetic.json',examples/'target.synthetic.json')
    shutil.copyfile(ROOT/'utility/d4planner/d4planner-be/release1/equipment.recorded.synthetic.json',examples/'equipment.recorded.synthetic.json')
    data=tmp_path/'data'
    targets,evidence,digest=tool._prepare(install,data)
    bootstrap={'protocol':'d4planner-managed/v1','contractVersion':'d4planner-r1-contract/1.0.0-candidate.6',
        'ownerInstanceId':'d5-owner','childInstanceId':'d5-child','generation':1,
        'dataDir':str(data/'state'),'targetFolder':str(targets),'wsEndpoint':{'host':'127.0.0.1','port':0},'credential':'synthetic-d5-credential-0000000000000000'}
    descriptor=tmp_path/'bootstrap.json';descriptor.write_text(json.dumps(bootstrap));descriptor.chmod(0o600)
    env=dict(os.environ,PYTHONPATH=str(ROOT/'utility/d4planner/d4planner-be/src'),D4PLANNER_BOOTSTRAP_FILE=str(descriptor),
        D4PLANNER_REPOSITORY_ROOT=str(ROOT),D4PLANNER_EQUIPMENT_EVIDENCE_FILE=str(evidence),
        D4PLANNER_RULEKIT_EXECUTABLE=shutil.which('node'), D4PLANNER_RULEKIT_WORKING_DIR=str(tmp_path),
        D4_RULEKIT_CHROMIUM_EXECUTABLE=chromium)
    executable=sys.executable
    if os.name=='nt':
        executable=sys._base_executable
        env['PYTHONPATH']+=os.pathsep+str(Path(sys.prefix)/'Lib/site-packages')
    process=subprocess.Popen([executable,'-m','d4planner.managed_backend'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
    try:
        ready=json.loads(process.stdout.readline())
        assert ready['event']=='READY',ready
        database=data/'state/hud.sqlite3'
        result=asyncio.run(tool._socket_flow(ready['wsEndpoint'],bootstrap['credential'],'d5-child',1,targets,digest,process,'d5-owner',database))
        assert result['finalTargetId']=='synthetic-target-b'
        assert result['rollbackPrevented']
        process.stdin.write(json.dumps({'type':'shutdown',**{k:bootstrap[k] for k in ('ownerInstanceId','childInstanceId','generation')}})+'\n');process.stdin.flush()
        assert process.wait(timeout=10)==0
        with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            persisted=json.loads(db.execute('SELECT payload_json FROM hud_current').fetchone()[0])
            assert persisted['hudRevision']==result['resyncRevision']
            assert persisted['context']['binding']['targetId']=='synthetic-target-b'
    finally:
        if process.poll() is None:
            process.stdin.close()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
