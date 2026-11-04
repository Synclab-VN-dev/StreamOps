import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from d4planner.cli import build_parser

ROOT = Path(__file__).resolve().parents[1]


def test_storage_command_is_discoverable_and_defaults_to_dry_run(tmp_path):
    args = build_parser().parse_args(['storage','migrate','--source',str(tmp_path/'old'),
                                     '--target',str(tmp_path/'new'),'--report',str(tmp_path/'report.json')])
    assert args.action == 'dry-run'
    result = subprocess.run([sys.executable,'-m','d4planner.cli','storage','migrate','--help'],capture_output=True,text=True)
    assert result.returncode == 0
    for word in ('dry-run','apply','verify','rollback','--manifest'):
        assert word in result.stdout


def test_malformed_manifest_cannot_delete_external_files(tmp_path):
    source = tmp_path/'old'; source.mkdir()
    target = tmp_path/'new'; target.mkdir()
    victim = tmp_path/'keep'; victim.write_text('must survive')
    manifest = tmp_path/'malicious.json'
    manifest.write_text(json.dumps({'schema':'d4planner-storage-migration/v1','id':'a'*32,
        'source':str(source),'target':str(target),'files':[{'path':'../keep','sourcePath':'../keep'}],
        'published':['../keep']}))
    result = subprocess.run([sys.executable,'-m','d4planner.cli','storage','migrate','--action','rollback',
        '--manifest',str(manifest),'--report',str(tmp_path/'result.json')],capture_output=True,text=True)
    assert result.returncode == 4
    assert json.loads(result.stdout)['status'] == 'BLOCKED'
    assert victim.read_text() == 'must survive'
    assert not list(source.iterdir()) and not list(target.iterdir())


def test_migration_guide_and_fixture_matrix_are_shipped_in_source():
    guide = (ROOT/'docs/unified-data-root.md').read_text()
    for name in ('state/hud.sqlite3','state/character.db','state/events.db','D4PLANNER_DATA_DIR',
                 'D4_RULEKIT_DATA_ROOT','CI_NOT_CHECKED','--manifest','rollback'):
        assert name in guide
    matrix = json.loads((ROOT/'tests/fixtures/unified-storage-cases.json').read_text())
    assert {'registered-conflict','isolated','state-is-not-root'} <= {item['name'] for item in matrix}


def test_acceptance_runner_reports_subprocess_failure(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('storage_acceptance_test',ROOT/'tools/storage_acceptance.py')
    runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
    monkeypatch.setattr(runner.subprocess, 'check_output', lambda args, **kw: 'head\n' if 'rev-parse' in args else '')
    monkeypatch.setattr(runner.subprocess, 'run', lambda *args, **kw: subprocess.CompletedProcess(args,3))
    output = tmp_path/'evidence'
    assert runner.main(['--output',str(output),'--only','UDR-01']) == 1
    case = json.loads((output/'report.json').read_text())['cases'][0]
    assert case['status'] == 'FAIL' and case['subprocessExit'] == 3
