"""Read-only XInput probe for Steam Link / Remote Play controllers."""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
import os


ERROR_SUCCESS = 0
ERROR_DEVICE_NOT_CONNECTED = 1167

BUTTON_MASKS: tuple[tuple[int, str], ...] = (
    (0x0001, "DPAD_UP"),
    (0x0002, "DPAD_DOWN"),
    (0x0004, "DPAD_LEFT"),
    (0x0008, "DPAD_RIGHT"),
    (0x0010, "START"),
    (0x0020, "BACK"),
    (0x0040, "LEFT_THUMB"),
    (0x0080, "RIGHT_THUMB"),
    (0x0100, "LEFT_SHOULDER"),
    (0x0200, "RIGHT_SHOULDER"),
    (0x1000, "A"),
    (0x2000, "B"),
    (0x4000, "X"),
    (0x8000, "Y"),
)


class _XInputGamepad(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_ushort),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class _XInputState(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", ctypes.c_uint32),
        ("Gamepad", _XInputGamepad),
    ]


@dataclass(frozen=True, slots=True)
class XInputSnapshot:
    slot: int
    packet_number: int
    buttons: int


def decode_buttons(mask: int) -> tuple[str, ...]:
    return tuple(name for bit, name in BUTTON_MASKS if mask & bit)


class XInputBackend:
    """Tiny ctypes wrapper around XInputGetState.

    It never sends vibration/input and never injects into another process.
    """

    DLL_CANDIDATES = ("xinput1_4.dll", "xinput9_1_0.dll", "xinput1_3.dll")

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("XInput probe requires Windows")

        loader = getattr(ctypes, "WinDLL", None)
        if loader is None:
            raise OSError("ctypes.WinDLL is unavailable")

        last_error: OSError | None = None
        dll = None
        dll_name = None
        for candidate in self.DLL_CANDIDATES:
            try:
                dll = loader(candidate)
                dll_name = candidate
                break
            except OSError as exc:
                last_error = exc

        if dll is None or dll_name is None:
            raise OSError("unable to load any XInput DLL") from last_error

        get_state = dll.XInputGetState
        get_state.argtypes = [ctypes.c_uint, ctypes.POINTER(_XInputState)]
        get_state.restype = ctypes.c_uint

        self._dll = dll
        self._get_state = get_state
        self.dll_name = dll_name

    def snapshot(self, slot: int) -> XInputSnapshot | None:
        if slot < 0 or slot > 3:
            raise ValueError("XInput slot must be in range 0..3")

        state = _XInputState()
        result = int(self._get_state(slot, ctypes.byref(state)))
        if result == ERROR_DEVICE_NOT_CONNECTED:
            return None
        if result != ERROR_SUCCESS:
            raise OSError(result, f"XInputGetState failed for slot {slot}")

        return XInputSnapshot(
            slot=slot,
            packet_number=int(state.dwPacketNumber),
            buttons=int(state.Gamepad.wButtons),
        )


__all__ = ["BUTTON_MASKS", "XInputBackend", "XInputSnapshot", "decode_buttons"]
