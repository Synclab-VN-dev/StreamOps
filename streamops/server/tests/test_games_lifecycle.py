"""Safety tests use controllable synthetic games, never real Diablo IV."""
from __future__ import annotations
import asyncio
from pathlib import Path
import pytest
from streamops.server.services.games.models import GameObservation, ProcessIdentity
from streamops.server.services.games.catalog import GameCatalogService
from streamops.server.services.games.providers.static import StaticProvider
from streamops.server.services.games.observer import GameObserver
from streamops.server.services.games.status_hub import GameStatusHub
from streamops.server.services.games.operations import GameOperationStore
from streamops.server.services.games.lifecycle import GameLifecycle, GameServiceError
from streamops.server.services.games.service import GameService

GAME = "steam:2344520"

class FakeGamePlatform:
    def __init__(self):
        self.running = False
        self.start_calls = 0
        self.stop_calls = 0
        self.installed = True
    def inspect(self, game):
        return GameObservation(installed=self.installed, process=ProcessIdentity(
            state="RUNNING" if self.running else "STOPPED",
            pid=23456 if self.running else None,
            session_id=1 if self.running else None,
            executable="C:/Steam/common/Diablo IV/Diablo IV.exe" if self.running else None,
            created_at="2026-10-10T00:00:00Z" if self.running else None,
            stale=False), window="BACKGROUND" if self.running else "NOT_DETECTED")
    def start(self, game):
        self.start_calls += 1
        self.running = True
    def stop(self, game, expected):
        assert expected.pid == 23456
        self.stop_calls += 1
        self.running = False

def build_service(tmp_path: Path, platform=None, *, interval=.02):
    platform = platform or FakeGamePlatform()
    catalog = GameCatalogService(StaticProvider())
    catalog.refresh()
    observer = GameObserver(catalog,platform)
    hub = GameStatusHub(observer,catalog,reconcile_interval=interval,heartbeat_interval=15.)
    store = GameOperationStore(tmp_path / "ops.sqlite")
    lifecycle = GameLifecycle(catalog,observer,hub,store,timeout=1.,interval=.01)
    return GameService(catalog,observer,hub,lifecycle),platform

async def complete(service, key, action):
    op = await service.action(GAME,action,key)
    for _ in range(100):
        status=service.operation(op["id"])
        if status["status"] in ("SUCCEEDED","FAILED","UNKNOWN"):
            return status
        await asyncio.sleep(.01)
    raise AssertionError("operation did not finish")

def test_start_stop_restart_are_verified_and_idempotent(tmp_path):
    async def scenario():
        service,platform=build_service(tmp_path)
        await service.hub.start()
        try:
            started=await complete(service,"start-1","start")
            assert started["status"]=="SUCCEEDED"
            repeated=await service.action(GAME,"start","start-1")
            assert repeated["id"]==started["id"]
            assert platform.start_calls==1
            restarted=await complete(service,"restart-1","restart")
            assert restarted["status"]=="SUCCEEDED"
            assert platform.stop_calls==1 and platform.start_calls==2
            stopped=await complete(service,"stop-1","stop")
            assert stopped["status"]=="SUCCEEDED"
            assert platform.stop_calls==2
        finally:
            await service.lifecycle.close()
            await service.hub.close()
    asyncio.run(scenario())

def test_capability_blocks_unknown_installation(tmp_path):
    async def scenario():
        platform=FakeGamePlatform()
        platform.installed=False
        service,_=build_service(tmp_path,platform)
        with pytest.raises(GameServiceError) as exc:
            await service.action(GAME,"start","disabled-1")
        assert exc.value.code=="capability_disabled"
        assert platform.start_calls==0
    asyncio.run(scenario())

def test_pending_operation_marked_unknown_after_node_restart(tmp_path):
    path=tmp_path/"ops.sqlite"
    store=GameOperationStore(path)
    item,_=store.begin(GAME,"start","key")
    assert store.get(item["id"])["status"]=="PENDING"
    reloaded=GameOperationStore(path)
    assert reloaded.get(item["id"])["status"]=="UNKNOWN"
    previous,created=reloaded.begin(GAME,"start","key")
    assert not created and previous["id"]==item["id"]

def test_hub_pushes_change_and_deduplicates_timestamps(tmp_path):
    async def scenario():
        service,platform=build_service(tmp_path)
        hub=service.hub
        await hub.start()
        q1=await hub.subscribe()
        q2=await hub.subscribe()
        try:
            while not q1.empty(): q1.get_nowait()
            while not q2.empty(): q2.get_nowait()
            initial=hub.revision
            await service.observer.refresh()
            assert hub.revision==initial  # observed_at must not advance revision
            platform.running=True  # external game start, no API mutation
            hub.trigger_refresh()
            a=await asyncio.wait_for(q1.get(),1.0)
            b=await asyncio.wait_for(q2.get(),1.0)
            assert a["event"]==b["event"]=="games.changed"
            assert a["data"]["revision"]==b["data"]["revision"]>initial
            assert a["data"]["epoch"]==hub.epoch
        finally:
            hub.unsubscribe(q1);hub.unsubscribe(q2)
            await service.lifecycle.close();await hub.close()
    asyncio.run(scenario())

def test_slow_subscriber_gets_explicit_resync_marker(tmp_path):
    async def scenario():
        service,_=build_service(tmp_path)
        hub=service.hub
        q=await hub.subscribe()
        try:
            while not q.empty(): q.get_nowait()
            for i in range(170):
                hub.broadcast("games.operation", {"operation_id":f"op-{i}","game_id":GAME,"action":"start","status":"RUNNING","phase":"STARTING"})
            markers=[]
            while not q.empty():
                markers.append(q.get_nowait())
            assert any(m["event"]=="games.snapshot" and m["data"]["resync_required"] for m in markers)
            assert hub.revision >= 170
        finally:
            hub.unsubscribe(q)
    asyncio.run(scenario())
