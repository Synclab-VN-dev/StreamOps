"""Exercise the source-to-installed boundary, not a second runtime contract."""
import importlib.util
import json
from pathlib import Path

from d4planner.release1.target_repository import TargetValidator

ROOT = Path(__file__).resolve().parents[4]
BE = ROOT / 'utility/d4planner/d4planner-be'


def test_release_resources_and_reviewed_sources_resolve_after_relocation():
    plan = json.loads((BE / 'release1/package-plan.json').read_text())
    policy = json.loads((BE / 'release1/public-content-policy.json').read_text())
    for resource in plan['resources']:
        assert (ROOT / resource['source']).is_file(), resource
    for source in policy['sourceAllowlist']:
        assert (ROOT / source).is_file(), source
    artifacts = {row['id']: row['path'] for row in plan['artifacts']}
    assert artifacts['root-launcher'] == 'D4Planner.exe'
    assert artifacts['native-fe'] == 'app/d4planner-fe.exe'
    assert artifacts['rulekit-modules'] == 'utility/d4-rulekit'
    assert artifacts['d4planner-contracts'] == 'utility/d4planner/contracts'


def test_release_builder_uses_relocated_repository_root():
    spec = importlib.util.spec_from_file_location('layout_release_ci', BE / 'tools/release_ci.py')
    # release_ci imports the sibling release helpers.
    import sys
    sys.path.insert(0, str(BE / 'tools'))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.ROOT == ROOT
        assert module.PRODUCT_PLAN == BE / 'release1/package-plan.json'
    finally:
        sys.path.remove(str(BE / 'tools'))


def test_installed_schema_validation_matches_source_checkout(tmp_path):
    import shutil
    pairs = {
        BE / 'contracts/release1/v1/schemas/target.schema.json':
            'utility/d4planner/contracts/release1/v1/schemas/target.schema.json',
        BE.parent / 'd4planner-rulekit/providers/maxroll/d4-build-v1.schema.json':
            'utility/d4-rulekit/providers/maxroll/d4-build-v1.schema.json',
    }
    for source, relative in pairs.items():
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    fixture = json.loads((BE / 'contracts/release1/v1/fixtures/target.valid.synthetic.json').read_text())
    assert TargetValidator.from_contract_tree(ROOT).validate(fixture) == TargetValidator.from_contract_tree(tmp_path).validate(fixture)
