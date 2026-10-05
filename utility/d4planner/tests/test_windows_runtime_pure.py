import os

import pytest
from datetime import datetime, timezone
import hashlib
import zipfile

from d4planner.runtime.model import ProcessInfo
from d4planner.runtime.store import RuntimePaths
from d4planner.runtime.windows import WindowsRuntime


def fake_pe(machine: int, marker: bytes = b"controller-client") -> bytes:
    payload = bytearray(0xA0)
    payload[0:2] = b"MZ"
    payload[0x3C:0x40] = (0x80).to_bytes(4, "little")
    payload[0x80:0x84] = b"PE\x00\x00"
    payload[0x84:0x86] = int(machine).to_bytes(2, "little")
    payload[0x90:0x90 + len(marker)] = marker
    return bytes(payload)


def test_controller_checksum_validation_is_deterministic(tmp_path, monkeypatch):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    dll = paths.controller / "nvdaControllerClient64.dll"
    content = fake_pe(0x8664)
    dll.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()
    monkeypatch.setenv("D4PLANNER_CONTROLLER_SHA256", expected)

    runtime = WindowsRuntime(paths)
    assert runtime.controller_machine() == 0x8664
    assert runtime.controller_ready() is True

    dll.write_bytes(fake_pe(0x8664, b"tampered"))
    assert runtime.controller_ready() is False


def test_controller_rejects_wrong_arch_even_when_checksum_matches(tmp_path, monkeypatch):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    dll = paths.controller / "nvdaControllerClient64.dll"
    x86 = fake_pe(0x014C)
    dll.write_bytes(x86)
    monkeypatch.setenv("D4PLANNER_CONTROLLER_SHA256", hashlib.sha256(x86).hexdigest())

    runtime = WindowsRuntime(paths)
    assert runtime.controller_machine() == 0x014C
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


def test_extract_official_controller_archive_validates_x64_and_checksum(tmp_path, monkeypatch):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    runtime = WindowsRuntime(paths)

    content = fake_pe(0x8664, b"official")
    monkeypatch.setenv(
        "D4PLANNER_CONTROLLER_SHA256",
        hashlib.sha256(content).hexdigest(),
    )

    archive = tmp_path / "controller.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("x64/nvdaControllerClient.dll", content)

    extracted = runtime._extract_controller_archive(archive)

    assert extracted.is_file()
    assert runtime.controller_machine(extracted) == 0x8664
    assert runtime.controller_sha256(extracted) == hashlib.sha256(content).hexdigest().upper()
