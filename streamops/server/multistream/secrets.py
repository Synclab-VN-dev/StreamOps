"""Local credential storage for public, slug-based multistream identities."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading

from ..errors import StreamingError


class MultistreamSecretStore:
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
                value = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError as exc:
                raise StreamingError("credential_missing", "Stream credential is not configured.", 409) from exc
            except (OSError, json.JSONDecodeError) as exc:
                raise StreamingError("credential_storage_failed", "Could not read stream credential.", 500) from exc
            credential = value.get("credential") if isinstance(value, dict) else None
            if not isinstance(credential, str) or not credential:
                raise StreamingError("credential_missing", "Stream credential is not configured.", 409)
            return credential

    def set(self, destination_id: str, credential: str) -> None:
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self._path(destination_id)
            temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
            try:
                with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                    json.dump({"credential": credential}, handle, ensure_ascii=False)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            except OSError as exc:
                temporary.unlink(missing_ok=True)
                raise StreamingError("credential_storage_failed", "Could not store stream credential.", 500) from exc

    def delete(self, destination_id: str) -> None:
        with self._lock:
            try:
                self._path(destination_id).unlink(missing_ok=True)
            except OSError as exc:
                raise StreamingError("credential_storage_failed", "Could not delete stream credential.", 500) from exc

    def _path(self, destination_id: str) -> Path:
        if not destination_id or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for character in destination_id
        ):
            raise StreamingError("destination_invalid", "Invalid destination_id.", 422)
        return self.root / f"{destination_id}.json"
