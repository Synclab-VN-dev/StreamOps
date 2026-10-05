from datetime import datetime, timezone
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
