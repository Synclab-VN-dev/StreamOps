"""Read-only keyboard marker probe for Steam Input dual bindings."""

from __future__ import annotations

import ctypes
import os


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


class AsyncKeyStateBackend:
    """Minimal read-only wrapper around Win32 GetAsyncKeyState."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("input marker probe requires Windows")
        user32 = getattr(ctypes, "windll", None)
        if user32 is None:
            raise OSError("ctypes.windll is unavailable")
        self._get_async_key_state = ctypes.windll.user32.GetAsyncKeyState
        self._get_async_key_state.argtypes = [ctypes.c_int]
        self._get_async_key_state.restype = ctypes.c_short

    def is_down(self, virtual_key: int) -> bool:
        return bool(int(self._get_async_key_state(int(virtual_key))) & 0x8000)


__all__ = [
    "AsyncKeyStateBackend",
    "KEY_CODES",
    "edge_transition",
    "virtual_key_code",
]
