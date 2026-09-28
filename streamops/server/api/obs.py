"""OBS and managed-scene endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..auth import require_access
from ..services.obs_scene import ObsSceneService


router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_access)])


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seconds: int = Field(default=30, ge=1, le=300)


def _service(request: Request) -> ObsSceneService:
    return request.app.state.obs_scene_service


@router.get("/obs/status")
async def obs_status(request: Request) -> dict[str, object]:
    return _service(request).status()


@router.get("/scenes")
async def list_scenes(request: Request) -> dict[str, object]:
    return {"scenes": _service(request).list_scenes()}


@router.get("/scenes/{scene_name}")
async def scene_status(scene_name: str, request: Request) -> dict[str, object]:
    return _service(request).scene(scene_name)


@router.post("/scenes/{scene_name}/apply")
async def apply_scene(scene_name: str, request: Request) -> dict[str, object]:
    return _service(request).apply(scene_name).to_dict()


@router.post("/scenes/{scene_name}/verify")
async def verify_scene(scene_name: str, request: Request) -> dict[str, object]:
    return _service(request).verify(scene_name, runtime_audio=True).to_dict()


@router.post("/scenes/{scene_name}/activate")
async def activate_scene(scene_name: str, request: Request) -> dict[str, object]:
    return _service(request).activate(scene_name)


@router.get("/scenes/{scene_name}/preview")
async def scene_preview(scene_name: str, request: Request) -> Response:
    return Response(
        content=_service(request).preview(scene_name),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/scenes/{scene_name}/review")
async def start_scene_review(
    scene_name: str,
    request: Request,
    payload: ReviewRequest | None = None,
) -> JSONResponse:
    job = _service(request).start_review(scene_name, seconds=(payload.seconds if payload else 30))
    return JSONResponse(status_code=202, content=job.to_dict())


@router.get("/scene-reviews/{job_id}")
async def scene_review_status(job_id: str, request: Request) -> dict[str, object]:
    return _service(request).review_job(job_id).to_dict()
