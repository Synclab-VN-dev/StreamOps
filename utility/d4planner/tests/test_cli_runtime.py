import json
from pathlib import Path

from d4planner import cli
from d4planner.runtime.store import EventStore, RuntimePaths, atomic_write_json


def test_cli_parser_exposes_expected_commands():
    parser = cli.build_parser()
    for args in (
        ["start", "-d"],
        ["status"],
        ["logs"],
        ["stop"],
        ["doctor"],
        ["path", "status"],
    ):
        parsed = parser.parse_args(args)
        assert parsed.command


def test_status_exit_codes_distinguish_blocked_and_restart_required(tmp_path, capsys):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()

    atomic_write_json(paths.runtime_state, {"state": "BLOCKED", "detail": "bad"})
    assert cli.command_status(paths, raw_json=False) == 2

    atomic_write_json(paths.runtime_state, {"state": "RESTART_REQUIRED", "detail": "restart"})
    assert cli.command_status(paths, raw_json=False) == 3


def test_logs_pretty_and_raw_use_same_unified_event_stream(tmp_path, capsys):
    paths = RuntimePaths(tmp_path / "home")
    store = EventStore.create(paths, silent=True, session_id="s")
    store.emit(
        "speech.raw",
        {
            "process": "diablo iv",
            "windowTitle": "Diablo IV",
            "text": "900 Item Power",
            "rawSpeech": ["900 Item Power"],
        },
    )
    atomic_write_json(
        paths.runtime_state,
        {
            "state": "RUNNING",
            "sessionDir": str(store.session.directory),
            "captureActive": True,
        },
    )

    assert cli.command_logs(paths, follow=False, raw=False) == 0
    pretty = capsys.readouterr().out
    assert "900 Item Power" in pretty

    assert cli.command_logs(paths, follow=False, raw=True) == 0
    raw = capsys.readouterr().out.strip()
    event = json.loads(raw)
    assert event["type"] == "speech.raw"
    assert event["data"]["text"] == "900 Item Power"


def test_start_detach_does_not_follow_logs(monkeypatch, tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    monkeypatch.setattr(cli, "_spawn_daemon", lambda **kwargs: 123)
    monkeypatch.setattr(
        cli,
        "_wait_start",
        lambda _paths, _pid, timeout: {"state": "RUNNING", "captureActive": True},
    )

    assert cli.command_start(
        paths,
        speech=False,
        isolated=False,
        detached=True,
        timeout=1,
    ) == 0


def test_supervisor_singleton_lock_rejects_duplicate(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    first = daemon._acquire_singleton(paths)
    assert first is not None
    try:
        assert daemon._acquire_singleton(paths) is None
    finally:
        first.unlink(missing_ok=True)


def test_stop_without_live_supervisor_disables_stale_capture(monkeypatch, tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    from d4planner.runtime.store import read_json

    atomic_write_json(
        paths.capture_state,
        {"enabled": True, "silent": True, "leaseUntilUnix": time.time() + 5},
    )
    monkeypatch.setattr(cli, "_pid_alive", lambda _pid: False)
    atomic_write_json(paths.runtime_state, {"state": "RUNNING", "supervisorPid": 999999})

    assert cli.command_stop(paths, timeout=0.1) == 0
    assert read_json(paths.capture_state)["enabled"] is False
