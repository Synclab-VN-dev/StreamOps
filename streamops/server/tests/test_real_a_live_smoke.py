from __future__ import annotations

from copy import deepcopy

import scripts.e2e.real_a_live_smoke as smoke


SOURCE_ID = "clock-source"
SESSION_ID = "managed-session"


class FakeApi:
    def __init__(self) -> None:
        self.visible = False
        self.x = 100.0
        self.y = 50.0
        self.status_reads = 0
        self.profile = {
            "id": "profile",
            "name": "Runtime profile",
            "canvas": {"width": 1920, "height": 1080, "fps": 60},
        }
        self.destination = {
            "id": "destination",
            "name": "Local RTMP",
            "type": "custom_rtmp",
            "enabled": True,
            "settings": {"server_url": "rtmp://127.0.0.1:1935/live"},
            "credential_configured": True,
        }

    def get(self, path: str):
        if path == "/api/v1/live/status":
            self.status_reads += 1
            return self.status()
        if path == "/api/v1/scene-profiles/profile":
            return deepcopy(self.profile)
        if path == "/api/v1/stream-destinations/destination":
            return deepcopy(self.destination)
        raise AssertionError(path)

    def patch(self, path: str, payload: dict):
        if path.endswith("/visibility"):
            self.visible = payload["visible"]
        elif path.endswith("/position"):
            self.x = float(payload["x"])
            self.y = float(payload["y"])
        else:
            raise AssertionError(path)
        return self.source()

    def post(self, path: str, payload: dict | None = None):
        if path.endswith("/move"):
            self.x += float(payload["dx"])
            self.y += float(payload["dy"])
            return self.source()
        if path == "/api/v1/scene-profiles/profile/verify":
            checks = [
                {"id": f"item.{SOURCE_ID}.enabled", "status": "PASS"},
                {"id": f"item.{SOURCE_ID}.transform.positionX", "status": "PASS"},
                {"id": f"item.{SOURCE_ID}.transform.positionY", "status": "PASS"},
            ]
            return {"status": "PASS", "checks": checks}
        raise AssertionError(path)

    def source(self) -> dict:
        override: dict = {}
        if self.visible is not False:
            override["visibility"] = self.visible
        if (self.x, self.y) != (100.0, 50.0):
            override["position"] = {"x": self.x, "y": self.y}
        return {
            "id": SOURCE_ID,
            "name": "Clock",
            "type": "browser_source",
            "baseline": {"visible": False, "position": {"x": 100.0, "y": 50.0}},
            "override": override,
            "effective": {"visible": self.visible, "position": {"x": self.x, "y": self.y}},
            "actual": {"visible": self.visible, "position": {"x": self.x, "y": self.y}},
            "drift": [],
        }

    def status(self) -> dict:
        source = self.source()
        overrides = {SOURCE_ID: source["override"]} if source["override"] else {}
        return {
            "state": "LIVE",
            "managed": True,
            "session_id": SESSION_ID,
            "output": {"active": True},
            "runtime_scene": {"status": "PASS", "sources": [source], "overrides": overrides},
        }


class FakeWsMonitor:
    created: list["FakeWsMonitor"] = []
    snapshot: dict = {}

    def __init__(self, url: str, secret: str, timeout: float) -> None:
        self.closed = False
        self.created.append(self)

    def start(self) -> None:
        pass

    def wait_connected(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def wait_live_snapshot(self, timeout: float, predicate=None) -> dict:
        assert predicate is not None
        assert predicate(self.snapshot)
        return {"type": "event", "event": "stream.snapshot", "data": self.snapshot}


def config() -> smoke.Config:
    return smoke.Config(
        base_url="http://127.0.0.1:8765",
        profile_id="profile",
        rtmp_server_url="rtmp://127.0.0.1:1935/live",
        stream_key="not-a-real-secret",
        ffprobe_input_url=None,
        timeout=1.0,
        live_timeout=1.0,
        post_stop_wait=0.0,
    )


def test_real_a_runner_proves_each_mutation_and_reconnect_recovery(monkeypatch) -> None:
    api = FakeApi()
    run = smoke.SmokeRun(config())
    run.api = api
    run.destination_id = "destination"

    evidence = run._verify_runtime_scene_control()

    assert api.status_reads == 4
    assert "source=Clock" in evidence
    assert "baseline x/y=100,50" in evidence
    assert "relative move result=130,70" in evidence
    assert run.runtime_override == {
        "visibility": True,
        "position": {"x": 130.0, "y": 70.0},
    }
    assert next(result for result in run.results if result.name == "AC24").status == "PASS"
    assert "server-owned override" in run._verify_runtime_refresh_recovery()

    old_ws = FakeWsMonitor("", "", 1.0)
    run.ws = old_ws
    FakeWsMonitor.snapshot = api.status()
    monkeypatch.setattr(smoke, "WsMonitor", FakeWsMonitor)
    recovery = run._verify_ws_reconnect_recovery()

    assert old_ws.closed is True
    assert "fresh WebSocket snapshot" in recovery
    assert run.ws is FakeWsMonitor.created[-1]


def test_real_a_runner_requires_stop_cleanup_and_profile_checks() -> None:
    api = FakeApi()
    run = smoke.SmokeRun(config())
    run.api = api
    run.profile_before_runtime = deepcopy(api.profile)
    run.runtime_source_id = SOURCE_ID
    run.runtime_source_name = "Clock"
    run.runtime_baseline = {"visible": False, "position": {"x": 100.0, "y": 50.0}}
    run.post_stop_status = {
        "state": "IDLE",
        "managed": False,
        "session_id": None,
        "output": {"active": False},
        "runtime_scene": None,
    }

    evidence = run._verify_runtime_restore()

    assert "profile_verify=PASS" in evidence
    assert "overrides_cleaned=true" in evidence



def test_real_a_runner_default_transport_timeout_covers_stream_convergence(monkeypatch) -> None:
    monkeypatch.setenv("STREAMOPS_BASE_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("PROFILE_ID", "profile")
    monkeypatch.setenv("RTMP_SERVER_URL", "rtmp://127.0.0.1:1935/live")
    monkeypatch.setenv("RTMP_STREAM_KEY", "not-a-real-secret")
    monkeypatch.delenv("FFPROBE_INPUT_URL", raising=False)

    parsed = smoke.parse_config([])

    assert smoke.DEFAULT_TIMEOUT == 20.0
    assert parsed.timeout == 20.0
    assert parsed.timeout > 12.0
