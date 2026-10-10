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
