"""E2E-01 ensures gates fail closed on skipped steps and relevant changes."""
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"
AUDIT = REPO_ROOT / "scripts" / "ci" / "verify_game_required_gates.ps1"

def test_game_gate_ids_and_audit_are_mandatory():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = data["jobs"]["windows"]
    steps = job["steps"]
    checks = {step.get("id"): step for step in steps if step.get("id")}
    for gate in ("game_g1","game_g2","game_g3","game_g4","game_g5","game_g6",
                 "game_wheel","game_race","server_regression"):
        assert gate in checks, gate
        assert checks[gate]["if"] == "steps.changes.outputs.server == 'true'"
        assert "pytest" in checks[gate]["run"] if gate != "game_race" else "pytest" in checks[gate]["run"]
    audit = next(step for step in steps if step.get("name") == "Game E2E-01 — required gate audit")
    assert audit["if"] == "always()"
    assert audit["run"] == "./scripts/ci/verify_game_required_gates.ps1"
    assert len({checks[g]["name"] for g in ("game_g1","game_g2","game_g3","game_g4","game_g5","game_g6")})==6
    for field in ("GAME_G1","GAME_G2","GAME_G3","GAME_G4","GAME_G5","GAME_G6",
                  "GAME_WHEEL","GAME_RACE","GAME_REGRESSION"):
        assert field in audit["env"],field
        assert field in AUDIT.read_text(encoding="utf-8"),field

def test_scope_catches_changes_to_critical_files():
    source = WORKFLOW.read_text(encoding="utf-8")
    audit = AUDIT.read_text(encoding="utf-8")
    for pattern in ("streamops/*","scripts/e2e/issue85*",
                    "scripts/devices/a-windows/issue85*",
                    "scripts/ci/*game*","pyproject.toml",".github/workflows/tests.yml"):
        assert pattern in source
        assert pattern in audit
    assert 'if ($mustRun -and $gameScope -ne' in audit
    assert "if ($entry.Value -ne 'success')" in audit

def test_master_ruleset_tool_is_safe_and_requires_explicit_apply():
    root = Path(__file__).resolve().parents[3]
    script = (root / "scripts" / "ci" / "ensure_game_required_ruleset.ps1").read_text(encoding="utf-8")
    assert "24454446" in script
    assert "required_status_checks" in script
    assert "RequiredContext = 'windows'" in script
    assert "[switch]$Apply" in script
    assert "if (!$Apply)" in script
    assert "name = $current.name" in script
    assert "conditions = $current.conditions" in script
    assert "bypass_actors = @($current.bypass_actors)" in script
    assert "--method PUT" in script
