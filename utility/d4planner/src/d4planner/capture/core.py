"""Pure-Python capture primitives shared by CI and the NVDA add-on.

This module intentionally contains no NVDA imports so it can be regression-tested
without NVDA or Diablo IV installed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable, Iterable, Sequence
from uuid import uuid4

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def flatten_speech_sequence(sequence: Sequence[object] | None) -> tuple[str, list[str]]:
    """Return visible text plus a diagnostic representation of all tokens."""
    if not sequence:
        return "", []

    raw: list[str] = []
    text_parts: list[str] = []
    for token in sequence:
        if isinstance(token, str):
            raw.append(token)
            if token:
                text_parts.append(token)
        else:
            raw.append(repr(token))

    return " ".join(text_parts).strip(), raw


def is_diablo_context(process: str | None, window_title: str | None) -> bool:
    """Return true only for a confidently identified Diablo IV process.

    Window titles are intentionally not trusted for production capture/suppression.
    Windows components such as DWM can expose titles like
    "Diablo IV (Not Responding)" even though the speech context is not the game.
    """
    del window_title
    normalized_process = "".join(ch for ch in (process or "").lower() if ch.isalnum())
    return normalized_process in {"diabloiv", "diablo4"}


@dataclass(frozen=True, slots=True)
class CaptureDecision:
    capture: bool
    suppress: bool


def capture_decision(
    *,
    enabled: bool,
    silent: bool,
    process: str | None,
    window_title: str | None,
    capture_all: bool = False,
) -> CaptureDecision:
    """Return fail-safe capture/suppression policy.

    Diagnostic capture-all may collect non-D4 speech, but suppression is *never*
    allowed unless the foreground context is confidently Diablo IV.
    """
    is_d4 = is_diablo_context(process, window_title)
    capture = bool(enabled and (is_d4 or capture_all))
    suppress = bool(capture and silent and is_d4)
    return CaptureDecision(capture=capture, suppress=suppress)


@dataclass(frozen=True, slots=True)
class CaptureEvent:
    session_id: str
    sequence: int
    timestamp: str
    process: str | None
    window_title: str | None
    text: str
    raw_speech: list[str]

    def as_json_dict(self) -> dict[str, object]:
        data = asdict(self)
        return {
            "sessionId": data["session_id"],
            "sequence": data["sequence"],
            "timestamp": data["timestamp"],
            "process": data["process"],
            "windowTitle": data["window_title"],
            "text": data["text"],
            "rawSpeech": data["raw_speech"],
        }


class CaptureSession:
    """Monotonic event factory for one NVDA capture run."""

    def __init__(self, *, session_id: str | None = None, clock: Clock = _utc_now):
        self.session_id = session_id or uuid4().hex
        self._clock = clock
        self._next_sequence = 1

    def make_event(
        self,
        *,
        speech_sequence: Sequence[object] | None,
        process: str | None,
        window_title: str | None,
    ) -> CaptureEvent:
        text, raw = flatten_speech_sequence(speech_sequence)
        event = CaptureEvent(
            session_id=self.session_id,
            sequence=self._next_sequence,
            timestamp=self._clock().astimezone().isoformat(timespec="milliseconds"),
            process=process,
            window_title=window_title,
            text=text,
            raw_speech=raw,
        )
        self._next_sequence += 1
        return event


class JsonlWriter:
    """Append-only writer whose failures never propagate into NVDA."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def write(self, event: CaptureEvent) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(event.as_json_dict(), ensure_ascii=False, separators=(",", ":"))
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.write("\n")
                handle.flush()
            return True
        except (OSError, TypeError, ValueError):
            return False


def read_jsonl(path: str | Path) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            parsed = json.loads(line)
            if not isinstance(parsed, dict):
                raise ValueError(f"line {line_number} is not a JSON object")
            events.append(parsed)
    return events


def validate_event_order(events: Iterable[dict[str, object]]) -> list[str]:
    errors: list[str] = []
    by_session: dict[str, int] = {}
    for index, event in enumerate(events, start=1):
        session = str(event.get("sessionId") or "")
        sequence = event.get("sequence")
        if not session:
            errors.append(f"event {index}: missing sessionId")
            continue
        if not isinstance(sequence, int) or sequence < 1:
            errors.append(f"event {index}: invalid sequence")
            continue
        expected = by_session.get(session, 0) + 1
        if sequence != expected:
            errors.append(
                f"event {index}: session {session} sequence {sequence}, expected {expected}"
            )
        by_session[session] = sequence
    return errors
