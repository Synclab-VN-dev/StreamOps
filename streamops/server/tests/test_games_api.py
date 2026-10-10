"""WebSocket/REST parity tests backed by the same fake platform."""
from __future__ import annotations
import os
from fastapi.testclient import TestClient
from streamops.server.app import create_app
from streamops.server.tests.test_games_lifecycle import GAME, build_service

TOKEN="long-operator-only-control-token-123456"

def _client(server_config,capture_service,tmp_path):
    service,platform=build_service(tmp_path)
    return TestClient(create_app(server_config,capture_service=capture_service,
                                 game_service=service, manage_runtime=False)),platform

def _snapshot(ws):
    for _ in range(6):
        message=ws.receive_json()
        if message["type"]=="event" and message["event"]=="games.snapshot":
            return message["data"]
    raise AssertionError("snapshot not delivered")

def _response(ws,rid):
    for _ in range(8):
        message=ws.receive_json()
        if message.get("type")=="response" and message.get("request_id")==rid:
            return message
    raise AssertionError("response not delivered")

def test_rest_games_contract(server_config,capture_service,tmp_path):
    client,platform=_client(server_config,capture_service,tmp_path)
    with client:
        listed=client.get("/api/v1/games").json()
        assert listed["total"]==1 and listed["games"][0]["id"]==GAME
        assert listed["games"][0]["observation"]["installed"] is True
        assert listed["games"][0]["observation"]["process"]["state"]=="STOPPED"
        assert client.get(f"/api/v1/games/{GAME}").json()["id"]==GAME
        assert client.post(f"/api/v1/games/{GAME}/reconcile").json()["id"]==GAME
        assert client.post("/api/v1/game-catalog/refresh").status_code==200
        assert client.get("/api/v1/game-operations/not-found").status_code==404
        assert client.post(f"/api/v1/games/{GAME}/actions",json={"action":"start"},
                           headers={"Idempotency-Key":"test"}).status_code==403
        assert platform.start_calls==0

def test_games_ws_envelope_unauthorized_and_static_state(server_config,capture_service,tmp_path):
    client,platform=_client(server_config,capture_service,tmp_path)
    with client, client.websocket_connect("/api/v1/games/ws",subprotocols=["streamops-games-v1"]) as ws:
        snapshot=_snapshot(ws)
        assert snapshot["games"][0]["id"]==GAME
        ws.send_json({"type":"request","request_id":"r1","operation":"games.list","payload":{}})
        reply=_response(ws,"r1")
        assert reply["ok"] and reply["data"]["total"]==1
        ws.send_json({"type":"request","request_id":"r2","operation":"games.lifecycle.start",
                      "payload":{"game_id":GAME,"idempotency_key":"test-ws"}})
        refused=_response(ws,"r2")
        assert not refused["ok"] and refused["error"]["code"]=="capability_disabled"
        assert platform.start_calls==0

def test_games_ws_authenticated_lifecycle_and_operation_lookup(monkeypatch,server_config,capture_service,tmp_path):
    monkeypatch.setenv("STREAMOPS_GAME_CONTROL_TOKEN",TOKEN)
    client,platform=_client(server_config,capture_service,tmp_path)
    with client, client.websocket_connect("/api/v1/games/ws",
            subprotocols=["streamops-games-v1",f"streamops-game-control.{TOKEN}"]) as ws:
        _snapshot(ws)
        ws.send_json({"type":"request","request_id":"r3","operation":"games.lifecycle.start",
                      "payload":{"game_id":GAME,"idempotency_key":"started-over-ws"}})
        result=_response(ws,"r3")
        assert result["ok"] and result["data"]["operation_id"].startswith("op-")
        assert result["data"]["game_id"]==GAME
