"""HTTP entry point for the shared multistream core."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Body, Depends, Request
from ..auth import require_access
from ..services.multistream import MultistreamService
router=APIRouter(prefix="/api/v1/multistream",dependencies=[Depends(require_access)])
def _s(r:Request)->MultistreamService:return r.app.state.multistream_service
@router.get("/destinations")
def list_destinations(request:Request): return _s(request).list_destinations()
@router.post("/destinations",status_code=201)
def create_destination(request:Request,payload:dict[str,Any]=Body(...)): return _s(request).create_destination(payload)
@router.get("/destinations/{destination_id}")
def get_destination(destination_id:str,request:Request): return _s(request).get_destination(destination_id)
@router.patch("/destinations/{destination_id}")
def update_destination(destination_id:str,request:Request,payload:dict[str,Any]=Body(...)): return _s(request).update_destination(destination_id,payload)
@router.delete("/destinations/{destination_id}")
def delete_destination(destination_id:str,request:Request): return _s(request).delete_destination(destination_id)
@router.post("/destinations/{destination_id}/start")
def start_destination(destination_id:str,request:Request): return _s(request).start_destination(destination_id)
@router.post("/destinations/{destination_id}/stop")
def stop_destination(destination_id:str,request:Request): return _s(request).stop_destination(destination_id)
@router.get("/destinations/{destination_id}/status")
def status(destination_id:str,request:Request): return _s(request).status(destination_id)
@router.get("/destinations/{destination_id}/stats")
def stats(destination_id:str,request:Request): return _s(request).stats(destination_id)
