"""NVDA global plugin for D4Planner runtime capture."""

from __future__ import annotations

import json
import os
from pathlib import Path

import api
import globalPluginHandler
from logHandler import log
import speech

from .core import CaptureSession, JsonlWriter, capture_decision


def _local_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(local_app_data) / "d4planner"


def _capture_state_path() -> Path:
    return _local_root() / "state" / "capture.json"


def _context() -> tuple[str | None, str | None]:
    try:
        foreground = api.getForegroundObject()
        if foreground is None:
            return None, None
        app_module = getattr(foreground, "appModule", None)
        process = getattr(app_module, "appName", None)
        window_title = getattr(foreground, "name", None)
        return process, window_title
    except Exception:
        log.exception("D4Planner: failed to read foreground context")
        return None, None


class _ConfigCache:
    def __init__(self):
        self._stamp: int | None = None
        self._value: dict[str, object] = {"enabled": False, "silent": False}

    @staticmethod
    def _effective(value: dict[str, object]) -> dict[str, object]:
        if not value.get("enabled"):
            return value
        try:
            lease_until = float(value.get("leaseUntilUnix") or 0)
        except (TypeError, ValueError):
            lease_until = 0
        if lease_until <= time.time():
            # Supervisor disappeared or stopped renewing the lease. Never leave
            # NVDA silently suppressing D4 speech after a backend failure.
            return {"enabled": False, "silent": False}
        return value

    def get(self) -> dict[str, object]:
        path = _capture_state_path()
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            self._stamp = None
            self._value = {"enabled": False, "silent": False}
            return self._value

        if stamp == self._stamp:
            return self._effective(self._value)

        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("capture config root must be object")
        except (OSError, ValueError, json.JSONDecodeError):
            # Fail safe: never suppress desktop speech when config is invalid.
            value = {"enabled": False, "silent": False}
        self._stamp = stamp
        self._value = value
        return self._effective(value)


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def __init__(self):
        super().__init__()
        self._config = _ConfigCache()
        self._session: CaptureSession | None = None
        self._writer: JsonlWriter | None = None
        self._capture_all = os.environ.get("D4PLANNER_CAPTURE_ALL", "").strip() == "1"
        speech.filter_speechSequence.register(self._filter_speech)
        log.info("D4Planner: runtime speech filter loaded")

    def terminate(self):
        try:
            speech.filter_speechSequence.unregister(self._filter_speech)
        except Exception:
            log.exception("D4Planner: failed to unregister speech filter")
        super().terminate()

    def _ensure_writer(self, config: dict[str, object]) -> bool:
        session_id = str(config.get("sessionId") or "")
        raw_path = str(config.get("rawSpeechPath") or "")
        if not session_id or not raw_path:
            return False
        if self._session is None or self._session.session_id != session_id:
            self._session = CaptureSession(session_id=session_id)
            self._writer = JsonlWriter(Path(raw_path))
        elif self._writer is None or str(self._writer.path) != raw_path:
            self._writer = JsonlWriter(Path(raw_path))
        return True

    def _filter_speech(self, speechSequence, **kwargs):
        original = speechSequence
        try:
            config = self._config.get()
            enabled = bool(config.get("enabled"))
            silent = bool(config.get("silent"))
            process, window_title = _context()
            decision = capture_decision(
                enabled=enabled,
                silent=silent,
                process=process,
                window_title=window_title,
                capture_all=self._capture_all,
            )
            if not decision.capture:
                return original
            if not self._ensure_writer(config):
                return original

            event = self._session.make_event(
                speech_sequence=speechSequence or [],
                process=process,
                window_title=window_title,
            )
            if not event.text and not event.raw_speech:
                return original

            persisted = bool(self._writer and self._writer.write(event))
            if not persisted:
                log.warning("D4Planner: capture event could not be persisted; speech passes through")
                return original

            # Suppress only after successful persistence and only for confident D4 context.
            return [] if decision.suppress else original
        except Exception:
            log.exception("D4Planner: speech filter failed; speech passes through")
            return original
