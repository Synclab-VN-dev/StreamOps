import json
import threading
import time

from d4planner import cli
from d4planner.character.repository import EquipmentRepository
from d4planner.runtime.events.repository import EventLogReader
from d4planner.runtime.input_marker import MarkerSample
from d4planner.runtime.model import ProcessInfo, RuntimeState, TolkHealth
from d4planner.runtime.pathing import MemoryPathBackend, UserPathManager
from d4planner.runtime.store import RuntimePaths, read_json
from d4planner.runtime.supervisor import Supervisor


class E2ERuntime:
    def __init__(self, paths):
        self.paths = paths
        self._nvda = ProcessInfo("nvda_noUIAccess", 100, session_id=1)
        self._steam = ProcessInfo("steam", 200, session_id=1)
        self._game = ProcessInfo("Diablo IV", 300, session_id=1)
        self.launch_calls = 0
        self.stop_nvda_calls = 0

    def require_windows(self):
        return None

    def ensure_controller_runtime(self):
        self.paths.controller.mkdir(parents=True, exist_ok=True)
        path = self.paths.controller / "nvdaControllerClient64.dll"
        path.write_bytes(b"e2e-controller")
        return path

    def controller_ready(self):
        return True

    def addon_installed(self):
        return True

    def ensure_addon_runtime(self):
        return False

    def nvda_version(self):
        return "2026.2"

    def nvda_version_compatible(self, version=None):
        return (version or self.nvda_version()).startswith("2026.2")

    def active_console_session_id(self):
        return 1

    def ensure_nvda_running(self, *, timeout=15.0):
        return self._nvda

    def restart_nvda(self, *, timeout=15.0):
        self._nvda = ProcessInfo("nvda_noUIAccess", self._nvda.pid + 1, session_id=1)
        return self._nvda

    def nvda_process(self):
        return self._nvda

    def stop_nvda(self, *, timeout=15.0):
        self.stop_nvda_calls += 1
        if self._nvda is None:
            return False
        self._nvda = None
        return True

    def steam_process(self):
        return self._steam

    def game_process(self):
        return self._game

    def probe_tolk(self):
        return TolkHealth("NVDA", True, True)

    def process_started_before(self, process, timestamp):
        return False

    def launch_game(self):
        self.launch_calls += 1

    def wait_for_game(self, *, timeout=90.0):
        return self._game


def wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_e2e_supervisor_status_logs_and_stop(monkeypatch, tmp_path, capsys):
    paths = RuntimePaths(tmp_path / "home")
    runtime = E2ERuntime(paths)
    manager = UserPathManager(
        paths,
        MemoryPathBackend(user_path="", machine_path="MACHINE"),
    )
    supervisor = Supervisor(
        paths=paths,
        runtime=runtime,
        path_manager=manager,
        silent=True,
        poll_interval=0.02,
        health_poll_interval=0.10,
        game_start_timeout=0.01,
    )

    thread = threading.Thread(target=supervisor.run, daemon=True)
    thread.start()

    assert wait_until(
        lambda: (read_json(paths.runtime_state) or {}).get("state") == RuntimeState.RUNNING.value
    )
    status = read_json(paths.runtime_state)
    session_dir = status["sessionDir"]
    raw_path = supervisor.store.session.raw_speech_path
    raw_path.write_text(
        json.dumps(
            {
                "sessionId": supervisor.store.session.session_id,
                "sequence": 1,
                "timestamp": "2026-10-06T04:00:00+07:00",
                "process": "diablo iv",
                "windowTitle": "Diablo IV",
                "text": "900 Item Power",
                "rawSpeech": ["900 Item Power"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def speech_arrived():
        reader = EventLogReader(paths.events_db)
        try:
            rows = reader.read_after(supervisor.store.session.session_id, 0)
            return any(row.type == "speech.raw" for row in rows)
        finally:
            reader.close()

    assert wait_until(speech_arrived)

    # This is an in-process fake supervisor; use its real pytest process PID as
    # alive evidence so CLI status/stop exercise the same persisted contract.
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: int(pid) == supervisor.status.supervisor_pid)

    assert cli.command_status(paths, raw_json=False) == 0
    status_output = capsys.readouterr().out
    assert "RUNNING" in status_output
    assert "ACTIVE" in status_output

    assert cli.command_logs(paths, follow=False, raw=False) == 0
    assert "900 Item Power" in capsys.readouterr().out

    assert cli.command_logs(paths, follow=False, raw=True) == 0
    raw_lines = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    assert any(row["type"] == "speech.raw" for row in raw_lines)

    assert cli.command_stop(paths, timeout=2.0) == 0
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    final = read_json(paths.runtime_state)
    assert final["state"] == RuntimeState.STOPPED.value
    assert runtime.launch_calls == 0
    assert runtime._game.pid == 300
    assert runtime._steam.pid == 200

def test_e2e_existing_game_wrong_backend_requires_restart_without_launch(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = E2ERuntime(paths)
    runtime.probe_tolk = lambda: TolkHealth("SAPI", True, False)
    manager = UserPathManager(
        paths,
        MemoryPathBackend(user_path="", machine_path="MACHINE"),
    )
    supervisor = Supervisor(
        paths=paths,
        runtime=runtime,
        path_manager=manager,
        silent=True,
        poll_interval=0.02,
        health_poll_interval=0.10,
        game_start_timeout=0.01,
        tolk_ready_timeout=0.01,
        tolk_retry_interval=0.001,
    )

    state = supervisor.bootstrap()

    assert state == RuntimeState.RESTART_REQUIRED
    assert runtime.launch_calls == 0
    status = read_json(paths.runtime_state)
    assert status["state"] == RuntimeState.RESTART_REQUIRED.value
    assert status["game"]["pid"] == 300
    assert read_json(paths.capture_state)["enabled"] is False




def test_e2e_stop_with_nvda_preserves_d4_and_steam(monkeypatch, tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = E2ERuntime(paths)
    manager = UserPathManager(
        paths,
        MemoryPathBackend(user_path="", machine_path="MACHINE"),
    )
    supervisor = Supervisor(
        paths=paths,
        runtime=runtime,
        path_manager=manager,
        silent=True,
        poll_interval=0.02,
        health_poll_interval=0.10,
        game_start_timeout=0.01,
    )
    thread = threading.Thread(target=supervisor.run, daemon=True)
    thread.start()
    assert wait_until(
        lambda: (read_json(paths.runtime_state) or {}).get("state") == RuntimeState.RUNNING.value
    )

    monkeypatch.setattr(
        cli,
        "_pid_alive",
        lambda pid: int(pid) == supervisor.status.supervisor_pid and thread.is_alive(),
    )
    monkeypatch.setattr(cli, "WindowsRuntime", lambda _paths: runtime)
    d4_pid = runtime._game.pid
    steam_pid = runtime._steam.pid

    assert cli.command_stop(paths, timeout=2.0, stop_nvda=True) == 0
    thread.join(timeout=2.0)

    assert runtime._nvda is None
    assert runtime.stop_nvda_calls == 1
    assert runtime._game.pid == d4_pid
    assert runtime._steam.pid == steam_pid
    capture = read_json(paths.capture_state)
    assert capture["enabled"] is False


def test_e2e_default_stop_keeps_nvda_running(monkeypatch, tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = E2ERuntime(paths)
    monkeypatch.setattr(cli, "_pid_alive", lambda _pid: False)
    monkeypatch.setattr(cli, "WindowsRuntime", lambda _paths: runtime)

    assert cli.command_stop(paths, timeout=0.1) == 0
    assert runtime._nvda is not None
    assert runtime.stop_nvda_calls == 0


def test_e2e_repeated_stop_nvda_is_idempotent(monkeypatch, tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = E2ERuntime(paths)
    monkeypatch.setattr(cli, "_pid_alive", lambda _pid: False)
    monkeypatch.setattr(cli, "WindowsRuntime", lambda _paths: runtime)

    assert cli.command_stop(paths, timeout=0.1, stop_nvda=True) == 0
    assert cli.command_stop(paths, timeout=0.1, stop_nvda=True) == 0
    assert runtime._nvda is None
    assert runtime.stop_nvda_calls == 2


class FakeMarkerCapture:
    def __init__(self):
        self.target_pid = None
        self.started = False
        self.stopped = False
        self.samples = []

    def set_target_pid(self, pid):
        self.target_pid = pid

    def start(self):
        self.started = True

    def stop(self, *, timeout=1.0):
        self.stopped = True

    def consume_error(self):
        return None

    def drain(self):
        values = list(self.samples)
        self.samples.clear()
        return values

    def push(self, sample):
        self.samples.append(sample)


def test_e2e_sqlite_stream_orders_speech_and_marker_without_equipment_mutation(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = E2ERuntime(paths)
    manager = UserPathManager(
        paths,
        MemoryPathBackend(user_path="", machine_path="MACHINE"),
    )
    marker = FakeMarkerCapture()
    supervisor = Supervisor(
        paths=paths,
        runtime=runtime,
        path_manager=manager,
        silent=True,
        poll_interval=0.01,
        health_poll_interval=0.05,
        game_start_timeout=0.01,
        marker_capture=marker,
    )

    thread = threading.Thread(target=supervisor.run, daemon=True)
    thread.start()
    assert wait_until(
        lambda: (read_json(paths.runtime_state) or {}).get("state") == RuntimeState.RUNNING.value
    )
    assert marker.started is True
    assert marker.target_pid == 300

    session_id = supervisor.status.session_id
    raw = supervisor.store.session.raw_speech_path
    raw.write_text(
        json.dumps(
            {
                "sessionId": session_id,
                "sequence": 1,
                "timestamp": "2026-10-09T03:00:00.100+07:00",
                "process": "diablo iv",
                "processId": 300,
                "contextSource": "win32Foreground",
                "windowTitle": "Diablo IV",
                "text": "Equip",
                "rawSpeech": ["Equip"],
            }
        )
        + "\n"
        + json.dumps(
            {
                "sessionId": session_id,
                "sequence": 2,
                "timestamp": "2026-10-09T03:00:00.300+07:00",
                "process": "diablo iv",
                "processId": 300,
                "contextSource": "win32Foreground",
                "windowTitle": "Diablo IV",
                "text": "Hands",
                "rawSpeech": ["Hands"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    marker.push(
        MarkerSample(
            timestamp="2026-10-09T03:00:00.200+07:00",
            key="f11",
            virtual_key=122,
            state="DOWN",
            process_id=300,
            window_title="Diablo IV",
        )
    )
    marker.push(
        MarkerSample(
            timestamp="2026-10-09T03:00:00.210+07:00",
            key="f11",
            virtual_key=122,
            state="UP",
            process_id=300,
            window_title="Diablo IV",
        )
    )

    observed = []

    def stream_arrived():
        nonlocal observed
        reader = EventLogReader(paths.events_db)
        try:
            rows = reader.read_after(session_id, 0)
        finally:
            reader.close()
        observed = [
            row
            for row in rows
            if row.type in {"speech.raw", "input.marker.raw"}
        ]
        return len(observed) >= 4

    assert wait_until(stream_arrived)
    assert [row.type for row in observed[:4]] == [
        "speech.raw",
        "input.marker.raw",
        "input.marker.raw",
        "speech.raw",
    ]
    assert [row.event_seq for row in observed[:4]] == sorted(
        row.event_seq for row in observed[:4]
    )
    assert {row.session_id for row in observed[:4]} == {session_id}
    assert observed[1].data["key"] == "F11"
    assert observed[1].data["state"] == "down"
    assert observed[2].data["state"] == "up"

    # Raw marker evidence must never mutate materialized character state.
    assert EquipmentRepository(paths.character_db).list_equipment() == []

    paths.stop_request.write_text("stop\n", encoding="utf-8")
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert marker.stopped is True


def test_e2e_shutdown_drains_pending_marker_before_store_close(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = E2ERuntime(paths)
    manager = UserPathManager(
        paths,
        MemoryPathBackend(user_path="", machine_path="MACHINE"),
    )
    marker = FakeMarkerCapture()
    supervisor = Supervisor(
        paths=paths,
        runtime=runtime,
        path_manager=manager,
        silent=True,
        poll_interval=0.01,
        health_poll_interval=0.05,
        game_start_timeout=0.01,
        marker_capture=marker,
    )

    thread = threading.Thread(target=supervisor.run, daemon=True)
    thread.start()
    assert wait_until(
        lambda: (read_json(paths.runtime_state) or {}).get("state")
        == RuntimeState.RUNNING.value
    )
    session_id = supervisor.status.session_id
    marker.push(
        MarkerSample(
            timestamp="2026-10-09T03:40:00.200+07:00",
            key="f11",
            virtual_key=122,
            state="DOWN",
            process_id=300,
            window_title="Diablo IV",
        )
    )

    # Stop before the next normal poll; Supervisor.finally must drain the queue.
    paths.stop_request.write_text("stop\n", encoding="utf-8")
    thread.join(timeout=2.0)
    assert not thread.is_alive()

    reader = EventLogReader(paths.events_db)
    try:
        rows = reader.read_after(session_id, 0)
    finally:
        reader.close()
    markers = [row for row in rows if row.type == "input.marker.raw"]
    assert len(markers) == 1
    assert markers[0].data["key"] == "F11"
    assert markers[0].data["state"] == "down"



def test_e2e_sqlite_speech_ingress_still_materializes_equipment(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = E2ERuntime(paths)
    manager = UserPathManager(
        paths,
        MemoryPathBackend(user_path="", machine_path="MACHINE"),
    )
    supervisor = Supervisor(
        paths=paths,
        runtime=runtime,
        path_manager=manager,
        silent=True,
        poll_interval=0.01,
        health_poll_interval=0.05,
        game_start_timeout=0.01,
    )

    thread = threading.Thread(target=supervisor.run, daemon=True)
    thread.start()
    assert wait_until(
        lambda: (read_json(paths.runtime_state) or {}).get("state")
        == RuntimeState.RUNNING.value
    )

    session_id = supervisor.status.session_id
    raw_path = supervisor.store.session.raw_speech_path
    texts = [
        "Head",
        "EQUIPPED",
        "CURRENT HELM",
        "Rare Helm",
        "850 Item Power",
        "Unequip",
    ]
    raw_path.write_text(
        "".join(
            json.dumps(
                {
                    "sessionId": session_id,
                    "sequence": seq,
                    "timestamp": f"2026-10-09T04:00:00.{seq:03}+07:00",
                    "process": "diablo iv",
                    "processId": 300,
                    "contextSource": "win32Foreground",
                    "windowTitle": "Diablo IV",
                    "text": text,
                    "rawSpeech": [text],
                }
            )
            + "\n"
            for seq, text in enumerate(texts, start=1)
        ),
        encoding="utf-8",
    )

    def equipment_materialized():
        rows = EquipmentRepository(paths.character_db).list_equipment()
        return (
            len(rows) == 1
            and rows[0]["slotFamily"] == "helm"
            and rows[0]["name"] == "CURRENT HELM"
            and rows[0]["itemPower"] == 850
        )

    assert wait_until(equipment_materialized)

    reader = EventLogReader(paths.events_db)
    try:
        speech = [
            row
            for row in reader.read_after(session_id, 0, limit=1000)
            if row.type == "speech.raw"
        ]
    finally:
        reader.close()

    assert [row.data["text"] for row in speech] == texts
    assert [row.event_seq for row in speech] == sorted(row.event_seq for row in speech)
    assert {row.session_id for row in speech} == {session_id}

    paths.stop_request.write_text("stop\n", encoding="utf-8")
    thread.join(timeout=2.0)
    assert not thread.is_alive()



def test_e2e_block_hook_speech_and_suppressed_marker_share_sqlite_without_equipment_mutation(
    tmp_path,
):
    from d4planner.runtime.input_marker import HookInputMarkerCapture
    from d4planner.runtime.keyboard_hook import BoundedSamples, F11Sample, WM_KEYDOWN, WM_KEYUP

    paths = RuntimePaths(tmp_path / "home")
    runtime = E2ERuntime(paths)
    manager = UserPathManager(
        paths, MemoryPathBackend(user_path="", machine_path="MACHINE"),
    )

    class ControlledHook:
        def __init__(self, *, game_pid, block):
            assert block is True
            self.game_pid = game_pid
            self.samples = BoundedSamples()
            self.hook_errors = 0
            self.started = False
            self.stopped = False

        def __enter__(self):
            self.started = True
            return self

        def __exit__(self, *_):
            self.stopped = True

        def set_target_pid(self, pid):
            self.game_pid = int(pid or 0)

        def pump(self):
            return True

        def send(self, msg):
            self.samples.append(F11Sample(
                timestamp_ms=int(__import__("datetime").datetime.fromisoformat(
                    "2026-10-09T03:00:00.200+07:00"
                ).timestamp() * 1000),
                message=msg, state="down" if msg == WM_KEYDOWN else "up",
                flags=0x10, foreground_pid=self.game_pid,
                suppressed=True, target_match=True,
            ))

    fake = ControlledHook(game_pid=0, block=True)
    marker = HookInputMarkerCapture(
        poll_interval=0.001, backend_factory=lambda **kw: fake,
    )
    supervisor = Supervisor(
        paths=paths, runtime=runtime, path_manager=manager,
        silent=True, block_marker=True, marker_capture=marker,
        poll_interval=0.01, health_poll_interval=0.05,
        game_start_timeout=0.01,
    )

    thread = threading.Thread(target=supervisor.run, daemon=True)
    thread.start()
    assert wait_until(
        lambda: (read_json(paths.runtime_state) or {})
        .get("extras", {}).get("inputMarker", {}).get("state") == "ACTIVE"
    )
    assert fake.game_pid == 300
    session_id = supervisor.status.session_id
    raw = supervisor.store.session.raw_speech_path
    raw.write_text(json.dumps({
        "sessionId": session_id, "sequence": 1,
        "timestamp": "2026-10-09T03:00:00.100+07:00",
        "process": "diablo iv", "processId": 300,
        "windowTitle": "Diablo IV", "text": "900 Item Power",
        "rawSpeech": ["900 Item Power"],
    }) + "\n", encoding="utf-8")
    fake.send(WM_KEYDOWN)
    fake.send(WM_KEYUP)

    def arrived():
        reader = EventLogReader(paths.events_db)
        try:
            events = reader.read_after(session_id, 0)
            return len([x for x in events if x.type == "input.marker.raw"]) == 2
        finally:
            reader.close()

    assert wait_until(arrived)
    reader = EventLogReader(paths.events_db)
    try:
        records = [
            e for e in reader.read_after(session_id, 0)
            if e.type in {"input.marker.raw", "speech.raw"}
        ]
    finally:
        reader.close()
    assert [e.data["state"] for e in records if e.type == "input.marker.raw"] == ["down", "up"]
    assert all(
        e.data["suppressed"] is True and e.data["captureMethod"] == "keyboardHook"
        for e in records if e.type == "input.marker.raw"
    )
    assert any(e.type == "speech.raw" for e in records)
    assert [e.event_seq for e in records] == sorted(e.event_seq for e in records)
    assert {e.session_id for e in records} == {session_id}
    assert EquipmentRepository(paths.character_db).list_equipment() == []
    paths.stop_request.write_text("stop\n", encoding="utf-8")
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert fake.stopped
    assert (read_json(paths.runtime_state) or {})["state"] == "STOPPED"


def test_block_runtime_hook_start_failure_must_fail_closed(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = E2ERuntime(paths)
    manager = UserPathManager(
        paths, MemoryPathBackend(user_path="", machine_path="MACHINE"),
    )

    class NoHook:
        def set_target_pid(self, pid):
            pass

        def start(self):
            raise RuntimeError("Windows hook refused registration")

        def stop(self, **kwargs):
            pass

        def drain(self):
            return []

        def consume_error(self):
            return None

    supervisor = Supervisor(
        paths=paths, runtime=runtime, path_manager=manager,
        marker_capture=NoHook(), block_marker=True, silent=True,
        game_start_timeout=0.01,
    )
    assert supervisor.run() == 2
    saved = read_json(paths.runtime_state)
    assert saved["state"] == "STOPPED"
    assert saved["extras"]["inputMarker"]["state"] == "ERROR"
    assert "Windows hook refused registration" in (saved["lastError"] or "")


class RuntimeFailMarker:
    def __init__(self, *, error="synthetic hook runtime failure", dropped_count=0):
        self.error = error
        self.dropped_count = dropped_count
        self.overflowed = dropped_count > 0
        self.started = False
        self.stopped = False

    def set_target_pid(self, pid):
        self.target_pid = pid

    def start(self):
        self.started = True

    def stop(self, **kwargs):
        self.stopped = True

    def drain(self):
        return []

    def consume_error(self):
        error, self.error = self.error, None
        return error


def _block_supervisor(paths, runtime, marker):
    return Supervisor(
        paths=paths,
        runtime=runtime,
        path_manager=UserPathManager(
            paths, MemoryPathBackend(user_path="", machine_path="MACHINE")
        ),
        marker_capture=marker,
        block_marker=True,
        silent=True,
        poll_interval=0.001,
        health_poll_interval=0.01,
        game_start_timeout=0.001,
    )


def test_e2e_block_hook_failure_after_start_returns_nonzero_and_keeps_diagnostics(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    marker = RuntimeFailMarker()
    supervisor = _block_supervisor(paths, E2ERuntime(paths), marker)

    assert supervisor.run() == 2
    saved = read_json(paths.runtime_state)
    assert saved["state"] == "STOPPED"
    assert saved["extras"]["inputMarker"]["state"] == "ERROR"
    assert "synthetic hook runtime failure" in saved["lastError"]
    assert marker.started and marker.stopped

    reader = EventLogReader(paths.events_db)
    try:
        types = [row.type for row in reader.read_after(saved["sessionId"], 0)]
    finally:
        reader.close()
    assert "runtime.blocked" in types
    assert "runtime.stop" in types


def test_e2e_block_hook_failure_while_waiting_for_game_is_controlled(tmp_path):
    class WaitingRuntime(E2ERuntime):
        def __init__(self, paths):
            super().__init__(paths)
            self._game = None
            self._steam = None

        def wait_for_game(self, *, timeout=90.0):
            return None

    paths = RuntimePaths(tmp_path / "home")
    marker = RuntimeFailMarker(error="hook failed while game absent")
    supervisor = _block_supervisor(paths, WaitingRuntime(paths), marker)

    assert supervisor.run() == 2
    saved = read_json(paths.runtime_state)
    assert saved["state"] == "STOPPED"
    assert "hook failed while game absent" in saved["lastError"]
    assert "invalid D4Planner transition" not in saved["lastError"]


def test_e2e_block_queue_overflow_propagates_status_and_log(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    marker = RuntimeFailMarker(
        error="Windows keyboard hook queue overflow: droppedCount=3",
        dropped_count=3,
    )
    supervisor = _block_supervisor(paths, E2ERuntime(paths), marker)

    assert supervisor.run() == 2
    saved = read_json(paths.runtime_state)
    marker_status = saved["extras"]["inputMarker"]
    assert marker_status["state"] == "ERROR"
    assert marker_status["droppedCount"] == 3
    assert marker_status["overflow"] is True

    reader = EventLogReader(paths.events_db)
    try:
        rows = reader.read_after(saved["sessionId"], 0)
    finally:
        reader.close()
    overflow = [row for row in rows if row.type == "input.marker.overflow"]
    assert len(overflow) == 1
    assert overflow[0].data["droppedCount"] == 3



def test_running_is_published_only_after_marker_hook_active(tmp_path):
    """Regression: clients must never see RUNNING before keyboard hook ready."""
    paths = RuntimePaths(tmp_path / "home")
    runtime = E2ERuntime(paths)
    manager = UserPathManager(
        paths, MemoryPathBackend(user_path="", machine_path="MACHINE")
    )
    entered = threading.Event()
    release = threading.Event()

    class GatedCapture(FakeMarkerCapture):
        def start(self):
            entered.set()
            if not release.wait(3.0):
                raise RuntimeError("synthetic hook startup gate timed out")
            super().start()

    marker = GatedCapture()
    supervisor = Supervisor(
        paths=paths, runtime=runtime, path_manager=manager,
        marker_capture=marker, block_marker=True,
        poll_interval=0.01, health_poll_interval=0.05,
    )
    worker = threading.Thread(target=supervisor.run, daemon=True)
    worker.start()
    try:
        assert entered.wait(2.0), "hook startup did not begin"
        state_before = read_json(paths.runtime_state) or {}
        assert state_before["state"] != RuntimeState.RUNNING.value
        assert state_before["extras"]["inputMarker"]["state"] != "ACTIVE"
        release.set()
        assert wait_until(
            lambda: (read_json(paths.runtime_state) or {}).get("state")
            == RuntimeState.RUNNING.value
        )
        ready = read_json(paths.runtime_state)
        assert marker.started is True
        assert ready["extras"]["inputMarker"]["state"] == "ACTIVE"
    finally:
        release.set()
        paths.stop_request.parent.mkdir(parents=True, exist_ok=True)
        paths.stop_request.write_text("stop\n", encoding="utf-8")
        worker.join(3.0)
    assert not worker.is_alive()
    assert marker.stopped



def test_profile_observe_hook_runtime_loss_is_not_false_running(tmp_path):
    """Explicit xbox16 OBSERVE must fail visibly on hook loss, never fallback."""
    from d4planner.controller import load_profile
    paths = RuntimePaths(tmp_path / "home")
    runtime = E2ERuntime(paths)
    marker = RuntimeFailMarker(error="synthetic observe hook lost")
    supervisor = Supervisor(
        paths=paths,
        runtime=runtime,
        path_manager=UserPathManager(
            paths, MemoryPathBackend(user_path="", machine_path="MACHINE")
        ),
        marker_capture=marker,
        controller_profile=load_profile("xbox16"),
        block_marker=False,
        poll_interval=0.001,
        health_poll_interval=0.01,
    )
    assert supervisor.run() == 2
    status = read_json(paths.runtime_state)
    assert status["state"] == "STOPPED"
    assert status["extras"]["inputMarker"]["state"] == "ERROR"
    assert status["extras"]["inputMarker"]["mode"] == "OBSERVE"
    assert "synthetic observe hook lost" in status["lastError"]
    assert marker.started and marker.stopped



def test_session_records_immutable_xbox16_contract_snapshot(tmp_path):
    from d4planner.controller import load_profile
    from pathlib import Path
    paths = RuntimePaths(tmp_path / "home")
    runtime = E2ERuntime(paths)
    profile = load_profile("xbox16")
    manager = UserPathManager(
        paths, MemoryPathBackend(user_path="", machine_path="MACHINE")
    )
    supervisor = Supervisor(
        paths=paths, runtime=runtime, path_manager=manager,
        controller_profile=profile, marker_capture=FakeMarkerCapture(),
    )
    assert supervisor.bootstrap() == RuntimeState.RUNNING
    metadata_path = Path(supervisor.status.session_dir) / "metadata.json"
    metadata = read_json(metadata_path)
    snapshot = metadata["controllerProfile"]
    assert snapshot["layoutId"] == "xbox-steaminput-18-v1"
    assert snapshot["sha256"] == profile.sha256
    assert snapshot["mappingSource"] == "configuredLayout"
    assert len(snapshot["digital"]) == 16
    assert len(snapshot["analog"]) == 2
    assert {entry["controlId"] for entry in snapshot["digital"]} == {
        entry.control_id for entry in profile.digital
    }
    assert all(not entry["captureEnabled"] for entry in snapshot["analog"])
    supervisor.store.close()



def test_supervisor_selects_exactly_one_marker_backend_for_each_mode(
    monkeypatch, tmp_path,
):
    """Profile observe/block never spawns the legacy F11 polling backend."""
    import d4planner.runtime.supervisor as supervisor_module
    from d4planner.controller import load_profile

    creations = []
    instances = []

    class FakeBackend(FakeMarkerCapture):
        def __init__(self, kind, kwargs):
            super().__init__()
            self.kind = kind
            self.kwargs = kwargs
            instances.append(self)

    def hook_factory(**kwargs):
        creations.append("HOOK")
        return FakeBackend("HOOK", kwargs)

    def poll_factory(**kwargs):
        creations.append("POLL")
        return FakeBackend("POLL", kwargs)

    monkeypatch.setattr(supervisor_module, "HookInputMarkerCapture", hook_factory)
    monkeypatch.setattr(supervisor_module, "InputMarkerCapture", poll_factory)
    for name, profile, block, expected in [
        ("legacy-observe", None, False, "POLL"),
        ("legacy-block", None, True, "HOOK"),
        ("xbox-observe", load_profile("xbox16"), False, "HOOK"),
        ("xbox-block", load_profile("xbox16"), True, "HOOK"),
    ]:
        home = RuntimePaths(tmp_path / name)
        runtime = E2ERuntime(home)
        mgr = UserPathManager(home, MemoryPathBackend(user_path="", machine_path="MACHINE"))
        sup = Supervisor(paths=home, runtime=runtime, path_manager=mgr,
                         controller_profile=profile, block_marker=block)
        before = len(creations)
        sup._start_marker_capture()
        assert len(creations) == before + 1
        assert creations[-1] == expected
        assert instances[-1].started
        assert sup.status.extras["inputMarker"]["backend"] == (
            "keyboardHook" if expected == "HOOK" else "asyncKeyState"
        )
        if profile:
            assert instances[-1].kwargs["profile"] == profile
            assert instances[-1].kwargs["block"] == block
        sup._stop_marker_capture()
        assert instances[-1].stopped


def test_e2e03_xbox16_session1_one_hook_end_to_end_to_sqlite(monkeypatch, tmp_path):
    """CI E2E: full Supervisor/adapter/SQLite lifecycle with fake Win32 events.

    Windows foreground PID and console session are modelled via E2ERuntime.
    Physical hook installation / Steam Input are DF-04/DF-06, not CI claims.
    """
    from d4planner.controller import load_profile
    from d4planner.runtime.input_marker import HookInputMarkerCapture
    from d4planner.runtime.keyboard_hook import (
        BoundedSamples, WM_KEYDOWN, WM_KEYUP, capture_or_pass,
    )
    from d4planner.runtime import supervisor as supervisor_module

    paths = RuntimePaths(tmp_path / "session1")
    profile = load_profile("xbox16")
    entered, release = threading.Event(), threading.Event()
    created = []
    polled = []

    class SyntheticWindowsHook:
        hook_errors = 0
        def __init__(self, *, game_pid, block, virtual_keys=None):
            self.pid, self.block = game_pid, block
            self.vks = virtual_keys or frozenset({0x7A})
            self.samples = BoundedSamples(capacity=128)
            self.registered = False
            self.unhooked = False
            self.sent = False
            created.append(self)
        def __enter__(self):
            entered.set()
            assert release.wait(2.0)
            self.registered = True
            return self
        def __exit__(self, *_):
            self.registered = False
            self.unhooked = True
        def set_target_pid(self, pid):
            self.pid = int(pid or 0)
        def pump(self):
            if not self.sent:
                self.sent = True
                for binding in profile.digital:
                    for msg in (WM_KEYDOWN, WM_KEYUP):
                        assert capture_or_pass(
                            n_code=0, message=msg, vk=binding.virtual_key,
                            flags=0, foreground_pid=300, game_pid=self.pid,
                            block=self.block, samples=self.samples,
                            timestamp_ms=1800000000000 + len(self.samples._items),
                            virtual_keys=self.vks,
                        )
            return True

    def hook_factory(**kwargs):
        return HookInputMarkerCapture(
            backend_factory=SyntheticWindowsHook, poll_interval=.002, **kwargs
        )
    def forbidden_poll(**kwargs):
        polled.append(kwargs)
        raise AssertionError("xbox16 must not create any F11 polling backend")
    monkeypatch.setattr(supervisor_module, "HookInputMarkerCapture", hook_factory)
    monkeypatch.setattr(supervisor_module, "InputMarkerCapture", forbidden_poll)
    sup = Supervisor(
        paths=paths, runtime=E2ERuntime(paths),
        path_manager=UserPathManager(
            paths, MemoryPathBackend(user_path="", machine_path="MACHINE")
        ), controller_profile=profile, block_marker=True,
        silent=True, poll_interval=.005, health_poll_interval=.02,
    )
    runner = threading.Thread(target=sup.run, daemon=True)
    runner.start()
    try:
        assert entered.wait(2.0)
        early = read_json(paths.runtime_state)
        assert early["state"] != "RUNNING"
        assert early["extras"]["inputMarker"]["state"] != "ACTIVE"
        release.set()
        assert wait_until(lambda: (
            (read_json(paths.runtime_state) or {}).get("state") == "RUNNING"
        ))
        ready = read_json(paths.runtime_state)
        marker = ready["extras"]["inputMarker"]
        assert marker["state"] == "ACTIVE" and marker["mode"] == "BLOCK"
        assert marker["sessionId"] == 1
        assert marker["configuredDigitalCount"] == 16
        assert marker["analogDisabledCount"] == 2
        assert marker["backend"] == "keyboardHook"
        assert len(created) == 1 and not polled
        assert created[0].registered
        assert created[0].vks == frozenset(x.virtual_key for x in profile.digital)
        def has_all_16_buttons():
            reader = EventLogReader(paths.events_db)
            try:
                rows = reader.read_after(sup.status.session_id, 0)
                return sum(row.type == "input.marker.raw" for row in rows) == 32
            finally:
                reader.close()

        assert wait_until(has_all_16_buttons)
        reader = EventLogReader(paths.events_db)
        try:
            events = reader.read_after(sup.status.session_id, 0)
        finally:
            reader.close()
        rows = [e for e in events if e.type == "input.marker.raw"]
        assert len(rows) == 32
        assert [(row.data["controlId"], row.data["state"]) for row in rows] == [
            (b.control_id, edge) for b in profile.digital for edge in ("down", "up")
        ]
        assert all(row.data["suppressed"] is True for row in rows)
        assert all(row.data["layoutId"] == profile.layout_id for row in rows)
    finally:
        release.set()
        paths.stop_request.parent.mkdir(parents=True, exist_ok=True)
        paths.stop_request.write_text("stop\n", encoding="utf-8")
        runner.join(3)
    assert not runner.is_alive()
    assert created[0].unhooked
    assert (read_json(paths.runtime_state) or {})["state"] == "STOPPED"


def test_e2e11_stop_unhooks_then_mode_switch_without_stale_capture(
    monkeypatch, tmp_path,
):
    """CI checks real adapter lifecycle with synthetic Win32; physical key DF-12."""
    from d4planner.controller import load_profile
    from d4planner.runtime.input_marker import HookInputMarkerCapture
    from d4planner.runtime.keyboard_hook import BoundedSamples, F11Sample, WM_KEYDOWN, WM_KEYUP
    from d4planner.runtime import supervisor as supervisor_module

    profile = load_profile("xbox16")
    created = []

    class SyntheticHook:
        hook_errors = 0
        def __init__(self, *, game_pid, block, virtual_keys=None):
            self.pid, self.block = game_pid, block
            self.keys = virtual_keys or frozenset({0x7A})
            self.samples = BoundedSamples(capacity=128)
            self.registered, self.unhooked = False, False
            self.sent = False
            created.append(self)
        def __enter__(self):
            self.registered = True
            return self
        def __exit__(self, *_):
            self.registered = False
            self.unhooked = True
            # Simulate release queued just before unhook completion.
            self.samples.append(F11Sample(
                1800000000033, WM_KEYUP, "up", 0, 300, self.block,
                virtual_key=0x7A,
            ))
        def set_target_pid(self, pid):
            self.pid = int(pid or 0)
        def pump(self):
            if not self.sent:
                self.sent = True
                self.samples.append(F11Sample(
                    1800000000001, WM_KEYDOWN, "down", 0, 300, self.block,
                    virtual_key=0x7A,
                ))
            return True
        def suppress(self, vk):
            return self.registered and self.block and vk in self.keys

    def fake_hook(**kwargs):
        return HookInputMarkerCapture(
            backend_factory=SyntheticHook, poll_interval=.002, **kwargs
        )
    monkeypatch.setattr(supervisor_module,"HookInputMarkerCapture",fake_hook)
    fake_runtime = None
    for index, (selected, blocking) in enumerate((
        (profile,True), (None,True), (profile,False),
    )):
        paths = RuntimePaths(tmp_path / f"cycle-{index}")
        runtime = E2ERuntime(paths)
        manager = UserPathManager(paths,MemoryPathBackend(
            user_path="",machine_path="MACHINE"
        ))
        supervisor = Supervisor(
            paths=paths, runtime=runtime, path_manager=manager,
            controller_profile=selected, block_marker=blocking,
            silent=True, poll_interval=.005, health_poll_interval=.02,
        )
        # Explicitly attach a hook adapter to avoid relying on platform os.name.
        supervisor.marker_capture = fake_hook(profile=selected,block=blocking)
        thread = threading.Thread(target=supervisor.run,daemon=True)
        thread.start()
        assert wait_until(lambda: (read_json(paths.runtime_state) or {}).get("state") == "RUNNING")
        instance = created[-1]
        assert instance.registered and not instance.unhooked
        assert instance.suppress(0x7A) is blocking
        if selected is not None:
            assert instance.suppress(0x7B) is blocking
        else:
            assert instance.suppress(0x7B) is False
        if blocking and selected:
            monkeypatch.setattr(cli, "_pid_alive", lambda pid: True)
            assert cli.command_start(paths, speech=False, isolated=False, detached=True,
                                     timeout=.1, controller_profile="xbox16",
                                     block_marker=False) == 4
            assert cli.command_start(paths, speech=False, isolated=False, detached=True,
                                     timeout=.1, controller_profile=None,
                                     block_marker=True) == 4
        paths.stop_request.write_text("stop\n", encoding="utf-8")
        thread.join(3)
        assert not thread.is_alive()
        assert instance.unhooked and not instance.registered
        assert instance.suppress(0x7A) is False
        assert instance.suppress(0x7B) is False
        state = read_json(paths.runtime_state)
        assert state["state"] == "STOPPED"
        reader = EventLogReader(paths.events_db)
        try:
            rows = [ev for ev in reader.read_after(state["sessionId"],0)
                    if ev.type == "input.marker.raw"]
        finally:
            reader.close()
        assert [ev.data["state"] for ev in rows] == (
            ["down","up"] if selected is not None or blocking else []
        )
        assert runtime._steam.pid == 200 and runtime._game.pid == 300
    assert len(created) == 3


def test_uat_attach_only_existing_steam_game_nvda_no_restart_or_launch(tmp_path):
    """Issue87 Real-A launcher safety, modelled in hosted CI."""
    from d4planner.controller import load_profile
    paths=RuntimePaths(tmp_path/"uat-attached")
    runtime=E2ERuntime(paths)
    calls=[]
    def forbidden(name):
        def rejected(*args,**kwargs):
            calls.append(name)
            raise AssertionError(f"UAT must never {name}")
        return rejected
    runtime.ensure_addon_runtime=forbidden("install/restart addon")
    runtime.restart_nvda=forbidden("restart NVDA")
    runtime.ensure_nvda_running=forbidden("launch NVDA")
    runtime.launch_game=forbidden("launch Diablo IV")
    sup=Supervisor(
        paths=paths,runtime=runtime,
        path_manager=UserPathManager(paths,MemoryPathBackend(user_path="",machine_path="MACHINE")),
        controller_profile=load_profile("xbox16"),
        block_marker=True,isolated=True,uat_attach_only=True,
        marker_capture=FakeMarkerCapture(),
    )
    assert sup.bootstrap() == RuntimeState.RUNNING
    assert runtime.launch_calls == 0 and calls == []
    assert sup.status.active_console_session_id == 1
    assert sup.status.game.pid == 300
    sup.store.close()


def test_uat_attach_only_missing_nvda_or_d4_fails_without_process_launch(tmp_path):
    from d4planner.controller import load_profile
    for missing in ("nvda","game"):
        paths=RuntimePaths(tmp_path/missing)
        runtime=E2ERuntime(paths)
        calls=[]
        if missing=="nvda":
            runtime._nvda=None
        else:
            runtime._game=None
        def rejected(*args,**kwargs):
            calls.append("unexpected process mutation")
            raise AssertionError("UAT must never start game/NVDA")
        runtime.ensure_nvda_running=rejected
        runtime.restart_nvda=rejected
        runtime.launch_game=rejected
        runtime.ensure_addon_runtime=rejected
        supervisor=Supervisor(
            paths=paths,runtime=runtime,
            path_manager=UserPathManager(paths,MemoryPathBackend(user_path="",machine_path="MACHINE")),
            controller_profile=load_profile("xbox16"),
            block_marker=True,isolated=True,uat_attach_only=True,
            marker_capture=FakeMarkerCapture(),
        )
        assert supervisor.bootstrap() == RuntimeState.BLOCKED
        assert not calls
        assert (read_json(paths.runtime_state) or {})["state"] == "BLOCKED"
        supervisor.store.close()
