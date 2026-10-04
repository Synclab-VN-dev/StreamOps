#!/usr/bin/env python3
"""Run the PR #31 Real-A livestream smoke test from an orchestrator host.

The runner intentionally uses only the public HTTP/WebSocket contract.  It does
not connect directly to OBS and never prints the configured stream credential.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


DEFAULT_TIMEOUT = 10.0
POLL_INTERVAL = 1.0
POLL_SAMPLES = 3


class SmokeError(RuntimeError):
    """A safe, user-facing smoke-test failure."""


class SecretLeakError(SmokeError):
    """The configured stream key appeared in an observed payload."""


@dataclass(frozen=True)
class Config:
    base_url: str
    profile_id: str
    rtmp_server_url: str
    stream_key: str
    ffprobe_input_url: str | None
    timeout: float
    live_timeout: float
    post_stop_wait: float


@dataclass(frozen=True)
class Result:
    name: str
    status: str
    evidence: str


class ApiClient:
    def __init__(self, base_url: str, secret: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.secret = secret
        self.timeout = timeout

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self.base_url + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = response.status
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as error:
            raw = error.read().decode("utf-8", errors="replace")
            self._assert_secret_absent(raw, f"HTTP {error.code} {method} {path} error")
            raise SmokeError(f"HTTP {error.code} {method} {path}: {self._safe(raw[:400])}") from None
        except (URLError, TimeoutError, OSError) as error:
            raise SmokeError(f"HTTP {method} {path} failed: {self._safe(str(error))}") from None

        self._assert_secret_absent(raw, f"HTTP {status} {method} {path}")
        if status < 200 or status >= 300:
            raise SmokeError(f"HTTP {status} {method} {path}: {self._safe(raw[:400])}")
        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise SmokeError(f"HTTP {status} {method} {path} returned invalid JSON") from error

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        return self.request("POST", path, payload)

    def put(self, path: str, payload: dict[str, Any]) -> Any:
        return self.request("PUT", path, payload)

    def patch(self, path: str, payload: dict[str, Any]) -> Any:
        return self.request("PATCH", path, payload)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    def _assert_secret_absent(self, value: str, context: str) -> None:
        if self.secret in value:
            raise SecretLeakError(f"stream credential appeared in {context}")

    def _safe(self, value: str) -> str:
        return value.replace(self.secret, "[REDACTED]")


class WsMonitor:
    def __init__(self, url: str, secret: str, timeout: float) -> None:
        self.url = url
        self.secret = secret
        self.timeout = timeout
        self.connected = threading.Event()
        self.finished = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.messages: list[dict[str, Any]] = []
        self.error: str | None = None
        self._thread = threading.Thread(target=self._thread_main, name="real-a-live-ws", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def wait_connected(self) -> None:
        if not self.connected.wait(timeout=self.timeout):
            raise SmokeError(self.error or "WebSocket did not connect before timeout")

    def wait_live_snapshot(self, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                for message in self.messages:
                    if (
                        message.get("type") == "event"
                        and message.get("event") == "stream.snapshot"
                        and isinstance(message.get("data"), dict)
                        and message["data"].get("state") == "LIVE"
                        and message["data"].get("output", {}).get("active") is True
                    ):
                        return message
            if self.error and not self.connected.is_set():
                break
            time.sleep(0.05)
        raise SmokeError(self.error or "No LIVE stream.snapshot received before timeout")

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(2.0, self.timeout + 1.0))

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._receive())
        except Exception as error:  # pragma: no cover - exercised by real integration run
            self.error = self._safe(str(error))
        finally:
            self.finished.set()

    async def _receive(self) -> None:
        try:
            from websockets.asyncio.client import connect
        except ImportError:
            from websockets import connect  # type: ignore[attr-defined]

        async with connect(self.url, open_timeout=self.timeout, close_timeout=self.timeout) as socket:
            self.connected.set()
            while not self._stop.is_set():
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                if self.secret in raw:
                    raise SecretLeakError("stream credential appeared in a WebSocket message")
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    raise SmokeError("WebSocket returned invalid JSON") from None
                if not isinstance(message, dict):
                    raise SmokeError("WebSocket returned a non-object JSON message")
                with self._lock:
                    self.messages.append(message)

    def _safe(self, value: str) -> str:
        return value.replace(self.secret, "[REDACTED]")


class SmokeRun:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.api = ApiClient(config.base_url, config.stream_key, config.timeout)
        self.results: list[Result] = []
        self.destination_id: str | None = None
        self.credential_configured = False
        self.ws: WsMonitor | None = None
        self.secret_leak = False
        self.profile_before_runtime: dict[str, Any] | None = None
        self.runtime_source_id: str | None = None
        self.runtime_session_id: str | None = None

    def run(self) -> int:
        try:
            self._run_flow()
        except SecretLeakError:
            self.secret_leak = True
            self._record("SECRET_REDACTION", "FAIL", "stream credential exposure detected")
        except Exception as error:
            self._record("UNEXPECTED_ERROR", "FAIL", self._safe(str(error)))
        finally:
            self._cleanup()
            if self.ws is not None:
                self.ws.close()
            if not any(result.name == "SECRET_REDACTION" for result in self.results):
                self._record("SECRET_REDACTION", "PASS", "credential absent from observed payloads and output")
        self._print_results()
        return 0 if all(result.status != "FAIL" for result in self.results) else 1

    def _run_flow(self) -> None:
        self._step("A_REACHABLE", self._verify_health)
        if self._failed("A_REACHABLE"):
            self._skip("OBS_READY", "blocked by A_REACHABLE")
        else:
            self._step("OBS_READY", self._verify_obs_ready)

        if self._failed("OBS_READY"):
            for name in (
                "DESTINATION_CREATE", "CREDENTIAL_SET", "PREFLIGHT", "START_LIVE",
                "OUTPUT_ACTIVE", "DURATION_INCREASING", "BYTES_INCREASING",
                "WS_LIVE_SNAPSHOT", "VIDEO_PRESENT", "AUDIO_PRESENT", "VIDEO_CODEC",
                "VIDEO_RESOLUTION", "VIDEO_FPS", "STOP_IDLE", "OUTPUT_QUIESCENT",
            ):
                self._skip(name, "blocked by OBS_READY")
            return

        self._step("DESTINATION_CREATE", self._create_destination)
        if self.destination_id is None:
            for name in (
                "CREDENTIAL_SET", "PREFLIGHT", "START_LIVE", "OUTPUT_ACTIVE",
                "DURATION_INCREASING", "BYTES_INCREASING", "WS_LIVE_SNAPSHOT",
                "VIDEO_PRESENT", "AUDIO_PRESENT", "VIDEO_CODEC", "VIDEO_RESOLUTION",
                "VIDEO_FPS", "STOP_IDLE", "OUTPUT_QUIESCENT",
            ):
                self._skip(name, "blocked by DESTINATION_CREATE")
            return

        self._step("CREDENTIAL_SET", self._set_credential)
        self._step("PREFLIGHT", self._preflight)

        self.ws = WsMonitor(self._ws_url(), self.config.stream_key, self.config.timeout)
        self.ws.start()
        self._step("WS_CONNECT", self.ws.wait_connected)

        self._step("START_LIVE", self._start_live)
        if self._failed("START_LIVE"):
            for name in (
                "OUTPUT_ACTIVE", "DURATION_INCREASING", "BYTES_INCREASING", "WS_LIVE_SNAPSHOT",
                "VIDEO_PRESENT", "AUDIO_PRESENT", "VIDEO_CODEC", "VIDEO_RESOLUTION", "VIDEO_FPS",
                "STOP_IDLE", "OUTPUT_QUIESCENT",
            ):
                self._skip(name, "blocked by START_LIVE")
            return

        samples = self._poll_live_samples()
        self._record("OUTPUT_ACTIVE", "PASS", f"{len(samples)} live samples")
        durations = [self._number(sample, "output", "duration_ms") for sample in samples]
        bytes_sent = [self._number(sample, "output", "bytes_sent") for sample in samples]
        self._record_increasing("DURATION_INCREASING", durations)
        self._record_increasing("BYTES_INCREASING", bytes_sent)

        self._step("AC32", self._verify_runtime_scene_control)
        if self._failed("AC32") and not any(result.name == "AC24" for result in self.results):
            self._record("AC24", "FAIL", "runtime continuity could not be proven because AC32 failed")

        if self.ws is None:
            self._record("WS_LIVE_SNAPSHOT", "FAIL", "WebSocket monitor was not started")
        else:
            self._step("WS_LIVE_SNAPSHOT", lambda: self.ws.wait_live_snapshot(self.config.live_timeout))

        if self.config.ffprobe_input_url:
            self._verify_ffprobe()
        else:
            for name in ("VIDEO_PRESENT", "AUDIO_PRESENT", "VIDEO_CODEC", "VIDEO_RESOLUTION", "VIDEO_FPS"):
                self._skip(name, "FFPROBE_INPUT_URL is not configured")

        self._step("STOP_IDLE", self._stop_and_verify_idle)
        if self.runtime_source_id is not None:
            self._step("AC21", self._verify_runtime_restore)
        else:
            self._skip("AC21", "runtime source control did not run")
        self._step("OUTPUT_QUIESCENT", self._verify_quiescent)

    def _verify_health(self) -> None:
        health = self.api.get("/api/v1/health")
        if not isinstance(health, dict) or health.get("status") != "ok":
            raise SmokeError("health endpoint did not report status=ok")

    def _verify_obs_ready(self) -> None:
        status = self.api.get("/api/v1/obs/process/status")
        if not isinstance(status, dict) or status.get("state") != "READY":
            raise SmokeError(f"OBS process state was {self._safe(str(status.get('state', 'unknown')))}")
        websocket = status.get("websocket")
        if not isinstance(websocket, dict) or websocket.get("connected") is not True:
            raise SmokeError("OBS process is not reporting a connected WebSocket")

    def _create_destination(self) -> None:
        payload = {
            "name": f"real-a-live-smoke-{uuid4().hex[:12]}",
            "type": "custom_rtmp",
            "enabled": True,
            "settings": {"server_url": self.config.rtmp_server_url},
        }
        response = self.api.post("/api/v1/stream-destinations", payload)
        if not isinstance(response, dict) or response.get("type") != "custom_rtmp":
            raise SmokeError("create response did not contain a custom_rtmp destination")
        destination_id = response.get("id")
        if not isinstance(destination_id, str) or not destination_id:
            raise SmokeError("create response did not contain a destination id")
        if response.get("credential_configured") is not False:
            raise SmokeError("new destination did not report credential_configured=false")
        self.destination_id = destination_id

    def _set_credential(self) -> None:
        response = self.api.put(
            f"/api/v1/stream-destinations/{self.destination_id}/credential",
            {"credential": self.config.stream_key},
        )
        if response != {"credential_configured": True}:
            raise SmokeError("credential endpoint did not confirm configuration")
        self.credential_configured = True
        destination = self.api.get(f"/api/v1/stream-destinations/{self.destination_id}")
        if not isinstance(destination, dict) or destination.get("credential_configured") is not True:
            raise SmokeError("destination did not report credential_configured=true")

    def _preflight(self) -> None:
        response = self.api.post(
            "/api/v1/live/preflight",
            {"profile_id": self.config.profile_id, "destination_id": self.destination_id},
        )
        if not isinstance(response, dict) or response.get("status") != "PASS":
            raise SmokeError(f"preflight status was {self._safe(str(response.get('status', 'unknown')))}")

    def _start_live(self) -> None:
        response = self.api.post(
            "/api/v1/live/start",
            {"profile_id": self.config.profile_id, "destination_id": self.destination_id},
        )
        if not isinstance(response, dict) or response.get("state") != "LIVE":
            raise SmokeError(f"start state was {self._safe(str(response.get('state', 'unknown')))}")

    def _poll_live_samples(self) -> list[dict[str, Any]]:
        samples: list[dict[str, Any]] = []
        deadline = time.monotonic() + self.config.live_timeout
        while len(samples) < POLL_SAMPLES and time.monotonic() < deadline:
            status = self.api.get("/api/v1/live/status")
            if not isinstance(status, dict):
                raise SmokeError("live status was not a JSON object")
            output = status.get("output")
            if isinstance(output, dict) and output.get("active") is True:
                samples.append(status)
            time.sleep(POLL_INTERVAL)
        if len(samples) < POLL_SAMPLES:
            raise SmokeError(f"only {len(samples)} active live status samples received")
        return samples


    def _verify_runtime_scene_control(self) -> None:
        profile = self.api.get(f"/api/v1/scene-profiles/{self.config.profile_id}")
        if not isinstance(profile, dict):
            raise SmokeError("Scene Profile response was not an object")
        self.profile_before_runtime = profile

        before = self.api.get("/api/v1/live/status")
        if not isinstance(before, dict):
            raise SmokeError("live status was not an object before runtime control")
        session_id = before.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise SmokeError("managed LIVE status did not expose session_id")
        if before.get("state") != "LIVE" or before.get("output", {}).get("active") is not True:
            raise SmokeError("stream was not active before runtime control")

        runtime_scene = before.get("runtime_scene")
        sources = runtime_scene.get("sources", []) if isinstance(runtime_scene, dict) else []
        positioned_sources = [
            item for item in sources
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and isinstance(item.get("actual"), dict)
            and isinstance(item["actual"].get("position"), dict)
        ]
        preferred = ("clock", "overlay", "camera", "cam")
        source = next(
            (
                item for needle in preferred for item in positioned_sources
                if needle in str(item.get("name") or "").lower()
            ),
            positioned_sources[0] if positioned_sources else None,
        )
        if source is None:
            raise SmokeError("active profile has no visual source with managed X/Y position")

        source_id = source["id"]
        actual = source["actual"]
        position = actual["position"]
        visible = bool(actual.get("visible"))
        try:
            x = float(position["x"])
            y = float(position["y"])
        except (KeyError, TypeError, ValueError) as error:
            raise SmokeError("runtime source did not expose numeric X/Y position") from error

        self.runtime_source_id = source_id
        self.runtime_session_id = session_id

        visibility = self.api.patch(
            f"/api/v1/live/sources/{source_id}/visibility",
            {"visible": not visible},
        )
        if visibility.get("actual", {}).get("visible") is not (not visible):
            raise SmokeError("runtime visibility mutation did not converge")

        positioned = self.api.patch(
            f"/api/v1/live/sources/{source_id}/position",
            {"x": x + 20.0, "y": y + 20.0},
        )
        positioned_actual = positioned.get("actual", {}).get("position", {})
        if abs(float(positioned_actual.get("x")) - (x + 20.0)) > 0.01:
            raise SmokeError("absolute runtime X position did not converge")
        if abs(float(positioned_actual.get("y")) - (y + 20.0)) > 0.01:
            raise SmokeError("absolute runtime Y position did not converge")

        moved = self.api.post(
            f"/api/v1/live/sources/{source_id}/move",
            {"dx": 10.0, "dy": 0.0},
        )
        moved_actual = moved.get("actual", {}).get("position", {})
        if abs(float(moved_actual.get("x")) - (x + 30.0)) > 0.01:
            raise SmokeError("relative runtime X movement did not converge")
        if abs(float(moved_actual.get("y")) - (y + 20.0)) > 0.01:
            raise SmokeError("relative runtime Y movement did not converge")

        after = self.api.get("/api/v1/live/status")
        if after.get("state") != "LIVE" or after.get("output", {}).get("active") is not True:
            raise SmokeError("stream output stopped during runtime source mutations")
        if after.get("session_id") != session_id:
            raise SmokeError("managed stream session changed during runtime source mutations")
        runtime_after = after.get("runtime_scene")
        if not isinstance(runtime_after, dict) or runtime_after.get("status") != "PASS":
            raise SmokeError("known runtime overrides were reported as unexpected drift")

        persisted = self.api.get(f"/api/v1/scene-profiles/{self.config.profile_id}")
        if persisted != self.profile_before_runtime:
            raise SmokeError("runtime source mutation changed the persisted Scene Profile")

        self._record(
            "AC24",
            "PASS",
            f"outputActive=true and session_id={session_id} stayed unchanged across Show/Hide + Move",
        )

    def _verify_runtime_restore(self) -> None:
        if self.profile_before_runtime is None or self.runtime_source_id is None:
            raise SmokeError("runtime baseline evidence is unavailable")
        persisted = self.api.get(f"/api/v1/scene-profiles/{self.config.profile_id}")
        if persisted != self.profile_before_runtime:
            raise SmokeError("persisted Scene Profile changed after Stop")
        verify = self.api.post(
            f"/api/v1/scene-profiles/{self.config.profile_id}/verify"
        )
        if not isinstance(verify, dict) or verify.get("status") != "PASS":
            raise SmokeError(
                f"post-Stop baseline verification was {self._safe(str(verify.get('status', 'unknown')))}"
            )

    def _verify_ffprobe(self) -> None:
        profile = None
        try:
            candidate = self.api.get(f"/api/v1/scene-profiles/{self.config.profile_id}")
            if isinstance(candidate, dict):
                profile = candidate
        except SmokeError:
            profile = None

        command = [
            "ffprobe", "-v", "error", "-rw_timeout", "5000000",
            "-of", "json", "-show_streams", "-show_format", self.config.ffprobe_input_url or "",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(5.0, self.config.timeout),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            for name in ("VIDEO_PRESENT", "AUDIO_PRESENT", "VIDEO_CODEC", "VIDEO_RESOLUTION", "VIDEO_FPS"):
                self._record(name, "FAIL", f"ffprobe failed: {self._safe(str(error))}")
            return
        if completed.returncode != 0:
            detail = self._safe(completed.stderr.strip()[:400]) or "ffprobe returned a non-zero exit code"
            for name in ("VIDEO_PRESENT", "AUDIO_PRESENT", "VIDEO_CODEC", "VIDEO_RESOLUTION", "VIDEO_FPS"):
                self._record(name, "FAIL", detail)
            return
        try:
            data = json.loads(completed.stdout)
        except json.JSONDecodeError:
            for name in ("VIDEO_PRESENT", "AUDIO_PRESENT", "VIDEO_CODEC", "VIDEO_RESOLUTION", "VIDEO_FPS"):
                self._record(name, "FAIL", "ffprobe returned invalid JSON")
            return

        streams = data.get("streams", []) if isinstance(data, dict) else []
        video = next((item for item in streams if item.get("codec_type") == "video"), None)
        audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
        self._record("VIDEO_PRESENT", "PASS" if video else "FAIL", "video stream found" if video else "no video stream")
        self._record("AUDIO_PRESENT", "PASS" if audio else "FAIL", "audio stream found" if audio else "no audio stream")
        if video:
            codec = str(video.get("codec_name", "")).lower()
            self._record("VIDEO_CODEC", "PASS" if codec == "h264" else "FAIL", f"codec={codec or 'unknown'}")
            expected_canvas = profile.get("canvas", {}) if isinstance(profile, dict) else {}
            expected_width = expected_canvas.get("width")
            expected_height = expected_canvas.get("height")
            actual_width = video.get("width")
            actual_height = video.get("height")
            if expected_width and expected_height and actual_width and actual_height:
                ok = actual_width == expected_width and actual_height == expected_height
                self._record("VIDEO_RESOLUTION", "PASS" if ok else "FAIL", f"actual={actual_width}x{actual_height}, expected={expected_width}x{expected_height}")
            else:
                self._skip("VIDEO_RESOLUTION", "profile or ffprobe resolution metadata unavailable")

            expected_fps = expected_canvas.get("fps")
            # For a short live probe, avg_frame_rate can be skewed by startup
            # timing; r_frame_rate is the stream's nominal cadence.
            actual_fps = _parse_rate(video.get("r_frame_rate") or video.get("avg_frame_rate"))
            if expected_fps and actual_fps is not None:
                ok = abs(actual_fps - float(expected_fps)) <= 0.5
                self._record("VIDEO_FPS", "PASS" if ok else "FAIL", f"actual={actual_fps:g}, expected={expected_fps}")
            else:
                self._skip("VIDEO_FPS", "profile or ffprobe FPS metadata unavailable")
        else:
            self._skip("VIDEO_RESOLUTION", "blocked by VIDEO_PRESENT")
            self._skip("VIDEO_FPS", "blocked by VIDEO_PRESENT")

    def _stop_and_verify_idle(self) -> None:
        response = self.api.post("/api/v1/live/stop")
        if not isinstance(response, dict) or response.get("state") != "IDLE":
            raise SmokeError(f"stop state was {self._safe(str(response.get('state', 'unknown')))}")
        status = self.api.get("/api/v1/live/status")
        output = status.get("output", {}) if isinstance(status, dict) else {}
        if status.get("state") != "IDLE" or output.get("active") is not False:
            raise SmokeError("post-stop status was not IDLE with output.active=false")

    def _verify_quiescent(self) -> None:
        first = self.api.get("/api/v1/live/status")
        time.sleep(self.config.post_stop_wait)
        second = self.api.get("/api/v1/live/status")
        first_output = first.get("output", {}) if isinstance(first, dict) else {}
        second_output = second.get("output", {}) if isinstance(second, dict) else {}
        if first_output.get("active") is not False or second_output.get("active") is not False:
            raise SmokeError("output became active again after stop")
        if first_output.get("bytes_sent") != second_output.get("bytes_sent"):
            raise SmokeError("bytes_sent changed after stop")

    def _cleanup(self) -> None:
        cleanup_failures: list[str] = []
        if self.destination_id is not None:
            try:
                self.api.post("/api/v1/live/stop")
            except Exception as error:
                cleanup_failures.append(f"stop: {self._safe(str(error))}")
            if self.credential_configured:
                try:
                    self.api.delete(f"/api/v1/stream-destinations/{self.destination_id}/credential")
                except Exception as error:
                    cleanup_failures.append(f"credential delete: {self._safe(str(error))}")
            try:
                self.api.delete(f"/api/v1/stream-destinations/{self.destination_id}")
            except Exception as error:
                cleanup_failures.append(f"destination delete: {self._safe(str(error))}")
        if cleanup_failures:
            self._record("CLEANUP", "FAIL", "; ".join(cleanup_failures))
        else:
            self._record("CLEANUP", "PASS", "stop, credential delete and destination delete completed")

    def _record_increasing(self, name: str, values: list[float]) -> None:
        ok = len(values) >= 2 and all(right > left for left, right in zip(values, values[1:]))
        self._record(name, "PASS" if ok else "FAIL", f"samples={','.join(_compact_number(value) for value in values)}")

    def _step(self, name: str, operation: Callable[[], Any]) -> None:
        try:
            value = operation()
            evidence = "completed"
            if isinstance(value, dict):
                evidence = "completed"
            self._record(name, "PASS", evidence)
        except SecretLeakError:
            self.secret_leak = True
            self._record(name, "FAIL", "stream credential exposure detected")
            self._record("SECRET_REDACTION", "FAIL", "stream credential exposure detected")
        except Exception as error:
            self._record(name, "FAIL", self._safe(str(error)))

    def _record(self, name: str, status: str, evidence: str) -> None:
        if any(result.name == name for result in self.results):
            return
        self.results.append(Result(name, status, self._safe(evidence)))

    def _skip(self, name: str, evidence: str) -> None:
        self._record(name, "SKIP", evidence)

    def _failed(self, name: str) -> bool:
        return any(result.name == name and result.status == "FAIL" for result in self.results)

    def _number(self, value: dict[str, Any], outer: str, inner: str) -> float:
        try:
            return float(value[outer][inner])
        except (KeyError, TypeError, ValueError) as error:
            raise SmokeError(f"status did not contain numeric {outer}.{inner}") from error

    def _ws_url(self) -> str:
        if self.config.base_url.startswith("https://"):
            return "wss://" + self.config.base_url[len("https://"):].rstrip("/") + "/api/v1/live/ws"
        return "ws://" + self.config.base_url.removeprefix("http://").rstrip("/") + "/api/v1/live/ws"

    def _safe(self, value: str) -> str:
        if self.config.stream_key and self.config.stream_key in value:
            return value.replace(self.config.stream_key, "[REDACTED]")
        return value

    def _print_results(self) -> None:
        lines = ["REAL_A_LIVE_SMOKE", "=" * 56]
        for result in self.results:
            lines.append(f"{result.name:<22} {result.status:<4} {self._safe(result.evidence)}")
        overall = "PASS" if all(result.status != "FAIL" for result in self.results) else "FAIL"
        lines.append(f"{'OVERALL':<22} {overall}")
        output = "\n".join(lines)
        if self.config.stream_key in output:
            self.secret_leak = True
            output = output.replace(self.config.stream_key, "[REDACTED]")
        print(output)


def _parse_rate(value: Any) -> float | None:
    if not isinstance(value, str) or not value or value in {"0/0", "N/A"}:
        return None
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None


def _compact_number(value: float) -> str:
    return f"{value:g}"


def _env_or_cli(cli_value: str | None, env_name: str, *, required: bool = True) -> str | None:
    value = cli_value if cli_value not in (None, "") else os.environ.get(env_name)
    if required and not value:
        raise SystemExit(f"missing required configuration: --{env_name.lower().replace('_', '-')} or {env_name}")
    return value


def parse_config(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url")
    parser.add_argument("--profile-id")
    parser.add_argument("--rtmp-server-url")
    parser.add_argument("--stream-key")
    parser.add_argument("--ffprobe-input-url")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--live-timeout", type=float, default=30.0)
    parser.add_argument("--post-stop-wait", type=float, default=2.0)
    args = parser.parse_args(argv)
    return Config(
        base_url=str(_env_or_cli(args.base_url, "STREAMOPS_BASE_URL")),
        profile_id=str(_env_or_cli(args.profile_id, "PROFILE_ID")),
        rtmp_server_url=str(_env_or_cli(args.rtmp_server_url, "RTMP_SERVER_URL")),
        stream_key=str(_env_or_cli(args.stream_key, "RTMP_STREAM_KEY")),
        ffprobe_input_url=_env_or_cli(args.ffprobe_input_url, "FFPROBE_INPUT_URL", required=False),
        timeout=args.timeout,
        live_timeout=args.live_timeout,
        post_stop_wait=args.post_stop_wait,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        config = parse_config(argv)
        return SmokeRun(config).run()
    except SystemExit:
        raise
    except Exception as error:
        print(f"REAL_A_LIVE_SMOKE\nOVERALL               FAIL   {_safe_cli_error(str(error))}")
        return 1


def _safe_cli_error(value: str) -> str:
    # Configuration errors occur before SmokeRun owns the secret.  Avoid showing
    # arbitrary CLI/environment values in this path altogether.
    return "configuration or runner initialization failed"


if __name__ == "__main__":
    raise SystemExit(main())
