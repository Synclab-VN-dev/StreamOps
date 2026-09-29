"""OBS and managed-scene endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import Any

from ..auth import require_access
from ..services.obs_scene import ObsSceneService


router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_access)])


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seconds: int = Field(default=30, ge=1, le=300)


class DuplicateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=120)


class TemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=120)


def _service(request: Request) -> ObsSceneService:
    return request.app.state.obs_scene_service


@router.get("/obs/status")
def obs_status(request: Request) -> dict[str, object]:
    return _service(request).status()


@router.get("/obs/source-catalog")
def obs_source_catalog(request: Request) -> dict[str, object]:
    return {"sources": _service(request).catalog()}


@router.get("/obs/inventory")
def obs_inventory(request: Request) -> dict[str, object]:
    return _service(request).inventory()


@router.get("/scene-profiles")
def list_scene_profiles(request: Request) -> dict[str, object]:
    return _service(request).list_profiles()


@router.post("/scene-profiles", status_code=201)
def create_scene_profile(payload: dict[str, Any], request: Request) -> dict[str, object]:
    return _service(request).create_profile(payload)


@router.get("/scene-profiles/{profile_id}")
def get_scene_profile(profile_id: str, request: Request) -> dict[str, object]:
    return _service(request).get_profile(profile_id)


@router.put("/scene-profiles/{profile_id}")
def update_scene_profile(profile_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    return _service(request).update_profile(profile_id, payload)


@router.delete("/scene-profiles/{profile_id}", status_code=204)
def delete_scene_profile(profile_id: str, request: Request) -> Response:
    _service(request).delete_profile(profile_id)
    return Response(status_code=204)


@router.post("/scene-profiles/{profile_id}/duplicate", status_code=201)
def duplicate_scene_profile(profile_id: str, request: Request, payload: DuplicateRequest | None = None) -> dict[str, object]:
    return _service(request).duplicate_profile(profile_id, name=payload.name if payload else None)


@router.post("/scene-profiles/{profile_id}/apply")
def apply_scene_profile(profile_id: str, request: Request) -> dict[str, object]:
    return _service(request).apply_profile(profile_id).to_dict()


@router.post("/scene-profiles/{profile_id}/verify")
def verify_scene_profile(profile_id: str, request: Request) -> dict[str, object]:
    return _service(request).verify_profile(profile_id, runtime=True).to_dict()


@router.post("/scene-profiles/{profile_id}/activate")
def activate_scene_profile(profile_id: str, request: Request) -> dict[str, object]:
    return _service(request).activate_profile(profile_id)


@router.get("/scene-profiles/{profile_id}/preview")
def scene_profile_preview(profile_id: str, request: Request) -> Response:
    return Response(content=_service(request).preview_profile(profile_id), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/scene-profiles/{profile_id}/review")
def review_scene_profile(profile_id: str, request: Request, payload: ReviewRequest | None = None) -> JSONResponse:
    job = _service(request).start_profile_review(profile_id, seconds=payload.seconds if payload else 30)
    return JSONResponse(status_code=202, content=job.to_dict())


@router.get("/scene-profile-templates")
def list_scene_profile_templates(request: Request) -> dict[str, object]:
    return {"templates": _service(request).list_templates()}


@router.post("/scene-profile-templates/{template_id}/instantiate", status_code=201)
def instantiate_scene_profile_template(template_id: str, request: Request, payload: TemplateRequest | None = None) -> dict[str, object]:
    return _service(request).instantiate_template(template_id, name=payload.name if payload else None)


@router.get("/scenes")
def list_scenes(request: Request) -> dict[str, object]:
    return {"scenes": _service(request).list_scenes()}


@router.get("/scenes/{scene_name}")
def scene_status(scene_name: str, request: Request) -> dict[str, object]:
    return _service(request).scene(scene_name)


@router.post("/scenes/{scene_name}/apply")
def apply_scene(scene_name: str, request: Request) -> dict[str, object]:
    return _service(request).apply(scene_name).to_dict()


@router.post("/scenes/{scene_name}/verify")
def verify_scene(scene_name: str, request: Request) -> dict[str, object]:
    return _service(request).verify(scene_name, runtime_audio=True).to_dict()


@router.post("/scenes/{scene_name}/activate")
def activate_scene(scene_name: str, request: Request) -> dict[str, object]:
    return _service(request).activate(scene_name)


@router.get("/scenes/{scene_name}/preview")
def scene_preview(scene_name: str, request: Request) -> Response:
    return Response(
        content=_service(request).preview(scene_name),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/scenes/{scene_name}/review")
def start_scene_review(
    scene_name: str,
    request: Request,
    payload: ReviewRequest | None = None,
) -> JSONResponse:
    job = _service(request).start_review(scene_name, seconds=(payload.seconds if payload else 30))
    return JSONResponse(status_code=202, content=job.to_dict())


@router.get("/scene-reviews/{job_id}")
def scene_review_status(job_id: str, request: Request) -> dict[str, object]:
    return _service(request).review_job(job_id).to_dict()
