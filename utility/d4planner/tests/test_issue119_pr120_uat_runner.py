"""Validate PR120 one-shot PowerShell UAT wrapper before exposing it to A."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/acceptance/issue119-pr120-uat.ps1"


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell UAT gate")
def test_pr120_runner_powershell_ast_has_no_parse_errors():
    executable = shutil.which("pwsh")
    assert executable, "Windows CI must provide PowerShell 7"
    expression = (
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{str(SCRIPT).replace(chr(39), chr(39)+chr(39))}',"
        "[ref]$tokens,[ref]$errors) | Out-Null; "
        "if($errors.Count) { $errors | Out-String | Write-Host; exit 1 }"
    )
    result = subprocess.run([executable, "-NoProfile", "-Command", expression],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell UAT gate")
def test_pr120_runner_wrong_head_blocks_and_preserves_db(tmp_path):
    executable = shutil.which("pwsh")
    assert executable
    home = tmp_path / "pr120-isolated-home"
    state = home / "state"
    state.mkdir(parents=True)
    db = state / "character.db"
    db.write_bytes(b"sentinel-unchanged")  # not a real DB; HEAD must fail first
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    result = subprocess.run([
        executable, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(SCRIPT), "-ExpectedHead", "0" * 40,
        "-DevHomeDir", str(home), "-EvidenceRoot", str(evidence),
    ], capture_output=True, text=True, timeout=60)
    assert result.returncode == 2, result.stdout + result.stderr
    assert db.read_bytes() == b"sentinel-unchanged"
    archive = evidence / "StreamOps-PR120-UAT.zip"
    report = evidence / "StreamOps-PR120-UAT" / "report.json"
    assert archive.is_file()
    actual = json.loads(report.read_text(encoding="utf-8-sig"))
    assert actual["status"] == "BLOCKED"
    assert actual["cases"][0]["status"] == "BLOCKED"
