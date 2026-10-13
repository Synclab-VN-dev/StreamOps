"""Single-file StreamOps Node operator entrypoint: safety and source-contract gates."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[3]
ENTRY = ROOT / "scripts" / "devices" / "a-windows" / "streamops-node.ps1"


def test_one_operator_entrypoint_and_internal_task_dispatch():
    text = ENTRY.read_text(encoding="utf-8")
    assert 'ValidateSet("start","stop","status","__run")' in text
    assert '"-File", (ConvertTo-TaskArgument $launcher), "__run"' in text
    assert '$launcher = $PSCommandPath' in text
    for action in ("start", "stop", "status", "__run"):
        assert f'"{action}" {{' in text
    assert "if (-not $PSBoundParameters.ContainsKey(" in text
    assert 'Port $Port is already listening' in text
    assert 'ObsPluginCredentialFile' in text
    assert 'Protect-TokenDirectory -Directory $secretDir' in text
    assert 'ZeroFreeBSTR' in text
    assert 'Set-Clipboard -Value " "' in text
    assert "TaskName" in text and "DataDir" in text
    for removed in (
        "start-streamops-node.ps1",
        "run-streamops-node.ps1",
        "stop-streamops-node.ps1",
        "status-streamops-node.ps1",
        "protect-obs-plugin-token-dir.ps1",
        "prepare-streamops-node-deployment.ps1",
        "activate-streamops-node-deployment.ps1",
        "rollback-streamops-node-deployment.ps1",
    ):
        assert not (ENTRY.parent / removed).exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Scheduled Task API")
def test_operator_powershell_parse_and_idle_status_stop():
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    assert pwsh, "Windows CI requires PowerShell"
    script = str(ENTRY).replace("'", "''")
    parse = (
        "$t=$null;$e=$null;"
        f"[Management.Automation.Language.Parser]::ParseFile('{script}',[ref]$t,[ref]$e)|Out-Null;"
        "if($e.Count){$e|Format-List;exit 1}"
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", parse],
        text=True, capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr + result.stdout

    # No actual task, process or production runtime is started or stopped.
    task = "StreamOps-PR52-CI-" + uuid.uuid4().hex[:8]
    absent = ROOT / ".streamops" / "pr52" / ("ci-absent-" + uuid.uuid4().hex[:8])
    for action, expected in (("status", 1), ("stop", 0)):
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-NonInteractive", "-File", str(ENTRY),
             action, "-TaskName", task, "-DataDir", str(absent)],
            text=True, capture_output=True, timeout=20,
        )
        assert proc.returncode == expected, (
            f"{action}: stdout={proc.stdout} stderr={proc.stderr}"
        )


def test_no_staged_deployment_artifact_dependency():
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "streamops_node_bundle.py" not in workflow
    assert "streamops-node-deployment-" not in workflow
    release = (ROOT / ".github" / "workflows" / "obs-multi-rtmp-build.yml").read_text(encoding="utf-8")
    assert "obs_plugin_package.py" in release
