"""Windows.Gaming.Input gamepad visibility via WinRT ABI (read-only)."""
from __future__ import annotations

import ctypes
import os
import time

from ._native import GUID, check_hr, method, release, timestamp, win_library
from .model import BackendResult, EdgeTracker, ProbeStatus
from .runner import BackendUnavailable

IGAMEPAD_STATICS = GUID.parse("8bbce529-d49c-39e9-9560-e47dde96b7c8")
# IVectorView<Windows.Gaming.Input.Gamepad> is declared in windows.gaming.input.h.
IGAMEPAD_VIEW = GUID.parse("eb97bb69-09c9-5a99-86b2-3e36085284d4")
MASKS = {
    "menu": 0x01, "view": 0x02, "A": 0x04, "B": 0x08, "X": 0x10,
    "Y": 0x20, "dpad-up": 0x40, "dpad-down": 0x80,
    "dpad-left": 0x100, "dpad-right": 0x200,
    "LB": 0x400, "RB": 0x800, "left-stick": 0x1000,
    "right-stick": 0x2000,
}


class GamepadReading(ctypes.Structure):
    _fields_ = [
        ("timestamp", ctypes.c_uint64), ("buttons", ctypes.c_uint32),
        ("leftTrigger", ctypes.c_double), ("rightTrigger", ctypes.c_double),
        ("leftThumbstickX", ctypes.c_double), ("leftThumbstickY", ctypes.c_double),
        ("rightThumbstickX", ctypes.c_double), ("rightThumbstickY", ctypes.c_double),
    ]


def pressed_buttons(mask: int) -> set[str]:
    return {f"button:0x{bit:04x}:{name}" for name, bit in MASKS.items() if mask & bit}


class WGIBackend:
    name = "Windows.Gaming.Input"

    def probe(self, seconds: float) -> BackendResult:
        if os.name != "nt":
            raise BackendUnavailable("Windows.Gaming.Input requires Windows")
        combase = win_library("combase.dll")
        combase.RoInitialize.argtypes = [ctypes.c_uint32]
        combase.RoInitialize.restype = ctypes.c_long
        combase.RoUninitialize.argtypes = []
        combase.WindowsCreateString.argtypes = [
            ctypes.c_wchar_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        combase.WindowsCreateString.restype = ctypes.c_long
        combase.WindowsDeleteString.argtypes = [ctypes.c_void_p]
        combase.RoGetActivationFactory.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
        combase.RoGetActivationFactory.restype = ctypes.c_long
        hr = combase.RoInitialize(1)  # RO_INIT_MULTITHREADED
        initialized = hr >= 0
        # RPC_E_CHANGED_MODE permits using the caller's existing apartment.
        if hr < 0 and hr & 0xffffffff != 0x80010106:
            raise BackendUnavailable(f"WinRT initialization HRESULT 0x{hr & 0xffffffff:08X}")
        hstring = ctypes.c_void_p()
        factory = ctypes.c_void_p()
        tracker = EdgeTracker(self.name)
        devices: dict[str, dict[str, object]] = {}
        events = []
        try:
            name = "Windows.Gaming.Input.Gamepad"
            check_hr(combase.WindowsCreateString(name, len(name), ctypes.byref(hstring)),
                     "WindowsCreateString")
            hr = combase.RoGetActivationFactory(
                hstring, ctypes.byref(IGAMEPAD_STATICS), ctypes.byref(factory))
            if hr < 0:
                raise BackendUnavailable(f"WGI factory unavailable HRESULT 0x{hr & 0xffffffff:08X}")
            deadline = time.monotonic() + seconds
            # Gamepad.Gamepads may populate asynchronously after initialization.
            while time.monotonic() < deadline:
                view = ctypes.c_void_p()
                try:
                    check_hr(method(factory, 10, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))(
                        factory, ctypes.byref(view)), "IGamepadStatics.get_Gamepads")
                    count = ctypes.c_uint32()
                    check_hr(method(view, 7, ctypes.c_long, ctypes.POINTER(ctypes.c_uint32))(
                        view, ctypes.byref(count)), "IVectorView.get_Size")
                    for index in range(min(count.value, 32)):
                        pad = ctypes.c_void_p()
                        try:
                            check_hr(method(view, 6, ctypes.c_long, ctypes.c_uint32,
                                            ctypes.POINTER(ctypes.c_void_p))(
                                view, index, ctypes.byref(pad)), "IVectorView.GetAt")
                            dev_id = f"wgi-slot:{index}"
                            devices[dev_id] = {"deviceId": dev_id, "slot": index}
                            reading = GamepadReading()
                            check_hr(method(pad, 8, ctypes.c_long,
                                            ctypes.POINTER(GamepadReading))(
                                pad, ctypes.byref(reading)), "IGamepad.GetCurrentReading")
                            events.extend(tracker.update(
                                dev_id, pressed_buttons(reading.buttons), timestamp()))
                        finally:
                            release(pad)
                finally:
                    release(view)
                time.sleep(0.01)
        finally:
            release(factory)
            if hstring.value:
                combase.WindowsDeleteString(hstring)
            if initialized:
                combase.RoUninitialize()

        status = (ProbeStatus.EVENTS_OBSERVED if events
                  else ProbeStatus.DEVICE_PRESENT_BUT_NO_EVENTS if devices
                  else ProbeStatus.NO_DEVICE)
        return BackendResult(
            self.name, status, devices=list(devices.values()), events=events[:2048],
            detail="WGI Gamepad.Gamepads; read-only polling; no vibration",
        )
