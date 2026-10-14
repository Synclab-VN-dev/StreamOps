"""Issue #75 E2E-10: BE auto-rollback failure in a disposable installer tree.

The file is intentionally required in the exact FE+BE combined CI. A FE-only
checkout has no BE #52 service implementation and must not counterfeit it.
"""
import asyncio
import os

import pytest

if os.environ.get("ISSUE75_EXACT_BE_COMBINED") != "1":
    pytest.skip("BE fault-injection test requires exact-HEAD FE+BE CI",
                allow_module_level=True)

from streamops.server.errors import ObsPluginError
from streamops.server.platform.windows.obs_plugin.installer import (
    PluginInstallerFailure, _file_records,
)
from streamops.server.services.obs_plugin import ObsPluginService
from streamops.server.tests.test_obs_plugin_adoption import (
    APPROVED_FILES, _Host, _Manager, _installer, _runtime,
)


def test_verify_failure_auto_rollback_failure_keeps_real_journal_pending(
    tmp_path, monkeypatch,
):
    """Fail *inside* the real rollback, after the journal records mutation.

    The real service must attempt rollback once, preserve the typed verify
    error and expose RECOVERY_REQUIRED. No filesystem overwrite is permitted.
    """
    legacy = {**APPROVED_FILES, "bin/64bit/obs-multi-rtmp.dll": b"legacy"}
    installer, config, _processes = _installer(tmp_path, legacy=legacy)
    installer.adopt()
    host, manager = _Host(installer), _Manager(_runtime("STOPPED"))
    service = ObsPluginService(manager, host, defer_restart=True)
    asyncio.run(service.install("obs-multi-rtmp"))
    assert installer.status().installation == "exact"
    approved_files = _file_records(installer.plugin_root)
    approved_config = config.read_bytes()
    manager.value = _runtime("READY")

    def verify_rejected():
        raise ObsPluginError("plugin_verify_failed", "Vendor check failed.", 409)

    host.verify = verify_rejected

    def interrupted_restore(_path):
        raise PluginInstallerFailure(
            "backup_invalid", "Injected failure after rollback intent."
        )

    monkeypatch.setattr(installer, "_clear_contents", interrupted_restore)
    with pytest.raises(ObsPluginError) as result:
        asyncio.run(service.verify("obs-multi-rtmp"))

    assert result.value.code == "plugin_verify_failed"
    assert host.calls.count("rollback") == 1, "one automatic rollback only"
    assert _file_records(installer.plugin_root) == approved_files
    assert config.read_bytes() == approved_config
    assert installer.status().installation == "recovery_required"
    pending = installer._pending_transactions()
    assert len(pending) == 1
    assert pending[0][1]["state"] == "rollback_pending"
    assert pending[0][1]["mutation_started"] is True
    assert service._operation_snapshot()["operation"] == "verify"
    assert service._operation_snapshot()["state"] == "FAILED"
    assert service._operation_snapshot()["error_code"] == "plugin_verify_failed"

    published = asyncio.run(service.status("obs-multi-rtmp"))
    assert published.state == "RECOVERY_REQUIRED"
    assert published.rollback["available"] is False
    # Fail-closed recovery never authorizes a fresh Install/Update.
    with pytest.raises(ObsPluginError) as blocked:
        asyncio.run(service.install("obs-multi-rtmp"))
    assert blocked.value.code == "plugin_recovery_required"
    assert host.calls.count("install") == 1
