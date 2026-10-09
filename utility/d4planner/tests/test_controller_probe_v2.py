"""#77: controller-probe-v2 pure-unit and fake end-to-end coverage."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import os

import pytest

from d4planner import cli
from d4planner.runtime.controller_probe import relay, worker
from d4planner.runtime.controller_probe.model import (
    BackendResult, ControlEdge, EdgeTracker, ProbeStatus,
)
from d4planner.runtime.controller_probe.runner import BackendUnavailable, render, run_backends
from d4planner.runtime.store import RuntimePaths, atomic_write_json


class FakeBackend:
    def __init__(self, name, status, *, devices=None, events=None, error=None):
        self.name = name
        self.status = status
        self.devices = devices or []
        self.events = events or []
        self.error = error
        self.calls = []

    def probe(self, seconds):
        self.calls.append(seconds)
        if self.error:
            raise self.error
        return BackendResult(
            self.name, self.status, devices=self.devices, events=self.events
        )


def edge(backend="RawInput", control="usage:0x09:0x01", state="DOWN"):
    return ControlEdge(backend, "device-path-1", control, state, "2026-10-09T12:00:00Z")


def test_cli_exposes_controller_probe_v2():
    args = cli.build_parser().parse_args(["controller-probe-v2", "--seconds", "30"])
    assert args.seconds == 30.0
    assert args.command == "controller-probe-v2"


@pytest.mark.parametrize("seconds", (0, -1, -0.1))
def test_invalid_seconds_rejected(tmp_path, capsys, seconds):
    assert cli.command_controller_probe_v2(RuntimePaths(tmp_path), seconds=seconds) == 2
    assert "between 0 and 300" in capsys.readouterr().err


def test_nonwindows_failure_is_clear(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "os", SimpleNamespace(name="posix"))
    assert cli.command_controller_probe_v2(RuntimePaths(tmp_path), seconds=1) == 2
    assert "requires Windows" in capsys.readouterr().err


def test_edge_tracker_emits_only_down_and_up():
    tracker = EdgeTracker("RawInput")
    assert tracker.update("d", set(), "t0") == []
    assert [(e.raw_control_id, e.state) for e in tracker.update("d", {"b2", "b1"}, "t1")] == [
        ("b1", "DOWN"), ("b2", "DOWN"),
    ]
    assert tracker.update("d", {"b2", "b1"}, "t2") == []
    assert [(e.raw_control_id, e.state) for e in tracker.update("d", {"b2"}, "t3")] == [
        ("b1", "UP")
    ]
    assert [(e.raw_control_id, e.state) for e in tracker.disconnect("d", "t4")] == [
        ("b2", "UP")
    ]


def test_identity_and_event_serialization_roundtrip():
    record = edge().as_dict()
    assert record == {
        "backend": "RawInput", "deviceId": "device-path-1",
        "rawControlId": "usage:0x09:0x01", "state": "DOWN",
        "timestamp": "2026-10-09T12:00:00Z",
    }
    with pytest.raises(ValueError, match="DOWN or UP"):
        ControlEdge("x", "d", "c", "hover", "now")


def test_first_usable_backend_stops_fallbacks():
    raw = FakeBackend("RawInput", ProbeStatus.EVENTS_OBSERVED, devices=[{"deviceId": "d"}], events=[edge()])
    wgi = FakeBackend("Windows.Gaming.Input", ProbeStatus.EVENTS_OBSERVED)
    results = run_backends(0.1, [raw, wgi])
    assert [r.backend for r in results] == ["RawInput"]
    assert raw.calls == [0.1]
    assert wgi.calls == []


def test_no_device_advances_to_fake_wgi():
    raw = FakeBackend("RawInput", ProbeStatus.NO_DEVICE)
    wgi = FakeBackend("Windows.Gaming.Input", ProbeStatus.EVENTS_OBSERVED, devices=[{"deviceId": "x"}], events=[edge("Windows.Gaming.Input")])
    assert [r.status for r in run_backends(1, [raw, wgi])] == [
        ProbeStatus.NO_DEVICE, ProbeStatus.EVENTS_OBSERVED
    ]


def test_unavailable_gameinput_does_not_stop_next_backend():
    raw = FakeBackend("RawInput", ProbeStatus.DEVICE_PRESENT_BUT_NO_EVENTS, devices=[{"deviceId": "d"}])
    wgi = FakeBackend("Windows.Gaming.Input", ProbeStatus.NO_DEVICE)
    gameinput = FakeBackend("GameInput", ProbeStatus.UNAVAILABLE)
    directinput = FakeBackend("DirectInput", ProbeStatus.NO_DEVICE)
    assert [r.status for r in run_backends(1, [raw, wgi, gameinput, directinput])] == [
        ProbeStatus.DEVICE_PRESENT_BUT_NO_EVENTS,
        ProbeStatus.NO_DEVICE, ProbeStatus.UNAVAILABLE, ProbeStatus.NO_DEVICE,
    ]


def test_backend_exception_is_isolated():
    broken = FakeBackend("RawInput", ProbeStatus.NO_DEVICE, error=OSError("native API failed"))
    fallback = FakeBackend("Windows.Gaming.Input", ProbeStatus.NO_DEVICE)
    got = run_backends(1, [broken, fallback])
    assert got[0].status == ProbeStatus.ERROR
    assert "native API failed" in got[0].detail
    assert fallback.calls == [1]


def test_mixed_results_render_exact_status_and_edges():
    results = [
        BackendResult("RawInput", ProbeStatus.DEVICE_PRESENT_BUT_NO_EVENTS, devices=[{"deviceId": "d"}]),
        BackendResult("Windows.Gaming.Input", ProbeStatus.UNAVAILABLE, runtime="UNAVAILABLE"),
        BackendResult("GameInput", ProbeStatus.EVENTS_OBSERVED, events=[edge("GameInput")], devices=[{"deviceId": "x"}]),
    ]
    output = render(results)
    assert "DEVICE_PRESENT BUT" not in output
    assert "DEVICE_PRESENT_BUT_NO_EVENTS" in output
    assert "runtime: UNAVAILABLE" in output
    assert "[GameInput] device=device-path-1 control=usage:0x09:0x01 DOWN" in output


def test_invalid_seconds_runner_rejected():
    with pytest.raises(ValueError, match="greater than zero"):
        run_backends(0, [])


class FakeRuntime:
    def __init__(self, paths, control=0, active=1):
        self.paths = paths
        self.control = control
        self.active = active
        self.prepared = []
        self.started = []
        self.worker_payload = None

    def require_windows(self):
        return None

    def current_process_session_id(self):
        return self.control

    def active_console_session_id(self):
        return self.active

    def _prepare_interactive_task(self, name, script):
        self.prepared.append((name, script, script.read_text(encoding="utf-8")))

    def run_task(self, name):
        self.started.append(name)
        if self.worker_payload is not None:
            request_file = self.prepared[-1][1].parent / "request.json"
            req = json.loads(request_file.read_text(encoding="utf-8"))
            out = self.prepared[-1][1].parent / "result.json"
            atomic_write_json(out, {"requestId": req["requestId"], **self.worker_payload})


def test_local_interactive_probe_does_not_schedule_task(monkeypatch, tmp_path):
    rt = FakeRuntime(RuntimePaths(tmp_path / "home"), control=1, active=1)
    monkeypatch.setattr(relay, "probe_payload", lambda runtime, seconds, mode="auto": {
        "probeProcessSession": 1, "activeConsoleSession": 1, "backends": [],
    })
    data = relay.run_or_relay(rt, 0.01)
    assert data["relayed"] is False
    assert rt.prepared == []


def test_ssh_relay_uses_interactive_task_and_validates_session(tmp_path):
    rt = FakeRuntime(RuntimePaths(tmp_path / "home"))
    rt.worker_payload = {
        "probeProcessSession": 1, "activeConsoleSession": 1, "backends": [],
    }
    data = relay.run_or_relay(rt, 0.01)
    assert data["controlSession"] == 0
    assert data["relayed"] is True
    assert rt.started == [relay.TASK_NAME]
    assert "d4planner.runtime.controller_probe.worker" in rt.prepared[0][2]
    assert "SendInput" not in rt.prepared[0][2]


def test_ssh_relay_rejects_wrong_session(tmp_path):
    rt = FakeRuntime(RuntimePaths(tmp_path / "home"))
    rt.worker_payload = {
        "probeProcessSession": 0, "activeConsoleSession": 1, "backends": [],
    }
    with pytest.raises(Exception, match="wrong-session"):
        relay.run_or_relay(rt, 0.01)


def test_worker_with_fake_rawinput_emits_diagnostics_without_db(monkeypatch, tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    rt = FakeRuntime(paths, control=1, active=1)
    fake = FakeBackend("RawInput", ProbeStatus.EVENTS_OBSERVED,
                       devices=[{"deviceId": "remote"}],
                       events=[edge(), edge(state="UP")])
    monkeypatch.setattr(worker, "RawInputBackend", lambda: fake)
    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    atomic_write_json(request, {"requestId": "id1", "seconds": 0.01})
    assert worker.execute_request(rt, request, result) == 0
    output = json.loads(result.read_text(encoding="utf-8"))
    assert [e["state"] for e in output["backends"][0]["events"]] == ["DOWN", "UP"]
    assert output["probeProcessSession"] == 1
    assert not (paths.state / "events.db").exists()
    assert not (paths.state / "character.db").exists()


def test_worker_wrong_session_is_error_not_success(tmp_path):
    rt = FakeRuntime(RuntimePaths(tmp_path / "home"), control=0, active=1)
    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    atomic_write_json(request, {"requestId": "id2", "seconds": 0.01})
    assert worker.execute_request(rt, request, result) == 2
    assert "wrong interactive session" in result.read_text(encoding="utf-8")


def test_backend_status_and_device_serialization():
    result = BackendResult("RawInput", ProbeStatus.NO_DEVICE)
    assert result.as_dict()["controller"] == "NO"
    assert result.as_dict()["status"] == "NO_DEVICE"
    assert BackendResult("GameInput", ProbeStatus.UNAVAILABLE, runtime="UNAVAILABLE").usable is False


def test_win64_rawinput_struct_layout_is_explicit():
    import ctypes
    from d4planner.runtime.controller_probe.rawinput import (
        HIDP_CAPS, RAWINPUTDEVICE, RAWINPUTHEADER, RID_DEVICE_INFO,
    )
    if os.name != "nt":
        pytest.skip("native Windows ABI layout only")
    assert ctypes.sizeof(ctypes.c_void_p) == 8, "Win32 64-bit expected on host A"
    assert ctypes.sizeof(RAWINPUTHEADER) == 24
    assert ctypes.sizeof(RAWINPUTDEVICE) == 16
    assert ctypes.sizeof(RID_DEVICE_INFO) == 24
    assert ctypes.sizeof(HIDP_CAPS) == 64


def test_missing_native_backend_is_reported_not_fatal(monkeypatch, tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    rt = FakeRuntime(paths, control=1, active=1)

    def missing_dll():
        raise BackendUnavailable("hid.dll could not be loaded")

    monkeypatch.setattr(worker, "RawInputBackend", missing_dll)
    request = tmp_path / "request.json"
    output = tmp_path / "result.json"
    atomic_write_json(request, {"requestId": "missing-hid", "seconds": 0.01, "mode": "hid"})
    assert worker.execute_request(rt, request, output) == 0
    results = json.loads(output.read_text(encoding="utf-8"))["backends"]
    assert results[0]["status"] == "UNAVAILABLE"
    assert results[0]["runtime"] == "UNAVAILABLE"
    assert "hid.dll could not be loaded" in results[0]["detail"]


def test_unavailable_status_always_reports_runtime_unavailable():
    result = BackendResult("GameInput", ProbeStatus.UNAVAILABLE)
    assert result.as_dict()["runtime"] == "UNAVAILABLE"


def test_cli_fake_end_to_end_renders_session_and_raw_identity(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(cli, "WindowsRuntime", lambda paths: SimpleNamespace(paths=paths))
    monkeypatch.setattr(relay, "run_or_relay", lambda runtime, seconds, mode="auto": {
        "controlSession": 0,
        "activeConsoleSession": 1,
        "probeProcessSession": 1,
        "relayed": True,
        "backends": [
            BackendResult(
                "RawInput", ProbeStatus.EVENTS_OBSERVED,
                devices=[{"deviceId": "C-controller"}],
                events=[edge(), edge(state="UP")],
            ).as_dict()
        ],
    })
    assert cli.command_controller_probe_v2(RuntimePaths(tmp_path), seconds=30) == 0
    output = capsys.readouterr().out
    assert "Control session: 0" in output
    assert "Probe process session: 1" in output
    assert "Relayed probe to interactive desktop." in output
    assert "control=usage:0x09:0x01 DOWN" in output
    assert "control=usage:0x09:0x01 UP" in output


def test_fake_wgi_to_cli_renderer_and_gameinput_unavailable():
    raw = FakeBackend("RawInput", ProbeStatus.NO_DEVICE)
    wgi = FakeBackend(
        "Windows.Gaming.Input", ProbeStatus.EVENTS_OBSERVED,
        devices=[{"deviceId": "gamepad-1"}], events=[edge("Windows.Gaming.Input")]
    )
    gameinput = FakeBackend("GameInput", ProbeStatus.UNAVAILABLE)
    got = run_backends(0.01, [raw, wgi, gameinput])
    output = render(got)
    assert "Backend Windows.Gaming.Input:" in output
    assert "control=usage:0x09:0x01 DOWN" in output
    assert gameinput.calls == []


def test_relay_timeout_is_bounded_and_does_not_claim_success(monkeypatch, tmp_path):
    rt = FakeRuntime(RuntimePaths(tmp_path / "home"))
    clock = iter([0.0, 30.0])
    monkeypatch.setattr(relay, "time", SimpleNamespace(
        monotonic=lambda: next(clock), sleep=lambda delay: None
    ))
    with pytest.raises(Exception, match="did not return"):
        relay.run_or_relay(rt, 0.01)
    assert rt.started == [relay.TASK_NAME]


def test_worker_rejects_invalid_duration(tmp_path):
    rt = FakeRuntime(RuntimePaths(tmp_path / "home"), control=1, active=1)
    request = tmp_path / "request.json"
    output = tmp_path / "result.json"
    atomic_write_json(request, {"requestId": "bad-time", "seconds": -10})
    assert worker.execute_request(rt, request, output) == 2
    assert "seconds must be between 0 and 300" in output.read_text(encoding="utf-8")


def test_cli_rejects_too_long_probe(tmp_path, capsys):
    assert cli.command_controller_probe_v2(RuntimePaths(tmp_path), seconds=301) == 2
    assert "between 0 and 300" in capsys.readouterr().err


@pytest.mark.parametrize("mode", (
    "auto", "all", "hid", "wgi", "gameinput", "directinput",
))
def test_mode_parser_accepts_modes(mode):
    parsed = cli.build_parser().parse_args([
        "controller-probe-v2", "--seconds", "0.1", "--mode", mode,
    ])
    assert parsed.mode == mode


def test_mode_parser_rejects_unknown_mode():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["controller-probe-v2", "--mode", "xinput"])


def test_mode_is_forwarded_to_interactive_task(tmp_path):
    rt = FakeRuntime(RuntimePaths(tmp_path / "home"))
    rt.worker_payload = {"probeProcessSession": 1, "activeConsoleSession": 1,
                         "mode": "wgi", "backends": []}
    result = relay.run_or_relay(rt, 0.01, "wgi")
    assert result["mode"] == "wgi"
    req = json.loads((rt.prepared[0][1].parent / "request.json").read_text())
    assert req["mode"] == "wgi"


def test_auto_stops_early_and_all_runs_every_backend(monkeypatch, tmp_path):
    rt = FakeRuntime(RuntimePaths(tmp_path / "home"), control=1, active=1)
    b1 = FakeBackend("RawInput", ProbeStatus.EVENTS_OBSERVED,
                     devices=[{"deviceId": "d"}], events=[edge()])
    b2 = FakeBackend("Windows.Gaming.Input", ProbeStatus.NO_DEVICE)
    b3 = FakeBackend("GameInput", ProbeStatus.UNAVAILABLE)
    b4 = FakeBackend("DirectInput", ProbeStatus.NO_DEVICE)
    monkeypatch.setattr(worker, "MODE_CLASSES", (
        ("hid", "RawInput", lambda: b1),
        ("wgi", "Windows.Gaming.Input", lambda: b2),
        ("gameinput", "GameInput", lambda: b3),
        ("directinput", "DirectInput", lambda: b4),
    ))
    auto = worker.probe_payload(rt, 0.01, "auto")
    assert [x["backend"] for x in auto["backends"]] == ["RawInput"]
    all_results = worker.probe_payload(rt, 0.01, "all")
    assert [x["backend"] for x in all_results["backends"]] == [
        "RawInput", "Windows.Gaming.Input", "GameInput", "DirectInput",
    ]
    assert b1.calls == [0.01, 0.01]
    assert b2.calls == [0.01]


@pytest.mark.parametrize("mode,expected", [
    ("hid", "RawInput"), ("wgi", "Windows.Gaming.Input"),
    ("gameinput", "GameInput"), ("directinput", "DirectInput"),
])
def test_single_mode_only_runs_selected_backend(monkeypatch, tmp_path, mode, expected):
    rt = FakeRuntime(RuntimePaths(tmp_path / "home"), control=1, active=1)
    fake = FakeBackend(expected, ProbeStatus.NO_DEVICE)
    monkeypatch.setattr(worker, "MODE_CLASSES", (
        (mode, expected, lambda: fake),
    ))
    got = worker.probe_payload(rt, 0.01, mode)
    assert len(got["backends"]) == 1
    assert got["backends"][0]["backend"] == expected


def test_wgi_gamepad_bitmask_is_exact():
    from d4planner.runtime.controller_probe.wgi import pressed_buttons
    assert pressed_buttons(0x04 | 0x400) == {
        "button:0x0004:A", "button:0x0400:LB",
    }


def test_gameinput_gamepad_bits_keep_raw_identity():
    from d4planner.runtime.controller_probe.gameinput import pressed_buttons
    assert pressed_buttons(0x81) == {
        "gameinput-bit:0x00000001", "gameinput-bit:0x00000080",
    }


def test_directinput_binary_button_and_hat_decoding():
    from d4planner.runtime.controller_probe.directinput import (
        _format_objects, decode_state,
    )
    result = _format_objects([
        ("button", 0x0c), ("button", 0x10c),
        ("pov", 0x110), ("button", 0x20c),
    ])
    assert result is not None
    fmt, objects, descriptors, size = result
    state = bytearray(size)
    state[0] = 0x80
    state[1] = 0
    state[2] = 0x80
    pov_offset = descriptors[3][1]
    state[pov_offset:pov_offset + 4] = (9000).to_bytes(4, "little")
    assert decode_state(state, descriptors) == {
        "button:0", "button:2", "pov:3:angle:9000",
    }


def test_native_com_guids_are_known_and_16_bytes():
    import ctypes
    from d4planner.runtime.controller_probe._native import GUID
    from d4planner.runtime.controller_probe.wgi import IGAMEPAD_STATICS
    from d4planner.runtime.controller_probe.gameinput import IID_IGAMEINPUT_V2
    assert ctypes.sizeof(GUID) == 16
    assert IGAMEPAD_STATICS.Data1 == 0x8bbce529
    assert IID_IGAMEINPUT_V2.Data1 == 0xbbaa66d2


def test_all_mode_preserves_unavailable_and_error_diagnostics():
    broken = FakeBackend("RawInput", ProbeStatus.ERROR, error=RuntimeError("read failure"))
    wgi = FakeBackend("Windows.Gaming.Input", ProbeStatus.NO_DEVICE)
    gameinput = FakeBackend("GameInput", ProbeStatus.UNAVAILABLE)
    dinput = FakeBackend("DirectInput", ProbeStatus.NO_DEVICE)
    statuses = [r.status for r in run_backends(
        .01, [broken, wgi, gameinput, dinput], stop_on_usable=False,
    )]
    assert statuses == [
        ProbeStatus.ERROR, ProbeStatus.NO_DEVICE,
        ProbeStatus.UNAVAILABLE, ProbeStatus.NO_DEVICE,
    ]


def test_native_struct_sizes_in_windows_64_bit():
    if os.name != "nt":
        pytest.skip("native Windows layouts")
    import ctypes
    from d4planner.runtime.controller_probe.wgi import GamepadReading
    from d4planner.runtime.controller_probe.gameinput import GameInputGamepadState
    from d4planner.runtime.controller_probe.directinput import DATA_FORMAT, OBJECT_FORMAT
    assert ctypes.sizeof(ctypes.c_void_p) == 8
    assert ctypes.sizeof(GamepadReading) == 64
    assert ctypes.sizeof(GameInputGamepadState) == 28
    assert ctypes.sizeof(DATA_FORMAT) == 32
    assert ctypes.sizeof(OBJECT_FORMAT) == 24


@pytest.mark.skipif(os.name != "nt", reason="requires Windows native APIs")
@pytest.mark.parametrize("module,class_name", [
    ("wgi", "WGIBackend"),
    ("gameinput", "GameInputBackend"),
    ("directinput", "DirectInputBackend"),
])
def test_native_backend_subprocess_smoke(module, class_name):
    """Native ABI crash must not terminate CI or the invoking test process.

    API absent/permission denied is acceptable; access violation is not.
    Does not require a physical controller or interactive game session.
    """
    import subprocess
    import sys
    script = (
        f"from d4planner.runtime.controller_probe.{module} import {class_name}\n"
        f"try:\n"
        f"    result = {class_name}().probe(0.05)\n"
        f"    print(result.status.value)\n"
        f"except Exception as exc:\n"
        f"    print(type(exc).__name__ + ': ' + str(exc))\n"
    )
    run = subprocess.run(
        [sys.executable, "-c", script], text=True, capture_output=True,
        timeout=20, check=False,
    )
    assert run.returncode == 0, (
        f"Native crash in {module}: returncode={run.returncode}, "
        f"stdout={run.stdout}, stderr={run.stderr}"
    )


def test_gameinput_v2_v1_interface_fallback(monkeypatch):
    import ctypes
    from d4planner.runtime.controller_probe import gameinput
    calls = []
    expected = ctypes.c_void_p(555)

    def fake_query(ptr, iid):
        calls.append(iid.Data1)
        if iid.Data1 == gameinput.IID_IGAMEINPUT_V2.Data1:
            raise OSError("QueryInterface: HRESULT 0x80004002")
        if iid.Data1 == gameinput.IID_IGAMEINPUT_V1.Data1:
            return expected
        raise AssertionError("unexpected requested COM interface")

    monkeypatch.setattr(gameinput, "_query_interface", fake_query)
    ptr, version = gameinput.negotiate_interface(ctypes.c_void_p(123))
    assert ptr is expected
    assert version == 1
    assert calls == [gameinput.IID_IGAMEINPUT_V2.Data1, gameinput.IID_IGAMEINPUT_V1.Data1]


def test_gameinput_v2_preferred_when_supported(monkeypatch):
    import ctypes
    from d4planner.runtime.controller_probe import gameinput
    calls = []
    monkeypatch.setattr(gameinput, "_query_interface", lambda ptr, iid: (
        calls.append(iid.Data1) or ctypes.c_void_p(999)
    ))
    _, version = gameinput.negotiate_interface(ctypes.c_void_p(123))
    assert version == 2
    assert calls == [gameinput.IID_IGAMEINPUT_V2.Data1]


def test_gameinput_unavailable_only_when_v1_and_v2_missing(monkeypatch):
    import ctypes
    from d4planner.runtime.controller_probe import gameinput
    from d4planner.runtime.controller_probe.runner import BackendUnavailable
    monkeypatch.setattr(gameinput, "_query_interface", lambda ptr, iid: (
        (_ for _ in ()).throw(OSError("E_NOINTERFACE"))
    ))
    with pytest.raises(BackendUnavailable, match="v1/v2"):
        gameinput.negotiate_interface(ctypes.c_void_p(123))
