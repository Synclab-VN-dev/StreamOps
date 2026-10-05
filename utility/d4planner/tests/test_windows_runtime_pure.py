import os\n\nimport pytest\nfrom datetime import datetime, timezone
import hashlib

from d4planner.runtime.model import ProcessInfo
from d4planner.runtime.store import RuntimePaths
from d4planner.runtime.windows import WindowsRuntime


def test_controller_checksum_validation_is_deterministic(tmp_path, monkeypatch):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    dll = paths.controller / "nvdaControllerClient64.dll"
    dll.write_bytes(b"controller-client")
    expected = hashlib.sha256(b"controller-client").hexdigest()
    monkeypatch.setenv("D4PLANNER_CONTROLLER_SHA256", expected)

    runtime = WindowsRuntime(paths)
    assert runtime.controller_ready() is True

    dll.write_bytes(b"tampered")
    assert runtime.controller_ready() is False


def test_process_started_before_path_update():
    process = ProcessInfo(
        "steam",
        10,
        session_id=1,
        started_at="2026-10-05T19:00:00+07:00",
    )
    assert WindowsRuntime.process_started_before(
        process,
        "2026-10-05T19:01:00+07:00",
    )
    assert not WindowsRuntime.process_started_before(
        process,
        "2026-10-05T18:59:00+07:00",
    )


def test_addon_runtime_sync_is_idempotent(tmp_path, monkeypatch):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    runtime = WindowsRuntime(paths)

    first = runtime.ensure_addon_runtime()
    second = runtime.ensure_addon_runtime()

    assert first is True
    assert second is False
    assert runtime.addon_installed() is True
    assert runtime.addon_version() == "0.2.0"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell runtime probe is Windows-only")
def test_windows_process_probe_script_is_valid(tmp_path):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    assert runtime._process(("d4planner-process-that-does-not-exist",)) is None
