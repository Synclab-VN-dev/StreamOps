"""E2E-02/03: real FastAPI HTTP and WS routers sharing one fake GameService."""
from __future__ import annotations
import time
import pytest
from streamops.server.tests.test_games_api import _client,_snapshot,_response,TOKEN
from streamops.server.tests.test_games_lifecycle import GAME

def call(ws,rid,operation,payload=None):
    ws.send_json({"type":"request","request_id":rid,"operation":operation,"payload":payload or {}})
    return _response(ws,rid)

def finish(ws,op_id):
    for i in range(100):
        item=call(ws,f"read-{i}","games.operations.get",{"operation_id":op_id})
        assert item["ok"]
        if item["data"]["status"] in ("SUCCEEDED","FAILED","UNKNOWN"):
            return item["data"]
        time.sleep(.01)
    pytest.fail("operation did not reach terminal status")

def test_all_eight_game_ws_operations_and_force_stop_disabled(monkeypatch,server_config,capture_service,tmp_path):
    monkeypatch.setenv("STREAMOPS_GAME_CONTROL_TOKEN",TOKEN)
    client,platform=_client(server_config,capture_service,tmp_path)
    with client, client.websocket_connect("/api/v1/games/ws",
            subprotocols=["streamops-games-v1",f"streamops-game-control.{TOKEN}"]) as ws:
        _snapshot(ws)
        assert call(ws,"r-list","games.list")["data"]["games"][0]["id"]==GAME
        assert call(ws,"r-get","games.get",{"game_id":GAME})["data"]["id"]==GAME
        assert call(ws,"r-reconcile","games.reconcile",{"game_id":GAME})["data"]["id"]==GAME
        assert call(ws,"r-refresh","games.catalog.refresh")["ok"]
        started=call(ws,"r-start","games.lifecycle.start",{"game_id":GAME,"idempotency_key":"start"})
        assert started["ok"]
        assert finish(ws,started["data"]["operation_id"])["status"]=="SUCCEEDED"
        restarted=call(ws,"r-restart","games.lifecycle.restart",{"game_id":GAME,"idempotency_key":"restart"})
        assert restarted["ok"]
        assert finish(ws,restarted["data"]["operation_id"])["status"]=="SUCCEEDED"
        stopped=call(ws,"r-stop","games.lifecycle.stop",{"game_id":GAME,"idempotency_key":"stop"})
        assert stopped["ok"]
        assert finish(ws,stopped["data"]["operation_id"])["status"]=="SUCCEEDED"
        forbidden=call(ws,"r-force","games.lifecycle.force_stop",{"game_id":GAME})
        assert not forbidden["ok"] and forbidden["error"]["code"]=="capability_disabled"
        assert platform.start_calls==2 and platform.stop_calls==2

def test_invalid_ws_requests_and_errors_are_typed(server_config,capture_service,tmp_path):
    client,_=_client(server_config,capture_service,tmp_path)
    with client,client.websocket_connect("/api/v1/games/ws") as ws:
        _snapshot(ws)
        for rid,op,payload,code in [
            ("bad-op","games.nonexistent",{},"unknown_operation"),
            ("bad-payload","games.get",{"game_id":GAME,"script":"evil"},"invalid_request"),
            ("missing-game","games.get",{"game_id":"steam:987654321"},"game_not_found"),
            ("invalid-provider","games.list",{"provider":"untrusted"},"invalid_provider"),
            ("readonly","games.lifecycle.start",{"game_id":GAME,"idempotency_key":"first"},"capability_disabled")
        ]:
            result=call(ws,rid,op,payload)
            assert result["request_id"]==rid
            assert result["ok"] is False
            assert result["error"]["code"]==code

def test_rest_ws_payload_semantic_parity(monkeypatch,server_config,capture_service,tmp_path):
    monkeypatch.setenv("STREAMOPS_GAME_CONTROL_TOKEN",TOKEN)
    client,platform=_client(server_config,capture_service,tmp_path)
    headers={"X-StreamOps-Game-Token":TOKEN,"Idempotency-Key":"parity"}
    with client,client.websocket_connect("/api/v1/games/ws",
            subprotocols=["streamops-games-v1",f"streamops-game-control.{TOKEN}"]) as ws:
        _snapshot(ws)
        for rid,op,url,method,payload in [
            ("list","games.list","/api/v1/games","get",{}),
            ("get","games.get",f"/api/v1/games/{GAME}","get",{"game_id":GAME}),
            ("reconcile","games.reconcile",f"/api/v1/games/{GAME}/reconcile","post",{"game_id":GAME}),
        ]:
            rest=getattr(client,method)(url)
            out=call(ws,rid,op,payload)
            assert rest.status_code==200 and out["ok"]
            assert rest.json()==out["data"]
        missing=client.get("/api/v1/game-operations/not-real")
        from_ws=call(ws,"missing","games.operations.get",{"operation_id":"not-real"})
        assert missing.status_code==404
        assert missing.json()["error"]["code"]==from_ws["error"]["code"]=="operation_not_found"
        rest=client.post(f"/api/v1/games/{GAME}/actions",json={"action":"start"},headers=headers)
        assert rest.status_code==202
        from_ws=call(ws,"same-idempotency","games.lifecycle.start",{"game_id":GAME,"idempotency_key":"parity"})
        assert from_ws["ok"]
        assert rest.json()==from_ws["data"]
        op_id=rest.json()["operation_id"]
        assert finish(ws,op_id)["status"]=="SUCCEEDED"
        assert client.get(f"/api/v1/game-operations/{op_id}").json()==call(ws,"op-final","games.operations.get",{"operation_id":op_id})["data"]
        assert client.post("/api/v1/game-catalog/refresh").status_code==200
        assert call(ws,"catalog","games.catalog.refresh")["ok"]
        assert platform.start_calls==1

def test_all_five_event_envelopes_and_new_snapshot(server_config,capture_service,tmp_path):
    client,platform=_client(server_config,capture_service,tmp_path)
    with client:
        hub=client.app.state.game_status_hub
        with client.websocket_connect("/api/v1/games/ws") as ws:
            first=_snapshot(ws)
            assert first["games"][0]["id"]==GAME
            assert first["epoch"]==hub.epoch
            hub.broadcast("games.operation",{"operation_id":"synthetic","game_id":GAME,"status":"PENDING"})
            hub.catalog_changed()
            hub.broadcast("games.heartbeat",{"observed_at":"2026-10-10T00:00:00Z"})
            platform.running=True
            hub.trigger_refresh()
            events=set(["games.snapshot"])
            for _ in range(12):
                event=ws.receive_json()
                if event["type"]=="event": events.add(event["event"])
                if len(events)==5: break
            assert events=={"games.snapshot","games.changed","games.operation","games.catalog.changed","games.heartbeat"}
        with client.websocket_connect("/api/v1/games/ws") as ws:
            new=_snapshot(ws)
            assert new["games"][0]["observation"]["process"]["state"]=="RUNNING"
            assert new["epoch"]==first["epoch"]
