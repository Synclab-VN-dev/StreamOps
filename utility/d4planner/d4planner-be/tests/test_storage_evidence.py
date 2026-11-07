"""Prevent downstream failures or unverifiable reuse from changing row evidence."""
import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('storage_evidence', Path(__file__).parents[1]/'tools/storage_evidence.py')
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)

def test_setup_failure_does_not_relabel_successful_s9():
    rows = [{'id':'UDR-05'}, {'id':'UDR-08'}, {'id':'UDR-10'}]
    evidence.attach(rows, {'status':'FAIL', 'phases':{
        'report-issue':{'status':'PASS', 'subprocessExit':0},
        'setup':{'status':'FAIL', 'subprocessExit':1}}})
    assert [r['nativeStatus'] for r in rows] == ['PASS','FAIL','NOT_RUN']
    assert all(r['ticketGate'] == 'NOT_RUN' for r in rows)

def test_legacy_aggregate_is_not_row_evidence():
    rows = [{'id':'UDR-05'}]
    evidence.attach(rows, {'status':'PASS'})
    assert rows[0]['nativeStatus'] == 'NOT_RUN'

def test_reuse_requires_exact_head_and_unchanged_artifacts(tmp_path):
    log = tmp_path/'s9.log'; log.write_text('21 passed')
    report = {'source':{'sourceHead':'abc'}, 'phases':{'report-issue':{
        'status':'PASS','artifacts':{'s9.log':evidence.digest(log)}}}}
    (tmp_path/'report.json').write_text(json.dumps(report))
    assert evidence.load_verified(tmp_path,'abc') == report
    with pytest.raises(ValueError, match='HEAD'): evidence.load_verified(tmp_path,'other')
    log.write_text('changed')
    with pytest.raises(ValueError, match='evidence'): evidence.load_verified(tmp_path,'abc')

def test_reuse_rejects_unattested_pass(tmp_path):
    (tmp_path/'report.json').write_text(json.dumps({'head':'abc','phases':{'setup':{'status':'PASS'}}}))
    with pytest.raises(ValueError, match='hashes'): evidence.load_verified(tmp_path,'abc')


def test_reused_native_failure_is_not_hidden_by_local_pass(tmp_path, monkeypatch):
    import subprocess
    runner_spec = importlib.util.spec_from_file_location('storage_acceptance_reuse', Path(__file__).parents[1]/'tools/storage_acceptance.py')
    runner = importlib.util.module_from_spec(runner_spec); runner_spec.loader.exec_module(runner)
    monkeypatch.setattr(runner.subprocess, 'check_output', lambda args, **kw: 'head\n' if 'rev-parse' in args else '')
    monkeypatch.setattr(runner.subprocess, 'run', lambda *args, **kw: subprocess.CompletedProcess(args, 0))
    monkeypatch.setattr(runner, 'load_verified', lambda *args: {'status':'FAIL','phases':{'python':{'status':'FAIL'}}})
    assert runner.main(['--output',str(tmp_path/'out'),'--only','UDR-01','--native-evidence',str(tmp_path/'prior')]) == 1
    report = json.loads((tmp_path/'out/report.json').read_text())
    assert report['cases'][0]['status'] == 'PASS'
    assert report['cases'][0]['nativeStatus'] == 'FAIL'
