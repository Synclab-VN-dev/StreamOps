from __future__ import annotations

from fastapi.testclient import TestClient
from pathlib import Path
from types import SimpleNamespace

from streamops.server.app import create_app
from streamops.server.errors import SceneOperationError, SceneReviewArtifactNotFoundError
from streamops.server.obs.scene import ApplyResult, Change, Check, VerifyResult
from streamops.server.services.obs_scene import ReviewJob


class FakeObsSceneService:
    def __init__(self) -> None:
        self.apply_error: Exception | None = None
        self.artifact_path: Path | None = None
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def status(self) -> dict:
        return {
            "connected": True,
            "obs_version": "32.0.2",
            "websocket_version": "5.7.0",
            "current_scene": "livestream-d4",
            "streaming": False,
            "recording": False,
        }

    def list_scenes(self) -> list[dict]:
        return [{"name": "livestream-d4"}]

    def scene(self, scene_name: str, *, runtime_audio: bool = False) -> dict:
        return {
            "name": scene_name,
            "video": {
                "base_width": 1920,
                "base_height": 1080,
                "output_width": 1920,
                "output_height": 1080,
                "fps": 60,
            },
            "sources": [],
            "verify": self.verify(scene_name).to_dict(),
        }

    def apply(self, scene_name: str) -> ApplyResult:
        if self.apply_error:
            raise self.apply_error
        return ApplyResult(
            scene=scene_name,
            changed=True,
            changes=(Change("scene.create", "created"),),
        )

    def verify(self, scene_name: str, *, runtime_audio: bool = True) -> VerifyResult:
        result = VerifyResult(
            scene=scene_name,
            status="PASS",
            generated_at="2026-09-28T12:00:00Z",
            obs_version="32.0.2",
        )
        result.add(Check("audio.voice.signal", "PASS", "voice signal"))
        return result.finalize()

    def activate(self, scene_name: str) -> dict:
        return {"scene": scene_name, "active": True}

    def preview(self, scene_name: str) -> bytes:
        return b"\x89PNG\r\n\x1a\npreview"

    def start_review(self, scene_name: str, *, seconds: int = 30) -> ReviewJob:
        return ReviewJob(
            job_id="job-1",
            scene=scene_name,
            state="queued",
            created_at="2026-09-28T12:00:00Z",
            updated_at="2026-09-28T12:00:00Z",
            seconds=seconds,
        )

    def review_job(self, job_id: str) -> ReviewJob:
        return ReviewJob(
            job_id=job_id,
            scene="livestream-d4",
            state="completed",
            created_at="2026-09-28T12:00:00Z",
            updated_at="2026-09-28T12:00:01Z",
            seconds=30,
            result=self.verify("livestream-d4").to_dict(),
        )

    def review_artifact(self, job_id: str, artifact_key: str) -> Path:
        if job_id != "job-1" or artifact_key != "preview" or self.artifact_path is None:
            raise SceneReviewArtifactNotFoundError(f"Scene review artifact not found: {artifact_key}")
        return self.artifact_path


class ReadyObsManager:
    def status(self):
        return SimpleNamespace(state="READY")


def _client(server_config, capture_service, service: FakeObsSceneService) -> TestClient:
    return TestClient(
        create_app(
            server_config,
            capture_service=capture_service,
            obs_manager=ReadyObsManager(),
            obs_scene_service=service,
            manage_runtime=False,
        )
    )


def test_obs_status_and_scene_contract(server_config, capture_service) -> None:
    service = FakeObsSceneService()
    with _client(server_config, capture_service, service) as client:
        status = client.get("/api/v1/obs/status")
        scene = client.get("/api/v1/scenes/livestream-d4")
        preview = client.get("/api/v1/scenes/livestream-d4/preview")

    assert status.status_code == 200
    assert status.json()["connected"] is True
    assert scene.status_code == 200
    assert scene.json()["video"]["fps"] == 60
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    assert preview.content.startswith(b"\x89PNG")


def test_apply_verify_activate_contract(server_config, capture_service) -> None:
    service = FakeObsSceneService()
    with _client(server_config, capture_service, service) as client:
        applied = client.post("/api/v1/scenes/livestream-d4/apply")
        verified = client.post("/api/v1/scenes/livestream-d4/verify")
        activated = client.post("/api/v1/scenes/livestream-d4/activate")

    assert applied.status_code == 200
    assert applied.json()["changed"] is True
    assert verified.status_code == 200
    assert verified.json()["status"] == "PASS"
    assert activated.json() == {"scene": "livestream-d4", "active": True}


def test_review_is_job_based_and_rejects_unknown_input(server_config, capture_service) -> None:
    service = FakeObsSceneService()
    with _client(server_config, capture_service, service) as client:
        started = client.post(
            "/api/v1/scenes/livestream-d4/review",
            json={"seconds": 45},
        )
        status = client.get("/api/v1/scene-reviews/job-1")
        rejected = client.post(
            "/api/v1/scenes/livestream-d4/review",
            json={"seconds": 30, "command": "arbitrary"},
        )

    assert started.status_code == 202
    assert started.json()["state"] == "queued"
    assert started.json()["seconds"] == 45
    assert status.status_code == 200
    assert status.json()["state"] == "completed"
    assert rejected.status_code == 422


def test_review_artifact_supports_inline_and_download(
    server_config, capture_service, tmp_path: Path
) -> None:
    service = FakeObsSceneService()
    service.artifact_path = tmp_path / "preview.png"
    service.artifact_path.write_bytes(b"\x89PNG\r\n\x1a\npreview")
    with _client(server_config, capture_service, service) as client:
        inline = client.get("/api/v1/scene-reviews/job-1/artifacts/preview")
        download = client.get("/api/v1/scene-reviews/job-1/artifacts/preview?download=true")
        missing = client.get("/api/v1/scene-reviews/job-1/artifacts/missing")
        traversal = client.get("/api/v1/scene-reviews/job-1/artifacts/../preview")

    assert inline.status_code == 200
    assert inline.content == service.artifact_path.read_bytes()
    assert inline.headers["content-type"] == "image/png"
    assert inline.headers["content-disposition"].startswith('inline; filename="preview.png"')
    assert inline.headers["cache-control"] == "no-store"
    assert download.headers["content-disposition"].startswith('attachment; filename="preview.png"')
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "scene_review_artifact_not_found"
    assert traversal.status_code == 404


def test_scene_operation_error_has_stable_contract(server_config, capture_service) -> None:
    service = FakeObsSceneService()
    service.apply_error = SceneOperationError("Unsafe mutation while streaming.")
    with _client(server_config, capture_service, service) as client:
        response = client.post("/api/v1/scenes/livestream-d4/apply")

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "scene_operation_failed",
        "message": "Unsafe mutation while streaming.",
    }
