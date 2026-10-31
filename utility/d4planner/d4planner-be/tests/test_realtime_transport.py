"""Real local socket D5 notification tests; no game/Windows claims."""
import asyncio
import json
import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus
from d4planner.transport.core import HudHub
from d4planner.transport.websocket import D4PlannerWebSocketServer, WebSocketServerConfig

CREDENTIAL = 'synthetic-credential-00000000000000000'
ORIGIN = 'tauri://localhost'

def hello(**extra):
    return {'protocolVersion':'d4planner-notify/v1','type':'hello','messageId':'hello',
            'credential':CREDENTIAL,'origin':ORIGIN, **extra}

def server(**extra):
    hub = HudHub({'dbId':'db','epoch':'epoch','hudRevision':7}, backend_generation=1)
    return D4PlannerWebSocketServer(WebSocketServerConfig(credential=CREDENTIAL,
        runtime_instance_id='runtime',backend_generation=1,origin=ORIGIN,**extra),None,hub), hub

def test_real_notify_reconnect_coalescing_and_no_business_channel():
    async def run():
        host, hub = server()
        await host.start()
        try:
            for attempt in range(2):
                async with connect(f'ws://127.0.0.1:{host.port}',origin=ORIGIN) as ws:
                    await ws.send(json.dumps(hello()))
                    assert json.loads(await ws.recv())['type'] == 'hello.accepted'
                    first = json.loads(await ws.recv())
                    assert set(first) == {'protocolVersion','type','messageId','dbId','epoch','hudRevision'}
                    assert first['hudRevision'] == 7 + attempt
                    for kind in ('target.list.request','target.select.request','hud.snapshot.request'):
                        await ws.send(json.dumps({'type':kind}))
                        assert json.loads(await ws.recv())['code'] == 'UNSUPPORTED_METHOD'
                    await hub.publish_after_commit({'dbId':'db','epoch':'epoch','hudRevision':8+attempt})
                    assert json.loads(await ws.recv())['hudRevision'] == 8+attempt
        finally:
            await host.close()
    asyncio.run(run())

@pytest.mark.parametrize('extra,code', [({'credential':'wrong'},'AUTH_FAILED'),({'origin':'https://evil'},'ORIGIN_REJECTED'),({'hud':{}},'INVALID_MESSAGE'),({'protocolVersion':'d4planner-ws/v1'},'INVALID_MESSAGE')])
def test_auth_fail_closed(extra,code):
    async def run():
        host,_ = server()
        await host.start()
        try:
            async with connect(f'ws://127.0.0.1:{host.port}',origin=ORIGIN) as ws:
                await ws.send(json.dumps(hello(**extra)))
                assert json.loads(await ws.recv())['code'] == code
                with pytest.raises(ConnectionClosed): await ws.recv()
        finally: await host.close()
    asyncio.run(run())

def test_bounded_queue_duplicate_old_and_replaced_database():
    async def run():
        _,hub = server()
        _,key,queue = await hub.snapshot_and_subscribe()
        for revision in range(8,100):
            await hub.publish_after_commit({'dbId':'db','epoch':'epoch','hudRevision':revision})
        assert queue.qsize() == 1
        assert (await queue.get())['hudRevision'] == 99
        assert not await hub.publish_after_commit({'dbId':'db','epoch':'epoch','hudRevision':98})
        assert await hub.publish_after_commit({'dbId':'db','epoch':'restored','hudRevision':2})
        assert (await queue.get())['epoch'] == 'restored'
        await hub.unsubscribe(key)
    asyncio.run(run())

def test_handshake_timeout_and_frame_limit():
    async def run():
        host,_ = server(handshake_timeout_seconds=.05,max_message_bytes=1024)
        await host.start()
        try:
            async with connect(f'ws://127.0.0.1:{host.port}',origin=ORIGIN) as ws:
                with pytest.raises(ConnectionClosed): await ws.recv()
            async with connect(f'ws://127.0.0.1:{host.port}',origin=ORIGIN) as ws:
                await ws.send('x'*2048)
                with pytest.raises(ConnectionClosed): await ws.recv()
            with pytest.raises(InvalidStatus):
                async with connect(f'ws://127.0.0.1:{host.port}',origin='https://evil'): pass
        finally: await host.close()
    asyncio.run(run())

def test_loopback_and_private_credential_configuration_are_enforced():
    with pytest.raises(ValueError): server(host='0.0.0.0')
    with pytest.raises(ValueError):
        WebSocketServerConfig(credential='short', runtime_instance_id='id',backend_generation=1,origin=ORIGIN)
