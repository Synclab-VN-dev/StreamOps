"""WS Steam adapter uses existing SteamService and never mutates without token."""
from fastapi.testclient import TestClient
from streamops.server.app import create_app
from streamops.server.services import SteamService
from streamops.server.tests.test_steam import FakeSteamBackend, RUNNING, STOPPED

def test_steam_ws_snapshot_status_and_legacy_rest(server_config,capture_service):
    backend=FakeSteamBackend(status=RUNNING)
    app=create_app(server_config,capture_service=capture_service,
                   steam_service=SteamService(backend),manage_runtime=False)
    with TestClient(app) as client:
        assert client.get("/api/v1/steam/status").json()["pid"]==RUNNING.pid
        with client.websocket_connect("/api/v1/steam/ws") as ws:
            initial=ws.receive_json()
            assert initial["event"]=="steam.snapshot"
            assert initial["data"]["pid"]==RUNNING.pid
            ws.send_json({"type":"request","request_id":"steam-r1",
                          "operation":"steam.status","payload":{}})
            response=ws.receive_json()
            assert response["type"]=="response" and response["ok"]
            assert response["data"]["pid"]==RUNNING.pid
            ws.send_json({"type":"request","request_id":"steam-r2",
                          "operation":"steam.lifecycle.restart","payload":{}})
            denied=ws.receive_json()
            assert denied["error"]["code"]=="capability_disabled"
            assert backend.restart_calls==0

def test_steam_ws_unknown_when_status_unavailable(server_config,capture_service):
    backend=FakeSteamBackend(status=RuntimeError("Steam inspection unavailable"))
    app=create_app(server_config,capture_service=capture_service,
                   steam_service=SteamService(backend),manage_runtime=False)
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/steam/ws") as ws:
            event=ws.receive_json()
            assert event["event"]=="steam.snapshot"
            assert event["data"]["state"]=="unknown"
            assert event["data"]["stale"] is True

def test_steam_ws_authenticated_restart_pushes_observed_snapshot(monkeypatch,server_config,capture_service):
    from dataclasses import replace
    token="steam-test-token-long-enough-123456789"
    monkeypatch.setenv("STREAMOPS_GAME_CONTROL_TOKEN",token)
    next_status=replace(RUNNING,pid=45678)
    class ChangingSteam(FakeSteamBackend):
        def restart(self):
            self.restart_calls+=1
            self.status_result=next_status
            return next_status
    backend=ChangingSteam()
    app=create_app(server_config,capture_service=capture_service,
                   steam_service=SteamService(backend),manage_runtime=False)
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/steam/ws",subprotocols=[
            "streamops-games-v1",f"streamops-game-control.{token}"]) as ws:
            assert ws.receive_json()["data"]["pid"]==RUNNING.pid
            ws.send_json({"type":"request","request_id":"restart","operation":"steam.lifecycle.restart","payload":{}})
            messages=[ws.receive_json(),ws.receive_json()]
            reply=next(x for x in messages if x.get("type")=="response")
            snapshot=next(x for x in messages if x.get("event")=="steam.snapshot")
            assert reply["ok"] and reply["data"]["pid"]==45678
            assert snapshot["data"]["pid"]==45678
            assert backend.restart_calls==1
            assert client.get("/api/v1/steam/status").json()["pid"]==45678
