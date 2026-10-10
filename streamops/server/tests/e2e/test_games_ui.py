"""Issue 86: independent FE E2E with the exact #85 WS operations and event shapes.
These tests do NOT import GameService or depend on the #85 branch.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
import socket
import threading

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import pytest
from playwright.sync_api import Page, expect
import uvicorn

from streamops.server.app import WEB_ROOT
from .conftest import wait_until

pytestmark = pytest.mark.only_browser("chromium")


def game(name="Diablo IV", game_id="steam:2344520", state="RUNNING"):
    return {
        "id": game_id, "provider": "steam", "name": name,
        "enabled": True, "metadataSource": "static", "revision": 1,
        "observation": {
            "owned": None, "installed": True,
            "process": {"state": state, "pid": 2100 if state == "RUNNING" else None,
                        "session_id": 1, "created_at": None, "executable": None,
                        "observed_at": "2026-10-10T00:00:00Z", "stale": False},
            "window": "FOREGROUND" if state == "RUNNING" else "NOT_DETECTED",
            "obsCapture": "CONFIGURED_ONLY", "selectedForStream": "NOT_SELECTED"
        },
        "capabilities": {"start": state == "STOPPED", "stop": state == "RUNNING",
                         "restart": state == "RUNNING", "force_stop": False},
        "capability_reason": None,
    }


class FakeContract:
    def __init__(self):
        self.games = [game()]
        self.epoch = "test-server-epoch"
        self.revision = 1
        self.peers = set()
        self.steam_peers = set()
        self.operations = {}
        self.received = []
        self.loop = None
        self.steam = {
            "state": "running", "running": True, "pid": 7777,
            "started_at": "2026-10-10T00:00:00Z", "uptime_seconds": 3723,
            "session_id": 1, "interactive": True, "installation_detected": True, "stale": False,
        }

    def snapshot(self):
        return {"revision": self.revision, "epoch": self.epoch,
                "stale": False, "observed_at": "2026-10-10T00:00:00Z",
                "resync_required": False, "catalog_version": 1,
                "total": len(self.games), "games": deepcopy(self.games)}

    async def dispatch(self, peers, name, data):
        msg = {"type": "event", "event": name, "data": deepcopy(data)}
        for ws in tuple(peers):
            await ws.send_json(msg)

    def send_change(self, state):
        async def update():
            self.revision += 1
            self.games[0]["observation"]["process"]["state"] = state
            self.games[0]["observation"]["process"]["stale"] = False
            self.games[0]["capabilities"]["start"] = state == "STOPPED"
            self.games[0]["capabilities"]["stop"] = state == "RUNNING"
            self.games[0]["capabilities"]["restart"] = state == "RUNNING"
            await self.dispatch(self.peers, "games.changed",
                {"epoch": self.epoch, "revision": self.revision,
                 "game_id": self.games[0]["id"], "game": self.games[0]})
        asyncio.run_coroutine_threadsafe(update(), self.loop).result(timeout=5)

    def set_library(self, records):
        async def update():
            self.revision += 1
            self.games = deepcopy(records)
            await self.dispatch(self.peers, "games.snapshot", self.snapshot())
        asyncio.run_coroutine_threadsafe(update(), self.loop).result(timeout=5)

    def set_steam(self, running):
        async def update():
            self.steam.update(running=running, state="running" if running else "stopped",
                              pid=7777 if running else None)
            await self.dispatch(self.steam_peers, "steam.snapshot", self.steam)
        asyncio.run_coroutine_threadsafe(update(), self.loop).result(timeout=5)


@pytest.fixture
def games_ui_server():
    fake = FakeContract()
    app = FastAPI()

    @app.get("/steam")
    def steam_page():
        return FileResponse(WEB_ROOT / "steam.html")

    @app.get("/games")
    def games_page():
        return FileResponse(WEB_ROOT / "games.html")

    app.mount("/assets", StaticFiles(directory=WEB_ROOT), name="assets")

    @app.websocket("/api/v1/games/ws")
    async def games_socket(ws: WebSocket):
        fake.loop = asyncio.get_running_loop()
        await ws.accept(subprotocol="streamops-games-v1"
                        if "streamops-games-v1" in ws.scope.get("subprotocols", []) else None)
        fake.peers.add(ws)
        await ws.send_json({"type":"event","event":"games.snapshot","data":fake.snapshot()})
        try:
            while True:
                obj = await ws.receive_json()
                if obj.get("type") != "request": continue
                op, data = obj["operation"], obj.get("payload", {})
                fake.received.append((op, data))
                error = None
                if op == "games.list": result = fake.snapshot()
                elif op == "games.get":
                    result = next((deepcopy(g) for g in fake.games if g["id"] == data["game_id"]), None)
                    if result is None: error = "game_not_found"
                elif op == "games.reconcile":
                    result = next((deepcopy(g) for g in fake.games if g["id"] == data["game_id"]), None)
                elif op == "games.catalog.refresh": result = {"catalog_version":1,"revision":fake.revision}
                elif op == "games.operations.get":
                    result = fake.operations.get(data["operation_id"])
                    if result is None: error = "operation_not_found"
                elif op.startswith("games.lifecycle."):
                    token_ok = any(s.startswith("streamops-game-control.") and len(s) >= 24
                                   for s in ws.scope.get("subprotocols", []))
                    if not token_ok: error = "control_token_required"
                    elif op.endswith("force_stop"): error = "capability_disabled"
                    else:
                        result = {"operation_id":"test-operation","game_id":data["game_id"],
                                  "action":op.split(".")[-1],"status":"PENDING","phase":"QUEUED"}
                        fake.operations[result["operation_id"]] = result
                else: error = "unknown_operation"
                if error:
                    await ws.send_json({"type":"response","request_id":obj["request_id"],
                                        "ok":False,"error":{"code":error,"message":error}})
                else:
                    await ws.send_json({"type":"response","request_id":obj["request_id"],
                                        "ok":True,"data":result})
        except WebSocketDisconnect:
            pass
        finally:
            fake.peers.discard(ws)

    @app.websocket("/api/v1/steam/ws")
    async def steam_socket(ws: WebSocket):
        await ws.accept(subprotocol="streamops-games-v1"
                        if "streamops-games-v1" in ws.scope.get("subprotocols",[]) else None)
        fake.steam_peers.add(ws)
        await ws.send_json({"type":"event","event":"steam.snapshot","data":fake.steam})
        try:
            while True:
                obj=await ws.receive_json()
                op=obj["operation"]
                fake.received.append((op,obj.get("payload",{})))
                if op == "steam.status": result=fake.steam
                elif op == "steam.lifecycle.restart":
                    result=fake.steam
                else:
                    await ws.send_json({"type":"response","request_id":obj["request_id"],
                         "ok":False,"error":{"code":"unknown_operation","message":"unknown"}})
                    continue
                await ws.send_json({"type":"response","request_id":obj["request_id"],
                                     "ok":True,"data":result})
        except WebSocketDisconnect: pass
        finally: fake.steam_peers.discard(ws)

    listener = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    listener.bind(("127.0.0.1",0)); listener.listen(128)
    port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level="warning",lifespan="on",timeout_graceful_shutdown=3))
    thread=threading.Thread(target=server.run,kwargs={"sockets":[listener]},daemon=True)
    thread.start()
    wait_until(lambda:server.started)
    try: yield f"http://127.0.0.1:{port}",fake
    finally:
        # Close live WS consumers before uvicorn lifespan shutdown; do not leave
        # a fixture waiting on a browser that is still open in pytest teardown.
        if fake.loop:
            async def close_peers():
                for ws in tuple(fake.peers | fake.steam_peers):
                    try:
                        await ws.close(code=1001)
                    except Exception:
                        pass
            asyncio.run_coroutine_threadsafe(close_peers(),fake.loop).result(timeout=5)
        server.should_exit=True;thread.join(timeout=10)
        if thread.is_alive(): raise RuntimeError("Fake WS server could not stop")


def test_games_catalog_filter_and_detail(page: Page, games_ui_server):
    base,fake=games_ui_server
    page.goto(base+"/games")
    expect(page.locator("#game-summary")).to_contain_text("1")
    expect(page.locator("#game-library button")).to_have_count(1)
    page.locator("#game-library button").first.click()
    # Display is user-friendly, but its canonical state remains machine-readable.
    expect(page.locator('#game-detail [data-code="CONFIGURED_ONLY"]')).to_have_count(1)
    expect(page.locator('#game-detail [data-code="VERIFIED_ACTIVE"]')).to_have_count(0)
    page.locator("#game-detail .gm-detail-advanced summary").click()
    expect(page.get_by_role("button",name="Force Stop (disabled)")).to_be_disabled()
    fake.set_library([game("First","steam:1"),game("Second","steam:2",state="STOPPED"),
                      game("Third","steam:3")])
    expect(page.locator("#game-library button")).to_have_count(3)
    page.locator("#game-filter").select_option("stopped")
    expect(page.locator("#game-library button")).to_have_count(1)
    page.locator("#game-search").fill("second")
    expect(page.locator("#game-library")).to_contain_text("Second")
    fake.set_library([])
    expect(page.locator("#game-library")).to_contain_text("No matching games")


def test_games_observers_auto_push_without_rest(page: Page, games_ui_server):
    base,fake=games_ui_server
    http_calls=[]
    page.on("request",lambda req:http_calls.append(req.url) if "/api/v1/" in req.url and "ws" not in req.url else None)
    other=page.context.new_page()
    page.goto(base+"/steam");other.goto(base+"/games")
    expect(page.locator("#steam-running-games")).to_contain_text("Diablo IV")
    expect(other.locator("#running-games")).to_contain_text("Diablo IV")
    fake.send_change("STOPPED")
    expect(page.locator("#steam-running-games")).to_contain_text("No running games")
    expect(other.locator("#running-games")).to_contain_text("No running games")
    assert not http_calls
    fake.set_steam(False)
    expect(page.locator("#steam-state")).to_have_text("Stopped")
    expect(page.locator("#steam-games-summary")).to_contain_text("1")
    other.close()


def test_mobile_detail_and_disabled_actions(page: Page, games_ui_server):
    base,_fake=games_ui_server
    page.set_viewport_size({"width":390,"height":844})
    page.goto(base+"/games")
    page.locator("#game-library button").first.click()
    expect(page.locator("#game-detail .gm-back")).to_be_visible()
    expect(page.locator("#games-main")).to_be_hidden()
    expect(page.get_by_role("button",name="Start",exact=True)).to_be_disabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.locator("#game-detail .gm-back").click()
    expect(page.locator("#games-main")).to_be_visible()


def test_steam_ui_ws_only_and_card_order(page: Page, games_ui_server):
    base,_fake=games_ui_server
    page.goto(base+"/steam")
    expect(page.locator("#steam-pid")).to_have_text("7777")
    expect(page.locator("#game-manager-card")).to_contain_text("Manage Games")
    ids=page.locator("main > section").evaluate_all("(els)=>els.map(x=>x.id || (x.classList.contains(\"activity-panel\") ? \"activity-panel\" : \"\"))")
    assert ids.index("steam-status-panel") < ids.index("game-manager-card") < ids.index("activity-panel")
    page.get_by_role("link",name="Manage Games").click()
    expect(page).to_have_url(base+"/games")
    expect(page.get_by_role("heading",name="Game Manager")).to_be_visible()


def test_store_epoch_reorder_and_counts(page: Page, games_ui_server):
    base,_fake=games_ui_server
    page.goto(base+"/games")
    result=page.evaluate("""() => {
      const S=window.StreamOpsGamesStore, s=new S.GameStore();
      s.connection('connected');
      s.snapshot({epoch:'one',revision:9,games:[],stale:false});
      s.changed({epoch:'one',revision:8,game_id:'steam:1',game:{id:'steam:1'}});
      const oldRejected=s.games.size===0;
      s.snapshot({epoch:'two',revision:1,games:[],stale:false});
      return {oldRejected,epoch:s.epoch,registered:s.summary().registered,verified:s.summary().verified};
    }""")
    assert result=={"oldRejected":True,"epoch":"two","registered":0,"verified":0}


def test_generic_inventory_ten_unicode_unknown_and_sort(page: Page, games_ui_server):
    base, fake = games_ui_server
    page.goto(base + "/games")
    records = [
        game("Game " + str(i), "steam:" + str(i + 100), "STOPPED")
        for i in range(10)
    ]
    records[0]["name"] = "Tiếng Việt – trò chơi thử nghiệm tên cực kỳ dài " * 3
    records[1]["provider"] = "epic"
    records[2]["observation"]["process"]["state"] = "UNKNOWN"
    records[2]["observation"]["process"]["stale"] = True
    fake.set_library(records)
    expect(page.locator("#game-library button")).to_have_count(10)
    expect(page.locator("#game-summary")).to_contain_text("Unknown")
    page.locator("#game-search").fill("Tiếng Việt")
    expect(page.locator("#game-library button")).to_have_count(1)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.locator("#game-search").fill("")
    page.locator("#game-filter").select_option("running")
    expect(page.locator("#game-library")).to_contain_text("No matching games")


def test_lifecycle_ack_pending_not_success_and_no_repeat(page: Page, games_ui_server):
    base, fake = games_ui_server
    page.goto(base + "/games")
    page.locator("#game-library button").first.click()
    page.locator(".gm-control-panel summary").click()
    page.locator("#game-control-token").fill("a" * 32)
    page.locator("#apply-token").click()
    expect(page.locator("#token-status")).to_contain_text("Credential ready")
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.get_by_role("button", name="Stop", exact=True).click()
    assert not [op for op, _ in fake.received if op == "games.lifecycle.stop"]
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Stop", exact=True).click()
    # Verify the actual mutation reached WS before checking asynchronous UI state.
    # A missing request is a product/transport bug, never treated as a PASS.
    wait_until(lambda: len([op for op, _ in fake.received if op == "games.lifecycle.stop"]) == 1)
    expect(page.locator("#games-error")).to_be_hidden()
    expect(page.locator("#game-detail")).to_contain_text("PENDING / QUEUED")
    assert len([op for op, _ in fake.received if op == "games.lifecycle.stop"]) == 1
    assert "SUCCEEDED" not in page.locator("#game-detail").inner_text()
    page.locator("#game-detail .gm-detail-advanced summary").click()
    expect(page.get_by_role("button", name="Force Stop (disabled)")).to_be_disabled()


def test_reconnect_resync_without_mutation_replay(page: Page, games_ui_server):
    base, fake = games_ui_server
    page.goto(base + "/games")
    expect(page.locator("#status-text")).to_contain_text("connected")
    page.evaluate("""() => {
      const s = window.StreamOpsGames.store;
      s.operation({operation_id: 'pending-test',game_id:'steam:2344520',
        action:'stop',status:'PENDING',phase:'STOPPING'});
    }""")
    assert not [x for x in fake.received if x[0].startswith("games.lifecycle.")]
    page.evaluate("window.StreamOpsGames.client.socket.close()")
    expect(page.locator("#status-text")).to_contain_text("offline")
    expect(page.locator("#status-text")).to_contain_text("connected", timeout=10000)
    expect(page.locator("#game-library")).to_contain_text("Diablo IV")
    assert not [x for x in fake.received if x[0].startswith("games.lifecycle.")]
    assert [op for op, _ in fake.received if op == "games.operations.get"]


def test_state_model_null_epoch_gap_recovery(page: Page, games_ui_server):
    base, _fake = games_ui_server
    page.goto(base + "/games")
    report = page.evaluate("""() => {
      const s = new window.StreamOpsGamesStore.GameStore();
      s.connection('connected');
      s.snapshot({epoch:'e1',revision:3,games:[
        {id:'steam:1',name:'A',observation:{process:{state:'RUNNING',stale:false},
          owned:null,installed:false,obsCapture:'CONFIGURED_ONLY'}}
      ],stale:false});
      const counts1 = s.summary();
      s.changed({epoch:'e1',revision:5,game_id:'steam:1',game:{
        id:'steam:1',name:'A',observation:{process:{state:'STOPPED',stale:false}}}});
      const gap = s.needsResync;
      s.operation({operation_id:'op1',status:'PENDING',phase:'QUEUED'});
      s.snapshot({epoch:'e2',revision:1,games:[],stale:false});
      const reset = s.epoch === 'e2' && s.operations.get('op1').status === 'UNKNOWN';
      s.connection('disconnected');
      const offline = s.summary().registered === null;
      return {initial:counts1.running===1 && counts1.verified===0,gap,reset,offline};
    }""")
    assert report == {"initial": True, "gap": True, "reset": True, "offline": True}


@pytest.mark.parametrize("width,height",[(360,800),(390,844),(768,1024),(1440,900)])
def test_games_responsive_geometry_and_detail_navigation(
    page: Page, games_ui_server, width: int, height: int, tmp_path: Path
):
    base, _fake = games_ui_server
    page.set_viewport_size({"width":width,"height":height})
    page.goto(base + "/games")
    expect(page.locator("#game-library button")).to_have_count(1)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(tmp_path / ("games-" + str(width) + ".png")), full_page=True)
    page.locator("#game-library button").first.click()
    expect(page.locator("#game-detail")).to_contain_text("Windows session")
    expect(page.locator("#game-detail")).to_contain_text("CONFIGURED_ONLY")
    related = page.locator("#game-detail .gm-related")
    assert not related.evaluate("(e) => e.open")
    related.locator("summary").click()
    assert related.evaluate("(e) => e.open")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if width <= 900:
        expect(page.locator("#games-main")).to_be_hidden()
        expect(page.locator("#game-detail .gm-back")).to_be_visible()
        page.locator("#game-detail .gm-back").click()
        expect(page.locator("#games-main")).to_be_visible()
    else:
        expect(page.locator("#games-main")).to_be_visible()
        expect(page.locator("#game-detail .gm-back")).to_be_hidden()


def test_disabled_session_capture_error_and_observation_safety(page: Page, games_ui_server):
    base, fake = games_ui_server
    page.goto(base + "/games")
    record = game()
    record["observation"]["obsCapture"] = "ERROR"
    record["observation"]["window"] = "UNKNOWN"
    record["observation"]["process"]["stale"] = True
    record["capabilities"] = {"start":False,"stop":False,"restart":False,"force_stop":False}
    record["capability_reason"] = "wrong_desktop_session"
    fake.set_library([record])
    page.locator("#game-library button").first.click()
    expect(page.locator("#game-detail")).to_contain_text("ERROR")
    expect(page.locator("#game-detail")).to_contain_text("UNKNOWN")
    expect(page.get_by_role("button",name="Stop",exact=True)).to_be_disabled()
    expect(page.get_by_role("button",name="Stop",exact=True)).to_have_attribute(
        "title","wrong_desktop_session")
    assert not [op for op, _ in fake.received if op.startswith("games.lifecycle.")]
