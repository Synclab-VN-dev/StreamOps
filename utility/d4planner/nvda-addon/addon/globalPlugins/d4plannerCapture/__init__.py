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


def _action_probe_state_path() -> Path:
    return _local_root() / "state" / "nvda-action-probe.json"


def _action_probe_default_log_path() -> Path:
    return _local_root() / "state" / "nvda-action-probe.jsonl"


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


class _ActionProbeConfigCache:
    def __init__(self):
        self._stamp: int | None = None
        self._value: dict[str, object] = {"enabled": False}

    def get(self) -> dict[str, object]:
        path = _action_probe_state_path()
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            self._stamp = None
            self._value = {"enabled": False}
            return self._value

        if stamp == self._stamp:
            return self._value

        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("action probe config root must be object")
        except (OSError, ValueError, json.JSONDecodeError):
            value = {"enabled": False}
        self._stamp = stamp
        self._value = value
        return value


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def __init__(self):
        super().__init__()
        self._config = _ConfigCache()
        self._action_probe = _ActionProbeConfigCache()
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

    @staticmethod
    def _probe_text(value: object) -> str | None:
        if value is None:
            return None
        try:
            display = getattr(value, "displayString", None)
            if display:
                return str(display)
            return str(value)
        except Exception:
            return None

    def _write_action_probe_event(self, event_name: str, obj, **event_kwargs) -> None:
        config = self._action_probe.get()
        if not bool(config.get("enabled")):
            return

        live_context = _live_context()
        if live_context is None:
            return
        process_id, process, window_title = live_context

        # Prefer the exact game PID already established by capture. If capture
        # is not active, fall back to the foreground Diablo identity only.
        capture_config = self._config.get()
        expected_process_id = self._positive_int(capture_config.get("gamePid"))
        if expected_process_id is not None:
            if process_id != expected_process_id:
                return
        else:
            process_text = str(process or "").casefold()
            title_text = str(window_title or "").casefold()
            if "diablo" not in process_text and "diablo iv" not in title_text:
                return

        role = self._probe_text(getattr(obj, "role", None))
        states_value = getattr(obj, "states", None)
        states: list[str] = []
        if states_value is not None:
            try:
                states = sorted(
                    text
                    for text in (self._probe_text(value) for value in states_value)
                    if text
                )
            except Exception:
                states = []

        automation_id = None
        control_type = None
        try:
            uia_element = getattr(obj, "UIAElement", None)
            if uia_element is not None:
                automation_id = self._probe_text(
                    getattr(uia_element, "currentAutomationId", None)
                )
                control_type = self._probe_text(
                    getattr(uia_element, "currentControlType", None)
                )
        except Exception:
            pass

        kwargs_payload: dict[str, str] = {}
        for key, value in event_kwargs.items():
            text = self._probe_text(value)
            if text is not None:
                kwargs_payload[str(key)] = text

        payload = {
            "timestampUnix": time.time(),
            "event": event_name,
            "processId": process_id,
            "process": process,
            "windowTitle": window_title,
            "name": self._probe_text(getattr(obj, "name", None)),
            "role": role,
            "value": self._probe_text(getattr(obj, "value", None)),
            "description": self._probe_text(getattr(obj, "description", None)),
            "states": states,
            "windowClassName": self._probe_text(
                getattr(obj, "windowClassName", None)
            ),
            "windowHandle": self._probe_text(getattr(obj, "windowHandle", None)),
            "uiaAutomationId": automation_id,
            "uiaControlType": control_type,
            "eventArgs": kwargs_payload,
        }

        path_text = str(config.get("logPath") or "")
        path = Path(path_text) if path_text else _action_probe_default_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            )
            handle.write("\n")
            handle.flush()

    def _probe_then_next(self, event_name: str, obj, nextHandler, **kwargs) -> None:
        try:
            self._write_action_probe_event(event_name, obj, **kwargs)
        except Exception:
            # Probe is debug-only and must never interfere with NVDA.
            log.exception("D4Planner: NVDA action probe failed")
        finally:
            nextHandler()

    def event_gainFocus(self, obj, nextHandler):
        self._probe_then_next("gainFocus", obj, nextHandler)

    def event_stateChange(self, obj, nextHandler):
        self._probe_then_next("stateChange", obj, nextHandler)

    def event_nameChange(self, obj, nextHandler):
        self._probe_then_next("nameChange", obj, nextHandler)

    def event_valueChange(self, obj, nextHandler):
        self._probe_then_next("valueChange", obj, nextHandler)

    def event_descriptionChange(self, obj, nextHandler):
        self._probe_then_next("descriptionChange", obj, nextHandler)

    def event_UIA_notification(self, obj, nextHandler, **kwargs):
        self._probe_then_next("UIA_notification", obj, nextHandler, **kwargs)

    def _write_action_probe_speech(
        self,
        event,
        *,
        process_id: int | None,
        process: str | None,
        window_title: str | None,
    ) -> None:
        """Write a control marker proving the existing D4 speech hook is alive."""
        config = self._action_probe.get()
        if not bool(config.get("enabled")):
            return

        path_text = str(config.get("logPath") or "")
        path = Path(path_text) if path_text else _action_probe_default_log_path()
        payload = {
            "timestampUnix": time.time(),
            "event": "speechHook",
            "processId": process_id,
            "process": process,
            "windowTitle": window_title,
            "text": str(getattr(event, "text", "") or ""),
            "rawSpeech": [
                str(value)
                for value in (getattr(event, "raw_speech", None) or [])
            ],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            )
            handle.write("\n")
            handle.flush()

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

            try:
                self._write_action_probe_speech(
                    event,
                    process_id=process_id,
                    process=process,
                    window_title=window_title,
                )
            except Exception:
                # The control marker is diagnostic only and must never affect
                # the proven speech capture path.
                log.exception("D4Planner: NVDA speech-hook probe failed")

            persisted = bool(self._writer and self._writer.write(event))
            if not persisted:
                log.warning("D4Planner: capture event could not be persisted; speech passes through")
                return original

            # Suppress only after successful persistence and only for confident D4 context.
            return [] if decision.suppress else original
        except Exception:
            log.exception("D4Planner: speech filter failed; speech passes through")
            return original
