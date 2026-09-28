"""Steam management endpoints."""

from fastapi import APIRouter, Depends, Request, Response

from ..auth import require_access
from ..errors import InvalidSteamRestartRequestError
from ..services import SteamService


router = APIRouter(prefix="/api/v1/steam", dependencies=[Depends(require_access)])


def _service(request: Request) -> SteamService:
    return request.app.state.steam_service


@router.get("/status")
async def steam_status(request: Request, response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    status = await _service(request).status()
    return status.api_payload()


@router.post("/restart")
async def restart_steam(request: Request) -> dict[str, object]:
    if await request.body():
        raise InvalidSteamRestartRequestError(
            "Steam restart does not accept a request body, executable path, command, or arguments."
        )
    result = await _service(request).restart()
    return result.api_payload()
