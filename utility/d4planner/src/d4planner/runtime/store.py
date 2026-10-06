"""Filesystem-backed session, state, and event storage."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import errno
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable
from uuid import uuid4

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now(clock: Clock = utc_now) -> str:
    return clock().astimezone().isoformat(timespec="milliseconds")


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    attempts = 4
    base_delay = 0.05
    try:
        for attempt in range(attempts):
            try:
                os.replace(temp, path)
                return
            except OSError as exc:
                transient_access_denied = (
                    isinstance(exc, PermissionError)
                    or getattr(exc, "winerror", None) == 5
                    or getattr(exc, "errno", None) in {errno.EACCES, errno.EPERM}
                )
                if not transient_access_denied or attempt + 1 >= attempts:
                    raise
                time.sleep(base_delay * (2**attempt))
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    root: Path

    @classmethod
    def default(cls) -> "RuntimePaths":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / ".local" / "share"
        return cls(base / "d4planner")

    @property
    def runtime(self) -> Path:
        return self.root / "runtime"

    @property
    def controller(self) -> Path:
        return self.runtime / "nvda-controller"

    @property
    def sessions(self) -> Path:
        return self.root / "sessions"

    @property
    def state(self) -> Path:
        return self.root / "state"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def runtime_state(self) -> Path:
        return self.state / "runtime.json"

    @property
    def capture_state(self) -> Path:
        return self.state / "capture.json"

    @property
    def stop_request(self) -> Path:
        return self.state / "stop.request"

    @property
    def path_backup(self) -> Path:
        return self.state / "user-path-backup.json"

    @property
    def path_managed(self) -> Path:
        return self.state / "user-path-managed.json"

    def ensure(self) -> None:
        for path in (self.runtime, self.controller, self.sessions, self.state, self.logs):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True, slots=True)
class SessionInfo:
    session_id: str
    started_at: str
    directory: Path
    metadata_path: Path
    raw_speech_path: Path
    context_diagnostics_path: Path
    events_path: Path
    runtime_log_path: Path


class EventStore:
    """Single-writer unified event stream for one D4Planner session."""

    def __init__(self, session: SessionInfo, *, clock: Clock = utc_now):
        self.session = session
        self._clock = clock
        self._lock = threading.Lock()
        self._next_seq = self._discover_next_sequence()

    @classmethod
    def create(
        cls,
        paths: RuntimePaths,
        *,
        silent: bool,
        metadata: dict[str, Any] | None = None,
        clock: Clock = utc_now,
        session_id: str | None = None,
    ) -> "EventStore":
        paths.ensure()
        sid = session_id or uuid4().hex
        started = iso_now(clock)
        stamp = clock().astimezone().strftime("%Y%m%d-%H%M%S")
        directory = paths.sessions / f"{stamp}-{sid[:8]}"
        suffix = 0
        candidate = directory
        while candidate.exists():
            suffix += 1
            candidate = paths.sessions / f"{stamp}-{sid[:8]}-{suffix}"
        directory = candidate
        directory.mkdir(parents=True)

        info = SessionInfo(
            session_id=sid,
            started_at=started,
            directory=directory,
            metadata_path=directory / "metadata.json",
            raw_speech_path=directory / "raw-speech.jsonl",
            context_diagnostics_path=directory / "capture-context.jsonl",
            events_path=directory / "events.jsonl",
            runtime_log_path=directory / "runtime.log",
        )
        payload = {
            "sessionId": sid,
            "startedAt": started,
            "game": "Diablo IV",
            "captureBackend": "NVDA",
            "silent": silent,
            **(metadata or {}),
        }
        atomic_write_json(info.metadata_path, payload)
        return cls(info, clock=clock)

    def _discover_next_sequence(self) -> int:
        path = self.session.events_path
        if not path.exists():
            return 1
        last = 0
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    seq = int(event.get("eventSeq") or 0)
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                last = max(last, seq)
        return last + 1

    def emit(self, event_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            event = {
                "eventSeq": self._next_seq,
                "type": event_type,
                "timestamp": iso_now(self._clock),
                "sessionId": self.session.session_id,
                "data": data or {},
            }
            self._next_seq += 1
            self.session.events_path.parent.mkdir(parents=True, exist_ok=True)
            with self.session.events_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
                handle.flush()
            if event_type.startswith("runtime."):
                detail = str((data or {}).get("detail") or "")
                with self.session.runtime_log_path.open("a", encoding="utf-8", newline="\n") as log:
                    log.write(f"[{event['timestamp']}] {event_type} {detail}".rstrip() + "\n")
                    log.flush()
            return event

    def ingest_capture(self, capture: dict[str, Any]) -> dict[str, Any]:
        return self.emit(
            "speech.raw",
            {
                "captureSessionId": capture.get("sessionId"),
                "captureSequence": capture.get("sequence"),
                "process": capture.get("process"),
                "processId": capture.get("processId"),
                "contextSource": capture.get("contextSource"),
                "windowTitle": capture.get("windowTitle"),
                "text": capture.get("text"),
                "rawSpeech": capture.get("rawSpeech") or [],
            },
        )


def write_capture_config(
    paths: RuntimePaths,
    *,
    enabled: bool,
    session: SessionInfo | None = None,
    silent: bool = True,
    game_pid: int | None = None,
    lease_seconds: float = 5.0,
) -> None:
    effective_enabled = bool(enabled and session is not None)
    payload: dict[str, Any] = {
        "enabled": effective_enabled,
        "silent": bool(silent) if effective_enabled else False,
        "updatedAt": iso_now(),
    }
    if effective_enabled and session:
        payload.update(
            {
                "sessionId": session.session_id,
                "rawSpeechPath": str(session.raw_speech_path),
                "diagnosticsPath": str(session.context_diagnostics_path),
                "gamePid": int(game_pid) if game_pid and game_pid > 0 else None,
                # Silent capture is fail-open: the add-on stops suppressing if
                # the supervisor no longer renews this short lease.
                "leaseUntilUnix": time.time() + max(1.0, float(lease_seconds)),
            }
        )
    atomic_write_json(paths.capture_state, payload)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None
