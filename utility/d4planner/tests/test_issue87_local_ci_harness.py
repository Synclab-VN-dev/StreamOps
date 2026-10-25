from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "acceptance"
    / "issue87-real-a-uat.ps1"
)


def script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_isolated_local_ci_installs_declared_dev_extra_and_verifies_source() -> None:
    script = script_text()
    install = script.index("'--editable','utility/d4planner[dev]'")
    post_install_source_check = script.index("Ensure-PR-Python", install)
    dependency_import = script.index("local-pr95-dependency-import", post_install_source_check)
    pip_check = script.index("local-pr95-pip-check", dependency_import)
    pytest = script.index("$unit=Run-Python 'local-pytest'", pip_check)
    assert install < post_install_source_check < dependency_import < pip_check < pytest
    assert "import jsonschema, referencing" in script
    assert "'-m','pip','check'" in script


def test_isolated_local_ci_reports_pytest_failure_and_restores_environment() -> None:
    script = script_text()
    run_python = script.index("function Run-Python")
    classification = script.index("function Get-LocalPytestClassification", run_python)
    failure_output = script.index("function Write-LocalPytestFailure", classification)
    invoke_failure_output = script.index("Write-LocalPytestFailure $unit", failure_output)
    fail_closed = script.index("if(!$good){throw 'Local CI failed; no supervisor started'}", invoke_failure_output)
    assert run_python < classification < failure_output < invoke_failure_output < fail_closed
    assert "$env:PYTHONPATH=$oldPythonPath" in script
    assert "$env:PATH=$oldPath" in script
    assert "Get-Content -LiteralPath $run.log" in script
    assert "classification='UNCLASSIFIED'" in script
