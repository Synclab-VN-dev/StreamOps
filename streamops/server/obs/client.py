"""Small OBS WebSocket v5 client used by StreamOps."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import uuid
from typing import Any

from ..errors import (
    ObsWebSocketConnectionError as ObsConnectionError,
    ObsWebSocketRequestError as ObsRequestError,
)


class ObsClient:
    """Synchronous OBS WebSocket v5 client.

    The implementation keeps the protocol surface small and explicit so scene
    reconciliation can be tested with a fake client.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 4455,
        password: str | None = None,
        *,
        timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.password = password or None
        self.timeout = timeout
        self._ws: Any | None = None

    @classmethod
    def from_env(cls) -> "ObsClient":
        local_config = _load_local_obs_websocket_config()
        port_raw = os.environ.get("OBS_WEBSOCKET_PORT") or _config_value(local_config, "server_port") or "4455"
        timeout_raw = os.environ.get("OBS_WEBSOCKET_TIMEOUT", "5")
        try:
            port = int(port_raw)
            timeout = float(timeout_raw)
        except ValueError as exc:
            raise ObsConnectionError("OBS_WEBSOCKET_PORT must be an integer and timeout must be numeric.") from exc

        password = os.environ.get("OBS_WEBSOCKET_PASSWORD") or None
        if password is None and _config_auth_required(local_config):
            password = _config_value(local_config, "server_password") or None

        return cls(
            host=os.environ.get("OBS_WEBSOCKET_HOST", "127.0.0.1"),
            port=port,
            password=password,
            timeout=timeout,
        )

    def __enter__(self) -> "ObsClient":
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def connect(self) -> None:
        if self._ws is not None:
            return
        try:
            from websockets.sync.client import connect
        except ImportError as exc:
            raise ObsConnectionError(
                "The 'websockets' dependency is not installed. Run `python -m pip install -e .`."
            ) from exc

        uri = f"ws://{self.host}:{self.port}"
        try:
            self._ws = connect(
                uri,
                subprotocols=["obswebsocket.json"],
                open_timeout=self.timeout,
                close_timeout=self.timeout,
            )
            hello = self._recv()
            if hello.get("op") != 0:
                raise ObsConnectionError("OBS did not send the expected Hello message.")

            hello_data = hello.get("d") or {}
            identify_data: dict[str, Any] = {
                "rpcVersion": min(int(hello_data.get("rpcVersion", 1)), 1),
                "eventSubscriptions": 0,
            }
            auth = hello_data.get("authentication")
            if auth:
                if not self.password:
                    raise ObsConnectionError(
                        "OBS WebSocket requires authentication; set OBS_WEBSOCKET_PASSWORD."
                    )
                identify_data["authentication"] = _make_auth(
                    self.password,
                    salt=auth["salt"],
                    challenge=auth["challenge"],
                )

            self._send({"op": 1, "d": identify_data})
            while True:
                message = self._recv()
                if message.get("op") == 2:
                    return
                if message.get("op") == 5:
                    continue
                raise ObsConnectionError(f"OBS rejected websocket identification: {message!r}")
        except ObsConnectionError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise ObsConnectionError(f"Could not connect to OBS WebSocket at {uri}: {exc}") from exc

    def close(self) -> None:
        if self._ws is None:
            return
        try:
            self._ws.close()
        finally:
            self._ws = None

    def request(self, request_type: str, request_data: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._ws is None:
            self.connect()

        request_id = f"streamops-{uuid.uuid4()}"
        self._send(
            {
                "op": 6,
                "d": {
                    "requestType": request_type,
                    "requestId": request_id,
                    "requestData": request_data or {},
                },
            }
        )

        while True:
            message = self._recv()
            if message.get("op") == 5:
                continue
            if message.get("op") != 7:
                continue

            data = message.get("d") or {}
            if data.get("requestId") != request_id:
                continue

            status = data.get("requestStatus") or {}
            if status.get("result") is True:
                return data.get("responseData") or {}

            comment = status.get("comment") or "OBS request failed"
            code = status.get("code", "unknown")
            raise ObsRequestError(f"{request_type} failed ({code}): {comment}")

    def get_version(self) -> dict[str, Any]:
        return self.request("GetVersion")

    def get_video_settings(self) -> dict[str, Any]:
        return self.request("GetVideoSettings")

    def set_video_settings(self, settings: dict[str, Any]) -> None:
        self.request("SetVideoSettings", settings)

    def get_scene_list(self) -> list[dict[str, Any]]:
        return list(self.request("GetSceneList").get("scenes", []))

    def get_current_program_scene(self) -> str | None:
        data = self.request("GetCurrentProgramScene")
        return data.get("currentProgramSceneName")

    def set_current_program_scene(self, scene_name: str) -> None:
        self.request("SetCurrentProgramScene", {"sceneName": scene_name})

    def create_scene(self, scene_name: str) -> None:
        self.request("CreateScene", {"sceneName": scene_name})

    def get_input_list(self) -> list[dict[str, Any]]:
        return list(self.request("GetInputList").get("inputs", []))

    def get_input_kind_list(self) -> list[str]:
        return list(self.request("GetInputKindList", {"unversioned": True}).get("inputKinds", []))

    def create_input(
        self,
        scene_name: str,
        input_name: str,
        input_kind: str,
        input_settings: dict[str, Any],
        *,
        enabled: bool = True,
    ) -> int:
        data = self.request(
            "CreateInput",
            {
                "sceneName": scene_name,
                "inputName": input_name,
                "inputKind": input_kind,
                "inputSettings": input_settings,
                "sceneItemEnabled": enabled,
            },
        )
        return int(data["sceneItemId"])

    def get_input_settings(self, input_name: str) -> dict[str, Any]:
        return dict(self.request("GetInputSettings", {"inputName": input_name}).get("inputSettings", {}))

    def get_input_properties_list_property_items(
        self,
        input_name: str,
        property_name: str,
    ) -> list[dict[str, Any]]:
        return list(
            self.request(
                "GetInputPropertiesListPropertyItems",
                {"inputName": input_name, "propertyName": property_name},
            ).get("propertyItems", [])
        )

    def get_monitor_list(self) -> list[dict[str, Any]]:
        return list(self.request("GetMonitorList").get("monitors", []))

    def set_input_settings(self, input_name: str, settings: dict[str, Any], *, overlay: bool = True) -> None:
        self.request(
            "SetInputSettings",
            {"inputName": input_name, "inputSettings": settings, "overlay": overlay},
        )

    def get_scene_item_list(self, scene_name: str) -> list[dict[str, Any]]:
        return list(self.request("GetSceneItemList", {"sceneName": scene_name}).get("sceneItems", []))

    def create_scene_item(self, scene_name: str, source_name: str, *, enabled: bool = True) -> int:
        data = self.request(
            "CreateSceneItem",
            {"sceneName": scene_name, "sourceName": source_name, "sceneItemEnabled": enabled},
        )
        return int(data["sceneItemId"])

    def remove_scene_item(self, scene_name: str, scene_item_id: int) -> None:
        self.request("RemoveSceneItem", {"sceneName": scene_name, "sceneItemId": scene_item_id})

    def get_scene_item_transform(self, scene_name: str, scene_item_id: int) -> dict[str, Any]:
        return dict(
            self.request(
                "GetSceneItemTransform",
                {"sceneName": scene_name, "sceneItemId": scene_item_id},
            ).get("sceneItemTransform", {})
        )

    def set_scene_item_transform(self, scene_name: str, scene_item_id: int, transform: dict[str, Any]) -> None:
        self.request(
            "SetSceneItemTransform",
            {"sceneName": scene_name, "sceneItemId": scene_item_id, "sceneItemTransform": transform},
        )

    def set_scene_item_enabled(self, scene_name: str, scene_item_id: int, enabled: bool) -> None:
        self.request(
            "SetSceneItemEnabled",
            {"sceneName": scene_name, "sceneItemId": scene_item_id, "sceneItemEnabled": enabled},
        )

    def set_scene_item_index(self, scene_name: str, scene_item_id: int, index: int) -> None:
        self.request("SetSceneItemIndex", {"sceneName": scene_name, "sceneItemId": scene_item_id, "sceneItemIndex": index})

    def save_source_screenshot(self, source_name: str, output_path: Path, *, width: int, height: int) -> None:
        self.request(
            "SaveSourceScreenshot",
            {
                "sourceName": source_name,
                "imageFormat": "png",
                "imageFilePath": str(output_path),
                "imageWidth": width,
                "imageHeight": height,
            },
        )

    def get_record_status(self) -> dict[str, Any]:
        return self.request("GetRecordStatus")

    def get_stream_status(self) -> dict[str, Any]:
        return self.request("GetStreamStatus")

    def start_record(self) -> None:
        self.request("StartRecord")

    def stop_record(self) -> dict[str, Any]:
        return self.request("StopRecord")

    def _send(self, payload: dict[str, Any]) -> None:
        if self._ws is None:
            raise ObsConnectionError("OBS WebSocket is not connected.")
        self._ws.send(json.dumps(payload))

    def _recv(self) -> dict[str, Any]:
        if self._ws is None:
            raise ObsConnectionError("OBS WebSocket is not connected.")
        raw = self._ws.recv(timeout=self.timeout)
        return json.loads(raw)


def _make_auth(password: str, *, salt: str, challenge: str) -> str:
    secret = base64.b64encode(hashlib.sha256((password + salt).encode("utf-8")).digest()).decode("utf-8")
    return base64.b64encode(hashlib.sha256((secret + challenge).encode("utf-8")).digest()).decode("utf-8")


def _load_local_obs_websocket_config() -> dict[str, Any]:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return {}

    path = Path(appdata) / "obs-studio" / "plugin_config" / "obs-websocket" / "config.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _config_value(config: dict[str, Any], key: str) -> str | None:
    value = config.get(key)
    if value is None:
        return None
    return str(value)


def _config_auth_required(config: dict[str, Any]) -> bool:
    return config.get("auth_required") is True
