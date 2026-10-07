import json
import time
from pathlib import Path

from d4planner import cli, daemon
from d4planner.runtime.store import EventStore, RuntimePaths, atomic_write_json


def test_cli_parser_exposes_expected_commands():
    parser = cli.build_parser()
    for args in (
        ["start", "-d"],
        ["status"],
        ["logs"],
        ["stop"],
        ["stop", "--stop-nvda"],
        ["doctor"],
        ["nvda-action-probe", "status"],
        ["path", "status"],
        ["character", "equipment"],
        ["character", "equipment", "replay", "sample.jsonl", "--trace"],
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


def test_equipment_component_logs_pretty_and_raw(tmp_path, capsys):
    paths = RuntimePaths(tmp_path / "home")
    store = EventStore.create(paths, silent=True, session_id="semantic")
    diagnostics_path = store.session.directory / "equipment-projector.jsonl"
    record = {
        "emittedAt": "2026-10-07T12:00:00.000+00:00",
        "component": "equipment",
        "event": "observation.high",
        "sessionId": "semantic",
        "sourceSeq": 42,
        "sourceTimestamp": "2026-10-07T19:00:00.000+07:00",
        "slot": "amulet",
        "item": "TEST AMULET",
        "reason": "slot+equipped+anchor+terminal_unequip",
    }
    diagnostics_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    atomic_write_json(
        paths.runtime_state,
        {
            "state": "RUNNING",
            "sessionDir": str(store.session.directory),
            "captureActive": True,
        },
    )

    assert (
        cli.command_logs(
            paths,
            follow=False,
            raw=False,
            component="equipment",
        )
        == 0
    )
    pretty = capsys.readouterr().out
    assert "observation.high" in pretty
    assert "slot=amulet" in pretty
    assert "item=TEST AMULET" in pretty

    assert (
        cli.command_logs(
            paths,
            follow=False,
            raw=True,
            component="equipment",
        )
        == 0
    )
    raw = json.loads(capsys.readouterr().out)
    assert raw["event"] == "observation.high"
    assert raw["sourceSeq"] == 42


def test_equipment_replay_uses_isolated_db_and_prints_semantic_trace(tmp_path, capsys):
    path = tmp_path / "equipment.jsonl"
    texts = [
        "Head",
        "EQUIPPED",
        "CURRENT HELM",
        "Rare Helm",
        "850 Item Power",
        "Unequip",
        "Head",
    ]
    events = [
        {
            "eventSeq": seq,
            "type": "speech.raw",
            "timestamp": f"2026-10-07T19:00:{seq:02}+07:00",
            "sessionId": "replay",
            "data": {"text": text},
        }
        for seq, text in enumerate(texts, start=1)
    ]
    path.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )

    assert cli.command_character_equipment_replay(path, trace=True) == 0
    output = capsys.readouterr().out
    assert "observation.high" in output
    assert "empty.confirmed" in output
    assert "db.clear" in output
    assert "0 projector errors" in output
    assert "0 current equipment rows" in output


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


def test_start_summary_is_safe_for_windows_cp1252(capsys):
    cli._print_start_summary(
        {
            "state": "RUNNING",
            "nvda": {"pid": 1},
            "tolk": {"reader": "NVDA"},
            "steam": {"pid": 2},
            "game": {"pid": 3},
            "captureActive": True,
        }
    )

    output = capsys.readouterr().out
    output.encode("cp1252")
    assert "[OK] Runtime: RUNNING" in output


def test_console_stream_configuration_replaces_unencodable_characters(monkeypatch):
    configured = []

    class FakeStream:
        def reconfigure(self, **kwargs):
            configured.append(kwargs)

    monkeypatch.setattr(cli.sys, "stdout", FakeStream())
    monkeypatch.setattr(cli.sys, "stderr", FakeStream())

    cli._configure_console_streams()

    assert configured == [
        {"errors": "backslashreplace"},
        {"errors": "backslashreplace"},
    ]


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


def test_status_marks_stale_running_state_when_supervisor_is_dead(monkeypatch, tmp_path, capsys):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    atomic_write_json(
        paths.runtime_state,
        {
            "state": "RUNNING",
            "supervisorPid": 424242,
            "captureActive": True,
        },
    )
    monkeypatch.setattr(cli, "_pid_alive", lambda _pid: False)

    assert cli.command_status(paths, raw_json=False) == 2
    captured = capsys.readouterr()
    assert "STALE" in captured.out
    assert "supervisor process is not running" in captured.err


def test_start_rejects_mode_change_without_stopping_existing_runtime(monkeypatch, tmp_path, capsys):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    atomic_write_json(
        paths.runtime_state,
        {
            "state": "RUNNING",
            "supervisorPid": 77,
            "silent": True,
        },
    )
    monkeypatch.setattr(cli, "_pid_alive", lambda _pid: True)

    result = cli.command_start(
        paths,
        speech=True,
        isolated=False,
        detached=True,
        timeout=1,
    )

    assert result == 4
    assert "already running in silent mode" in capsys.readouterr().err


def test_doctor_reports_stale_supervisor_and_capture_lease(monkeypatch, tmp_path, capsys):
    from types import SimpleNamespace
    from d4planner.runtime.store import write_capture_config

    paths = RuntimePaths(tmp_path / "home")
    store = EventStore.create(paths, silent=True, session_id="doctor")
    atomic_write_json(
        paths.runtime_state,
        {
            "state": "RUNNING",
            "supervisorPid": 99,
            "sessionDir": str(store.session.directory),
            "captureActive": True,
            "lastEventAt": None,
        },
    )
    write_capture_config(paths, enabled=False)

    class FakeWindowsRuntime:
        def __init__(self, _paths):
            pass

        def doctor(self):
            return SimpleNamespace(
                checks={
                    "nvda": {"status": "PASS", "detail": "ok"},
                    "tolk": {"status": "PASS", "detail": "NVDA"},
                }
            )

        def steam_process(self):
            return None

        def game_process(self):
            return None

    monkeypatch.setattr(cli, "WindowsRuntime", FakeWindowsRuntime)
    monkeypatch.setattr(cli, "_pid_alive", lambda _pid: False)

    assert cli.command_doctor(paths, raw_json=False) == 1
    out = capsys.readouterr().out
    assert "supervisor" in out
    assert "capture_lease" in out
    assert "FAIL" in out


def test_doctor_reports_dead_blocked_supervisor_as_warning(monkeypatch, tmp_path, capsys):
    from types import SimpleNamespace

    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    atomic_write_json(
        paths.runtime_state,
        {
            "state": "BLOCKED",
            "supervisorPid": 8884,
            "captureActive": False,
            "detail": "Tolk cannot detect NVDA",
        },
    )

    class FakeWindowsRuntime:
        def __init__(self, _paths):
            pass

        def doctor(self):
            return SimpleNamespace(
                checks={
                    "nvda": {"status": "PASS", "detail": "ok"},
                    "tolk": {"status": "PASS", "detail": "NVDA"},
                }
            )

        def steam_process(self):
            return None

        def game_process(self):
            return None

    monkeypatch.setattr(cli, "WindowsRuntime", FakeWindowsRuntime)
    monkeypatch.setattr(cli, "_pid_alive", lambda _pid: False)

    assert cli.command_doctor(paths, raw_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["supervisor"]["status"] == "WARN"
    assert payload["supervisor"]["detail"]["state"] == "BLOCKED"
    assert payload["supervisor"]["detail"]["alive"] is False


def test_task_preparation_failure_persists_blocked_before_supervisor(
    monkeypatch, tmp_path, capsys
):
    from d4planner.runtime.store import read_json
    from d4planner.runtime.windows import RuntimeBlocked

    paths = RuntimePaths(tmp_path / "home")
    monkeypatch.setattr(
        cli,
        "_spawn_daemon",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeBlocked("priority migration denied")),
    )

    result = cli.command_start(
        paths,
        speech=True,
        isolated=False,
        detached=True,
        timeout=1,
    )

    assert result == 2
    state = read_json(paths.runtime_state)
    assert state["state"] == "BLOCKED"
    assert state["captureActive"] is False
    assert "priority migration denied" in state["lastError"]
    assert read_json(paths.capture_state)["enabled"] is False
    assert "Unable to start" in capsys.readouterr().err


def test_second_start_does_not_spawn_duplicate_supervisor(monkeypatch, tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    atomic_write_json(
        paths.runtime_state,
        {
            "state": "RUNNING",
            "supervisorPid": 123,
            "silent": True,
        },
    )
    monkeypatch.setattr(cli, "_pid_alive", lambda _pid: True)

    def forbidden_spawn(**_kwargs):
        raise AssertionError("second start must not spawn another daemon")

    monkeypatch.setattr(cli, "_spawn_daemon", forbidden_spawn)

    assert cli.command_start(
        paths,
        speech=False,
        isolated=False,
        detached=True,
        timeout=1,
    ) == 0


def test_ctrl_c_detaches_logs_without_requesting_stop(monkeypatch, tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    store = EventStore.create(paths, silent=True, session_id="detach")
    atomic_write_json(
        paths.runtime_state,
        {
            "state": "RUNNING",
            "supervisorPid": 123,
            "sessionDir": str(store.session.directory),
        },
    )

    def interrupted(*_args, **_kwargs):
        yield '{"type":"runtime.start","timestamp":"","data":{}}'
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_event_lines", interrupted)

    assert cli.command_logs(paths, follow=True, raw=False) == 0
    assert not paths.stop_request.exists()


def test_wait_start_ignores_stale_terminal_state_from_previous_daemon(monkeypatch, tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    old = {"state": "RUNNING", "supervisorPid": 999, "captureActive": True}
    new = {"state": "RUNNING", "supervisorPid": 123, "captureActive": True}
    states = iter([old, new])

    monkeypatch.setattr(cli, "_state", lambda _paths: next(states, new))
    monkeypatch.setattr(cli, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: None)

    result = cli._wait_start(paths, 123, timeout=1)
    assert result["supervisorPid"] == 123
    assert result["state"] == "RUNNING"


def test_wait_start_reports_blocked_when_new_daemon_exits_before_state(monkeypatch, tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    monkeypatch.setattr(
        cli,
        "_state",
        lambda _paths: {"state": "RUNNING", "supervisorPid": 999},
    )
    monkeypatch.setattr(cli, "_pid_alive", lambda _pid: False)

    result = cli._wait_start(paths, 123, timeout=1)
    assert result["state"] == "BLOCKED"
    assert result["supervisorPid"] == 123


def test_path_restore_refuses_while_runtime_active(monkeypatch, tmp_path, capsys):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    atomic_write_json(
        paths.runtime_state,
        {
            "state": "RUNNING",
            "supervisorPid": 42,
        },
    )
    monkeypatch.setattr(cli, "_pid_alive", lambda _pid: True)

    class FakeBackend:
        def get_user_path(self):
            return str(paths.controller)

        def set_user_path(self, _value):
            raise AssertionError("PATH must not change while runtime is active")

        def get_machine_path(self):
            return "MACHINE"

    monkeypatch.setattr(cli, "WindowsRegistryPathBackend", lambda: FakeBackend())

    assert cli.command_path(paths, "restore") == 4
    assert "Run 'd4planner stop' first" in capsys.readouterr().err


def test_broken_pipe_detaches_logs_without_stop_request(monkeypatch, tmp_path):
    import builtins

    paths = RuntimePaths(tmp_path / "home")
    store = EventStore.create(paths, silent=True, session_id="ssh-disconnect")
    store.emit("speech.raw", {"text": "900 Item Power"})
    atomic_write_json(
        paths.runtime_state,
        {
            "state": "RUNNING",
            "supervisorPid": 123,
            "sessionDir": str(store.session.directory),
        },
    )

    original_print = builtins.print

    def disconnected_print(*args, **kwargs):
        if kwargs.get("flush"):
            raise BrokenPipeError("ssh disconnected")
        return original_print(*args, **kwargs)

    monkeypatch.setattr(builtins, "print", disconnected_print)

    assert cli.command_logs(paths, follow=False, raw=False) == 0
    assert not paths.stop_request.exists()



def test_stop_parser_exposes_stop_nvda_flag():
    args = cli.build_parser().parse_args(["stop", "--stop-nvda"])
    assert args.stop_nvda is True


def test_default_stop_never_constructs_nvda_runtime(monkeypatch, tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    monkeypatch.setattr(cli, "_pid_alive", lambda _pid: False)
    monkeypatch.setattr(
        cli,
        "WindowsRuntime",
        lambda _paths: (_ for _ in ()).throw(AssertionError("NVDA runtime must be untouched")),
    )

    assert cli.command_stop(paths, timeout=0.1) == 0


def test_stop_nvda_runs_after_capture_disabled_when_planner_already_stopped(
    monkeypatch, tmp_path
):
    from d4planner.runtime.store import read_json

    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    monkeypatch.setattr(cli, "_pid_alive", lambda _pid: False)
    observed = []

    class FakeRuntime:
        def __init__(self, _paths):
            pass

        def stop_nvda(self, *, timeout):
            observed.append(read_json(paths.capture_state)["enabled"])
            return True

    monkeypatch.setattr(cli, "WindowsRuntime", FakeRuntime)

    assert cli.command_stop(paths, timeout=0.1, stop_nvda=True) == 0
    assert observed == [False]


def test_stop_nvda_already_absent_is_success(monkeypatch, tmp_path, capsys):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    monkeypatch.setattr(cli, "_pid_alive", lambda _pid: False)

    class FakeRuntime:
        def __init__(self, _paths):
            pass

        def stop_nvda(self, *, timeout):
            return False

    monkeypatch.setattr(cli, "WindowsRuntime", FakeRuntime)

    assert cli.command_stop(paths, timeout=0.1, stop_nvda=True) == 0
    assert "NVDA already stopped." in capsys.readouterr().out


def test_stop_nvda_failure_is_nonzero_and_capture_stays_disabled(
    monkeypatch, tmp_path, capsys
):
    from d4planner.runtime.store import read_json
    from d4planner.runtime.windows import RuntimeBlocked

    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    monkeypatch.setattr(cli, "_pid_alive", lambda _pid: False)

    class FakeRuntime:
        def __init__(self, _paths):
            pass

        def stop_nvda(self, *, timeout):
            raise RuntimeBlocked("NVDA did not exit; no force kill was attempted")

    monkeypatch.setattr(cli, "WindowsRuntime", FakeRuntime)

    assert cli.command_stop(paths, timeout=0.1, stop_nvda=True) == 1
    assert read_json(paths.capture_state)["enabled"] is False
    err = capsys.readouterr().err
    assert "no force kill" in err


def test_nvda_action_probe_cli_on_off_status(tmp_path, capsys):
    from d4planner.runtime.store import read_json

    paths = RuntimePaths(tmp_path / "home")

    assert cli.command_nvda_action_probe(paths, "status") == 0
    assert "DISABLED" in capsys.readouterr().out

    assert cli.command_nvda_action_probe(paths, "on") == 0
    out = capsys.readouterr().out
    assert "ENABLED" in out
    config_path = paths.state / "nvda-action-probe.json"
    log_path = paths.state / "nvda-action-probe.jsonl"
    config = read_json(config_path)
    assert config["enabled"] is True
    assert config["logPath"] == str(log_path)

    assert cli.command_nvda_action_probe(paths, "status") == 0
    status = capsys.readouterr().out
    assert "ENABLED" in status
    assert str(log_path) in status

    assert cli.command_nvda_action_probe(paths, "off") == 0
    capsys.readouterr()
    assert read_json(config_path)["enabled"] is False
