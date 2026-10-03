"""Persistent live-session state with a separate private restore snapshot."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import threading
from typing import Any

from ..errors import StreamingError


class LiveSessionStore:
    """Persist non-secret session metadata separately from sensitive OBS restore state."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.session_path = root / "session.json"
        self.restore_path = root / "restore.private.json"
        self._lock = threading.RLock()

    def load_session(self) -> dict[str, Any] | None:
        return self._read_optional(self.session_path, "live session")

    def save_session(self, session: dict[str, Any]) -> None:
        with self._lock:
            self._atomic_write(self.session_path, deepcopy(session))

    def clear_session(self) -> None:
        self._delete(self.session_path)

    def load_restore(self) -> dict[str, Any] | None:
        return self._read_optional(self.restore_path, "private OBS restore snapshot")

    def save_restore(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            self._atomic_write(self.restore_path, deepcopy(snapshot))

    def clear_restore(self) -> None:
        self._delete(self.restore_path)

    def clear_all(self) -> None:
        with self._lock:
            self._delete(self.session_path)
            self._delete(self.restore_path)

    def has_restore(self) -> bool:
        return self.restore_path.is_file()

    def _read_optional(self, path: Path, label: str) -> dict[str, Any] | None:
        with self._lock:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return None
            except (OSError, json.JSONDecodeError) as exc:
                raise StreamingError(
                    "stream_session_storage_failed",
                    f"Could not read persisted {label}.",
                    500,
                ) from exc
            if not isinstance(raw, dict):
                raise StreamingError(
                    "stream_session_storage_failed",
                    f"Persisted {label} is invalid.",
                    500,
                )
            return raw

    def _delete(self, path: Path) -> None:
        with self._lock:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                raise StreamingError(
                    "stream_session_storage_failed",
                    "Could not clear persisted live session state.",
                    500,
                ) from exc

    def _atomic_write(self, path: Path, payload: dict[str, Any]) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StreamingError(
                "stream_session_storage_failed",
                "Could not create live session storage.",
                500,
            ) from exc
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
            raise StreamingError(
                "stream_session_storage_failed",
                "Could not atomically persist live session state.",
                500,
            ) from exc
