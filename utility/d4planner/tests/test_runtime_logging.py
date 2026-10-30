from __future__ import annotations
import asyncio, json, os, subprocess, time, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from d4planner.runtime_logging import Sink, Logger, LIMITS
ROOT=Path(__file__).resolve().parents[3]
NODE=ROOT/'utility/d4-rulekit/runtime-logging/src/logger.js'
CANARY='SECRET_CANARY_ws_token_age_private_raw_build'

def session(tmp_path):
    run=str(uuid.uuid4()); directory=tmp_path/'logs'/('20261030-000000_'+run); directory.mkdir(parents=True);(directory.parent/'.control').mkdir()
    for c in LIMITS:
        s=Sink(directory,run,c);s.path.write_bytes(s.encode(s.record('INFO','logger','SESSION_HEADER',{})))
    return directory,run

def records(path):return [json.loads(line) for line in path.read_text().splitlines()]

def test_python_parallel_bounded_queue_secret_canary_and_debug(tmp_path):
    directory,run=session(tmp_path);sink=Sink(directory,run,'BE',7,{'BE':{'capture':'DEBUG'}});logger=Logger(sink)
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda i:logger.emit('DEBUG','capture','DEBUG_PROBE',count=i,token=CANARY,exception={'secret':CANARY}),range(4000)))
    logger.emit('ERROR','capture','ERROR',message=CANARY);logger.close()
    text=sink.path.read_text();assert CANARY not in text
    rows=records(sink.path);assert any(r['event']=='DEBUG_PROBE' for r in rows)
    assert all(r['runId']==run and r['component']=='BE' for r in rows)
    assert sink.path.stat().st_size<=10_000_000
    assert any(r['event']=='LOG_DROPPED' for r in rows) or logger.dropped>0

def test_default_filter_and_invalid_event_dropped(tmp_path):
    directory,run=session(tmp_path);s=Sink(directory,run)
    s.emit('DEBUG','capture','DEBUG_PROBE',count=1);s.emit('INFO',CANARY,CANARY,secret=CANARY)
    s.emit('ERROR','capture','ERROR',count=3)
    rows=records(s.path);assert [r['event'] for r in rows]==['SESSION_HEADER','ERROR'];assert s.dropped==1

def test_python_actual_ten_mb_cap_compact_crash_repair(tmp_path):
    directory,run=session(tmp_path);s=Sink(directory,run)
    for i in range(45000):s.emit('INFO','capture','STATE_CHANGE',count=i)
    assert s.path.stat().st_size<=10_000_000
    rows=records(s.path);assert rows[0]['event']=='SESSION_HEADER';assert any(r['event']=='LOG_TRIMMED' for r in rows);assert rows[-1]['fields']['count']==44999
    with s.path.open('ab') as f:f.write(b'{incomplete')
    s2=Sink(directory,run,generation=2);s2.emit('INFO','lifecycle','RESTART')
    assert records(s.path)[-1]['generation']==2

def test_replace_failure_drops_and_keeps_original(tmp_path,monkeypatch):
    directory,run=session(tmp_path);s=Sink(directory,run);s.cap=2000
    for i in range(5):s.emit('INFO','capture','STATE_CHANGE',count=i)
    original=s.path.read_bytes()
    def fail(*args):raise PermissionError('simulated Windows file sharing violation')
    monkeypatch.setattr(os,'replace',fail)
    for _ in range(30):s.emit('INFO','capture','STATE_CHANGE',count=9)
    assert s.path.stat().st_size<=s.cap;assert s.dropped>0;assert s.path.read_bytes().startswith(original)
    assert s.temp.stat().st_size<=s.cap

def test_symlink_writer_fails_open_without_mutating_foreign(tmp_path):
    directory,run=session(tmp_path);s=Sink(directory,run);foreign=tmp_path/'private';foreign.write_text(CANARY);s.path.unlink();s.path.symlink_to(foreign)
    s.emit('ERROR','capture','ERROR');assert foreign.read_text()==CANARY;assert s.dropped==1

def test_node_real_thread_privacy_filter_and_fifteen_mb_quota(tmp_path):
    directory,run=session(tmp_path)
    script="""const {Sink}=require(process.argv[1]);const s=new Sink(process.argv[2],process.argv[3],4,{RULEKIT:{api:'DEBUG'}});for(let i=0;i<65000;i++)s.emit('DEBUG','api','DEBUG_PROBE',{count:i,token:process.argv[4],exception:process.argv[4]});s.emit('ERROR','api','ERROR');console.log(JSON.stringify({dropped:s.dropped,trimmed:s.trimmed}));"""
    p=subprocess.run(['node','-e',script,str(NODE),str(directory),run,CANARY],capture_output=True,text=True,timeout=40)
    assert p.returncode==0,p.stderr;assert json.loads(p.stdout)['trimmed']>0
    f=directory/'rulekit.log';assert f.stat().st_size<=15_000_000;assert CANARY not in f.read_text();assert records(f)[-1]['event']=='ERROR'

def test_real_worker_ipc_restart_reuses_run_and_new_generation(tmp_path):
    from d4planner.rulekit import LaunchSpecification,RuleKitProcessWrapper
    directory,run=session(tmp_path)
    spec=LaunchSpecification(executable='node',args=(str(ROOT/'utility/d4planner/rulekit-worker/worker.js'),),working_directory=ROOT,environment_allow_list={'D4_RULEKIT_COMPOSITION_MODULE':str(ROOT/'utility/d4planner/tests/fixtures/rulekit-test-composition.js'),'D4_LOG_DIR':str(directory),'D4_LOG_RUN_ID':run,'D4_LOG_POLICY':json.dumps({'RULEKIT':{'*':'DEBUG'}})},readiness_timeout=4,graceful_stop_timeout=3,kill_timeout=1)
    async def scenario():
        w=RuleKitProcessWrapper(spec);c=await w.start();assert await c.list_providers();await w.restart();await w.stop();assert w._child is None
    asyncio.run(scenario());rows=records(directory/'rulekit.log');assert {1,2}<={r['generation'] for r in rows};assert any(r['event']=='READY' for r in rows);assert all(r['runId']==run for r in rows);assert sorted(p.name for p in directory.iterdir())==['be.log','fe.log','rulekit.log']

def test_real_worker_startup_failure_is_sanitized_and_flushed(tmp_path):
    directory,run=session(tmp_path)
    composition=tmp_path/'bad.cjs';composition.write_text("throw new Error('"+CANARY+"');")
    env={**os.environ,'D4_RULEKIT_COMPOSITION_MODULE':str(composition),'D4_RULEKIT_WORKER_INSTANCE_ID':str(uuid.uuid4()),'D4_RULEKIT_WORKER_GENERATION':'3','D4_LOG_DIR':str(directory),'D4_LOG_RUN_ID':run}
    p=subprocess.run(['node',str(ROOT/'utility/d4planner/rulekit-worker/worker.js')],input='',capture_output=True,text=True,env=env,timeout=8)
    assert p.returncode!=0
    text=(directory/'rulekit.log').read_text();assert CANARY not in text;assert any(r['event']=='ERROR' for r in records(directory/'rulekit.log'))

def test_schema_and_correlation_are_safe(tmp_path):
    import jsonschema
    directory,run=session(tmp_path);s=Sink(directory,run);correlation=str(uuid.uuid4())
    s.emit('ERROR','api','ERROR',correlationId=correlation,errorCode='TIMEOUT',password=CANARY)
    s.emit('ERROR','api','ERROR',errorCode={'credential':CANARY},correlationId=CANARY)
    schema=json.loads((ROOT/'utility/d4planner/contracts/runtime-logging/v1/log.schema.json').read_text())
    for row in records(s.path):jsonschema.Draft202012Validator(schema,format_checker=jsonschema.FormatChecker()).validate(row)
    assert records(s.path)[-2]['correlationId']!=correlation;assert CANARY not in s.path.read_text()


def test_component_tag_minimum_level_filter(tmp_path):
    directory,run=session(tmp_path);s=Sink(directory,run,policy={'BE':{'*':'ERROR','capture':'WARN'}})
    s.emit('INFO','capture','STATE_CHANGE');s.emit('WARN','capture','ERROR');s.emit('WARN','api','ERROR');s.emit('ERROR','api','ERROR')
    assert [(r['level'],r['tag']) for r in records(s.path)[1:]]==[('WARN','capture'),('ERROR','api')]
