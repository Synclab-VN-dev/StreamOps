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

def test_real_synthetic_child_drives_two_ws_observers_without_client_polling(
        server_config,capture_service,tmp_path):
    from streamops.server.app import create_app
    from streamops.server.tests.test_games_lifecycle import FakeGamePlatform,build_service
    class ProcessBacked(FakeGamePlatform):
        def __init__(self):
            super().__init__()
            self.child=None
        def inspect(self,game):
            self.running=self.child is not None and self.child.poll() is None
            observation=super().inspect(game)
            if self.running:
                observation=observation.model_copy(update={"process":observation.process.model_copy(
                    update={"pid":self.child.pid,"executable":sys.executable})})
            return observation

    platform=ProcessBacked()
    service,_=build_service(tmp_path,platform)
    client=TestClient(create_app(server_config,capture_service=capture_service,
                                 game_service=service,manage_runtime=False))
    child=None
    try:
        with client:
            with client.websocket_connect("/api/v1/games/ws") as first:
                with client.websocket_connect("/api/v1/games/ws") as second:
                    _snapshot(first)
                    _snapshot(second)
                    child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"],
                                            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL)
                    platform.child=child
                    service.hub.trigger_refresh()
                    for ws in (first,second):
                        event=ws.receive_json()
                        assert event["event"]=="games.changed"
                        assert event["data"]["game"]["observation"]["process"]["pid"]==child.pid
                    child.terminate()
                    child.wait(timeout=3)
                    service.hub.trigger_refresh()
                    for ws in (first,second):
                        event=ws.receive_json()
                        assert event["event"]=="games.changed"
                        assert event["data"]["game"]["observation"]["process"]["state"]=="STOPPED"
                    assert not service.hub._subscribers or len(service.hub._subscribers)==2
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait(timeout=3)
    assert child is not None and child.poll() is not None

def test_foreground_session_loss_stale_and_recovery_push_to_two_ws_clients(
        server_config,capture_service,tmp_path):
    from streamops.server.app import create_app
    from streamops.server.tests.test_games_lifecycle import FakeGamePlatform,build_service
    from streamops.server.platform.windows.game_process import GamePlatformError
    class ChangingPlatform(FakeGamePlatform):
        def __init__(self):
            super().__init__()
            self.running=True
            self.window="BACKGROUND"
            self.session=1
        def inspect(self,game):
            if self.session != 1:
                raise GamePlatformError("wrong_desktop_session","synthetic session drift")
            observation=super().inspect(game)
            return observation.model_copy(update={"window":self.window})
    platform=ChangingPlatform()
    service,_=build_service(tmp_path,platform)
    client=TestClient(create_app(server_config,capture_service=capture_service,
                                 game_service=service,manage_runtime=False))
    with client:
        with client.websocket_connect("/api/v1/games/ws") as first:
            with client.websocket_connect("/api/v1/games/ws") as second:
                for ws in (first,second):
                    initial=_snapshot(ws)
                    assert initial["games"][0]["observation"]["window"]=="BACKGROUND"
                for change,value,expected,stale in [
                    ("window","FOREGROUND","RUNNING",False),
                    ("session",2,"UNKNOWN",True),
                    ("session",1,"RUNNING",False),
                ]:
                    setattr(platform,change,value)
                    service.hub.trigger_refresh()
                    for ws in (first,second):
                        event=ws.receive_json()
                        assert event["event"]=="games.changed"
                        record=event["data"]["game"]["observation"]
                        assert record["process"]["state"]==expected
                        assert record["process"]["stale"] is stale
                        if expected=="RUNNING":
                            assert record["window"]=="FOREGROUND"
        with client.websocket_connect("/api/v1/games/ws") as reconnect:
            snapshot=_snapshot(reconnect)
            assert snapshot["stale"] is False
            assert snapshot["games"][0]["observation"]["process"]["state"]=="RUNNING"
            assert snapshot["games"][0]["observation"]["window"]=="FOREGROUND"

def test_unknown_timeout_operation_recovered_after_ws_and_node_restart(
        monkeypatch,server_config,capture_service,tmp_path):
    from streamops.server.app import create_app
    from streamops.server.tests.test_games_lifecycle import FakeGamePlatform,build_service
    monkeypatch.setenv("STREAMOPS_GAME_CONTROL_TOKEN",TOKEN)
    class NonConvergent(FakeGamePlatform):
        def start(self,game): self.start_calls+=1
    first_service,platform=build_service(tmp_path,NonConvergent())
    first_service.lifecycle.timeout=.05
    first=TestClient(create_app(server_config,capture_service=capture_service,
                                game_service=first_service,manage_runtime=False))
    with first:
        with first.websocket_connect("/api/v1/games/ws",
                subprotocols=["streamops-games-v1",f"streamops-game-control.{TOKEN}"]) as ws:
            _snapshot(ws)
            sent=request(ws,"unknown","games.lifecycle.start",{"game_id":GAME,"idempotency_key":"crash-replay"})
            assert sent["ok"]
            op_id=sent["data"]["operation_id"]
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            state=first.get(f"/api/v1/game-operations/{op_id}").json()
            if state["status"] in ("SUCCEEDED","FAILED","UNKNOWN"):
                break
            time.sleep(.01)
        assert state["status"]=="UNKNOWN"
        assert state["code"]=="operation_timeout"
    # A second application instance recreates both WS and SQLite handles.
    second_service,_=build_service(tmp_path,NonConvergent())
    second=TestClient(create_app(server_config,capture_service=capture_service,
                                 game_service=second_service,manage_runtime=False))
    with second, second.websocket_connect("/api/v1/games/ws") as ws:
        snap=_snapshot(ws)
        assert snap["games"][0]["observation"]["process"]["state"]=="STOPPED"
        recovered=request(ws,"recovered","games.operations.get",{"operation_id":op_id})
        assert recovered["ok"] and recovered["data"]["status"]=="UNKNOWN"
        assert recovered["data"]["code"]=="operation_timeout"
        reconciled=request(ws,"readonly","games.reconcile",{"game_id":GAME})
        assert reconciled["ok"] and reconciled["data"]["observation"]["process"]["state"]=="STOPPED"
    assert platform.start_calls==1
