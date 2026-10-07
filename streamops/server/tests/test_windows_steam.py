from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import subprocess
import time

import pytest

from streamops.server.errors import (
    SteamLaunchError,
    SteamNotFoundError,
    SteamShutdownTimeoutError,
    WrongDesktopSessionError,
)
from streamops.server.platform.windows.session import DesktopSessionInfo
from streamops.server.platform.windows.steam import SteamProcess, WindowsSteamBackend


def _steam_executable(tmp_path: Path) -> Path:
    executable = tmp_path / "Steam" / "steam.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"test")
    return executable


def test_installation_prefers_registry_candidate(tmp_path, monkeypatch) -> None:
    first = _steam_executable(tmp_path)
    running = tmp_path / "Other" / "steam.exe"
    running.parent.mkdir()
    running.write_bytes(b"test")
    backend = WindowsSteamBackend()
    monkeypatch.setattr(backend, "_registry_candidates", lambda: iter([first]))

    result = backend.resolve_installation(
        processes=[SteamProcess(12, running, time.time(), 1)], required=True
    )

    assert result == first.resolve()


def test_installation_falls_back_to_running_process(tmp_path, monkeypatch) -> None:
    executable = _steam_executable(tmp_path)
    backend = WindowsSteamBackend()
    monkeypatch.setattr(backend, "_registry_candidates", lambda: iter(()))

    result = backend.resolve_installation(
        processes=[SteamProcess(12, executable, time.time(), 1)], required=True
    )

    assert result == executable.resolve()


def test_missing_installation_has_specific_error(monkeypatch) -> None:
    backend = WindowsSteamBackend()
    monkeypatch.setattr(backend, "_registry_candidates", lambda: iter(()))

    with pytest.raises(SteamNotFoundError, match="not found"):
        backend.resolve_installation(processes=[], required=True)


def test_status_reports_running_process(tmp_path, monkeypatch) -> None:
    executable = _steam_executable(tmp_path)
    started_at = time.time() - 120
    backend = WindowsSteamBackend()
    monkeypatch.setattr(
        backend,
        "_steam_processes",
        lambda: [SteamProcess(1234, executable, started_at, 2)],
    )
    monkeypatch.setattr(backend, "_registry_candidates", lambda: iter([executable]))
    monkeypatch.setattr(
        "streamops.server.platform.windows.steam.desktop_session_info",
        lambda: DesktopSessionInfo(2, 2),
    )

    status = backend.status()

    assert status.state == "running"
    assert status.pid == 1234
    assert 120 <= status.uptime_seconds <= 121
    assert status.session_id == 2
    assert status.interactive is True
    assert status.installation_detected is True


def test_status_reports_stopped_with_detected_installation(tmp_path, monkeypatch) -> None:
    executable = _steam_executable(tmp_path)
    backend = WindowsSteamBackend()
    monkeypatch.setattr(backend, "_steam_processes", lambda: [])
    monkeypatch.setattr(backend, "_registry_candidates", lambda: iter([executable]))

    status = backend.status()

    assert status.state == "stopped"
    assert status.pid is None
    assert status.interactive is False
    assert status.installation_detected is True


def test_restart_gracefully_stops_before_big_picture_launch(tmp_path, monkeypatch) -> None:
    executable = _steam_executable(tmp_path)
    old = SteamProcess(100, executable, time.time() - 60, 1)
    new = SteamProcess(200, executable, time.time(), 1)
    backend = WindowsSteamBackend()
    spawned: list[str] = []
    monkeypatch.setattr(
        "streamops.server.platform.windows.steam.desktop_session_info",
        lambda: DesktopSessionInfo(1, 1),
    )
    monkeypatch.setattr(backend, "_steam_processes", lambda: [old])
    monkeypatch.setattr(backend, "resolve_installation", lambda **_kwargs: executable)
    monkeypatch.setattr(
        backend,
        "_spawn",
        lambda _executable, argument, _error: (
            spawned.append(argument) or SimpleNamespace(pid=150 if argument == "-shutdown" else 200)
        ),
    )
    monkeypatch.setattr(backend, "_wait_until_stopped", lambda pids: pids == {100})
    monkeypatch.setattr(backend, "_wait_for_new_process", lambda *_args, **_kwargs: new)

    status = backend.restart()

    assert spawned == ["-shutdown", "-bigpicture"]
    assert status.pid == 200
    assert status.interactive is True


def test_restart_launches_directly_when_steam_is_stopped(tmp_path, monkeypatch) -> None:
    executable = _steam_executable(tmp_path)
    new = SteamProcess(200, executable, time.time(), 1)
    backend = WindowsSteamBackend()
    spawned: list[str] = []
    monkeypatch.setattr(
        "streamops.server.platform.windows.steam.desktop_session_info",
        lambda: DesktopSessionInfo(1, 1),
    )
    monkeypatch.setattr(backend, "_steam_processes", lambda: [])
    monkeypatch.setattr(backend, "resolve_installation", lambda **_kwargs: executable)
    monkeypatch.setattr(
        backend,
        "_spawn",
        lambda _executable, argument, _error: (
            spawned.append(argument) or SimpleNamespace(pid=200)
        ),
    )
    monkeypatch.setattr(backend, "_wait_for_new_process", lambda *_args, **_kwargs: new)

    status = backend.restart()

    assert spawned == ["-bigpicture"]
    assert status.pid == 200


def test_shutdown_timeout_never_launches_or_force_kills(tmp_path, monkeypatch) -> None:
    executable = _steam_executable(tmp_path)
    old = SteamProcess(100, executable, time.time() - 60, 1)
    backend = WindowsSteamBackend(shutdown_timeout=0.01)
    spawned: list[str] = []
    monkeypatch.setattr(
        "streamops.server.platform.windows.steam.desktop_session_info",
        lambda: DesktopSessionInfo(1, 1),
    )
    monkeypatch.setattr(backend, "_steam_processes", lambda: [old])
    monkeypatch.setattr(backend, "resolve_installation", lambda **_kwargs: executable)
    monkeypatch.setattr(
        backend,
        "_spawn",
        lambda _executable, argument, _error: (spawned.append(argument) or SimpleNamespace(pid=150)),
    )
    monkeypatch.setattr(backend, "_wait_until_stopped", lambda _pids: False)

    with pytest.raises(SteamShutdownTimeoutError, match="not force-killed"):
        backend.restart()

    assert spawned == ["-shutdown"]


def test_launch_must_be_verified(tmp_path, monkeypatch) -> None:
    executable = _steam_executable(tmp_path)
    backend = WindowsSteamBackend(launch_timeout=0.01)
    monkeypatch.setattr(
        "streamops.server.platform.windows.steam.desktop_session_info",
        lambda: DesktopSessionInfo(1, 1),
    )
    monkeypatch.setattr(backend, "_steam_processes", lambda: [])
    monkeypatch.setattr(backend, "resolve_installation", lambda **_kwargs: executable)
    monkeypatch.setattr(
        backend,
        "_spawn",
        lambda _executable, _argument, _error: SimpleNamespace(pid=200),
    )
    monkeypatch.setattr(backend, "_wait_for_new_process", lambda *_args, **_kwargs: None)

    with pytest.raises(SteamLaunchError, match="no process appeared"):
        backend.restart()


def test_wrong_session_fails_before_installation_or_process_mutation(monkeypatch) -> None:
    backend = WindowsSteamBackend()
    monkeypatch.setattr(
        "streamops.server.platform.windows.steam.desktop_session_info",
        lambda: DesktopSessionInfo(0, 1),
    )
    monkeypatch.setattr(
        backend,
        "_steam_processes",
        lambda: pytest.fail("processes must not be inspected before session validation"),
    )

    with pytest.raises(WrongDesktopSessionError, match="Steam restart"):
        backend.restart()


def test_spawn_requests_normal_priority_without_console(tmp_path, monkeypatch) -> None:
    executable = _steam_executable(tmp_path)
    backend = WindowsSteamBackend()
    observed = {}

    def fake_popen(command, **kwargs):
        observed["command"] = command
        observed.update(kwargs)
        return SimpleNamespace(pid=123)

    monkeypatch.setattr(
        "streamops.server.platform.windows.steam.subprocess.Popen",
        fake_popen,
    )
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "NORMAL_PRIORITY_CLASS", 0x00000020, raising=False)

    backend._spawn(executable, "-bigpicture", SteamLaunchError)

    assert observed["creationflags"] == 0x08000020
    assert observed["command"] == [str(executable), "-bigpicture"]
