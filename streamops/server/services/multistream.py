"""Shared multistream core used by both HTTP and WebSocket transports."""
from __future__ import annotations
import threading
from typing import Any, Callable
from urllib.parse import urlparse
from ..errors import StreamingError
from ..multistream import MultiRtmpAdapter, MultistreamRepository

class MultistreamService:
    def __init__(self, repository: MultistreamRepository, adapter: MultiRtmpAdapter) -> None:
        self.repository=repository; self.adapter=adapter; self._listeners:set[Callable[[dict[str,Any]],None]]=set(); self._lock=threading.RLock()
    def subscribe(self, listener: Callable[[dict[str,Any]],None]) -> None: self._listeners.add(listener)
    def unsubscribe(self, listener: Callable[[dict[str,Any]],None]) -> None: self._listeners.discard(listener)
    def _emit(self,event:str,item:dict[str,Any],data:dict[str,Any]|None=None)->None:
        message={"type":event,"destination_id":item["id"],"data":data if data is not None else self._public(item)}
        for listener in tuple(self._listeners): listener(message)
    def snapshot(self)->dict[str,Any]: return {"destinations":[self._with_runtime(x) for x in self.repository.list()]}
    def list_destinations(self)->dict[str,Any]: return self.snapshot()
    def get_destination(self,destination_id:str)->dict[str,Any]: return self._with_runtime(self.repository.get(destination_id))
    def create_destination(self,payload:dict[str,Any])->dict[str,Any]:
        item=self._normalize(payload); self.adapter.add_target(item["name"]); target=self._unique_target(item["name"]); item["plugin_target_id"]=str(target["id"]); self._configure(item,payload.get("credential")); self.repository.save(item,create=True); self._emit("destination.created",item); return self._public(item)
    def update_destination(self,destination_id:str,payload:dict[str,Any])->dict[str,Any]:
        old=self.repository.get(destination_id); item=self._normalize({**self._public(old),**payload},destination_id=destination_id); item["plugin_target_id"]=old["plugin_target_id"]
        if item["name"]!=old["name"]: self.adapter.update_name(item["plugin_target_id"],item["name"])
        self.adapter.update_server(item["plugin_target_id"],item["server_url"])
        if "credential" in payload: self.adapter.update_stream_key(item["plugin_target_id"],str(payload["credential"]))
        self.repository.save(item); self._emit("destination.updated",item); return self._public(item)
    def delete_destination(self,destination_id:str)->dict[str,bool]:
        item=self.repository.get(destination_id); self.adapter.delete_target(item["plugin_target_id"]); self.repository.delete(destination_id); self._emit("destination.deleted",item,{"deleted":True}); return {"deleted":True}
    def start_destination(self,destination_id:str)->dict[str,Any]:
        item=self.repository.get(destination_id); before=self._runtime(item); 
        if before["state"]=="LIVE": return self._public_runtime(item,before)
        self._emit("destination.state_changed",item,{"previous_state":before["state"],"state":"STARTING"}); self.adapter.start(item["plugin_target_id"]); after=self._runtime(item); self._emit("destination.state_changed",item,{"previous_state":"STARTING","state":after["state"]}); return self._public_runtime(item,after)
    def stop_destination(self,destination_id:str)->dict[str,Any]:
        item=self.repository.get(destination_id); before=self._runtime(item)
        if before["state"]=="IDLE": return self._public_runtime(item,before)
        self._emit("destination.state_changed",item,{"previous_state":before["state"],"state":"STOPPING"}); self.adapter.stop(item["plugin_target_id"]); after=self._runtime(item); self._emit("destination.state_changed",item,{"previous_state":"STOPPING","state":after["state"]}); return self._public_runtime(item,after)
    def status(self,destination_id:str)->dict[str,Any]:
        item=self.repository.get(destination_id); return self._public_runtime(item,self._runtime(item))
    def stats(self,destination_id:str)->dict[str,Any]:
        item=self.repository.get(destination_id); return {"destination_id":item["id"],"stats":self._safe(self.adapter.stats(item["plugin_target_id"]))}
    def reconcile(self)->dict[str,Any]:
        targets=self.adapter.list_targets(); by_id={str(x.get("id")):x for x in targets}; changed=[]
        for item in self.repository.list():
            if item.get("plugin_target_id") in by_id: continue
            matches=[x for x in targets if x.get("name")==item["name"]]
            if len(matches)==1: item["plugin_target_id"]=str(matches[0]["id"]); self.repository.save(item); changed.append(item["id"])
        return {"reconciled":changed}
    def _configure(self,item:dict[str,Any],credential:Any)->None:
        tid=item["plugin_target_id"]; self.adapter.update_server(tid,item["server_url"])
        if credential is not None: self.adapter.update_stream_key(tid,str(credential))
    def _unique_target(self,name:str)->dict[str,Any]:
        matches=[x for x in self.adapter.list_targets() if x.get("name")==name]
        if len(matches)!=1: raise StreamingError("vendor_identity_ambiguous",f"Expected one plugin target named {name}.",409)
        return matches[0]
    def _normalize(self,payload:dict[str,Any],destination_id:str|None=None)->dict[str,Any]:
        allowed={"id","name","server_url","enabled","credential"}; extras=set(payload)-allowed
        if extras: raise StreamingError("destination_invalid",f"Unknown field(s): {', '.join(sorted(extras))}",422)
        did=destination_id or payload.get("id"); name=payload.get("name"); url=payload.get("server_url"); enabled=payload.get("enabled",True)
        if not isinstance(did,str) or not did: raise StreamingError("destination_invalid","id is required.",422)
        if not isinstance(name,str) or not name.strip(): raise StreamingError("destination_invalid","name is required.",422)
        if not isinstance(url,str) or urlparse(url).scheme not in {"rtmp","rtmps"}: raise StreamingError("destination_invalid","server_url must use rtmp or rtmps.",422)
        if type(enabled) is not bool: raise StreamingError("destination_invalid","enabled must be boolean.",422)
        return {"id":did,"name":name.strip(),"server_url":url,"enabled":enabled}
    def _runtime(self,item:dict[str,Any])->dict[str,Any]:
        raw=self._safe(self.adapter.state(item["plugin_target_id"])); running=bool(raw.get("isRunning",raw.get("streaming",False))); status=str(raw.get("status") or raw.get("rawStatus") or "")
        failed=any(x in status.casefold() for x in ("fail","error"))
        return {"state":"FAILED" if failed else ("LIVE" if running else "IDLE"),"vendor_status":status}
    def _with_runtime(self,item:dict[str,Any])->dict[str,Any]: return self._public_runtime(item,self._runtime(item))
    def _public_runtime(self,item:dict[str,Any],runtime:dict[str,Any])->dict[str,Any]: return {**self._public(item),**runtime}
    @staticmethod
    def _public(item:dict[str,Any])->dict[str,Any]: return {k:v for k,v in item.items() if k!="plugin_target_id"}
    @staticmethod
    def _safe(value:Any)->Any:
        sensitive={"key","token","password","credential","streamkey","stream_key","newstreamkey"}
        if isinstance(value,dict): return {k:("[REDACTED]" if k.replace("-","_").casefold() in sensitive else MultistreamService._safe(v)) for k,v in value.items()}
        if isinstance(value,list): return [MultistreamService._safe(v) for v in value]
        return value
