"""Atomic persistence for StreamOps-owned multistream identity."""
from __future__ import annotations
import json, os, threading
from pathlib import Path
from typing import Any
from ..errors import StreamingError

class MultistreamRepository:
    def __init__(self, root: Path) -> None:
        self.root=root; self._lock=threading.RLock()
    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            return [self._read(p) for p in sorted(self.root.glob("*.json")) if ".tmp-" not in p.name]
    def get(self, destination_id: str) -> dict[str, Any]:
        p=self._path(destination_id)
        if not p.is_file(): raise StreamingError("destination_not_found", f"Multistream destination not found: {destination_id}",404)
        return self._read(p)
    def save(self, item: dict[str, Any], *, create: bool=False) -> dict[str, Any]:
        with self._lock:
            p=self._path(str(item["id"]))
            if create and p.exists(): raise StreamingError("destination_conflict","Multistream destination already exists.",409)
            self.root.mkdir(parents=True, exist_ok=True)
            tmp=p.with_name(f".{p.name}.tmp-{os.getpid()}-{threading.get_ident()}")
            tmp.write_text(json.dumps(item,indent=2,ensure_ascii=False)+"\n",encoding="utf-8"); os.replace(tmp,p); return dict(item)
    def delete(self, destination_id: str) -> None:
        p=self._path(destination_id)
        if not p.is_file(): raise StreamingError("destination_not_found",f"Multistream destination not found: {destination_id}",404)
        p.unlink()
    def _path(self, value: str) -> Path:
        if not value or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in value): raise StreamingError("destination_invalid","id must contain only letters, digits, '-' or '_'.",422)
        return self.root/f"{value}.json"
    def _read(self,p:Path)->dict[str,Any]: return dict(json.loads(p.read_text(encoding="utf-8")))
