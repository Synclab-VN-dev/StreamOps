"""Atomic, process-local thread-safe JSON store for OBS scene profiles."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from typing import Any

from .errors import SceneProfileNotFoundError, SceneProfileStorageError, SceneProfileValidationError
from .scene_profiles import duplicate_profile, new_profile, normalize_profile, _require_uuid


class SceneProfileStore:
    def __init__(self, root: Path, *, template_root: Path | None = None) -> None:
        self.root = root
        self.template_root = template_root
        self._lock = threading.RLock()

    def list(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_root()
            profiles, errors = [], []
            for path in sorted(self.root.glob("*.json")):
                if path.name == "index.json" or ".tmp-" in path.name:
                    continue
                try:
                    profile = self._read(path)
                    if path.stem != profile['id']:
                        raise SceneProfileValidationError('Profile filename does not match its ID.')
                    profiles.append(_summary(profile))
                except (SceneProfileValidationError, SceneProfileStorageError) as exc:
                    errors.append({"file": path.name, "error": str(exc)})
            profiles.sort(key=lambda item: (item["name"].casefold(), item["id"]))
            # The index is a rebuildable cache, never the authoritative commit.
            try:
                self._write_index(profiles)
            except SceneProfileStorageError as exc:
                errors.append({'file': 'index.json', 'error': str(exc)})
            return {"profiles": profiles, "errors": errors}

    def get(self, profile_id: str) -> dict[str, Any]:
        with self._lock:
            path = self._path(profile_id)
            if not path.is_file():
                raise SceneProfileNotFoundError(f"Scene profile not found: {profile_id}")
            return self._read(path)

    def create(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            profile = normalize_profile(payload or new_profile(), regenerate_ids=True)
            self._write_profile(profile)
            self.list()
            return profile

    def update(self, profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = self.get(profile_id)
            requested_id = payload.get("id")
            if requested_id not in (None, profile_id):
                raise SceneProfileValidationError("Profile id cannot be changed by PUT.")
            profile = normalize_profile({**payload, "id": profile_id}, existing=current)
            self._write_profile(profile)
            self.list()
            return profile

    def duplicate(self, profile_id: str, *, name: str | None = None) -> dict[str, Any]:
        with self._lock:
            profile = duplicate_profile(self.get(profile_id), name=name)
            self._write_profile(profile)
            self.list()
            return profile

    def delete(self, profile_id: str) -> None:
        with self._lock:
            path = self._path(profile_id)
            if not path.is_file():
                raise SceneProfileNotFoundError(f"Scene profile not found: {profile_id}")
            try:
                path.unlink()
            except OSError as exc:
                raise SceneProfileStorageError(f"Could not delete scene profile {profile_id}: {exc}") from exc
            self.list()

    def list_templates(self) -> list[dict[str, Any]]:
        result = []
        if self.template_root is None or not self.template_root.is_dir():
            return result
        for path in sorted(self.template_root.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                result.append({"id": path.stem, "name": str(raw.get("name") or path.stem)})
            except (OSError, json.JSONDecodeError, AttributeError):
                continue
        return result

    def instantiate_template(self, template_id: str, *, name: str | None = None) -> dict[str, Any]:
        if self.template_root is None or Path(template_id).name != template_id:
            raise SceneProfileNotFoundError(f"Scene profile template not found: {template_id}")
        path = self.template_root / f"{template_id}.json"
        if not path.is_file():
            raise SceneProfileNotFoundError(f"Scene profile template not found: {template_id}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SceneProfileStorageError(f"Could not load scene profile template {template_id}: {exc}") from exc
        raw["name"] = name or raw.get("name") or template_id
        profile = normalize_profile(raw, regenerate_ids=True)
        with self._lock:
            self._write_profile(profile)
            self.list()
        return profile

    def _path(self, profile_id: str) -> Path:
        try:
            _require_uuid(profile_id, 'profile id')
        except (SceneProfileValidationError, ValueError, TypeError, AttributeError):
            raise SceneProfileNotFoundError(f"Scene profile not found: {profile_id}")
        return self.root / f"{profile_id}.json"

    def _read(self, path: Path) -> dict[str, Any]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SceneProfileStorageError(f"Could not read {path.name}: {exc}") from exc
        if not isinstance(raw, dict) or any(key not in raw for key in ('id', 'name', 'schema_version', 'sources', 'canvas')):
            raise SceneProfileValidationError(f'{path.name} is not a complete persisted profile.')
        _require_uuid(raw['id'], 'profile id')
        for source in raw['sources'] if isinstance(raw['sources'], list) else []:
            if not isinstance(source, dict):
                raise SceneProfileValidationError('Stored source must be an object.')
            _require_uuid(source.get('id'), 'source id')
        return normalize_profile(raw, existing=raw, preserve_updated_at=True)

    def _write_profile(self, profile: dict[str, Any]) -> None:
        self._ensure_root()
        self._atomic_write(self._path(profile["id"]), profile)

    def _ensure_root(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SceneProfileStorageError(f'Could not create profile storage: {exc}') from exc

    def _write_index(self, summaries: list[dict[str, Any]]) -> None:
        self._atomic_write(self.root / "index.json", {"schema_version": 1, "profiles": summaries})

    @staticmethod
    def _atomic_write(path: Path, payload: Any) -> None:
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
            raise SceneProfileStorageError(f"Could not atomically write {path.name}: {exc}") from exc


def _summary(profile: dict[str, Any]) -> dict[str, Any]:
    return {key: profile[key] for key in ("id", "name", "obs_scene_name", "updated_at")}
