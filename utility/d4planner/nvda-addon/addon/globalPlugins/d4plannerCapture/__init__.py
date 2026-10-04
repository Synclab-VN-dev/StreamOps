"""NVDA global plugin for the D4Planner capture POC."""

from __future__ import annotations

import os
from pathlib import Path

import api
import globalPluginHandler
from logHandler import log
from speech import extensions as speech_extensions

from .core import CaptureSession, JsonlWriter, is_diablo_context


def _capture_path() -> Path:
    configured = os.environ.get("D4PLANNER_CAPTURE_PATH")
    if configured:
        return Path(configured)
    local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(local_app_data) / "d4planner" / "raw-d4-speech.jsonl"


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


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def __init__(self):
        super().__init__()
        self._session = CaptureSession()
        self._writer = JsonlWriter(_capture_path())
        self._capture_all = os.environ.get("D4PLANNER_CAPTURE_ALL", "").strip() == "1"
        speech_extensions.pre_speech.register(self._on_pre_speech)
        log.info("D4Planner: raw NVDA speech capture POC loaded")

    def terminate(self):
        try:
            speech_extensions.pre_speech.unregister(self._on_pre_speech)
        except Exception:
            log.exception("D4Planner: failed to unregister speech hook")
        super().terminate()

    def _on_pre_speech(
        self,
        speechSequence=None,
        originalSpeechSequence=None,
        symbolLevel=None,
        priority=None,
        **kwargs,
    ):
        try:
            process, window_title = _context()
            if not self._capture_all and not is_diablo_context(process, window_title):
                return

            source_sequence = originalSpeechSequence or speechSequence or []
            event = self._session.make_event(
                speech_sequence=source_sequence,
                process=process,
                window_title=window_title,
            )
            if not event.text and not event.raw_speech:
                return
            if not self._writer.write(event):
                log.warning("D4Planner: capture event could not be persisted")
        except Exception:
            log.exception("D4Planner: capture callback failed")
