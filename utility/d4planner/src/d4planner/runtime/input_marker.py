"""Read-only Steam Input keyboard marker capture."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import ctypes
from ctypes import wintypes
import os
import queue
import threading
import time
from typing import Protocol

from .events.model import EventDraft


KEY_CODES: dict[str, int] = {
    "scroll-lock": 0x91,
    **{f"f{index}": 0x6F + index for index in range(1, 13)},
}


def virtual_key_code(name: str) -> int:
    key = str(name or "").strip().casefold().replace("_", "-")
    if key not in KEY_CODES:
        supported = ", ".join(sorted(KEY_CODES))
        raise ValueError(f"unsupported marker key: {name!r}; supported: {supported}")
    return KEY_CODES[key]


def edge_transition(previous_down: bool, current_down: bool) -> str | None:
    if current_down == previous_down:
        return None
    return "DOWN" if current_down else "UP"


class KeyStateBackend(Protocol):
    def is_down(self, virtual_key: int) -> bool: ...
    def foreground_context(self) -> tuple[int | None, str]: ...


class AsyncKeyStateBackend:
    """Minimal read-only Win32 input + foreground context wrapper."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("input marker capture requires Windows")
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            raise OSError("ctypes.windll is unavailable")
        self._user32 = windll.user32
        self._get_async_key_state = self._user32.GetAsyncKeyState
        self._get_async_key_state.argtypes = [ctypes.c_int]
        self._get_async_key_state.restype = ctypes.c_short

        self._get_foreground_window = self._user32.GetForegroundWindow
        self._get_foreground_window.argtypes = []
        self._get_foreground_window.restype = wintypes.HWND

        self._get_window_thread_process_id = self._user32.GetWindowThreadProcessId
        self._get_window_thread_process_id.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._get_window_thread_process_id.restype = wintypes.DWORD

        self._get_window_text_length = self._user32.GetWindowTextLengthW
        self._get_window_text_length.argtypes = [wintypes.HWND]
        self._get_window_text_length.restype = ctypes.c_int

        self._get_window_text = self._user32.GetWindowTextW
        self._get_window_text.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        self._get_window_text.restype = ctypes.c_int

    def is_down(self, virtual_key: int) -> bool:
        return bool(int(self._get_async_key_state(int(virtual_key))) & 0x8000)

    def foreground_context(self) -> tuple[int | None, str]:
        hwnd = self._get_foreground_window()
        if not hwnd:
            return None, ""
        pid = wintypes.DWORD()
        self._get_window_thread_process_id(hwnd, ctypes.byref(pid))
        length = int(self._get_window_text_length(hwnd))
        title = ""
        if length > 0:
            buffer = ctypes.create_unicode_buffer(length + 1)
            self._get_window_text(hwnd, buffer, length + 1)
            title = str(buffer.value)
        return (int(pid.value) if pid.value else None), title


@dataclass(frozen=True, slots=True)
class MarkerSample:
    timestamp: str
    key: str
    virtual_key: int
    state: str
    process_id: int
    window_title: str

    def as_draft(self) -> EventDraft:
        return EventDraft(
            "input.marker.raw",
            {
                "source": "steamInput",
                "device": "keyboard",
                "key": self.key.upper(),
                "virtualKey": self.virtual_key,
                "state": self.state.casefold(),
                "process": "diablo iv",
                "processId": self.process_id,
                "contextSource": "win32Foreground",
                "windowTitle": self.window_title,
            },
            timestamp=self.timestamp,
        )


class InputMarkerCapture:
    """Poll one harmless Steam Input marker and queue edge events.

    The worker never writes SQLite. The Supervisor remains the only event writer.
    """

    def __init__(
        self,
        *,
        key: str = "f11",
        poll_interval: float = 0.01,
        backend: KeyStateBackend | None = None,
    ) -> None:
        self.key = str(key).strip().casefold().replace("_", "-")
        self.virtual_key = virtual_key_code(self.key)
        self.poll_interval = max(0.001, float(poll_interval))
        self._backend = backend
        self._target_pid: int | None = None
        self._samples: queue.SimpleQueue[MarkerSample] = queue.SimpleQueue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None

    def set_target_pid(self, pid: int | None) -> None:
        self._target_pid = int(pid) if pid and int(pid) > 0 else None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if self._backend is None:
            self._backend = AsyncKeyStateBackend()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="d4planner-input-marker",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, timeout: float = 1.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=max(0.0, timeout))

    def _observe(self, previous_down: bool) -> bool:
        backend = self._backend
        if backend is None:
            return previous_down
        current_down = backend.is_down(self.virtual_key)
        transition = edge_transition(previous_down, current_down)
        if transition is not None:
            foreground_pid, title = backend.foreground_context()
            target_pid = self._target_pid
            if target_pid is not None and foreground_pid == target_pid:
                self._samples.put(
                    MarkerSample(
                        timestamp=datetime.now()
                        .astimezone()
                        .isoformat(timespec="milliseconds"),
                        key=self.key,
                        virtual_key=self.virtual_key,
                        state=transition,
                        process_id=target_pid,
                        window_title=title,
                    )
                )
        return current_down

    def _run(self) -> None:
        backend = self._backend
        if backend is None:
            return
        try:
            previous_down = backend.is_down(self.virtual_key)
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            return

        while not self._stop.is_set():
            try:
                previous_down = self._observe(previous_down)
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
            self._stop.wait(self.poll_interval)

    def drain(self) -> list[MarkerSample]:
        values: list[MarkerSample] = []
        while True:
            try:
                values.append(self._samples.get_nowait())
            except queue.Empty:
                return values

    def consume_error(self) -> str | None:
        value = self._last_error
        self._last_error = None
        return value


__all__ = [
    "AsyncKeyStateBackend",
    "InputMarkerCapture",
    "KEY_CODES",
    "MarkerSample",
    "edge_transition",
    "virtual_key_code",
]
