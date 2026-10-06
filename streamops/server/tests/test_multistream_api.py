from __future__ import annotations
from pathlib import Path
from fastapi.testclient import TestClient
from streamops.server.app import create_app
from streamops.server.multistream.repository import MultistreamRepository
from streamops.server.services.multistream import MultistreamService

class FakeAdapter:
    def __init__(self): self.targets=[]; self.running={}; self.calls=[]; self.next_id=1
    def list_targets(self): return [dict(x) for x in self.targets]
    def add_target(self,name):
        self.calls.append(("add",name)); t={"id":str(self.next_id),"name":name}; self.next_id+=1; self.targets.append(t); self.running[t["id"]]=False; return {"status":"added"}
    def delete_target(self,i): self.calls.append(("delete",i)); self.targets=[x for x in self.targets if x["id"]!=i]; return {}
    def update_name(self,i,n): self.calls.append(("name",i,n)); next(x for x in self.targets if x["id"]==i)["name"]=n; return {}
    def update_server(self,i,u): self.calls.append(("server",i,u)); return {}
    def update_stream_key(self,i,k): self.calls.append(("key",i,k)); return {"status":"updated"}
    def start(self,i): self.calls.append(("start",i)); self.running[i]=True; return {"status":"start_requested"}
    def stop(self,i): self.calls.append(("stop",i)); self.running[i]=False; return {"status":"stop_requested"}
    def state(self,i): return {"isRunning":self.running[i],"status":"live" if self.running[i] else "idle"}
    def stats(self,i): return {"bytesSent":123,"streamKey":"must-not-leak"}
class NoopCapture:
    def start(self): pass
    def close(self): pass

def make(tmp_path:Path):
    a=FakeAdapter(); return MultistreamService(MultistreamRepository(tmp_path/"multi"),a),a
def payload(): return {"id":"youtube-main","name":"YouTube Main","server_url":"rtmp://receiver/live","credential":"super-secret"}

def test_core_lifecycle_redacts_secret(tmp_path):
    svc,a=make(tmp_path); created=svc.create_destination(payload()); assert "credential" not in created and "plugin_target_id" not in created
    assert svc.start_destination("youtube-main")["state"]=="LIVE"; assert svc.stop_destination("youtube-main")["state"]=="IDLE"
    stats=svc.stats("youtube-main"); assert stats["stats"]["streamKey"]=="[REDACTED]"; assert "super-secret" not in repr(stats)

def test_http_and_ws_use_same_core(tmp_path,server_config):
    svc,a=make(tmp_path); app=create_app(server_config,capture_service=NoopCapture(),multistream_service=svc,manage_runtime=False)
    with TestClient(app) as client:
        assert client.post("/api/v1/multistream/destinations",json=payload()).status_code==201
        assert client.post("/api/v1/multistream/destinations/youtube-main/start").json()["state"]=="LIVE"
        client.post("/api/v1/multistream/destinations/youtube-main/stop")
        with client.websocket_connect("/api/v1/multistream/ws") as ws:
            assert ws.receive_json()["type"]=="multistream.snapshot"
            ws.send_json({"type":"request","request_id":"1","operation":"destination.start","payload":{"destination_id":"youtube-main"}})
            messages=[ws.receive_json(),ws.receive_json(),ws.receive_json()]
            response=next(x for x in messages if x.get("type")=="response")
            assert response["ok"] is True and response["data"]["state"]=="LIVE"
    assert [x[0] for x in a.calls].count("start")==2

def test_reconcile_repairs_mapping(tmp_path):
    svc,a=make(tmp_path); svc.create_destination(payload()); item=svc.repository.get("youtube-main"); item["plugin_target_id"]="stale"; svc.repository.save(item)
    assert svc.reconcile()=={"reconciled":["youtube-main"]}; assert svc.repository.get("youtube-main")["plugin_target_id"]=="1"
