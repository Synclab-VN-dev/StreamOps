"""Verified, allowlisted game lifecycle with bounded asynchronous operations."""
from __future__ import annotations
import asyncio
from .operations import GameOperationStore
from .models import GameDefinition
from ...platform.windows.game_process import GamePlatformError

class GameServiceError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code=code
        super().__init__(message)

class GameLifecycle:
    def __init__(self, catalog, observer, hub, store: GameOperationStore, *,
                 timeout: float = 45.0, interval: float = .25):
        self.catalog, self.observer, self.hub, self.store = catalog, observer, hub, store
        self.timeout, self.interval = timeout, interval
        self._inflight = set()
        self._lock = asyncio.Lock()
        self._tasks = set()

    async def close(self):
        for task in tuple(self._tasks): task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        for operation_id in tuple(self._inflight):
            self._inflight.discard(operation_id)

    async def submit(self, game_id: str, action: str, key: str):
        if action not in ("start", "stop", "restart"):
            raise GameServiceError("invalid_action", "Only start, stop and restart are allowed.")
        if not isinstance(key, str) or not (1 <= len(key) <= 128):
            raise GameServiceError("invalid_request", "idempotency_key length must be 1..128.")
        definition = self.catalog.get(game_id)
        if definition is None or not definition.enabled:
            raise GameServiceError("game_not_found", "Unknown or disabled game.")
        async with self._lock:
            # Lookup idempotent attempts before rejecting concurrent actions.
            try:
                op, fresh = self.store.begin(game_id, action, key)
            except ValueError as exc:
                raise GameServiceError("idempotency_conflict", str(exc)) from exc
            if not fresh:
                return op
            if game_id in self._inflight:
                self._notify(self.store.update(op["id"],"FAILED","REJECTED","operation_in_progress"))
                raise GameServiceError("operation_in_progress", "Another operation is running.")
            observed = await self.observer.get(game_id)
            if observed is None or not observed.capabilities.get(action, False):
                self._notify(self.store.update(op["id"],"FAILED","REJECTED",
                    observed.capability_reason if observed else "game_not_found"))
                raise GameServiceError("capability_disabled", "Operation not verified safe on this host.")
            self._inflight.add(game_id)
            task = asyncio.create_task(self._run(op, definition), name=f"game-{action}-{game_id}")
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            self._notify(op)
            return op

    def _notify(self, op):
        self.hub.broadcast("games.operation", {"operation_id":op["id"],"game_id":op["game_id"],
            "action":op["action"],"phase":op["phase"],"status":op["status"],
            "code":op["code"],"revision":self.hub.revision})

    def _phase(self, op, phase, status="RUNNING", code=None):
        value = self.store.update(op["id"],status,phase,code)
        self._notify(value)
        return value

    async def _until(self, game_id: str, state: str):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout
        while True:
            observed = await self.observer.get(game_id)
            if observed and observed.observation.process.state == state and not observed.observation.process.stale:
                return observed
            if loop.time() >= deadline:
                raise GameServiceError("operation_timeout", f"Game did not reach {state} before timeout.")
            await asyncio.sleep(self.interval)

    async def _run(self, op, game: GameDefinition):
        try:
            if op["action"] in ("stop", "restart"):
                self._phase(op, "STOPPING")
                observed = await self.observer.get(game.id)
                if not observed or observed.observation.process.state != "RUNNING":
                    raise GameServiceError("game_status_unknown","Cannot verify game before stopping.")
                await asyncio.to_thread(self.observer.platform.stop, game, observed.observation.process)
                await self._until(game.id,"STOPPED")
            if op["action"] in ("start", "restart"):
                self._phase(op,"STARTING")
                await asyncio.to_thread(self.observer.platform.start, game)
                await self._until(game.id, "RUNNING")
            self._phase(op,"COMPLETE","SUCCEEDED")
        except asyncio.CancelledError:
            self._phase(op,"INTERRUPTED","UNKNOWN","node_restarted")
            raise
        except (GamePlatformError, GameServiceError) as exc:
            state = "UNKNOWN" if exc.code in ("operation_timeout","game_status_unknown") else "FAILED"
            self._phase(op,"FAILED" if state == "FAILED" else "RECONCILE_REQUIRED",state,exc.code)
        except Exception:
            self._phase(op,"FAILED","FAILED","internal_error")
        finally:
            self._inflight.discard(game.id)
            self.hub.trigger_refresh()
