"""UNIT-06/G4: observer events, subscriber lifecycle, and loss-visible recovery."""
import asyncio
from streamops.server.tests.test_games_lifecycle import GAME,FakeGamePlatform,build_service

def test_revisions_are_deduplicated_per_game_and_monotonic(tmp_path):
    async def main():
        svc,platform=build_service(tmp_path)
        hub=svc.hub
        q=await hub.subscribe()
        first=hub.revision
        assert first==1
        initial=q.get_nowait()
        assert initial["event"]=="games.snapshot"
        assert initial["data"]["revision"]==first
        await svc.observer.refresh()
        assert hub.revision==first
        assert q.empty()
        platform.running=True
        await svc.observer.refresh()
        event=q.get_nowait()
        assert event["event"]=="games.changed"
        assert event["data"]["revision"]==first+1
        await svc.observer.refresh()
        assert q.empty()
        platform.running=False
        await svc.observer.refresh()
        assert q.get_nowait()["data"]["revision"]==first+2
        hub.unsubscribe(q)
        await svc.lifecycle.close()
    asyncio.run(main())

def test_resubscribe_gets_complete_snapshot_and_cleanup(tmp_path):
    async def main():
        svc,platform=build_service(tmp_path)
        hub=svc.hub
        q1=await hub.subscribe()
        assert q1.get_nowait()["event"]=="games.snapshot"
        hub.unsubscribe(q1)
        assert q1 not in hub._subscribers
        platform.running=True
        await svc.observer.refresh()
        assert q1.empty()
        q2=await hub.subscribe()
        item=q2.get_nowait()
        assert item["event"]=="games.snapshot"
        assert item["data"]["games"][0]["observation"]["process"]["state"]=="RUNNING"
        assert q2.empty()
        hub.unsubscribe(q2)
        assert not hub._subscribers
        await svc.lifecycle.close()
    asyncio.run(main())

def test_error_uses_unknown_and_marks_hub_snapshot_stale(tmp_path):
    class Broken(FakeGamePlatform):
        def inspect(self,game): raise OSError("synthetic process scan failure")
    async def main():
        svc,_=build_service(tmp_path,Broken())
        hub=svc.hub
        snap=hub.snapshot()
        assert snap["total"]==0
        await svc.observer.refresh()
        snap=hub.snapshot()
        assert snap["stale"] is True
        assert snap["games"][0]["observation"]["process"]["state"]=="UNKNOWN"
        assert not any(snap["games"][0]["capabilities"].values())
    asyncio.run(main())

def test_backpressure_resync_and_sqlite_result_recovery(tmp_path):
    async def main():
        svc,_=build_service(tmp_path)
        hub=svc.hub
        q=await hub.subscribe()
        q.get_nowait()
        record=svc.lifecycle.store
        item,_=record.begin(GAME,"start","pending")
        record.update(item["id"],"SUCCEEDED","COMPLETE")
        for i in range(150):
            hub.broadcast("games.operation",{"operation_id":item["id"],"game_id":GAME,
                                               "status":"RUNNING","phase":"TEST"})
        messages=[]
        while not q.empty(): messages.append(q.get_nowait())
        assert any(msg["event"]=="games.snapshot" and msg["data"]["resync_required"] for msg in messages)
        assert svc.operation(item["id"])["status"]=="SUCCEEDED"
        hub.unsubscribe(q)
    asyncio.run(main())

def test_hub_start_close_stops_background_monitor(tmp_path):
    async def main():
        svc,_=build_service(tmp_path)
        hub=svc.hub
        await hub.start()
        await hub.start()
        assert hub._monitor_task is not None and not hub._monitor_task.done()
        await hub.close()
        assert hub._monitor_task is None
        assert not hub._subscribers
        await svc.lifecycle.close()
    asyncio.run(main())
