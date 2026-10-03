"""Separate local storage for stream credentials.

The public destination API never returns values from this store.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading

from ..errors import StreamingError
from .models import require_destination_id


class SecretStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.RLock()

    def exists(self, destination_id: str) -> bool:
        with self._lock:
            return self._path(destination_id).is_file()

    def get(self, destination_id: str) -> str:
        with self._lock:
            path = self._path(destination_id)
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError as exc:
                raise StreamingError("credential_missing", "Stream credential is not configured.", 409) from exc
            except (OSError, json.JSONDecodeError) as exc:
                raise StreamingError("credential_storage_failed", "Could not read stream credential.", 500) from exc
            credential = raw.get("credential") if isinstance(raw, dict) else None
            if not isinstance(credential, str) or not credential:
                raise StreamingError("credential_missing", "Stream credential is not configured.", 409)
            return credential

    def set(self, destination_id: str, credential: str) -> None:
        require_destination_id(destination_id)
        if not isinstance(credential, str) or not credential.strip() or "\x00" in credential or len(credential) > 4096:
            raise StreamingError("credential_invalid", "credential must be a non-empty string of at most 4096 characters.", 422)
        with self._lock:
            self._ensure_root()
            self._atomic_write(self._path(destination_id), {"credential": credential.strip()})

    def delete(self, destination_id: str) -> None:
        with self._lock:
            path = self._path(destination_id)
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                raise StreamingError("credential_storage_failed", "Could not delete stream credential.", 500) from exc

    def _path(self, destination_id: str) -> Path:
        require_destination_id(destination_id)
        return self.root / f"{destination_id}.json"

    def _ensure_root(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StreamingError("credential_storage_failed", "Could not create credential storage.", 500) from exc

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, str]) -> None:
        temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise StreamingError("credential_storage_failed", "Could not atomically write stream credential.", 500) from exc
