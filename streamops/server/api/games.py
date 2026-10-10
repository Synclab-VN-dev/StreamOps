"""REST mirror: diagnostics/CLI only; one GameService shared with games/ws."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from ..auth import require_access
from ..services.games.access import GameAccessDenied, require_mutation
from ..services.games.lifecycle import GameServiceError

router = APIRouter(dependencies=[Depends(require_access)])

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Action(Strict):
    action: str

def _service(request: Request):
    return request.app.state.game_service

def _raise(exc: GameServiceError):
    status = 404 if exc.code in ("game_not_found","operation_not_found") else 409
    if exc.code in ("invalid_request","invalid_action","invalid_provider","idempotency_conflict"):
        status = 422
    raise HTTPException(status_code=status, detail={"code":exc.code,"message":str(exc)})

@router.get("/api/v1/games")
async def games_list(request: Request, response: Response, provider: str | None = None):
    response.headers["Cache-Control"]="no-store"
    try: return await _service(request).list(provider)
    except GameServiceError as exc: _raise(exc)

@router.get("/api/v1/games/{game_id}")
async def games_get(game_id: str, request: Request, response: Response):
    response.headers["Cache-Control"]="no-store"
    try: return await _service(request).get(game_id)
    except GameServiceError as exc: _raise(exc)

@router.post("/api/v1/games/{game_id}/actions", status_code=202)
async def game_action(game_id: str, body: Action, request: Request,
                      idempotency_key: str | None = Header(default=None)):
    try: require_mutation(request.headers)
    except GameAccessDenied as exc: raise HTTPException(status_code=403,detail={"code":exc.code,"message":str(exc)})
    try: return await _service(request).action(game_id, body.action, idempotency_key or "")
    except GameServiceError as exc: _raise(exc)

@router.get("/api/v1/game-operations/{operation_id}")
async def game_operation(operation_id: str, request: Request):
    try: return _service(request).operation(operation_id)
    except GameServiceError as exc: _raise(exc)

@router.post("/api/v1/games/{game_id}/reconcile")
async def game_reconcile(game_id: str, request: Request):
    try: return await _service(request).reconcile(game_id)
    except GameServiceError as exc: _raise(exc)

@router.post("/api/v1/game-catalog/refresh")
async def game_catalog_refresh(request: Request):
    try: return await _service(request).refresh_catalog()
    except GameServiceError as exc: _raise(exc)
