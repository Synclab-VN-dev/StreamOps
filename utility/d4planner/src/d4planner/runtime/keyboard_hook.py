"""Shared Win32 F11 low-level hook for POC #82 and production D4Planner.

No game injection. Never does SQLite writes inside a hook callback.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import ctypes
from ctypes import wintypes
import os
from pathlib import PureWindowsPath
import threading
import time
from collections import deque
from typing import Callable

VK_F11 = 0x7A
WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
PM_REMOVE = 0x0001
WM_QUIT = 0x0012
KEY_STATES = {
    WM_KEYDOWN: "down",
    WM_SYSKEYDOWN: "down",
    WM_KEYUP: "up",
    WM_SYSKEYUP: "up",
}


@dataclass(frozen=True, slots=True)
class Decision:
    capture: bool = False
    suppress: bool = False
    state: str | None = None


def decide_f11(*, n_code: int, message: int, vk: int,
               foreground_pid: int | None, game_pid: int,
               block: bool) -> Decision:
    """Pure, fail-open policy for target PID foreground F11 only."""
    if (
        n_code != HC_ACTION
        or vk != VK_F11
        or message not in KEY_STATES
        or game_pid <= 0
        or foreground_pid != game_pid
    ):
        return Decision()
    return Decision(capture=True, suppress=bool(block), state=KEY_STATES[message])


@dataclass(frozen=True, slots=True)
class F11Sample:
    timestamp_ms: int
    message: int
    state: str
    flags: int
    foreground_pid: int | None
    suppressed: bool
    target_match: bool = True

    def as_dict(self) -> dict[str, object]:
        stamp = datetime.fromtimestamp(self.timestamp_ms / 1000).astimezone()
        return {
            "timestamp": stamp.isoformat(timespec="milliseconds"),
            "event": "poc.f11",
            "key": "F11",
            "state": self.state,
            "message": hex(self.message),
            "flags": hex(self.flags),
            "injected": bool(self.flags & 0x10),  # not Steam-specific proof
            "foregroundPid": self.foreground_pid,
            "suppressed": self.suppressed,
            "targetMatch": self.target_match,
        }


class BoundedSamples:
    """No disk/network IO inside hook; keep only a bounded event queue."""

    def __init__(self, capacity: int = 2048) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._items: deque[F11Sample] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self.dropped = 0

    def append(self, sample: F11Sample) -> None:
        with self._lock:
            if len(self._items) == self._items.maxlen:
                self.dropped += 1
            self._items.append(sample)

    def drain(self) -> list[F11Sample]:
        with self._lock:
            items = list(self._items)
            self._items.clear()
            return items


def capture_or_pass(
    *, n_code: int, message: int, vk: int, flags: int,
    foreground_pid: int | None, game_pid: int, block: bool,
    samples: BoundedSamples, timestamp_ms: int,
) -> bool:
    """Return True only after the marker has been safely queued."""
    decision = decide_f11(
        n_code=n_code, message=message, vk=vk,
        foreground_pid=foreground_pid, game_pid=game_pid, block=block,
    )
    if not decision.capture:
        return False
    samples.append(F11Sample(
        timestamp_ms=timestamp_ms,
        message=message,
        state=decision.state or "",
        flags=flags,
        foreground_pid=int(foreground_pid),
        suppressed=decision.suppress,
    ))
    return decision.suppress


def safe_capture_or_pass(*, on_error: Callable[[], None] | None = None,
                         **kwargs: object) -> bool:
    """Do not swallow keystrokes if even diagnostic capture fails."""
    try:
        return capture_or_pass(**kwargs)
    except Exception:
        if on_error is not None:
            on_error()
        return False


def require_game_pid(pid: int) -> None:
    """Verify the opted-in PID is a real Diablo IV executable, before hook."""
    if os.name != "nt":
        raise OSError("This POC requires Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, pid)  # query only
    if not handle:
        raise OSError(ctypes.get_last_error(), f"Cannot query game PID {pid}")
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            raise OSError(ctypes.get_last_error(), "Cannot read game executable")
        exe = PureWindowsPath(buf.value).name.casefold()
        if exe != "diablo iv.exe":
            raise ValueError(f"PID {pid} is {exe!r}, not Diablo IV.exe")
    finally:
        kernel32.CloseHandle(handle)


class WindowsF11Hook:
    """Message-pumped low-level keyboard hook; no game-process injection."""

    def __init__(self, *, game_pid: int, block: bool, diagnose: bool = False,
                 capacity: int = 2048) -> None:
        if os.name != "nt":
            raise OSError("WindowsF11Hook requires Windows")
        if game_pid < 0:
            raise ValueError("game_pid must not be negative")
        self.game_pid = game_pid
        self.block = block
        self.diagnose = diagnose
        self.samples = BoundedSamples(capacity)
        self.hook_errors = 0
        self.keyboard_seen = 0
        self.f11_seen = 0
        self.f11_target = 0
        self.f11_other_foreground = 0
        self._hook: int | None = None
        self._hook_proc = None
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t),
            ]

        self._kb_struct = KBDLLHOOKSTRUCT
        hookproc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t
        )
        self._hookproc_type = hookproc_type
        # Explicit 32/64-bit-safe MSG layout (WPARAM/LPARAM are pointer-sized).
        class WinMessage(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", ctypes.c_size_t),
                ("lParam", ctypes.c_ssize_t),
                ("time", wintypes.DWORD),
                ("pt", wintypes.POINT),
                ("lPrivate", wintypes.DWORD),
            ]

        self._msg_type = WinMessage
        self._set_hook = self._user32.SetWindowsHookExW
        self._set_hook.argtypes = [ctypes.c_int, hookproc_type, ctypes.c_void_p, wintypes.DWORD]
        self._set_hook.restype = ctypes.c_void_p
        self._unhook = self._user32.UnhookWindowsHookEx
        self._unhook.argtypes = [ctypes.c_void_p]
        self._unhook.restype = wintypes.BOOL
        self._call_next = self._user32.CallNextHookEx
        self._call_next.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t,
        ]
        self._call_next.restype = ctypes.c_ssize_t
        self._foreground = self._user32.GetForegroundWindow
        self._foreground.argtypes = []
        self._foreground.restype = wintypes.HWND
        self._foreground_pid = self._user32.GetWindowThreadProcessId
        self._foreground_pid.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD),
        ]
        self._foreground_pid.restype = wintypes.DWORD
        self._peek = self._user32.PeekMessageW
        self._peek.argtypes = [
            ctypes.POINTER(self._msg_type), wintypes.HWND,
            wintypes.UINT, wintypes.UINT, wintypes.UINT,
        ]
        self._peek.restype = wintypes.BOOL
        self._translate = self._user32.TranslateMessage
        self._translate.argtypes = [ctypes.POINTER(self._msg_type)]
        self._translate.restype = wintypes.BOOL
        self._dispatch = self._user32.DispatchMessageW
        self._dispatch.argtypes = [ctypes.POINTER(self._msg_type)]
        self._dispatch.restype = ctypes.c_ssize_t

    def set_target_pid(self, pid: int | None) -> None:
        # Called by Supervisor after a game PID transition. Python reference
        # assignment is atomic under the GIL; 0 deliberately matches nothing.
        self.game_pid = int(pid) if pid and pid > 0 else 0

    def _count_error(self) -> None:
        self.hook_errors += 1

    def start(self) -> None:
        if self._hook is not None:
            raise RuntimeError("hook already installed")

        def callback(n_code: int, message: int, param: int) -> int:
            if n_code == HC_ACTION and message in KEY_STATES:
                try:
                    kb = ctypes.cast(
                        param, ctypes.POINTER(self._kb_struct)
                    ).contents
                    self.keyboard_seen += 1
                    if kb.vkCode == VK_F11:
                        self.f11_seen += 1
                        hwnd = self._foreground()
                        pid = wintypes.DWORD()
                        if hwnd:
                            self._foreground_pid(hwnd, ctypes.byref(pid))
                        foreground_pid = int(pid.value) or None
                        if foreground_pid == self.game_pid:
                            self.f11_target += 1
                        else:
                            self.f11_other_foreground += 1
                            if self.diagnose:
                                # Diagnostic trace only: off-target F11 always passes.
                                self.samples.append(F11Sample(
                                    timestamp_ms=time.time_ns() // 1_000_000,
                                    message=message,
                                    state=KEY_STATES[message],
                                    flags=kb.flags,
                                    foreground_pid=foreground_pid,
                                    suppressed=False,
                                    target_match=False,
                                ))
                        if safe_capture_or_pass(
                            on_error=self._count_error,
                            n_code=n_code, message=message, vk=kb.vkCode,
                            flags=kb.flags, foreground_pid=foreground_pid,
                            game_pid=self.game_pid, block=self.block,
                            samples=self.samples, timestamp_ms=time.time_ns() // 1_000_000,
                        ):
                            return 1
                except Exception:
                    # Windows hook callbacks must never raise, or block on IO.
                    self.hook_errors += 1
            return int(self._call_next(self._hook, n_code, message, param))

        self._hook_proc = self._hookproc_type(callback)  # retain callback reference
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_module = kernel32.GetModuleHandleW
        get_module.argtypes = [wintypes.LPCWSTR]
        get_module.restype = ctypes.c_void_p
        module = get_module(None)
        handle = self._set_hook(WH_KEYBOARD_LL, self._hook_proc, module, 0)
        if not handle:
            self._hook_proc = None
            raise OSError(ctypes.get_last_error(), "SetWindowsHookExW failed")
        self._hook = handle

    def pump(self) -> bool:
        message = self._msg_type()
        while self._peek(ctypes.byref(message), None, 0, 0, PM_REMOVE):
            if message.message == WM_QUIT:
                return False
            self._translate(ctypes.byref(message))
            self._dispatch(ctypes.byref(message))
        return True

    def close(self) -> None:
        handle = self._hook
        self._hook = None
        if handle:
            self._unhook(handle)
        self._hook_proc = None

    def __enter__(self) -> "WindowsF11Hook":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


