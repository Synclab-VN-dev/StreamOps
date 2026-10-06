"""NVDA global plugin for D4Planner runtime capture."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time

import api
import appModuleHandler
import globalPluginHandler
from logHandler import log
import speech
import winUser

from .core import CaptureSession, JsonlWriter, capture_decision


def _local_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(local_app_data) / "d4planner"


def _capture_state_path() -> Path:
    return _local_root() / "state" / "capture.json"


def _cached_context() -> tuple[str | None, str | None]:
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


def _live_context() -> tuple[int, str | None, str | None] | None:
    """Resolve foreground identity from Win32 at speech-filter time.

    NVDA's foreground object is intentionally not used for the capture decision:
    that object is cached and can trail rapid focus changes inside a game.
    """
    try:
        hwnd = winUser.getForegroundWindow()
        if not hwnd:
            return None
        process_id, _thread_id = winUser.getWindowThreadProcessID(hwnd)
        process_id = int(process_id)
        if process_id <= 0:
            return None
        process = appModuleHandler.getAppNameFromProcessID(process_id)
        window_title = winUser.getWindowText(hwnd)
        return process_id, process, window_title
    except Exception:
        # Fail open. A lookup error must never mute desktop or game speech.
        log.exception("D4Planner: failed to read live Win32 foreground context")
        return None


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
        self._last_diagnostic_signature: tuple[object, ...] | None = None
        self._last_diagnostic_at = 0.0
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

    @staticmethod
    def _positive_int(value: object) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _write_rejection_diagnostic(
        self,
        config: dict[str, object],
        *,
        reason: str,
        expected_process_id: int | None,
        live_context: tuple[int, str | None, str | None] | None,
    ) -> None:
        path_text = str(config.get("diagnosticsPath") or "")
        if not path_text:
            return
        cached_process, cached_title = _cached_context()
        live_pid, live_process, live_title = live_context or (None, None, None)
        signature = (
            reason,
            expected_process_id,
            live_pid,
            live_process,
            live_title,
            cached_process,
            cached_title,
        )
        now = time.monotonic()
        if signature == self._last_diagnostic_signature and now - self._last_diagnostic_at < 2.0:
            return
        payload = {
            "timestampUnix": time.time(),
            "sessionId": str(config.get("sessionId") or ""),
            "reason": reason,
            "expectedProcessId": expected_process_id,
            "foregroundProcessId": live_pid,
            "foregroundProcess": live_process,
            "foregroundWindowTitle": live_title,
            "cachedNvdaProcess": cached_process,
            "cachedNvdaWindowTitle": cached_title,
            "contextSource": "win32Foreground",
        }
        try:
            path = Path(path_text)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
                handle.flush()
            self._last_diagnostic_signature = signature
            self._last_diagnostic_at = now
        except (OSError, TypeError, ValueError):
            log.exception("D4Planner: capture context diagnostic could not be persisted")

    def _filter_speech(self, speechSequence, **kwargs):
        original = speechSequence
        try:
            config = self._config.get()
            enabled = bool(config.get("enabled"))
            silent = bool(config.get("silent"))
            expected_process_id = self._positive_int(config.get("gamePid"))
            live_context = _live_context()
            process_id, process, window_title = live_context or (None, None, None)
            decision = capture_decision(
                enabled=enabled,
                silent=silent,
                process=process,
                window_title=window_title,
                expected_process_id=expected_process_id,
                foreground_process_id=process_id,
                capture_all=self._capture_all,
            )
            if not decision.capture:
                if enabled:
                    if expected_process_id is None:
                        reason = "missingExpectedGamePid"
                    elif live_context is None:
                        reason = "foregroundLookupFailed"
                    else:
                        reason = "foregroundPidMismatch"
                    self._write_rejection_diagnostic(
                        config,
                        reason=reason,
                        expected_process_id=expected_process_id,
                        live_context=live_context,
                    )
                return original
            if not self._ensure_writer(config):
                return original

            event = self._session.make_event(
                speech_sequence=speechSequence or [],
                process=process,
                window_title=window_title,
                process_id=process_id,
                context_source="win32Foreground",
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
