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
from d4planner.runtime.controller_probe.runner import render, run_backends
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
    monkeypatch.setattr(relay, "probe_payload", lambda runtime, seconds: {
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
