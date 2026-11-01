"""E2E-01 gate coverage stays fail-closed across component-owned CI migration."""
from pathlib import Path
import ast
import yaml

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT/'streamops/ci.test.py'
AUDIT = ROOT/'scripts/ci/verify_game_required_gates.ps1'

def test_game_gate_ids_and_audit_are_mandatory():
    source=CONTRACT.read_text();audit=AUDIT.read_text()
    for field in ('GAME_G1','GAME_G2','GAME_G3','GAME_G4','GAME_G5','GAME_G6',
                  'GAME_WHEEL','GAME_RACE','GAME_REGRESSION','GAME_AUDIT_SELFTEST'):
        assert f"ctx.env['{field}']='success'" in source
        assert field in audit
    assert "finally:\n        try:\n            ctx.shell('./scripts/ci/verify_game_required_gates.ps1'" in source
    assert 'if primary_failure is None:raise' in source
    for name in ('Game G1','Game G2','Game G3','Game G4','Game G5','Game G6','Test installed wheel',
                 'Game observer/lifecycle race regression','Test StreamOps','FE-G1','FE-G2','FE-G3','FE-G4','FE-G6'):
        assert name in source
    workflow=yaml.safe_load((ROOT/'.github/workflows/main.yml').read_text())
    assert workflow['jobs']['result']['name']=='windows'
    assert workflow['jobs']['result']['if']=='always()'
    assert 'aggregate' in workflow['jobs']['result']['steps'][-1]['run']

def test_scope_catches_changes_to_critical_files():
    source=CONTRACT.read_text();audit=AUDIT.read_text()
    for pattern in ('scripts/e2e/issue85*','scripts/devices/a-windows/issue85*',
                    'scripts/ci/*game*','pyproject.toml','.github/workflows/main.yml'):
        assert pattern in source and pattern in audit
    # Automatic nearest-folder ownership covers streamops/* without a registry.
    assert CONTRACT.parent.name=='streamops'
    assert 'if ($mustRun -and $gameScope -ne' in audit
    assert "if ($entry.Value -ne 'success')" in audit

def test_master_ruleset_tool_is_safe_and_requires_explicit_apply():
    script=(ROOT/'scripts/ci/ensure_game_required_ruleset.ps1').read_text()
    for requirement in ('24454446','required_status_checks',"RequiredContext = 'windows'",'[switch]$Apply',
                        'if (!$Apply)','name = $current.name','conditions = $current.conditions',
                        'bypass_actors = @($current.bypass_actors)','--method PUT'):
        assert requirement in script

def test_negative_guard_scenarios_are_wired_to_ci():
    source=CONTRACT.read_text()
    assert 'Game E2E-01 — fail-closed negative tests' in source
    assert "'skipped'" in source and "'false'" in source
    assert "ctx.env['GAME_AUDIT_SELFTEST']='success'" in source
    assert 'GuardNegativeSelfTest' in AUDIT.read_text()
