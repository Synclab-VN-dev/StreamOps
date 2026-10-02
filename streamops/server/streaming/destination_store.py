"""Atomic JSON store for livestream destinations."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from typing import Any

from ..errors import StreamingError
from .models import normalize_destination, require_destination_id


class DestinationStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.RLock()

    def list(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_root()
            destinations: list[dict[str, Any]] = []
            errors: list[dict[str, str]] = []
            for path in sorted(self.root.glob("*.json")):
                if ".tmp-" in path.name:
                    continue
                try:
                    destination = self._read(path)
                    if path.stem != destination["id"]:
                        raise StreamingError("destination_invalid", "Destination filename does not match its id.", 422)
                    destinations.append(destination)
                except StreamingError as exc:
                    errors.append({"file": path.name, "error": str(exc)})
            destinations.sort(key=lambda item: (item["name"].casefold(), item["id"]))
            return {"destinations": destinations, "errors": errors}

    def get(self, destination_id: str) -> dict[str, Any]:
        with self._lock:
            path = self._path(destination_id)
            if not path.is_file():
                raise StreamingError("destination_not_found", f"Streaming destination not found: {destination_id}", 404)
            return self._read(path)

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            destination = normalize_destination(payload)
            path = self._path(destination["id"])
            if path.exists():
                raise StreamingError("destination_conflict", "Streaming destination already exists.", 409)
            self._write(path, destination)
            return destination

    def update(self, destination_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.get(destination_id)
            destination = normalize_destination(payload, destination_id=destination_id)
            self._write(self._path(destination_id), destination)
            return destination

    def delete(self, destination_id: str) -> None:
        with self._lock:
            path = self._path(destination_id)
            if not path.is_file():
                raise StreamingError("destination_not_found", f"Streaming destination not found: {destination_id}", 404)
            try:
                path.unlink()
            except OSError as exc:
                raise StreamingError("destination_storage_failed", f"Could not delete streaming destination: {exc}", 500) from exc

    def _path(self, destination_id: str) -> Path:
        require_destination_id(destination_id)
        return self.root / f"{destination_id}.json"

    def _read(self, path: Path) -> dict[str, Any]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StreamingError("destination_storage_failed", f"Could not read {path.name}: {exc}", 500) from exc
        if not isinstance(raw, dict):
            raise StreamingError("destination_invalid", f"{path.name} must contain an object.", 422)
        return normalize_destination(raw, destination_id=str(raw.get("id") or ""))

    def _ensure_root(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StreamingError("destination_storage_failed", f"Could not create destination storage: {exc}", 500) from exc

    def _write(self, path: Path, payload: dict[str, Any]) -> None:
        self._ensure_root()
        temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise StreamingError("destination_storage_failed", f"Could not atomically write {path.name}: {exc}", 500) from exc
