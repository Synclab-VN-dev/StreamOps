from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from streamops.server.errors import ObsPluginError
from streamops.server.platform.windows.obs_plugin import WindowsObsMultiRtmpHost


def completed(payload, returncode=0):
    return SimpleNamespace(stdout=json.dumps(payload), stderr="must-not-leak", returncode=returncode)


def test_host_runs_only_fixed_script_and_action(tmp_path: Path):
    script = tmp_path / "manage.ps1"
    script.write_text("# fixed", encoding="utf-8")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return completed({
            "ok": True,
            "installation": "exact",
            "compatible": True,
            "loaded": True,
            "loaded_version": "0.7.4.0",
        })

    status = WindowsObsMultiRtmpHost(script=script, executable="pwsh.exe", runner=runner).status()
    assert status.loaded is True
    command = calls[0][0]
    assert command[-4:] == [str(script), "-Action", "Status", "-Confirm:$false"]
    assert not any("url" in value.casefold() or "command" in value.casefold() for value in command)


@pytest.mark.parametrize(
    ("lower_code", "action", "expected"),
    [
        ("artifact_hash_mismatch", "install", "plugin_install_failed"),
        ("module_not_loaded", "verify", "plugin_verify_failed"),
        ("rollback_conflict", "rollback", "plugin_state_conflict"),
    ],
)
def test_host_maps_structured_errors_without_leaking_output(tmp_path, lower_code, action, expected):
    script = tmp_path / "manage.ps1"
    script.write_text("# fixed", encoding="utf-8")

    def runner(*_args, **_kwargs):
        return completed({"ok": False, "error": {"code": lower_code, "secret": "stream-key"}}, 1)

    host = WindowsObsMultiRtmpHost(script=script, executable="pwsh.exe", runner=runner)
    with pytest.raises(ObsPluginError) as error:
        getattr(host, action)()
    assert error.value.code == expected
    assert "stream-key" not in str(error.value)


def test_permission_denied_is_typed_by_service_boundary(tmp_path):
    script = tmp_path / "manage.ps1"
    script.write_text("# fixed", encoding="utf-8")
    host = WindowsObsMultiRtmpHost(
        script=script,
        executable="pwsh.exe",
        runner=lambda *_a, **_k: completed({"ok": False, "error": {"code": "permission_denied"}}, 1),
    )
    with pytest.raises(PermissionError):
        host.install()
