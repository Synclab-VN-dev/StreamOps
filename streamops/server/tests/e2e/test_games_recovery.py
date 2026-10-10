"""E2E-04/05/07: HTTP/WS recovery, independent process fixture, bounded cleanup."""
from __future__ import annotations
import subprocess
import sys
import time
from fastapi.testclient import TestClient
from streamops.server.tests.test_games_api import _client,_snapshot,_response,TOKEN
from streamops.server.tests.test_games_lifecycle import GAME

def request(ws,rid,op,data=None):
    ws.send_json({"type":"request","request_id":rid,"operation":op,"payload":data or {}})
    return _response(ws,rid)

def test_reconnect_recovers_terminal_operation_after_event_loss(monkeypatch,server_config,capture_service,tmp_path):
    monkeypatch.setenv("STREAMOPS_GAME_CONTROL_TOKEN",TOKEN)
    client,platform=_client(server_config,capture_service,tmp_path)
    with client:
        with client.websocket_connect("/api/v1/games/ws",
                subprotocols=["streamops-games-v1",f"streamops-game-control.{TOKEN}"]) as ws:
            original=_snapshot(ws)
            response=request(ws,"start","games.lifecycle.start",{"game_id":GAME,"idempotency_key":"connect-reconnect"})
            assert response["ok"]
            operation_id=response["data"]["operation_id"]
        # Deliberately lose the operation events by disconnecting.
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            operation=client.get(f"/api/v1/game-operations/{operation_id}").json()
            if operation["status"] in ("SUCCEEDED","FAILED","UNKNOWN"):
                break
            time.sleep(.01)
        assert operation["status"]=="SUCCEEDED"
        with client.websocket_connect("/api/v1/games/ws") as ws:
            snap=_snapshot(ws)
            assert snap["epoch"]==original["epoch"]
            assert snap["games"][0]["observation"]["process"]["state"]=="RUNNING"
            from_store=request(ws,"resume","games.operations.get",{"operation_id":operation_id})
            assert from_store["ok"] and from_store["data"]["status"]=="SUCCEEDED"
            assert from_store["data"]["operation_id"]==operation_id
        assert platform.start_calls==1

def test_process_fixture_lifecycle_and_cleanup_does_not_target_real_game():
    # This process is owned solely by the test. Never call taskkill/Steam APIs.
    child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"],
                           stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    pid=child.pid
    try:
        assert pid>0 and child.poll() is None
        assert child.args[0]==sys.executable
    finally:
        child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=3)
    assert child.poll() is not None
