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
from ..controller import ControllerProfile, ControllerResolver


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
    suppressed: bool | None = None
    capture_method: str | None = None
    control_id: str | None = None
    layout_id: str | None = None
    mapping_source: str | None = None
    scan_code: int | None = None

    def as_draft(self) -> EventDraft:
        data = {
            "source": "steamInput",
            "device": "keyboard",
            "key": self.key.upper(),
            "virtualKey": self.virtual_key,
            "state": self.state.casefold(),
            "process": "diablo iv",
            "processId": self.process_id,
            "contextSource": "win32Foreground",
            "windowTitle": self.window_title,
        }
        if self.suppressed is not None:
            data["suppressed"] = self.suppressed
        if self.capture_method is not None:
            data["captureMethod"] = self.capture_method
        if self.control_id is not None:
            data["controlId"] = self.control_id
        if self.layout_id is not None:
            data["layoutId"] = self.layout_id
        if self.mapping_source is not None:
            data["mappingSource"] = self.mapping_source
        if self.scan_code is not None:
            data["scanCode"] = self.scan_code
        return EventDraft("input.marker.raw", data, timestamp=self.timestamp)


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



class HookInputMarkerCapture:
    """One hook for an optional Xbox16 profile in OBSERVE or BLOCK mode.

    No polling duplicates: one callback queues markers, Supervisor writes SQLite.
    """

    def __init__(
        self, *, poll_interval: float = 0.01, backend_factory=None,
        profile: ControllerProfile | None = None, block: bool = True,
        sample_capacity: int = 8192,
    ) -> None:
        if sample_capacity < 1:
            raise ValueError("sample_capacity must be positive")
        self.poll_interval = max(0.001, float(poll_interval))
        self._backend_factory = backend_factory
        self.profile = profile
        self.block = bool(block)
        self.resolver = ControllerResolver(profile) if profile else None
        self._target_pid: int | None = None
        # The Supervisor can stall during SQLite backpressure. Avoid an
        # unbounded second-stage queue behind the bounded Win32 hook queue.
        self._samples: queue.Queue[MarkerSample] = queue.Queue(maxsize=sample_capacity)
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None
        self._hook = None
        self._running = False
        self._dropped_count = 0

    def set_target_pid(self, pid: int | None) -> None:
        self._target_pid = int(pid) if pid and int(pid) > 0 else None

    def _convert_sample(self, sample) -> MarkerSample | None:
        vk = int(getattr(sample, "virtual_key", 0x7A))
        binding = self.resolver.by_virtual_key(vk) if self.resolver else None
        if self.resolver and binding is None:
            return None
        if not self.resolver and vk != 0x7A:
            return None
        profile = self.profile
        return MarkerSample(
            timestamp=datetime.fromtimestamp(sample.timestamp_ms / 1000)
            .astimezone().isoformat(timespec="milliseconds"),
            key=binding.key if binding else "f11",
            virtual_key=vk,
            state=sample.state,
            process_id=sample.foreground_pid,
            window_title="Diablo IV",
            suppressed=bool(sample.suppressed),
            capture_method="keyboardHook",
            control_id=binding.control_id if binding else None,
            layout_id=profile.layout_id if profile else None,
            mapping_source=profile.mapping_source if profile else None,
            scan_code=int(getattr(sample, "scan_code", 0)) if profile else None,
        )

    def _drain_hook(self, hook) -> None:
        samples = getattr(hook, "samples", None)
        if samples is None:
            return
        for sample in samples.drain():
            if not sample.target_match or not sample.foreground_pid:
                continue
            if self.profile is None and not sample.suppressed:
                continue
            converted = self._convert_sample(sample)
            if converted is not None:
                try:
                    self._samples.put_nowait(converted)
                except queue.Full as exc:
                    self._dropped_count += 1
                    # Explicit fatal diagnostic; never silently lose input or
                    # claim that suppression remains reliable.
                    raise RuntimeError(
                        "Controller adapter queue overflow: "
                        f"droppedCount={self._dropped_count}"
                    ) from exc

    def _update_overflow(self, hook) -> None:
        dropped = int(getattr(getattr(hook, "samples", None), "dropped", 0))
        if dropped > self._dropped_count:
            self._dropped_count = dropped

    @property
    def dropped_count(self) -> int:
        hook = self._hook
        if hook is not None:
            self._update_overflow(hook)
        return self._dropped_count

    @property
    def overflowed(self) -> bool:
        return self.dropped_count > 0

    def _run(self) -> None:
        from .keyboard_hook import WindowsF11Hook

        hook = None
        try:
            factory = self._backend_factory or WindowsF11Hook
            kwargs = {"game_pid": self._target_pid or 0, "block": self.block}
            if self.profile is not None:
                kwargs["virtual_keys"] = frozenset(
                    binding.virtual_key for binding in self.profile.digital
                )
            hook = factory(**kwargs)
            try:
                with hook:
                    self._hook = hook
                    self._running = True
                    self._ready.set()
                    while not self._stop.is_set():
                        hook.set_target_pid(self._target_pid)
                        if not hook.pump():
                            raise RuntimeError("Windows keyboard hook message loop quit")
                        self._drain_hook(hook)
                        self._update_overflow(hook)
                        if self._dropped_count:
                            raise RuntimeError(
                                "Windows keyboard hook queue overflow: "
                                f"droppedCount={self._dropped_count}"
                            )
                        if hook.hook_errors:
                            raise RuntimeError(
                                f"Windows keyboard hook callback errors={hook.hook_errors}"
                            )
                        self._stop.wait(self.poll_interval)
            finally:
                # The context manager has unhooked before this final drain, so
                # no callback can enqueue a tail event behind the drain.
                self._update_overflow(hook)
                self._drain_hook(hook)
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
        finally:
            self._running = False
            self._hook = None
            self._ready.set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._last_error = None
        self._dropped_count = 0
        self._stop.clear()
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="d4planner-keyboard-hook"
        )
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            self._stop.set()
            raise RuntimeError("F11 keyboard hook did not become ready in 5 seconds")
        if self._last_error or not self._running:
            raise RuntimeError(self._last_error or "F11 keyboard hook exited on startup")

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=max(0.0, timeout))
        if thread and thread.is_alive():
            raise RuntimeError("F11 hook thread failed to unhook on shutdown")

    def drain(self) -> list[MarkerSample]:
        values: list[MarkerSample] = []
        while True:
            try:
                values.append(self._samples.get_nowait())
            except queue.Empty:
                return values

    def consume_error(self) -> str | None:
        error = self._last_error
        self._last_error = None
        if not error and self._thread and not self._thread.is_alive() and not self._stop.is_set():
            error = "F11 keyboard hook thread unexpectedly exited"
        return error
