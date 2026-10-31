import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


def _cli(*args: str):
    return subprocess.run([sys.executable, "-m", "d4_rulekit.cli", *map(str, args)],
                          capture_output=True, text=True, check=False)


def test_cli_schema_self_check():
    result = _cli("schema-check")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "PASS"
    assert data["actionVariants"] == 15


def test_cli_batch_pass_and_report(tmp_path):
    names = sorted((FIXTURES / "valid").glob("*.json"))
    report_path = tmp_path / "contract.json"
    result = _cli("validate", *names, "--report", report_path)
    assert result.returncode == 0, result.stdout + result.stderr
    body = json.loads(report_path.read_text(encoding="utf-8"))
    assert body["gate"] == "G1_SCHEMA_ONLY"
    assert body["status"] == "PASS"
    assert body["count"] == 4


def test_cli_invalid_and_blocked_codes():
    invalid = _cli("validate", FIXTURES / "invalid" / "unknown-op.json")
    assert invalid.returncode == 1
    assert json.loads(invalid.stdout)["status"] == "FAIL"
    blocked = _cli("validate", FIXTURES / "does-not-exist.json")
    assert blocked.returncode == 2
    assert json.loads(blocked.stdout)["status"] == "BLOCKED"
