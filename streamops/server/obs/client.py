"""Small synchronous OBS WebSocket v5 client for streamops-node."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from pathlib import Path
import time
import uuid
from typing import Any, Iterable

from ..errors import (
    ObsWebSocketConnectionError as ObsConnectionError,
    ObsWebSocketRequestError as ObsRequestError,
)


INPUT_VOLUME_METERS_SUBSCRIPTION = 1 << 16


class ObsClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 4455,
        password: str | None = None,
        *,
        timeout: float = 5.0,
        event_subscriptions: int = 0,
    ) -> None:
        self.host = host
        self.port = port
        self.password = password or None
        self.timeout = timeout
        self.event_subscriptions = event_subscriptions
        self._ws: Any | None = None

    @classmethod
    def from_env(cls, *, event_subscriptions: int = 0) -> "ObsClient":
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
            event_subscriptions=event_subscriptions,
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
            raise ObsConnectionError("The 'websockets' dependency is not installed.") from exc

        uri = f"ws://{self.host}:{self.port}"
        try:
            self._ws = connect(
                uri,
                subprotocols=["obswebsocket.json"],
                open_timeout=self.timeout,
                close_timeout=self.timeout,
                # Full-resolution OBS screenshots are returned inline as
                # base64 JSON and can exceed websockets' 1 MiB default.
                max_size=16 * 1024 * 1024,
            )
            hello = self._recv()
            if hello.get("op") != 0:
                raise ObsConnectionError("OBS did not send the expected Hello message.")

            hello_data = hello.get("d") or {}
            identify_data: dict[str, Any] = {
                "rpcVersion": min(int(hello_data.get("rpcVersion", 1)), 1),
                "eventSubscriptions": self.event_subscriptions,
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

    def get_scene_collection_list(self) -> dict[str, Any]:
        return self.request('GetSceneCollectionList')

    def get_profile_parameter(self, category: str, name: str) -> Any:
        response = self.request('GetProfileParameter', {'parameterCategory': category, 'parameterName': name})
        return response.get('parameterValue') if response.get('parameterValue') is not None else response.get('defaultParameterValue')

    def get_current_program_scene(self) -> str | None:
        return self.request("GetCurrentProgramScene").get("currentProgramSceneName")

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

    def get_input_default_settings(self, input_kind: str) -> dict[str, Any]:
        return dict(self.request('GetInputDefaultSettings', {'inputKind': input_kind}).get('defaultInputSettings', {}))

    def set_input_settings(self, input_name: str, settings: dict[str, Any], *, overlay: bool = True) -> None:
        self.request(
            "SetInputSettings",
            {"inputName": input_name, "inputSettings": settings, "overlay": overlay},
        )

    def get_input_properties_list_property_items(
        self, input_name: str, property_name: str
    ) -> list[dict[str, Any]]:
        return list(
            self.request(
                "GetInputPropertiesListPropertyItems",
                {"inputName": input_name, "propertyName": property_name},
            ).get("propertyItems", [])
        )

    def get_monitor_list(self) -> list[dict[str, Any]]:
        return list(self.request("GetMonitorList").get("monitors", []))

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
        self.request(
            "SetSceneItemIndex",
            {"sceneName": scene_name, "sceneItemId": scene_item_id, "sceneItemIndex": index},
        )

    def get_input_mute(self, input_name: str) -> bool:
        return bool(self.request("GetInputMute", {"inputName": input_name}).get("inputMuted"))

    def set_input_mute(self, input_name: str, muted: bool) -> None:
        self.request("SetInputMute", {"inputName": input_name, "inputMuted": muted})

    def get_input_volume(self, input_name: str) -> dict[str, Any]:
        return self.request("GetInputVolume", {"inputName": input_name})

    def set_input_volume_db(self, input_name: str, volume_db: float) -> None:
        self.request("SetInputVolume", {"inputName": input_name, "inputVolumeDb": volume_db})

    def get_input_audio_sync_offset(self, input_name: str) -> int:
        return int(
            self.request("GetInputAudioSyncOffset", {"inputName": input_name}).get("inputAudioSyncOffset", 0)
        )

    def set_input_audio_sync_offset(self, input_name: str, offset_ms: int) -> None:
        self.request(
            "SetInputAudioSyncOffset",
            {"inputName": input_name, "inputAudioSyncOffset": offset_ms},
        )

    def get_input_audio_tracks(self, input_name: str) -> dict[str, bool]:
        raw = self.request("GetInputAudioTracks", {"inputName": input_name}).get("inputAudioTracks", {})
        return {str(key): bool(value) for key, value in dict(raw).items()}

    def set_input_audio_tracks(self, input_name: str, tracks: dict[str, bool]) -> None:
        self.request(
            "SetInputAudioTracks",
            {"inputName": input_name, "inputAudioTracks": tracks},
        )

    def get_record_status(self) -> dict[str, Any]:
        return self.request("GetRecordStatus")

    def get_stream_status(self) -> dict[str, Any]:
        return self.request("GetStreamStatus")

    def get_stream_service_settings(self) -> dict[str, Any]:
        return self.request("GetStreamServiceSettings")

    def set_stream_service_settings(self, service_type: str, settings: dict[str, Any]) -> None:
        self.request(
            "SetStreamServiceSettings",
            {"streamServiceType": service_type, "streamServiceSettings": settings},
        )

    def start_stream(self) -> None:
        self.request("StartStream")

    def stop_stream(self) -> None:
        self.request("StopStream")

    def get_stats(self) -> dict[str, Any]:
        return self.request("GetStats")

    def start_record(self) -> None:
        self.request("StartRecord")

    def stop_record(self) -> dict[str, Any]:
        return self.request("StopRecord")

    def save_source_screenshot(
        self, source_name: str, output_path: Path, *, width: int, height: int
    ) -> None:
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

    def get_source_screenshot(self, source_name: str, *, width: int, height: int) -> bytes:
        data = self.request(
            "GetSourceScreenshot",
            {
                "sourceName": source_name,
                "imageFormat": "png",
                "imageWidth": width,
                "imageHeight": height,
            },
        )
        image_data = str(data.get("imageData") or "")
        marker = "base64,"
        if marker not in image_data:
            raise ObsRequestError("OBS screenshot response did not contain base64 image data.")
        try:
            return base64.b64decode(image_data.split(marker, 1)[1], validate=True)
        except Exception as exc:
            raise ObsRequestError("OBS screenshot response contained invalid base64 data.") from exc

    def sample_input_volume_meters(
        self,
        input_names: Iterable[str],
        *,
        seconds: float,
    ) -> dict[str, dict[str, Any]]:
        if self._ws is None:
            self.connect()
        names = set(input_names)
        samples: dict[str, list[float]] = {name: [] for name in names}
        self._reidentify(INPUT_VOLUME_METERS_SUBSCRIPTION)
        deadline = time.monotonic() + seconds
        try:
            while time.monotonic() < deadline:
                remaining = max(0.01, deadline - time.monotonic())
                try:
                    message = self._recv(timeout=min(self.timeout, remaining))
                except TimeoutError:
                    break
                if message.get("op") != 5:
                    continue
                data = message.get("d") or {}
                if data.get("eventType") != "InputVolumeMeters":
                    continue
                event_data = data.get("eventData") or {}
                for item in event_data.get("inputs", []):
                    name = item.get("inputName")
                    if name not in names:
                        continue
                    peak_mul = _max_meter_multiplier(item.get("inputLevelsMul"))
                    if peak_mul is not None:
                        samples[name].append(_mul_to_db(peak_mul))
        finally:
            self._reidentify(self.event_subscriptions)

        return {
            name: {
                "sample_count": len(values),
                "peak_db": max(values) if values else None,
                "mean_db": sum(values) / len(values) if values else None,
            }
            for name, values in samples.items()
        }

    def _reidentify(self, event_subscriptions: int) -> None:
        if self._ws is None:
            raise ObsConnectionError("OBS WebSocket is not connected.")
        self._send({"op": 3, "d": {"eventSubscriptions": event_subscriptions}})

    def _send(self, payload: dict[str, Any]) -> None:
        if self._ws is None:
            raise ObsConnectionError("OBS WebSocket is not connected.")
        self._ws.send(json.dumps(payload))

    def _recv(self, *, timeout: float | None = None) -> dict[str, Any]:
        if self._ws is None:
            raise ObsConnectionError("OBS WebSocket is not connected.")
        raw = self._ws.recv(timeout=self.timeout if timeout is None else timeout)
        return json.loads(raw)


def _max_meter_multiplier(raw: Any) -> float | None:
    if not isinstance(raw, list):
        return None
    values: list[float] = []
    for channel in raw:
        if not isinstance(channel, list):
            continue
        for value in channel:
            if isinstance(value, int | float) and math.isfinite(float(value)):
                values.append(float(value))
    return max(values) if values else None


def _mul_to_db(value: float) -> float:
    if value <= 0:
        return -100.0
    return max(-100.0, 20.0 * math.log10(value))


def _make_auth(password: str, *, salt: str, challenge: str) -> str:
    secret = base64.b64encode(
        hashlib.sha256((password + salt).encode("utf-8")).digest()
    ).decode("utf-8")
    return base64.b64encode(
        hashlib.sha256((secret + challenge).encode("utf-8")).digest()
    ).decode("utf-8")


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
    return None if value is None else str(value)


def _config_auth_required(config: dict[str, Any]) -> bool:
    return config.get("auth_required") is True
