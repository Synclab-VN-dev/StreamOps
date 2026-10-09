"""GameInput v2 COM API diagnostics with GetCurrentReading, read-only."""
from __future__ import annotations

import ctypes
import os
import time

from ._native import GUID, check_hr, method, release, timestamp, win_library
from .model import BackendResult, EdgeTracker, ProbeStatus
from .runner import BackendUnavailable

# Values and IIDs from Microsoft's GameInput v2 headers.
GAMEINPUT_KIND_GAMEPAD = 0x00040000
IID_IGAMEINPUT_V2 = GUID.parse("bbaa66d2-837a-40f7-a303-917d500955f4")
IID_IGAMEINPUT_READING_V2 = GUID.parse("65f06483-db76-40b7-b745-f591fae55fc9")


class GameInputGamepadState(ctypes.Structure):
    _fields_ = [
        ("buttons", ctypes.c_uint32), ("leftTrigger", ctypes.c_float),
        ("rightTrigger", ctypes.c_float), ("leftThumbstickX", ctypes.c_float),
        ("leftThumbstickY", ctypes.c_float), ("rightThumbstickX", ctypes.c_float),
        ("rightThumbstickY", ctypes.c_float),
    ]


def pressed_buttons(buttons: int) -> set[str]:
    # Preserve raw GameInput bit identity; no semantic Xbox layout in this POC.
    return {f"gameinput-bit:0x{1 << i:08x}" for i in range(32) if buttons & (1 << i)}


def _query_interface(ptr: ctypes.c_void_p, iid: GUID) -> ctypes.c_void_p:
    result = ctypes.c_void_p()
    check_hr(method(ptr, 0, ctypes.c_long,
                    ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(
        ptr, ctypes.byref(iid), ctypes.byref(result)), "QueryInterface")
    return result


class GameInputBackend:
    name = "GameInput"

    def probe(self, seconds: float) -> BackendResult:
        if os.name != "nt":
            raise BackendUnavailable("GameInput requires Windows")
        lib = win_library("GameInput.dll")
        try:
            create = lib.GameInputCreate
        except AttributeError as exc:
            raise BackendUnavailable("GameInputCreate export unavailable") from exc
        create.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        create.restype = ctypes.c_long
        base = ctypes.c_void_p()
        api = ctypes.c_void_p()
        tracker = EdgeTracker(self.name)
        devices: dict[str, dict[str, str]] = {}
        events = []
        no_reading = 0
        try:
            hr = create(ctypes.byref(base))
            if hr < 0 or not base.value:
                raise BackendUnavailable(f"GameInputCreate HRESULT 0x{hr & 0xffffffff:08X}")
            try:
                api = _query_interface(base, IID_IGAMEINPUT_V2)
            except OSError as exc:
                raise BackendUnavailable(f"GameInput v2 interface unavailable: {exc}") from exc
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                reading = ctypes.c_void_p()
                reading_v2 = ctypes.c_void_p()
                device = ctypes.c_void_p()
                try:
                    hr = method(api, 4, ctypes.c_long, ctypes.c_uint32, ctypes.c_void_p,
                                ctypes.POINTER(ctypes.c_void_p))(
                        api, GAMEINPUT_KIND_GAMEPAD, None, ctypes.byref(reading))
                    if hr < 0 or not reading.value:
                        no_reading += 1
                        time.sleep(0.01)
                        continue
                    reading_v2 = _query_interface(reading, IID_IGAMEINPUT_READING_V2)
                    method(reading_v2, 5, None, ctypes.POINTER(ctypes.c_void_p))(
                        reading_v2, ctypes.byref(device))
                    # Pointer identity is diagnostic-only within this run.
                    identity = f"gameinput-device:{device.value:x}" if device.value else "gameinput-device:unknown"
                    devices[identity] = {"deviceId": identity}
                    state = GameInputGamepadState()
                    success = method(reading_v2, 18, ctypes.c_bool,
                                     ctypes.POINTER(GameInputGamepadState))(
                        reading_v2, ctypes.byref(state))
                    if success:
                        events.extend(tracker.update(identity, pressed_buttons(state.buttons),
                                                     timestamp()))
                finally:
                    release(device)
                    release(reading_v2)
                    release(reading)
                time.sleep(0.01)
        finally:
            release(api)
            release(base)
        status = (ProbeStatus.EVENTS_OBSERVED if events
                  else ProbeStatus.DEVICE_PRESENT_BUT_NO_EVENTS if devices
                  else ProbeStatus.NO_DEVICE)
        return BackendResult(self.name, status, devices=list(devices.values()),
                             events=events[:2048],
                             detail=f"GameInput v2 GetCurrentReading; emptyPolls={no_reading}")
