"""WebSocket/REST parity tests backed by the same fake platform."""
from __future__ import annotations
import time
from fastapi.testclient import TestClient
from streamops.server.app import create_app
from streamops.server.tests.test_games_lifecycle import GAME, build_service

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
        missing = client.get("/api/v1/game-operations/not-found")
        assert missing.status_code==404 and missing.json()["error"]["code"]=="operation_not_found"
        missing_key=client.post(f"/api/v1/games/{GAME}/actions",json={"action":"start"})
        assert missing_key.status_code==422
        assert missing_key.json()["error"]["code"]=="invalid_request"
        assert platform.start_calls==0

def test_games_ws_envelope_tokenless_start_and_static_state(server_config,capture_service,tmp_path):
    client,platform=_client(server_config,capture_service,tmp_path)
    with client, client.websocket_connect("/api/v1/games/ws",subprotocols=["streamops-games-v1"]) as ws:
        snapshot=_snapshot(ws)
        assert snapshot["games"][0]["id"]==GAME
        ws.send_json({"type":"request","request_id":"r1","operation":"games.list","payload":{}})
        reply=_response(ws,"r1")
        assert reply["ok"] and reply["data"]["total"]==1
        ws.send_json({"type":"request","request_id":"r2","operation":"games.lifecycle.start",
                      "payload":{"game_id":GAME,"idempotency_key":"test-ws"}})
        accepted=_response(ws,"r2")
        assert accepted["ok"] and accepted["data"]["operation_id"].startswith("op-")
        assert accepted["data"]["game_id"]==GAME

def test_games_ws_tokenless_lifecycle_and_operation_lookup(server_config,capture_service,tmp_path):
    client,platform=_client(server_config,capture_service,tmp_path)
    with client, client.websocket_connect("/api/v1/games/ws",
            subprotocols=["streamops-games-v1"]) as ws:
        _snapshot(ws)
        ws.send_json({"type":"request","request_id":"r3","operation":"games.lifecycle.start",
                      "payload":{"game_id":GAME,"idempotency_key":"started-over-ws"}})
        result=_response(ws,"r3")
        assert result["ok"] and result["data"]["operation_id"].startswith("op-")
        assert result["data"]["game_id"]==GAME



def test_rest_tokenless_start_restart_stop_with_idempotency_and_allowlist(
        server_config,capture_service,tmp_path):
    client,platform=_client(server_config,capture_service,tmp_path)
    def execute(action,key):
        response=client.post(f"/api/v1/games/{GAME}/actions",
            json={"action":action},headers={"Idempotency-Key":key})
        assert response.status_code==202, response.text
        accepted=response.json()
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            operation=client.get(
                f"/api/v1/game-operations/{accepted['operation_id']}").json()
            if operation["status"] in ("SUCCEEDED","FAILED","UNKNOWN"):
                break
            time.sleep(.01)
        assert operation["status"]=="SUCCEEDED", operation
        return accepted
    with client:
        started=execute("start","tokenless-start")
        assert client.get(f"/api/v1/games/{GAME}").json()["observation"]["process"]["state"]=="RUNNING"
        duplicated=client.post(f"/api/v1/games/{GAME}/actions",
            json={"action":"start"},headers={"Idempotency-Key":"tokenless-start"})
        assert duplicated.status_code==202
        assert duplicated.json()["operation_id"]==started["operation_id"]
        execute("restart","tokenless-restart")
        execute("stop","tokenless-stop")
        assert client.get(f"/api/v1/games/{GAME}").json()["observation"]["process"]["state"]=="STOPPED"
        assert platform.start_calls==2 and platform.stop_calls==2
        forbidden=client.post(f"/api/v1/games/{GAME}/actions",
            json={"action":"force_stop"},headers={"Idempotency-Key":"force-attempt"})
        assert forbidden.status_code==422
        assert forbidden.json()["error"]["code"]=="invalid_action"
        not_allowlisted=client.post("/api/v1/games/steam:99999999/actions",
            json={"action":"start"},headers={"Idempotency-Key":"unknown-game"})
        assert not_allowlisted.status_code==404
        assert not_allowlisted.json()["error"]["code"]=="game_not_found"
        assert platform.start_calls==2 and platform.stop_calls==2


def test_two_ws_observers_receive_external_process_transition(server_config,capture_service,tmp_path):
    client,platform=_client(server_config,capture_service,tmp_path)
    with client:
        with client.websocket_connect("/api/v1/games/ws") as first:
            _snapshot(first)
            with client.websocket_connect("/api/v1/games/ws") as second:
                _snapshot(second)
                platform.running=True  # external process change; no API reconcile/poll
                for ws in (first,second):
                    for _ in range(6):
                        event=ws.receive_json()
                        if event.get("event")=="games.changed":
                            assert event["data"]["game_id"]==GAME
                            assert event["data"]["game"]["observation"]["process"]["state"]=="RUNNING"
                            break
                    else:
                        raise AssertionError("GameObserver did not notify both clients")
