from __future__ import annotations

import asyncio

from streamops.server.services.live_status import LiveStatusHub


class CountingLiveService:
    def __init__(self) -> None:
        self.calls = 0

    def snapshot(self):
        self.calls += 1
        return {
            "state": "IDLE",
            "managed": False,
            "profile": None,
            "destination": None,
            "output": {"active": False},
            "started_at": None,
            "destinations": [],
            "destination_errors": [],
        }


def test_live_status_hub_stays_idle_without_stream_manage_subscriber() -> None:
    async def scenario() -> None:
        service = CountingLiveService()
        hub = LiveStatusHub(service, reconcile_interval=0.01, heartbeat_interval=1000)
        await hub.start()
        try:
            await asyncio.sleep(0.04)
            assert service.calls == 0

            queue = await hub.subscribe(fresh=True)
            initial = await queue.get()
            assert initial["event"] == "stream.snapshot"
            assert service.calls >= 1
            hub.unsubscribe(queue)
        finally:
            await hub.close()

    asyncio.run(scenario())
