"""Adapter boundary for the obs-multi-rtmp Vendor API."""
from __future__ import annotations

from typing import Any, Protocol

from ..obs.client import ObsClient
from ..errors import StreamingError

VENDOR_NAME = "sorayuki.multi_rtmp"

class MultiRtmpAdapter(Protocol):
    def list_targets(self) -> list[dict[str, Any]]: ...
    def add_target(self, name: str) -> dict[str, Any]: ...
    def delete_target(self, target_id: str) -> dict[str, Any]: ...
    def update_name(self, target_id: str, name: str) -> dict[str, Any]: ...
    def update_server(self, target_id: str, server_url: str) -> dict[str, Any]: ...
    def update_stream_key(self, target_id: str, stream_key: str) -> dict[str, Any]: ...
    def start(self, target_id: str) -> dict[str, Any]: ...
    def stop(self, target_id: str) -> dict[str, Any]: ...
    def state(self, target_id: str) -> dict[str, Any]: ...
    def stats(self, target_id: str) -> dict[str, Any]: ...

class MultiRtmpVendorAdapter:
    def _call(self, request_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        with ObsClient.from_env() as obs:
            response = obs.request("CallVendorRequest", {
                "vendorName": VENDOR_NAME,
                "requestType": request_type,
                "requestData": data or {},
            })
        data = dict(response.get("responseData") or {})
        if data.get("error"):
            raise StreamingError("multistream_vendor_error", str(data["error"]), 503)
        return data

    def list_targets(self) -> list[dict[str, Any]]:
        return list(self._call("list_targets").get("targets") or [])
    def add_target(self, name: str) -> dict[str, Any]:
        return self._call("add_target", {"name": name, "protocol": "RTMP"})
    def delete_target(self, target_id: str) -> dict[str, Any]:
        return self._call("delete_target", {"id": target_id})
    def update_name(self, target_id: str, name: str) -> dict[str, Any]:
        return self._call("update_target_name", {"id": target_id, "newName": name})
    def update_server(self, target_id: str, server_url: str) -> dict[str, Any]:
        return self._call("update_service_param", {"id": target_id, "key": "server", "value": server_url})
    def update_stream_key(self, target_id: str, stream_key: str) -> dict[str, Any]:
        return self._call("update_stream_key", {"id": target_id, "streamKey": stream_key})
    def start(self, target_id: str) -> dict[str, Any]: return self._call("start_target", {"id": target_id})
    def stop(self, target_id: str) -> dict[str, Any]: return self._call("stop_target", {"id": target_id})
    def state(self, target_id: str) -> dict[str, Any]: return self._call("get_target_state", {"id": target_id})
    def stats(self, target_id: str) -> dict[str, Any]: return self._call("get_target_stats", {"id": target_id})
