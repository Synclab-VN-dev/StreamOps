"""Issue #87: CLI, status, SQLite logging and legacy compatibility."""
from __future__ import annotations

import json

from d4planner import cli
from d4planner.controller import load_profile
from d4planner.runtime.events.store import EventStore
from d4planner.runtime.input_marker import MarkerSample
from d4planner.runtime.store import RuntimePaths, atomic_write_json


def test_new_commands_parse_without_touching_steam_or_windows():
    parser = cli.build_parser()
    args = parser.parse_args(["start", "-d", "--controller-profile", "xbox16", "--block"])
    assert args.detach and args.controller_profile == "xbox16" and args.block
    assert parser.parse_args(["controller", "profiles"]).controller_command == "profiles"
    assert parser.parse_args(["controller", "validate", "xbox16"]).profile == "xbox16"
    args = parser.parse_args(["logs", "-f", "--input", "--raw", "--from-end"])
    assert args.input and args.follow and args.raw and args.from_end


def test_controller_profiles_validate_and_reject_unknown(monkeypatch, tmp_path, capsys):
    paths = RuntimePaths(tmp_path / "home")
    monkeypatch.setattr(cli, "_paths", lambda: paths)
    assert cli.main(["controller", "profiles"]) == 0
    assert "xbox16" in capsys.readouterr().out
    assert cli.main(["controller", "validate", "xbox16"]) == 0
    out = capsys.readouterr().out
    assert "digital=16" in out and "analogDisabled=2" in out
    assert cli.main(["controller", "validate", "unknown"]) == 4
    assert "unknown controller profile" in capsys.readouterr().err


def test_bad_profile_does_not_launch_supervisor(monkeypatch, tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    def cannot_launch(**kwargs):
        raise AssertionError("invalid profile must fail before launch")
    monkeypatch.setattr(cli, "_spawn_daemon", cannot_launch)
    assert cli.command_start(paths, speech=False, isolated=False,
                             detached=True, timeout=1,
                             controller_profile="invalid") == 4


def test_mode_and_profile_conflict_is_nonzero(monkeypatch, tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    monkeypatch.setattr(cli, "_state", lambda _paths: {
        "state": "RUNNING", "supervisorPid": 128,
        "extras": {"inputMarker":{"mode":"BLOCK", "layoutId":None}},
    })
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: True)
    assert cli.command_start(paths, speech=False, isolated=False,
                             detached=True, timeout=1, block_marker=True,
                             controller_profile="xbox16") == 4


def test_raw_input_logs_filter_but_speech_remains_in_sqlite(tmp_path, capsys, monkeypatch):
    # Synthetic E2E owns no real supervisor process; make process ownership
    # explicit rather than exercising the stale-runtime protection by accident.
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: int(pid) == 77777)
    paths = RuntimePaths(tmp_path / "home")
    store = EventStore.create(paths, silent=True, session_id="capture-87")
    store.emit("speech.raw", {"text": "900 Item Power", "process":"diablo iv"})
    profile = load_profile("xbox16")
    for button in profile.digital:
        for state in ("down", "up"):
            store.emit_batch([MarkerSample(
                timestamp="2026-10-11T18:00:00.000+07:00",
                key=button.key, virtual_key=button.virtual_key, state=state,
                process_id=500, window_title="Diablo IV", suppressed=True,
                capture_method="keyboardHook", control_id=button.control_id,
                layout_id=profile.layout_id, mapping_source="configuredLayout",
            ).as_draft()])
    atomic_write_json(paths.runtime_state, {
        "state":"RUNNING", "supervisorPid":77777, "sessionId":store.session.session_id,
        "sessionDir":str(store.session.directory), "captureActive":True,
        "extras":{"inputMarker":{
            "layoutId":profile.layout_id, "mode":"BLOCK", "state":"ACTIVE",
            "configuredDigitalCount":16, "analogDisabledCount":2,
            "backend":"keyboardHook", "droppedCount":0,
        }},
    })
    assert cli.command_logs(paths, follow=False, raw=True, input_only=True) == 0
    messages=[json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert len(messages)==32
    assert all(x["type"]=="input.marker.raw" for x in messages)
    assert {x["data"]["controlId"] for x in messages}=={b.control_id for b in profile.digital}
    assert [(x["data"]["state"]) for x in messages]==["down","up"]*16
    assert cli.command_logs(paths, follow=False, raw=False, input_only=True) == 0
    output=capsys.readouterr().out
    assert "A (F11) DOWN [BLOCKED]" in output
    assert "speech.raw" not in output
    assert cli.command_logs(paths, follow=False, raw=True) == 0
    all_events=[json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert len(all_events)==33
    assert all_events[0]["type"]=="speech.raw"
    assert len({x["eventSeq"] for x in all_events})==33
    # Read-only SQLite integrity check; input shares the same canonical stream.
    import sqlite3
    with sqlite3.connect(paths.events_db) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert cli.command_status(paths, raw_json=True) == 0
    raw_status = json.loads(capsys.readouterr().out)
    marker_status = raw_status["extras"]["inputMarker"]
    assert marker_status["layoutId"] == profile.layout_id
    assert marker_status["configuredDigitalCount"] == 16
    assert marker_status["analogDisabledCount"] == 2
    assert marker_status["mode"] == "BLOCK"
    assert marker_status["backend"] == "keyboardHook"
    assert cli.command_status(paths, raw_json=False) == 0
    assert profile.layout_id in capsys.readouterr().out
    assert cli.command_logs(paths, follow=False, raw=True,
                            input_only=True, component="equipment")==2
    store.close()


def test_legacy_input_marker_has_no_new_metadata():
    from d4planner.runtime.input_marker import MarkerSample
    data=MarkerSample("2026-10-11T00:00:00+07:00","f11",122,"down",33,"Diablo IV").as_draft().data
    assert "controlId" not in data
    assert "layoutId" not in data
    assert "mappingSource" not in data


def test_daemon_explicit_home_overrides_parent_environment_without_side_effects(
    monkeypatch, tmp_path,
):
    from d4planner import daemon
    seen = []
    monkeypatch.setenv("D4PLANNER_HOME", str(tmp_path / "default-production"))
    monkeypatch.setattr(
        daemon, "_acquire_singleton", lambda paths: seen.append(paths.root) or None
    )
    home = tmp_path / "pr95-isolated"
    assert daemon.main([
        "--home", str(home), "--controller-profile", "xbox16",
        "--block", "--isolated", "--uat-attach-only",
    ]) == 5  # deliberate singleton-denied; never starts NVDA/Steam.
    assert seen == [home]
    assert not (tmp_path / "default-production").exists()


def test_daemon_uat_attach_only_rejects_mutating_modes(tmp_path):
    from d4planner import daemon
    import pytest
    invalid = [
        ["--uat-attach-only"],
        ["--uat-attach-only","--isolated","--block","--controller-profile","xbox16"],
        ["--uat-attach-only","--home",str(tmp_path),"--block","--controller-profile","xbox16"],
        ["--uat-attach-only","--home",str(tmp_path),"--isolated","--controller-profile","xbox16"],
    ]
    for args in invalid:
        with pytest.raises(SystemExit) as failure:
            daemon.main(args)
        assert failure.value.code == 2
