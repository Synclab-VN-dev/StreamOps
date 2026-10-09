"""DirectInput 8 read-only game-controller diagnostic (non-exclusive/background).

DIDATAFORMAT is built from enumerated device objects rather than assuming every
controller has the full DIJOYSTATE2 predefined format.
"""
from __future__ import annotations

import ctypes
import os
import time
import uuid

from ._native import GUID, check_hr, method, release, timestamp, win_library
from .model import BackendResult, EdgeTracker, ProbeStatus
from .runner import BackendUnavailable

IID_DIRECTINPUT8W = GUID.parse("bf798031-483a-4da2-aa99-5d64ed369700")
DI8DEVCLASS_GAMECTRL = 4
DIEDFL_ATTACHEDONLY = 1
DISCL_BACKGROUND = 0x10
DISCL_NONEXCLUSIVE = 0x02
DIDF_ABSAXIS = 0x01
DIDFT_BUTTON = 0x0C
DIDFT_POV = 0x10
DIENUM_CONTINUE = 1


class DEVICE_INSTANCE(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32), ("guidInstance", GUID),
        ("guidProduct", GUID), ("dwDevType", ctypes.c_uint32),
        ("tszInstanceName", ctypes.c_wchar * 260),
        ("tszProductName", ctypes.c_wchar * 260),
        ("guidFFDriver", GUID), ("wUsagePage", ctypes.c_uint16),
        ("wUsage", ctypes.c_uint16),
    ]


class OBJECT_INSTANCE_HEAD(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32), ("guidType", GUID),
        ("dwOfs", ctypes.c_uint32), ("dwType", ctypes.c_uint32),
    ]


class OBJECT_FORMAT(ctypes.Structure):
    _fields_ = [
        ("pguid", ctypes.c_void_p), ("dwOfs", ctypes.c_uint32),
        ("dwType", ctypes.c_uint32), ("dwFlags", ctypes.c_uint32),
    ]


class DATA_FORMAT(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32), ("dwObjSize", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32), ("dwDataSize", ctypes.c_uint32),
        ("dwNumObjs", ctypes.c_uint32),
        ("rgodf", ctypes.POINTER(OBJECT_FORMAT)),
    ]


def _id_from_guid(guid: GUID) -> str:
    return str(uuid.UUID(bytes_le=bytes(guid)))


def _format_objects(objects: list[tuple[str, int]]):
    """Create a nonstandard immediate format limited to present digital objects."""
    buttons = [(kind, type_code) for kind, type_code in objects if kind == "button"][:128]
    povs = [(kind, type_code) for kind, type_code in objects if kind == "pov"][:4]
    selected = buttons + povs
    if not selected:
        return None
    object_array = (OBJECT_FORMAT * len(selected))()
    descriptors = []
    offset = 0
    for i, (kind, type_code) in enumerate(selected):
        if kind == "pov":
            offset = (offset + 3) & ~3
            descriptors.append((kind, offset))
            object_array[i] = OBJECT_FORMAT(None, offset, type_code, 0)
            offset += 4
        else:
            descriptors.append((kind, offset))
            object_array[i] = OBJECT_FORMAT(None, offset, type_code, 0)
            offset += 1
    size = (offset + 3) & ~3
    data_format = DATA_FORMAT(ctypes.sizeof(DATA_FORMAT),
                              ctypes.sizeof(OBJECT_FORMAT), DIDF_ABSAXIS,
                              size, len(selected), object_array)
    return data_format, object_array, descriptors, size


def decode_state(data: bytes, descriptors: list[tuple[str, int]]) -> set[str]:
    pressed = set()
    for index, (kind, offset) in enumerate(descriptors):
        if kind == "button":
            if data[offset] & 0x80:
                pressed.add(f"button:{index}")
        else:
            value = int.from_bytes(data[offset:offset + 4], "little")
            if value != 0xffffffff:
                pressed.add(f"pov:{index}:angle:{value}")
    return pressed


class DirectInputBackend:
    name = "DirectInput"

    def probe(self, seconds: float) -> BackendResult:
        if os.name != "nt":
            raise BackendUnavailable("DirectInput requires Windows")
        dll = win_library("dinput8.dll")
        kernel = win_library("kernel32.dll")
        kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        kernel.GetModuleHandleW.restype = ctypes.c_void_p
        dll.DirectInput8Create.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(GUID),
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
        ]
        dll.DirectInput8Create.restype = ctypes.c_long
        api = ctypes.c_void_p()
        check_hr(dll.DirectInput8Create(kernel.GetModuleHandleW(None), 0x0800,
                                       ctypes.byref(IID_DIRECTINPUT8W),
                                       ctypes.byref(api), None),
                 "DirectInput8Create")
        instance_cb_type = ctypes.WINFUNCTYPE(
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        device_guids = []
        devices = {}
        held = []
        events = []
        trackers = {}
        failures = []
        try:
            def record_device(pointer, context):
                info = ctypes.cast(pointer, ctypes.POINTER(DEVICE_INSTANCE)).contents
                if len(device_guids) < 32:
                    guid = GUID.from_buffer_copy(bytes(info.guidInstance))
                    identity = f"dinput:{_id_from_guid(guid)}"
                    devices[identity] = {
                        "deviceId": identity,
                        "product": str(info.tszProductName),
                    }
                    device_guids.append((identity, guid))
                return DIENUM_CONTINUE

            enum_callback = instance_cb_type(record_device)
            check_hr(method(api, 4, ctypes.c_long, ctypes.c_uint32, instance_cb_type,
                            ctypes.c_void_p, ctypes.c_uint32)(
                api, DI8DEVCLASS_GAMECTRL, enum_callback, None,
                DIEDFL_ATTACHEDONLY), "IDirectInput8.EnumDevices")
            for identity, guid in device_guids:
                dev = ctypes.c_void_p()
                try:
                    check_hr(method(api, 3, ctypes.c_long, ctypes.POINTER(GUID),
                                    ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p)(
                        api, ctypes.byref(guid), ctypes.byref(dev), None),
                        "IDirectInput8.CreateDevice")
                    object_codes: list[tuple[str, int]] = []

                    def record_object(pointer, context):
                        info = ctypes.cast(pointer, ctypes.POINTER(OBJECT_INSTANCE_HEAD)).contents
                        if info.dwType & DIDFT_POV:
                            object_codes.append(("pov", int(info.dwType)))
                        elif info.dwType & DIDFT_BUTTON:
                            object_codes.append(("button", int(info.dwType)))
                        return DIENUM_CONTINUE

                    obj_callback = instance_cb_type(record_object)
                    check_hr(method(dev, 4, ctypes.c_long, instance_cb_type,
                                    ctypes.c_void_p, ctypes.c_uint32)(
                        dev, obj_callback, None, 0), "IDirectInputDevice8.EnumObjects")
                    prepared = _format_objects(object_codes)
                    if not prepared:
                        failures.append(f"{identity}: no digital objects")
                        continue
                    fmt, keep_alive, descriptors, size = prepared
                    check_hr(method(dev, 11, ctypes.c_long, ctypes.POINTER(DATA_FORMAT))(
                        dev, ctypes.byref(fmt)), "IDirectInputDevice8.SetDataFormat")
                    # Explicitly nonexclusive, never changes Steam/game's controller mapping.
                    check_hr(method(dev, 13, ctypes.c_long, ctypes.c_void_p,
                                    ctypes.c_uint32)(
                        dev, None, DISCL_BACKGROUND | DISCL_NONEXCLUSIVE),
                        "IDirectInputDevice8.SetCooperativeLevel")
                    check_hr(method(dev, 7, ctypes.c_long)(dev),
                             "IDirectInputDevice8.Acquire")
                    held.append((identity, dev, descriptors, size))
                    trackers[identity] = EdgeTracker(self.name)
                    dev = ctypes.c_void_p()  # ownership transferred to held
                except OSError as exc:
                    failures.append(f"{identity}: {exc}")
                finally:
                    release(dev)

            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                for identity, dev, descriptors, size in held:
                    data = ctypes.create_string_buffer(size)
                    hr = method(dev, 9, ctypes.c_long, ctypes.c_uint32,
                                ctypes.c_void_p)(dev, size, data)
                    if hr < 0:
                        continue
                    events.extend(trackers[identity].update(
                        identity, decode_state(data.raw, descriptors), timestamp()))
                time.sleep(0.01)
        finally:
            for identity, dev, _, _ in held:
                try:
                    method(dev, 8, ctypes.c_long)(dev)
                finally:
                    release(dev)
            release(api)
        status = (ProbeStatus.EVENTS_OBSERVED if events
                  else ProbeStatus.DEVICE_PRESENT_BUT_NO_EVENTS if devices
                  else ProbeStatus.NO_DEVICE)
        return BackendResult(self.name, status, devices=list(devices.values()),
                             events=events[:2048],
                             detail="nonexclusive/background; " +
                             ("; ".join(failures[:8]) if failures else "no device errors"))
