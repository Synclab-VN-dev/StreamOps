"""Small, read-only COM ABI helpers shared by diagnostic Windows backends.

Uses stdlib ctypes only; no drivers, hooks, SendInput or input mutation.
"""
from __future__ import annotations

import ctypes
import os
import uuid
from datetime import datetime, timezone

from .runner import BackendUnavailable


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, value: str) -> "GUID":
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


def win_library(name: str):
    if os.name != "nt":
        raise BackendUnavailable("Windows required")
    try:
        return ctypes.WinDLL(name, use_last_error=True)
    except OSError as exc:
        raise BackendUnavailable(f"{name} not installed: {exc}") from exc


def method(ptr: ctypes.c_void_p, index: int, restype, *args):
    """Construct a typed STDMETHODCALLTYPE callable from a COM vtable entry."""
    if not ptr or not ptr.value:
        raise OSError("NULL COM interface")
    table = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    address = table[index]
    if not address:
        raise OSError(f"NULL COM method {index}")
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *args)(address)


def release(ptr: ctypes.c_void_p) -> None:
    if ptr and ptr.value:
        method(ptr, 2, ctypes.c_uint32)(ptr)
        ptr.value = None


def check_hr(hr: int, label: str) -> None:
    if hr < 0:
        raise OSError(f"{label}: HRESULT 0x{hr & 0xffffffff:08X}")


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
