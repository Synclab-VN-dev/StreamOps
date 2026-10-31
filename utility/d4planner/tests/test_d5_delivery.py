"""Packaging contract regressions; not a substitute for native installer UAT."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

def test_public_rulekit_runtime_and_python_worker_are_packaged():
    policy=json.loads((ROOT/'utility/d4planner/release1/public-content-policy.json').read_text())
    for module in ('bootstrap.js','managed-snapshot-composition.js','production-composition.js'):
        name='utility/d4-rulekit/application/src/runtime/'+module
        assert name in policy['sourceAllowlist']
        assert (ROOT/name).is_file()
    builder=(ROOT/'utility/d4planner/tools/build_release1_stage.py').read_text()
    assert 'backend/site-packages/d4planner/rulekit/worker.js' in builder
    assert 'utility/d4planner/rulekit-worker' not in builder

def test_launcher_passes_independent_data_directory_and_viewer_mode():
    source=(ROOT/'utility/d4planner/release1/native-launcher/src/main.rs').read_text()
    assert '.env("D4PLANNER_DATA_DIR", data.join("state"))' in source
    assert 'if viewer { command.env_remove("D4PLANNER_BOOTSTRAP_FILE"); }' in source
    assert 'Command::new(payload.join("app/d4planner-fe.exe"))' in source
    assert 'Command::new(payload.join("runtime/python/python.exe"))' not in source

def test_package_revision_and_migration_range():
    plan=json.loads((ROOT/'utility/d4planner/release1/package-plan.json').read_text())
    assert plan['contractRevision']=='d4planner-r1-contract/1.0.0-candidate.6'
    assert plan['hudSchemaCompatibility']=={'minimum':2,'maximum':3}
    assert not any(a['id']=='rulekit-worker' for a in plan['artifacts'])
