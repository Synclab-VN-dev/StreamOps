"""One shared Game monitor, monotonic revisions and loss-visible fan-out."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import json
import uuid
from .models import GameRecord

def _now():
    return datetime.now(timezone.utc).isoformat()

def _signature(record: GameRecord) -> str:
    value = record.model_dump()
    value.pop("revision", None)
    value["observation"]["process"].pop("observed_at", None)
    return json.dumps(value, sort_keys=True)

class GameStatusHub:
    def __init__(self, observer, catalog, *, reconcile_interval: float = 1.0, heartbeat_interval: float = 15.0):
        self.observer, self.catalog = observer, catalog
        self.reconcile_interval, self.heartbeat_interval = reconcile_interval, heartbeat_interval
        self._revision = 0
        self.epoch = uuid.uuid4().hex  # clients reset revision on node restart
        self._signatures: dict[str,str] = {}
        self._records: dict[str,GameRecord] = {}
        self._subscribers: set[asyncio.Queue] = set()
        self._refresh = asyncio.Event()
        self._monitor_task = None
        self._heartbeat_task = None
        observer.bind_hub(self)

    @property
    def revision(self):
        return self._revision

    def snapshot(self, *, resync_required=False):
        return {"revision": self._revision, "epoch": self.epoch, "observed_at": _now(), "stale": False,
            "resync_required": resync_required,
            "total": len(self._records),
            "games": [r.model_dump() for r in self._records.values()],
            "catalog_version": self.catalog.version}

    async def start(self):
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor(), name="game-observer")
            self._heartbeat_task = asyncio.create_task(self._heartbeat(), name="game-heartbeat")

    async def close(self):
        tasks = [x for x in (self._monitor_task, self._heartbeat_task) if x]
        for task in tasks: task.cancel()
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)
        self._monitor_task = self._heartbeat_task = None
        self._subscribers.clear()

    def trigger_refresh(self):
        self._refresh.set()

    async def subscribe(self):
        q = asyncio.Queue(maxsize=128)
        self._subscribers.add(q)
        try:
            await self.observer.refresh()
            # Initial event must be a complete snapshot, never a premature delta.
            while not q.empty():
                q.get_nowait()
            self._enqueue(q, {"type":"event","event":"games.snapshot","data":self.snapshot()})
            return q
        except BaseException:
            self._subscribers.discard(q)
            raise

    def unsubscribe(self, q):
        self._subscribers.discard(q)

    def _enqueue(self, q, event):
        if q.full():
            # A slow client is explicitly instructed to resync. Operation results
            # remain available through durable games.operations.get.
            while not q.empty():
                q.get_nowait()
            q.put_nowait({"type":"event","event":"games.snapshot",
                          "data":self.snapshot(resync_required=True)})
        else:
            q.put_nowait(event)

    def broadcast(self, event, data):
        data = dict(data)
        if event in ("games.operation", "games.catalog.changed"):
            self._revision += 1
            data["revision"] = self._revision
        data["epoch"] = self.epoch
        message = {"type":"event","event":event,"data":data}
        for q in tuple(self._subscribers):
            self._enqueue(q, message)

    def publish(self, records: list[GameRecord]):
        old = set(self._records)
        changed = []
        for record in records:
            signature = _signature(record)
            if self._signatures.get(record.id) != signature:
                self._revision += 1
                changed.append((record.id, self._revision))
                self._signatures[record.id] = signature
                record_revision = self._revision
            else:
                record_revision = self._records[record.id].revision
            record = record.model_copy(update={"revision": record_revision})
            self._records[record.id] = record
        for removed in old - {r.id for r in records}:
            self._records.pop(removed, None)
            self._signatures.pop(removed, None)
            self._revision += 1
            changed.append((removed, self._revision))
        for game_id, revision in changed:
            self.broadcast("games.changed", {"revision":revision,"game_id":game_id,
                "game":self._records[game_id].model_dump() if game_id in self._records else None})
        return [self._records[item.id] for item in records]

    async def _monitor(self):
        while True:
            try:
                await self.observer.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Do not turn an observation error into a false STOPPED.
                pass
            try:
                await asyncio.wait_for(self._refresh.wait(), self.reconcile_interval)
                self._refresh.clear()
            except TimeoutError: pass

    async def _heartbeat(self):
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            self.broadcast("games.heartbeat", {"observed_at":_now(),"revision":self._revision})

    def catalog_changed(self):
        self.broadcast("games.catalog.changed", {"catalog_version":self.catalog.version,
            "revision":self._revision})
