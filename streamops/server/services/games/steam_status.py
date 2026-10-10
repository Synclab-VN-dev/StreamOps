"""Minimal Steam WS observer, reusing the existing SteamService."""
from __future__ import annotations
import asyncio
from datetime import datetime,timezone

class SteamStatusHub:
    def __init__(self, steam, *, interval=1., heartbeat_interval=15.):
        self.steam=steam
        self.interval, self.heartbeat_interval = interval,heartbeat_interval
        self._subscribers=set()
        self._last=None
        self._monitor=None
        self._heartbeat=None
        self._refresh=asyncio.Event()

    async def start(self):
        if self._monitor is None:
            self._monitor=asyncio.create_task(self._run())
            self._heartbeat=asyncio.create_task(self._beat())

    async def close(self):
        tasks=[t for t in (self._monitor,self._heartbeat) if t]
        for task in tasks: task.cancel()
        if tasks: await asyncio.gather(*tasks,return_exceptions=True)
        self._monitor=self._heartbeat=None
        self._subscribers.clear()

    def trigger_refresh(self): self._refresh.set()

    async def snapshot(self):
        try:
            current=(await self.steam.status()).api_payload()
            current["stale"]=False
        except asyncio.CancelledError:
            raise
        except Exception:
            current={"state":"unknown","running":None,"pid":None,"started_at":None,
                     "uptime_seconds":None,"session_id":None,"interactive":None,
                     "installation_detected":None,"stale":True,
                     "error_code":"steam_status_failed"}
        signature=tuple((k,v) for k,v in current.items() if k != "uptime_seconds")
        if self._last != signature:
            self._last=signature
            self.broadcast("steam.snapshot",current)
        return current

    async def subscribe(self):
        q=asyncio.Queue(maxsize=16)
        self._subscribers.add(q)
        try:
            value=await self.snapshot()
            # A newly subscribed client first receives a complete snapshot.
            while not q.empty():
                q.get_nowait()
            q.put_nowait({"type":"event","event":"steam.snapshot","data":value})
        except BaseException:
            self._subscribers.discard(q)
            raise
        return q

    def unsubscribe(self,q): self._subscribers.discard(q)

    def broadcast(self,event,data):
        for q in tuple(self._subscribers):
            if q.full(): q.get_nowait()
            q.put_nowait({"type":"event","event":event,"data":data})

    async def _run(self):
        while True:
            try:
                if self._subscribers:
                    await self.snapshot()
            except asyncio.CancelledError: raise
            except Exception: pass
            try:
                await asyncio.wait_for(self._refresh.wait(), self.interval)
                self._refresh.clear()
            except TimeoutError: pass

    async def _beat(self):
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            self.broadcast("steam.heartbeat",{"observed_at":datetime.now(timezone.utc).isoformat()})
