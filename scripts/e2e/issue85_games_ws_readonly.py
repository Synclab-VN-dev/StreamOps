#!/usr/bin/env python3
"""Issue #85 read-only two-observer WebSocket smoke for Windows A / Android B.

Never sends lifecycle actions. Start/stop the game externally while running,
then collect both observer notifications to support Dev F acceptance.
"""
from __future__ import annotations
import argparse
import asyncio
import json
from urllib.parse import urlsplit
import websockets

async def run(base: str, seconds: float):
    parts=urlsplit(base)
    if parts.scheme not in ("http","https") or not parts.netloc or parts.path not in ("","/"):
        raise ValueError("--base must be a server root http(s) URL")
    ws_scheme="wss" if parts.scheme=="https" else "ws"
    url=f"{ws_scheme}://{parts.netloc}/api/v1/games/ws"
    async with (
        websockets.connect(url, subprotocols=["streamops-games-v1"], open_timeout=8) as a,
        websockets.connect(url, subprotocols=["streamops-games-v1"], open_timeout=8) as b,
    ):
        for name,socket in (("A",a),("B",b)):
            frame=json.loads(await asyncio.wait_for(socket.recv(),timeout=8))
            if frame.get("event")!="games.snapshot":
                raise RuntimeError(f"{name}: initial frame is not games.snapshot")
            snap=frame["data"]
            print(f"{name}: SNAPSHOT epoch={snap.get('epoch')} revision={snap.get('revision')} total={snap.get('total')}",flush=True)
        await a.send(json.dumps({"type":"request","request_id":"smoke-readonly-1",
                                 "operation":"games.list","payload":{}}))
        while True:
            frame=json.loads(await asyncio.wait_for(a.recv(),timeout=8))
            if frame.get("request_id")=="smoke-readonly-1":
                if not frame.get("ok"):
                    raise RuntimeError("games.list failed: "+json.dumps(frame.get("error")))
                games=frame["data"]["games"]
                print("GAMES: "+", ".join(f"{x['id']}={x['observation']['process']['state']}" for x in games),flush=True)
                break
        print("Listening for externally triggered game state changes (read-only)...",flush=True)
        end=asyncio.get_running_loop().time()+seconds
        async def listen(name,socket):
            while True:
                remaining=end-asyncio.get_running_loop().time()
                if remaining<=0: return
                try:
                    frame=json.loads(await asyncio.wait_for(socket.recv(),timeout=remaining))
                except TimeoutError:
                    return
                if frame.get("event")=="games.changed":
                    data=frame["data"]
                    state=(data.get("game") or {}).get("observation",{}).get("process",{}).get("state")
                    print(f"{name}: CHANGED game={data['game_id']} state={state} revision={data['revision']}",flush=True)
                elif frame.get("event")=="games.operation":
                    print(f"{name}: OPERATION id={frame['data'].get('operation_id')} status={frame['data'].get('status')}",flush=True)
        await asyncio.gather(listen("A",a),listen("B",b))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base",default="http://127.0.0.1:8765")
    parser.add_argument("--seconds",type=float,default=20.)
    args=parser.parse_args()
    if not (1<=args.seconds<=300):
        parser.error("--seconds must be 1..300")
    asyncio.run(run(args.base,args.seconds))

if __name__=="__main__":
    main()
