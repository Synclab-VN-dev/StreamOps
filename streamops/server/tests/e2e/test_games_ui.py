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

    def emit(self, event, data, *, steam=False):
        """Push a real JSON WS event to each subscribed observer."""
        async def dispatch_event():
            await self.dispatch(self.steam_peers if steam else self.peers, event, data)
        asyncio.run_coroutine_threadsafe(dispatch_event(), self.loop).result(timeout=5)

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
    expect(page.locator('#game-detail .gm-detail-section').first.locator('[data-code="CONFIGURED_ONLY"]')).to_have_count(1)
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
    expect(page.locator("#steam-running-games")).to_contain_text("No games running")
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
    expect(page.locator("#game-detail .gm-detail-back")).to_be_visible()
    expect(page.locator("#games-main")).to_be_hidden()
    expect(page.get_by_role("button",name="Start",exact=True)).to_be_disabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.locator("#game-detail .gm-detail-back").click()
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
    expect(page.locator('#game-detail .gm-detail-section').first.locator('[data-code="CONFIGURED_ONLY"]')).to_have_count(1)
    related = page.locator("#game-detail .gm-detail-advanced")
    assert not related.evaluate("(e) => e.open")
    related.locator("summary").click()
    assert related.evaluate("(e) => e.open")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if width <= 900:
        expect(page.locator("#games-main")).to_be_hidden()
        expect(page.locator("#game-detail .gm-detail-back")).to_be_visible()
        page.locator("#game-detail .gm-detail-back").click()
        expect(page.locator("#games-main")).to_be_visible()
    else:
        expect(page.locator("#games-main")).to_be_visible()
        expect(page.locator("#game-detail .gm-detail-back")).to_be_visible()


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
    expect(page.locator('#game-detail [data-code="ERROR"]')).to_have_count(2)
    expect(page.locator('#game-detail [data-code="UNKNOWN"]')).not_to_have_count(0)
    expect(page.get_by_role("button",name="Stop",exact=True)).to_be_disabled()
    expect(page.get_by_role("button",name="Stop",exact=True)).to_have_attribute(
        "title","wrong_desktop_session")
    assert not [op for op, _ in fake.received if op.startswith("games.lifecycle.")]


def test_steam_summary_limits_multiple_observed_games_and_expands(page: Page, games_ui_server):
    """Observed 5 running / 12 registered remain truthful, and pagination is interactive."""
    base, fake = games_ui_server
    page.goto(base + "/steam")
    running = [game(f"Observed game {i}", f"steam:{500+i}", "RUNNING") for i in range(5)]
    library = [game(f"Registered game {i}", f"steam:{600+i}", "STOPPED") for i in range(7)]
    fake.set_library(running + library)
    expect(page.locator("#steam-running-games .gm-game-row")).to_have_count(3)
    expect(page.locator("#steam-games-summary")).to_contain_text("12")
    expect(page.locator("#steam-games-summary")).to_contain_text("5")
    expand = page.get_by_role("button", name="+2 more games")
    expect(expand).to_have_attribute("aria-expanded", "false")
    expand.click()
    expect(page.locator("#steam-running-games .gm-game-row")).to_have_count(5)
    collapse = page.get_by_role("button", name="Show fewer games")
    expect(collapse).to_have_attribute("aria-expanded", "true")
    collapse.click()
    expect(page.locator("#steam-running-games .gm-game-row")).to_have_count(3)
    assert not any(op.startswith("games.lifecycle") for op, _ in fake.received)


def test_games_summary_selectors_zero_unknown_false_and_independent_steam(page: Page, games_ui_server):
    """UNIT-02: show unknown as unknown, not a fabricated zero; keep launchers distinct."""
    base, fake = games_ui_server
    page.goto(base + "/steam")
    expect(page.locator("#steam-state")).to_have_text("Running")
    fake.set_library([])
    expect(page.locator("#steam-games-summary")).to_contain_text("0")
    records = [
        game("Alpha", "steam:1000", "RUNNING"),
        game("Bravo", "other:1001", "STOPPED"),
        game("Charlie", "other:1002", "RUNNING"),
    ]
    records[0]["observation"]["owned"] = False
    records[0]["observation"]["installed"] = True
    records[0]["observation"]["obsCapture"] = "VERIFIED_ACTIVE"
    records[1]["provider"] = "other"
    records[1]["observation"]["owned"] = None
    records[1]["observation"]["installed"] = False
    fake.set_library(records)
    expect(page.locator("#steam-games-summary")).to_contain_text("3")
    expect(page.locator("#steam-games-summary")).to_contain_text("2")
    fake.set_steam(False)
    expect(page.locator("#steam-state")).to_have_text("Stopped")
    # Stopping the launcher does NOT mark a verified independent game STOPPED.
    expect(page.locator("#steam-games-summary")).to_contain_text("2")
    records[2]["observation"]["process"]["state"] = "UNKNOWN"
    records[2]["observation"]["process"]["stale"] = True
    fake.set_library(records)
    expect(page.locator("#steam-games-summary")).to_contain_text("—")
    assert page.evaluate("""() => {
      const m=window.StreamOpsGamesStore;
      const s=new m.GameStore();s.connection('connected');
      s.snapshot({epoch:'owned-false',revision:1,stale:false,games:[
       {id:'other:1',name:'other',observation:{owned:false,installed:true,
         obsCapture:'VERIFIED_ACTIVE',process:{state:'RUNNING',stale:false}}},
       {id:'other:2',name:'other2',observation:{owned:null,installed:false,
         obsCapture:'CONFIGURED_ONLY',process:{state:'STOPPED',stale:false}}}
      ]});
      const c=s.summary();
      return c.registered===2 && c.running===1 && c.verified===1 &&
       s.games.get('other:1').observation.owned===false &&
       s.games.get('other:2').observation.owned===null;
    }""")


def test_back_close_escape_focus_and_navigation(page: Page, games_ui_server):
    """UNIT-07/E2E-02/04: navigation, keyboard dismissal and focus restoration."""
    base, _fake = games_ui_server
    page.set_viewport_size({"width":390,"height":844})
    page.goto(base + "/steam")
    page.get_by_role("link",name="Manage Games").click()
    expect(page).to_have_url(base + "/games")
    opener=page.locator('#game-library .gm-game-row[data-game-id="steam:2344520"]')
    opener.focus()
    opener.press("Enter")
    expect(page.locator("#game-detail")).to_contain_text("Diablo IV")
    expect(page.locator("#games-main")).to_be_hidden()
    page.keyboard.press("Escape")
    expect(page.locator("#games-main")).to_be_visible()
    assert page.evaluate(
        'document.activeElement?.dataset?.gameId === "steam:2344520"'
    ), "Escape must return focus to the game which opened the panel"
    opener.click()
    page.get_by_role("button",name="Close game details").click()
    assert page.evaluate(
        'document.activeElement?.dataset?.gameId === "steam:2344520"'
    ), "Close button must return focus to original game row"
    opener.click()
    page.get_by_role("button",name="Back to games").click()
    expect(page.locator("#games-main")).to_be_visible()
    page.get_by_role("link",name="← Steam").click()
    expect(page).to_have_url(base + "/steam")


def test_generic_game_list_sorting_is_deterministic(page: Page, games_ui_server):
    """UNIT-06: generic provider metadata is sorted by name and search is read only."""
    base, fake = games_ui_server
    page.goto(base + "/games")
    records=[
      game("Zulu", "other:1", "STOPPED"),
      game("Alpha", "steam:2", "RUNNING"),
      game("Mango", "other:3", "STOPPED"),
    ]
    records[0]["provider"]="other"
    records[2]["provider"]="other"
    fake.set_library(records)
    names=page.locator("#game-library .gm-game-label strong")
    expect(names).to_have_count(3)
    assert names.all_text_contents()==["Alpha","Mango","Zulu"]
    page.locator("#game-search").fill("other")
    expect(names).to_have_count(2)
    assert not any(op.startswith("games.lifecycle") for op,_ in fake.received)


def test_ws_cached_snapshots_cannot_replay_across_generation_and_cleanup(page: Page, games_ui_server):
    """UNIT-03: old snapshots are not fresh; detach listeners and pagehide cleanup."""
    base, fake = games_ui_server
    page.goto(base + "/games")
    expect(page.locator("#status-text")).to_contain_text("connected")
    page.wait_for_function("window.StreamOpsGames.client.cachedEvents.has('games.snapshot')")
    before = page.evaluate("""async () => {
      const c=window.StreamOpsGames.client;
      const old=c.cachedEvents.get('games.snapshot');
      let duplicate=0;
      const callback=()=>duplicate++;
      const off=c.on('games.snapshot',callback,{replay:true});
      off();
      await Promise.resolve();await Promise.resolve();
      return {duplicate,revision:old.revision,generation:c.generation};
    }""")
    assert before["duplicate"] == 0, "Unsubscribed replay callback must not execute"
    page.evaluate("window.StreamOpsGames.client.socket.close()")
    expect(page.locator("#status-text")).to_contain_text("offline")
    assert page.evaluate("window.StreamOpsGames.client.cachedEvents.size") == 0
    expect(page.locator("#status-text")).to_contain_text("connected", timeout=15000)
    page.wait_for_function("window.StreamOpsGames.client.cachedEvents.has('games.snapshot')")
    assert page.evaluate("!window.StreamOpsGames.store.stale")
    assert page.evaluate("window.StreamOpsGames.client.generation") > before["generation"]
    assert not any(name.startswith("games.lifecycle.") for name, _ in fake.received)
    page.evaluate("window.dispatchEvent(new Event('pagehide'))")
    assert page.evaluate("""() => {
      const c=window.StreamOpsGames.client;
      return c.destroyed && !c.connected && c.cachedEvents.size===0 &&
             c.pending.size===0 && c.watchdogTimer===null;
    }""")
    page.evaluate("window.dispatchEvent(new Event('pageshow'))")
    expect(page.locator("#status-text")).to_contain_text("connected", timeout=15000)


@pytest.mark.parametrize("action,state",[
    ("start","STOPPED"),("stop","RUNNING"),("restart","RUNNING")
])
def test_games_lifecycle_progress_terminal_events_and_safety(page: Page, games_ui_server, action, state):
    """UNIT-04/E2E-07: real control WS, confirmation, idempotency, operation progress."""
    base, fake = games_ui_server
    page.goto(base + "/games")
    fake.set_library([game("Lifecycle", "steam:2344520", state)])
    page.locator('#game-library button[data-game-id="steam:2344520"]').click()
    page.locator(".gm-control-panel summary").click()
    page.locator("#game-control-token").fill("x"*32)
    page.locator("#apply-token").click()
    expect(page.locator("#token-status")).to_contain_text("Credential ready")
    target=page.locator('#game-detail button[data-action="'+action+'"]')
    expect(target).to_be_enabled()
    page.once("dialog", lambda dlg: dlg.dismiss())
    target.click()
    assert not any(op == "games.lifecycle."+action for op,_ in fake.received)
    page.once("dialog", lambda dlg: dlg.accept())
    target.click()
    wait_until(lambda: len([data for op,data in fake.received if op=="games.lifecycle."+action])==1)
    requests=[data for op,data in fake.received if op=="games.lifecycle."+action]
    assert requests[0]["game_id"]=="steam:2344520"
    assert requests[0]["idempotency_key"].startswith("game-")
    expect(page.locator("#game-detail .gm-operation")).to_contain_text("PENDING / QUEUED")
    expect(target).to_be_disabled()
    assert not any("succeeded" in text.lower() for text in page.locator("#activity-log li").all_text_contents())
    fake.emit("games.operation",{
        "operation_id":"test-operation","game_id":"steam:2344520",
        "action":action,"status":"RUNNING","phase":"VERIFYING",
    })
    expect(page.locator("#game-detail .gm-operation")).to_contain_text("RUNNING / VERIFYING")
    fake.emit("games.operation",{
        "operation_id":"test-operation","game_id":"steam:2344520",
        "action":action,"status":"SUCCEEDED","phase":"VERIFIED",
    })
    expect(page.locator("#game-detail .gm-operation")).to_contain_text("SUCCEEDED / VERIFIED")
    assert len([op for op,_ in fake.received if op=="games.lifecycle."+action])==1
    # Delayed ACK/event from an earlier state cannot undo terminal completion.
    fake.emit("games.operation",{
        "operation_id":"test-operation","game_id":"steam:2344520",
        "action":action,"status":"PENDING","phase":"QUEUED",
    })
    expect(page.locator("#game-detail .gm-operation")).to_contain_text("SUCCEEDED / VERIFIED")


@pytest.mark.parametrize("terminal,phase",[
    ("FAILED","WRONG_SESSION"),("UNKNOWN","TIMEOUT"),
])
def test_games_operation_failure_never_claims_success(page: Page, games_ui_server, terminal, phase):
    """E2E-07/08: failure or uncertain outcome must not turn into SUCCEEDED."""
    base, fake = games_ui_server
    page.goto(base+"/games")
    page.locator('#game-library button[data-game-id="steam:2344520"]').click()
    fake.emit("games.operation",{
      "operation_id":"op-failure","game_id":"steam:2344520",
      "action":"stop","status":terminal,"phase":phase,"code":"test_"+phase.lower(),
    })
    expect(page.locator("#game-detail .gm-operation")).to_contain_text(terminal+" / "+phase)
    if terminal=="UNKNOWN":
        expect(page.locator("#game-detail")).to_contain_text("outcome unknown")
    assert "SUCCEEDED" not in page.locator("#game-detail").inner_text()
    assert not any(op.startswith("games.lifecycle.") for op,_ in fake.received)


def test_game_process_external_exit_and_disabled_session_with_obs_error(page: Page, games_ui_server):
    """UNIT-06/E2E-03: loss of running process is observed, not synthesized as success."""
    base, fake = games_ui_server
    page.goto(base+"/games")
    page.locator('#game-library button[data-game-id="steam:2344520"]').click()
    expect(page.locator('#game-detail [data-code="RUNNING"]')).to_have_count(1)
    fake.send_change("STOPPED")
    expect(page.locator('#game-detail [data-code="STOPPED"]')).to_have_count(1)
    assert "2100" not in page.locator("#game-detail .gm-detail-metrics").inner_text()
    record=game(state="RUNNING")
    record["capabilities"].update(start=False, stop=False, restart=False)
    record["capability_reason"]="wrong_desktop_session"
    record["observation"]["process"]["stale"]=True
    record["observation"]["obsCapture"]="ERROR"
    record["observation"]["window"]="UNKNOWN"
    fake.set_library([record])
    expect(page.locator('#game-detail [data-code="ERROR"]')).to_have_count(2)
    expect(page.locator("#game-detail button[data-action='stop']")).to_be_disabled()
    expect(page.locator("#game-detail button[data-action='stop']")).to_have_attribute("title","wrong_desktop_session")
    assert not any(op.startswith("games.lifecycle.") for op,_ in fake.received)


def test_lifecycle_disconnect_marks_unknown_and_reconciles_without_replay(page: Page, games_ui_server):
    """E2E-08: recover by operation ID, never resend a start/stop/restart."""
    base, fake = games_ui_server
    page.goto(base+"/games")
    page.locator('#game-library button[data-game-id="steam:2344520"]').click()
    page.evaluate("""() => {
      window.StreamOpsGames.store.operation({
        operation_id:'recover-op',game_id:'steam:2344520',
        action:'stop',status:'PENDING',phase:'QUEUED'
      })
    }""")
    page.evaluate("window.StreamOpsGames.client.socket.close()")
    expect(page.locator("#status-text")).to_contain_text("offline")
    expect(page.locator("#game-detail .gm-operation")).to_contain_text("UNKNOWN / RECOVERY_REQUIRED")
    expect(page.locator("#game-detail button[data-action='stop']")).to_be_disabled()
    expect(page.locator("#status-text")).to_contain_text("connected",timeout=15000)
    # Fake backend has no record of this operation. Failed read-only lookup must
    # not replay the original mutating command.
    wait_until(lambda: any(name=="games.operations.get" and p.get("operation_id")=="recover-op"
                           for name,p in fake.received))
    expect(page.locator("#game-detail .gm-operation")).to_contain_text("UNKNOWN / RECOVERY_REQUIRED")
    assert not any(op.startswith("games.lifecycle.") for op,_ in fake.received)
    page.get_by_role("button",name="Refresh / reconcile process").click()
    wait_until(lambda: any(op=="games.reconcile" for op,_ in fake.received))
    assert not any(op.startswith("games.lifecycle.") for op,_ in fake.received)


@pytest.mark.parametrize("width,height",[(360,800),(390,844),(768,1024),(1440,900)])
def test_games_keyboard_focus_live_status_and_touch_geometry(page: Page, games_ui_server, width, height):
    """E2E-11: keyboard operation, visible focus, machine-readable status, no clipping."""
    base, fake = games_ui_server
    page.set_viewport_size({"width":width,"height":height})
    page.goto(base+"/games")
    expect(page.locator("#game-library .gm-game-row")).to_have_count(1)
    search=page.locator("#game-search")
    search.focus()
    assert search.evaluate("(e)=>e.matches(':focus-visible')")
    assert search.evaluate("(e)=>getComputedStyle(e).outlineStyle!=='none'")
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement?.id==='game-filter'")
    opener=page.locator('#game-library button[data-game-id="steam:2344520"]')
    opener.focus()
    opener.press("Enter")
    detail=page.locator("#game-detail")
    expect(detail).to_contain_text("Diablo IV")
    expect(detail.locator('[data-code="CONFIGURED_ONLY"]')).not_to_have_count(0)
    assert detail.get_attribute("aria-label")=="Game detail"
    sizes=page.evaluate("""() => {
      const nodes=[...document.querySelectorAll('#game-detail .gm-detail-action-row button')];
      return nodes.map(e=>({w:e.getBoundingClientRect().width,h:e.getBoundingClientRect().height}));
    }""")
    assert len(sizes)==3 and all(x["h"]>=44 and x["w"]>=44 for x in sizes)
    assert page.evaluate("document.documentElement.scrollWidth<=window.innerWidth")
    page.keyboard.press("Escape")
    assert page.evaluate('document.activeElement?.dataset?.gameId==="steam:2344520"')
    assert page.evaluate("document.documentElement.scrollWidth<=window.innerWidth")
    assert not any(name.startswith("games.lifecycle.") for name,_ in fake.received)


def test_heartbeat_is_read_only_deduplicated_and_resyncs_epoch_gap(page: Page, games_ui_server):
    """UNIT-03: normal heartbeat must not log duplicates; epoch mismatch refetches."""
    base, fake = games_ui_server
    page.goto(base+"/games")
    expect(page.locator("#game-library .gm-game-row")).to_have_count(1)
    page.wait_for_function("!window.StreamOpsGames.store.loading")
    count=page.locator("#activity-log li").count()
    before=len([op for op,_ in fake.received if op=="games.list"])
    fake.emit("games.heartbeat",{"epoch":fake.epoch})
    expect(page.locator("#activity-log li")).to_have_count(count)
    assert len([op for op,_ in fake.received if op=="games.list"]) == before
    fake.emit("games.heartbeat",{"epoch":"node-restarted-unknown"})
    wait_until(lambda: len([op for op,_ in fake.received if op=="games.list"]) > before)
    expect(page.locator("#game-library")).to_contain_text("Diablo IV")
    assert not any(op.startswith("games.lifecycle.") for op,_ in fake.received)
