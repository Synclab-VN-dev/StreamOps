"""OBS scene application service and review-job lifecycle."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any
from uuid import uuid4

from ..errors import (
    SceneOperationError,
    SceneReviewNotFoundError,
)
from ..obs.client import ObsClient
from ..obs.profile_scene import apply_profile, verify_profile
from ..obs.profile_ownership import ProfileOwnership
from ..obs.scene import ApplyResult, VerifyResult, apply_scene, verify_scene
from ..profile_store import SceneProfileStore
from ..scene_profiles import source_catalog
from ..scene_config import find_project_root, list_scene_names, load_scene_config


@dataclass
class ReviewJob:
    job_id: str
    scene: str
    state: str
    created_at: str
    updated_at: str
    seconds: int
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "scene": self.scene,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "seconds": self.seconds,
            "result": self.result,
            "error": self.error,
        }


class ObsSceneService:
    def __init__(
        self,
        *,
        root: Path | None = None,
        data_dir: Path | None = None,
        artifact_root: Path | None = None,
        client_factory: type[ObsClient] | Any = ObsClient,
        inventory_provider: Any = None,
    ) -> None:
        self.root = root or find_project_root()
        profile_root = data_dir or (self.root / ".streamops" / "node" / "scene-profiles")
        template_root = self.root / "streamops" / "config" / "scene-templates"
        self.profile_store = SceneProfileStore(profile_root, template_root=template_root)
        self.ownership = ProfileOwnership(profile_root.parent / 'scene-ownership')
        self.artifact_root = artifact_root or (self.root / "streamops" / "artifacts" / "scene-review")
        self.client_factory = client_factory
        self.inventory_provider = inventory_provider
        self._mutation_lock = threading.RLock()
        self._jobs_lock = threading.Lock()
        self._jobs: dict[str, ReviewJob] = {}
        self._profile_snapshots: dict[str, dict[str, Any]] = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="streamops-scene-review")

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def status(self) -> dict[str, Any]:
        client = self._client()
        try:
            version = client.get_version()
            return {
                "connected": True,
                "obs_version": version.get("obsVersion") or version.get("obsStudioVersion"),
                "websocket_version": version.get("obsWebSocketVersion"),
                "current_scene": client.get_current_program_scene(),
                "streaming": bool(client.get_stream_status().get("outputActive")),
                "recording": bool(client.get_record_status().get("outputActive")),
            }
        finally:
            client.close()

    def list_scenes(self) -> list[dict[str, Any]]:
        return [{"name": name} for name in list_scene_names(root=self.root)]

    # Generic profile-manager API. Legacy named-scene methods remain available for
    # the CLI and existing automation while consumers migrate to stable profile IDs.
    def list_profiles(self) -> dict[str, Any]:
        return self.profile_store.list()

    def get_profile(self, profile_id: str) -> dict[str, Any]:
        return self.profile_store.get(profile_id)

    def create_profile(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.profile_store.create(payload)

    def update_profile(self, profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.profile_store.update(profile_id, payload)

    def duplicate_profile(self, profile_id: str, *, name: str | None = None) -> dict[str, Any]:
        return self.profile_store.duplicate(profile_id, name=name)

    def delete_profile(self, profile_id: str) -> None:
        self.profile_store.delete(profile_id)

    def catalog(self) -> list[dict[str, Any]]:
        return source_catalog()

    def list_templates(self) -> list[dict[str, Any]]:
        return self.profile_store.list_templates()

    def instantiate_template(self, template_id: str, *, name: str | None = None) -> dict[str, Any]:
        return self.profile_store.instantiate_template(template_id, name=name)

    def inventory(self) -> dict[str, Any]:
        from .source_inventory import discover
        client = self._client()
        try:
            return discover(client, **({"native_provider": self.inventory_provider} if self.inventory_provider else {}))
        finally:
            client.close()

    def apply_profile(self, profile_id: str) -> ApplyResult:
        profile = self._runtime_profile(self.profile_store.get(profile_id))
        with self._mutation_lock:
            client = self._client()
            try:
                return apply_profile(profile, client, ownership=self.ownership.session(client, profile))
            finally:
                client.close()

    def verify_profile(self, profile_id: str, *, runtime: bool = True) -> VerifyResult:
        profile = self._runtime_profile(self.profile_store.get(profile_id))
        with self._mutation_lock:
            client = self._client()
            try:
                return verify_profile(profile, client, runtime=runtime, ownership=self.ownership.session(client, profile))
            finally:
                client.close()

    def activate_profile(self, profile_id: str) -> dict[str, Any]:
        profile = self.profile_store.get(profile_id)
        with self._mutation_lock:
            client = self._client()
            try:
                client.set_current_program_scene(profile["obs_scene_name"])
                actual = client.get_current_program_scene()
                if actual != profile["obs_scene_name"]:
                    raise SceneOperationError(
                        f"OBS did not activate {profile['obs_scene_name']!r}; current scene is {actual!r}."
                    )
                return {"profile_id": profile_id, "scene": actual, "active": True}
            finally:
                client.close()

    def preview_profile(self, profile_id: str) -> bytes:
        profile = self.profile_store.get(profile_id)
        client = self._client()
        try:
            return client.get_source_screenshot(
                profile["obs_scene_name"], width=profile["canvas"]["width"], height=profile["canvas"]["height"]
            )
        finally:
            client.close()

    def start_profile_review(self, profile_id: str, *, seconds: int = 30) -> ReviewJob:
        profile = self.profile_store.get(profile_id)
        if not 1 <= seconds <= 300:
            raise SceneOperationError("Review seconds must be between 1 and 300.")
        now = _now()
        job = ReviewJob(uuid4().hex, profile_id, "queued", now, now, seconds)
        with self._jobs_lock:
            if any(j.state in ("queued", "running") for j in self._jobs.values()):
                raise SceneOperationError("A scene review is already queued or running.")
            self._jobs[job.job_id] = job
            self._profile_snapshots[job.job_id] = deepcopy(profile)
        self._executor.submit(self._run_profile_review, job.job_id)
        return job

    def _run_profile_review(self, job_id: str) -> None:
        from ..obs.scene import Check
        from ..obs.media_review import analyze_recording, recording_tracks
        self._update_job(job_id, state="running")
        job = self.review_job(job_id)
        profile = self._profile_snapshots[job_id]
        artifact_dir = self.artifact_root / profile["id"] / job.job_id
        verify = VerifyResult(profile["obs_scene_name"], "FAIL", _now(), None)
        failure = None
        client = None
        previous_scene = None
        switched = started = False
        try:
            artifact_dir.mkdir(parents=True, exist_ok=False)
            snapshot = artifact_dir / "profile.json"
            snapshot.write_text(json.dumps(profile, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            verify.artifacts["profile"] = str(snapshot)
            with self._mutation_lock:
                client = self._client()
                try:
                    if client.get_stream_status().get("outputActive") or client.get_record_status().get("outputActive"):
                        raise SceneOperationError("Review refuses active streaming or recording.")
                    runtime_profile = self._runtime_profile(profile)
                    ownership = self.ownership.session(client, profile)
                    verify = verify_profile(runtime_profile, client, ownership=ownership)
                    verify.artifacts["profile"] = str(snapshot)
                    if verify.status == "FAIL":
                        raise SceneOperationError("Structural verification failed before recording.")
                    tracks = recording_tracks(client)
                    previous_scene = client.get_current_program_scene()
                    client.set_current_program_scene(profile["obs_scene_name"])
                    switched = True
                    verify = verify_profile(runtime_profile, client, runtime=True, ownership=ownership)
                    verify.artifacts["profile"] = str(snapshot)
                    preview_path = artifact_dir / "preview.png"
                    preview_path.write_bytes(client.get_source_screenshot(profile["obs_scene_name"], width=profile["canvas"]["width"], height=profile["canvas"]["height"]))
                    verify.artifacts["preview"] = str(preview_path)
                    if verify.status == "FAIL":
                        raise SceneOperationError("Runtime signal verification failed before recording.")
                    client.start_record()
                    started = True
                    time.sleep(job.seconds)
                    stopped = _stop_recording_and_wait(client)
                    started = False
                    if not stopped.get("outputPath"):
                        raise SceneOperationError("OBS stopped recording without returning outputPath.")
                    source_path = Path(stopped["outputPath"])
                    _wait_for_stable_file(source_path)
                    target_path = artifact_dir / f"sample-{job.seconds}s{source_path.suffix or '.mkv'}"
                    shutil.copy2(source_path, target_path)
                    _wait_for_stable_file(target_path)
                    verify.artifacts["video"] = str(target_path)
                    checks, analysis = analyze_recording(target_path, _probe_media(target_path), profile, tracks, job.seconds)
                    verify.checks.extend(checks)
                    analysis_path = artifact_dir / "media-analysis.json"
                    analysis_path.write_text(json.dumps(analysis, indent=2, allow_nan=False), encoding="utf-8")
                    verify.artifacts["media_analysis"] = str(analysis_path)
                finally:
                    try:
                        if started:
                            _stop_recording_and_wait(client)
                    finally:
                        if switched and previous_scene:
                            client.set_current_program_scene(previous_scene)
        except Exception as exc:
            failure = str(exc)
            verify.add(Check("review.error", "FAIL", failure))
        finally:
            if client:
                client.close()
            self._profile_snapshots.pop(job_id, None)
        try:
            result = self._write_review_artifacts(artifact_dir, verify)
        except Exception as exc:
            result = verify.finalize().to_dict()
            failure = failure or f"Could not write review report: {exc}"
        self._update_job(job_id, state="failed" if failure else "completed", result=result, error=failure)

    def scene(self, scene_name: str, *, runtime_audio: bool = False) -> dict[str, Any]:
        config = load_scene_config(scene_name, root=self.root)
        client = self._client()
        try:
            result = verify_scene(
                scene_name,
                root=self.root,
                client=client,
                runtime_audio=runtime_audio,
                runtime_video=False,
            )
        finally:
            client.close()
        return {
            "name": config.name,
            "video": {
                "base_width": config.video.base_width,
                "base_height": config.video.base_height,
                "output_width": config.video.output_width,
                "output_height": config.video.output_height,
                "fps": config.video.fps,
            },
            "sources": [
                {
                    "role": source.role,
                    "source_name": source.source_name,
                    "media": source.media,
                    "managed": source.managed,
                    "signal_required": bool(source.audio and source.audio.signal_required),
                }
                for source in config.sources
            ],
            "verify": result.to_dict(),
        }

    def apply(self, scene_name: str) -> ApplyResult:
        with self._mutation_lock:
            client = self._client()
            try:
                return apply_scene(scene_name, root=self.root, client=client)
            finally:
                client.close()

    def verify(self, scene_name: str, *, runtime_audio: bool = True) -> VerifyResult:
        client = self._client()
        try:
            return verify_scene(
                scene_name,
                root=self.root,
                client=client,
                runtime_audio=runtime_audio,
                runtime_video=runtime_audio,
            )
        finally:
            client.close()

    def activate(self, scene_name: str) -> dict[str, Any]:
        load_scene_config(scene_name, root=self.root)
        with self._mutation_lock:
            client = self._client()
            try:
                client.set_current_program_scene(scene_name)
                actual = client.get_current_program_scene()
                if actual != scene_name:
                    raise SceneOperationError(
                        f"OBS did not activate {scene_name!r}; current scene is {actual!r}."
                    )
                return {"scene": scene_name, "active": True}
            finally:
                client.close()

    def preview(self, scene_name: str) -> bytes:
        config = load_scene_config(scene_name, root=self.root)
        client = self._client()
        try:
            return client.get_source_screenshot(
                scene_name,
                width=config.video.output_width,
                height=config.video.output_height,
            )
        finally:
            client.close()

    def start_review(self, scene_name: str, *, seconds: int = 30) -> ReviewJob:
        load_scene_config(scene_name, root=self.root)
        if not 1 <= seconds <= 300:
            raise SceneOperationError("Review seconds must be between 1 and 300.")
        now = _now()
        job = ReviewJob(
            job_id=uuid4().hex,
            scene=scene_name,
            state="queued",
            created_at=now,
            updated_at=now,
            seconds=seconds,
        )
        with self._jobs_lock:
            self._jobs[job.job_id] = job
        self._executor.submit(self._run_review, job.job_id)
        return job

    def review_job(self, job_id: str) -> ReviewJob:
        with self._jobs_lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise SceneReviewNotFoundError(f"Scene review job not found: {job_id}")
            return ReviewJob(**job.__dict__)

    def _run_review(self, job_id: str) -> None:
        self._update_job(job_id, state="running")
        try:
            result = self._perform_review(self.review_job(job_id))
        except Exception as exc:
            self._update_job(job_id, state="failed", error=str(exc))
        else:
            self._update_job(job_id, state="completed", result=result)

    def _perform_review(self, job: ReviewJob) -> dict[str, Any]:
        with self._mutation_lock:
            config = load_scene_config(job.scene, root=self.root)
            client = self._client()
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            artifact_dir = self.artifact_root / job.scene / f"{stamp}-{job.job_id[:8]}"
            artifact_dir.mkdir(parents=True, exist_ok=False)
            try:
                verify = verify_scene(
                    job.scene,
                    root=self.root,
                    client=client,
                    runtime_audio=True,
                    runtime_video=True,
                )
                preview_path = artifact_dir / "preview.png"
                client.save_source_screenshot(
                    job.scene,
                    preview_path,
                    width=config.video.output_width,
                    height=config.video.output_height,
                )
                verify.artifacts["preview"] = str(preview_path)

                if verify.status == "FAIL":
                    return self._write_review_artifacts(artifact_dir, verify)

                if client.get_stream_status().get("outputActive"):
                    raise SceneOperationError("Refusing scene review recording while streaming is active.")
                if client.get_record_status().get("outputActive"):
                    raise SceneOperationError("Refusing scene review recording while recording is already active.")

                previous_scene = client.get_current_program_scene()
                started = False
                try:
                    client.set_current_program_scene(job.scene)
                    client.start_record()
                    started = True
                    time.sleep(job.seconds)
                    stop = _stop_recording_and_wait(client)
                    started = False
                    output_path = stop.get("outputPath")
                    if not output_path:
                        raise SceneOperationError("OBS stopped recording without returning outputPath.")
                    source_path = Path(str(output_path)).expanduser()
                    _wait_for_stable_file(source_path)
                    target_path = artifact_dir / f"sample-{job.seconds}s{source_path.suffix or '.mkv'}"
                    shutil.copy2(source_path, target_path)
                    _wait_for_stable_file(target_path, timeout_seconds=5)
                    verify.artifacts["video"] = str(target_path)
                    verify.artifacts["video_source"] = str(source_path)
                    probe = _probe_media(target_path)
                    (artifact_dir / "media-analysis.json").write_text(
                        json.dumps(probe, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    verify.artifacts["media_analysis"] = str(artifact_dir / "media-analysis.json")
                    _append_media_checks(verify, probe, config.video.output_width, config.video.output_height)
                finally:
                    if started:
                        _stop_recording_and_wait(client)
                    if previous_scene and previous_scene != job.scene:
                        client.set_current_program_scene(previous_scene)

                return self._write_review_artifacts(artifact_dir, verify)
            finally:
                client.close()

    def _write_review_artifacts(
        self,
        artifact_dir: Path,
        verify: VerifyResult,
    ) -> dict[str, Any]:
        verify.finalize()
        verify_path = artifact_dir / "verify.json"
        report_path = artifact_dir / "report.md"
        verify.artifacts["verify"] = str(verify_path)
        verify.artifacts["report"] = str(report_path)
        verify_path.write_text(
            json.dumps(verify.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        report_path.write_text(_render_report(verify), encoding="utf-8")
        return verify.to_dict()

    def _client(self) -> ObsClient:
        factory = self.client_factory
        if hasattr(factory, "from_env"):
            return factory.from_env()
        return factory()

    def _runtime_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(profile)
        for source in result["sources"]:
            for key in ("file", "local_file"):
                value = source["settings"].get(key)
                if not isinstance(value, str) or not value:
                    continue
                path = Path(value).expanduser()
                if not path.is_absolute() and (self.root / path).is_file():
                    source["settings"][key] = str((self.root / path).resolve())
        return result

    def _update_job(
        self,
        job_id: str,
        *,
        state: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self._jobs_lock:
            job = self._jobs[job_id]
            job.state = state
            job.updated_at = _now()
            job.result = result
            job.error = error


def _append_media_checks(
    verify: VerifyResult,
    probe: dict[str, Any],
    expected_width: int,
    expected_height: int,
) -> None:
    from ..obs.scene import Check

    streams = probe.get("streams", [])
    video_streams = [item for item in streams if item.get("codec_type") == "video"]
    audio_streams = [item for item in streams if item.get("codec_type") == "audio"]
    verify.add(Check(
        id="review.video_stream",
        status="PASS" if video_streams else "FAIL",
        message="Recorded sample contains a video stream.",
        expected=True,
        actual=bool(video_streams),
    ))
    verify.add(Check(
        id="review.audio_stream",
        status="PASS" if audio_streams else "FAIL",
        message="Recorded sample contains an audio stream.",
        expected=True,
        actual=bool(audio_streams),
    ))
    if video_streams:
        first = video_streams[0]
        actual = {"width": first.get("width"), "height": first.get("height")}
        expected = {"width": expected_width, "height": expected_height}
        verify.add(Check(
            id="review.resolution",
            status="PASS" if actual == expected else "FAIL",
            message="Recorded sample resolution matches desired output.",
            expected=expected,
            actual=actual,
        ))


def _probe_media(path: Path) -> dict[str, Any]:
    executable = shutil.which("ffprobe")
    if executable is None:
        raise SceneOperationError("ffprobe is required for G4 recorded E2E review.")
    completed = subprocess.run(
        [
            executable,
            "-v", "error",
            "-show_streams",
            "-show_format",
            "-of", "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if completed.returncode != 0:
        raise SceneOperationError(
            f"ffprobe failed for review sample: {completed.stderr.strip() or completed.returncode}"
        )
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SceneOperationError("ffprobe returned invalid JSON.") from exc

    duration = _positive_duration((data.get("format") or {}).get("duration"))
    if duration is None:
        stream_durations = [
            value
            for value in (
                _positive_duration(stream.get("duration"))
                for stream in data.get("streams", [])
                if isinstance(stream, dict)
            )
            if value is not None
        ]
        duration = max(stream_durations, default=None)

    if duration is None:
        duration = _probe_packet_duration(executable, path)

    if duration is None:
        raise SceneOperationError(
            "Recorded review sample duration is unavailable from container, stream, and packet timestamps."
        )

    media_format = data.setdefault("format", {})
    if not isinstance(media_format, dict):
        media_format = {}
        data["format"] = media_format
    media_format["duration"] = f"{duration:.6f}"
    return data


def _positive_duration(value: Any) -> float | None:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(duration) or duration <= 0:
        return None
    return duration


def _probe_packet_duration(executable: str, path: Path) -> float | None:
    completed = subprocess.run(
        [
            executable,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_packets",
            "-show_entries", "packet=pts_time,dts_time,duration_time",
            "-of", "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None

    starts: list[float] = []
    ends: list[float] = []
    for packet in payload.get("packets", []):
        if not isinstance(packet, dict):
            continue
        start = _packet_timestamp(packet)
        if start is None:
            continue
        starts.append(start)
        packet_duration = _positive_duration(packet.get("duration_time")) or 0.0
        ends.append(start + packet_duration)

    if not starts or not ends:
        return None
    duration = max(ends) - min(starts)
    return duration if math.isfinite(duration) and duration > 0 else None


def _packet_timestamp(packet: dict[str, Any]) -> float | None:
    for key in ("pts_time", "dts_time"):
        value = packet.get(key)
        try:
            timestamp = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(timestamp):
            return timestamp
    return None


def _wait_for_stable_file(
    path: Path,
    *,
    timeout_seconds: float = 30,
    poll_seconds: float = 0.5,
    quiet_seconds: float = 2.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_size: int | None = None
    stable_since: float | None = None
    while True:
        observed_at = time.monotonic()
        if observed_at >= deadline:
            break
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if size > 0 and size != last_size:
            stable_since = observed_at
        elif size <= 0:
            stable_since = None
        elif stable_since is None:
            stable_since = observed_at
        if stable_since is not None and observed_at - stable_since >= quiet_seconds:
            return
        last_size = size
        time.sleep(poll_seconds)
    raise SceneOperationError(f"Review sample was not finalized: {path}")


def _stop_recording_and_wait(
    client: Any,
    *,
    timeout_seconds: float = 30,
    poll_seconds: float = 0.1,
) -> dict[str, Any]:
    if not client.get_record_status().get("outputActive"):
        return {}

    result = client.stop_record()
    deadline = time.monotonic() + timeout_seconds
    while client.get_record_status().get("outputActive"):
        if time.monotonic() >= deadline:
            raise SceneOperationError(
                f"OBS recording did not become inactive within {timeout_seconds:g} seconds."
            )
        time.sleep(poll_seconds)
    return result


def _render_report(result: VerifyResult) -> str:
    lines = [
        f"# {result.scene} Review: {result.status}",
        "",
        f"- Generated: `{result.generated_at}`",
        f"- OBS version: `{result.obs_version or 'unknown'}`",
        "",
        "## Checks",
        "",
    ]
    for check in result.checks:
        lines.append(f"- `{check.status}` `{check.id}`: {check.message}")
    lines.extend(["", "## Artifacts", ""])
    for name, path in sorted(result.artifacts.items()):
        lines.append(f"- `{name}`: `{path}`")
    lines.extend([
        "",
        "## Manual acceptance checklist (G5)",
        "",
        "- [ ] Preview composition and crops are visually correct.",
        "- [ ] Recorded sample has acceptable lip-sync and subjective audio quality.",
        "- [ ] Operator confirms the final mix and any optional isolated tracks.",
    ])
    return "\n".join(lines) + "\n"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
