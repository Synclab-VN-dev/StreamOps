"""Windows Raw Input/HID diagnostic backend; no injection, hooks, or game writes.

Runs exclusively on the active interactive desktop. RIDEV_INPUTSINK is
registered only for Generic Desktop gamepad/joystick usages (never mouse/key).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import os
import struct
import time

from .model import BackendResult, ControlEdge, EdgeTracker, ProbeStatus


RIM_TYPEHID = 2
RIDI_DEVICENAME = 0x20000007
RIDI_DEVICEINFO = 0x2000000B
RIDI_PREPARSEDDATA = 0x20000005
RID_INPUT = 0x10000003
WM_INPUT = 0x00FF
PM_REMOVE = 0x0001
RIDEV_INPUTSINK = 0x00000100
RIDEV_REMOVE = 0x00000001
MAX_EVENTS = 2048


class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [("hDevice", ctypes.c_void_p), ("dwType", wintypes.DWORD)]


class RID_DEVICE_INFO_HID(ctypes.Structure):
    _fields_ = [
        ("dwVendorId", wintypes.DWORD), ("dwProductId", wintypes.DWORD),
        ("dwVersionNumber", wintypes.DWORD),
        ("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
    ]


class RID_DEVICE_INFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("dwType", wintypes.DWORD),
                ("hid", RID_DEVICE_INFO_HID)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD), ("hwndTarget", ctypes.c_void_p)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                ("hDevice", ctypes.c_void_p), ("wParam", ctypes.c_void_p)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", wintypes.USHORT), ("UsagePage", wintypes.USHORT),
        ("InputReportByteLength", wintypes.USHORT),
        ("OutputReportByteLength", wintypes.USHORT),
        ("FeatureReportByteLength", wintypes.USHORT),
        ("Reserved", wintypes.USHORT * 17),
        ("NumberLinkCollectionNodes", wintypes.USHORT),
        ("NumberInputButtonCaps", wintypes.USHORT),
        ("NumberInputValueCaps", wintypes.USHORT),
        ("NumberInputDataIndices", wintypes.USHORT),
        ("NumberOutputButtonCaps", wintypes.USHORT),
        ("NumberOutputValueCaps", wintypes.USHORT),
        ("NumberOutputDataIndices", wintypes.USHORT),
        ("NumberFeatureButtonCaps", wintypes.USHORT),
        ("NumberFeatureValueCaps", wintypes.USHORT),
        ("NumberFeatureDataIndices", wintypes.USHORT),
    ]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _checked(value: int, label: str) -> None:
    if value == 0xFFFFFFFF:
        raise OSError(f"{label} failed: {ctypes.get_last_error()}")


class RawInputBackend:
    name = "RawInput"

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Raw Input requires Windows")
        # Lazy native loading avoids import failures on Linux CI.
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.hid = ctypes.WinDLL("hid", use_last_error=True)
        ptr, uint, word = ctypes.c_void_p, wintypes.UINT, wintypes.USHORT
        self.user32.GetRawInputDeviceList.argtypes = [ptr, ctypes.POINTER(uint), uint]
        self.user32.GetRawInputDeviceList.restype = uint
        self.user32.GetRawInputDeviceInfoW.argtypes = [ptr, uint, ptr, ctypes.POINTER(uint)]
        self.user32.GetRawInputDeviceInfoW.restype = uint
        self.user32.GetRawInputData.argtypes = [ptr, uint, ptr, ctypes.POINTER(uint), uint]
        self.user32.GetRawInputData.restype = uint
        self.user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ptr, ptr, ptr, ptr,
        ]
        self.user32.CreateWindowExW.restype = ptr
        self.user32.DefWindowProcW.argtypes = [ptr, uint, ctypes.c_size_t, ctypes.c_ssize_t]
        self.user32.DefWindowProcW.restype = ctypes.c_ssize_t
        self.user32.RegisterClassW.argtypes = [ptr]
        self.user32.RegisterClassW.restype = word
        self.user32.RegisterRawInputDevices.argtypes = [
            ctypes.POINTER(RAWINPUTDEVICE), uint, uint,
        ]
        self.user32.RegisterRawInputDevices.restype = wintypes.BOOL
        self.user32.PeekMessageW.argtypes = [ptr, ptr, uint, uint, uint]
        self.user32.PeekMessageW.restype = wintypes.BOOL
        self.user32.TranslateMessage.argtypes = [ptr]
        self.user32.DispatchMessageW.argtypes = [ptr]
        self.user32.DestroyWindow.argtypes = [ptr]
        self.user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, ptr]
        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetModuleHandleW.restype = ptr
        self.hid.HidP_GetCaps.argtypes = [ptr, ptr]
        self.hid.HidP_GetUsages.argtypes = [
            ctypes.c_int, word, word, ptr, ctypes.POINTER(wintypes.ULONG),
            ptr, ptr, wintypes.ULONG,
        ]
        self.hid.HidP_GetUsageValue.argtypes = [
            ctypes.c_int, word, word, word, ctypes.POINTER(wintypes.ULONG),
            ptr, ptr, wintypes.ULONG,
        ]
        for fn in ("HidP_GetUsages", "HidP_GetUsageValue", "HidP_GetCaps"):
            getattr(self.hid, fn).restype = ctypes.c_long
        self._tracker = EdgeTracker(self.name)
        self._devices: dict[int, dict[str, str | int]] = {}
        self._preparsed: dict[int, object] = {}
        self._events: list[ControlEdge] = []
        self._decode_failures = 0

    def _info(self, handle: int) -> dict[str, str | int] | None:
        info = RID_DEVICE_INFO()
        info.cbSize = ctypes.sizeof(info)
        size = wintypes.UINT(ctypes.sizeof(info))
        rc = self.user32.GetRawInputDeviceInfoW(
            ctypes.c_void_p(handle), RIDI_DEVICEINFO, ctypes.byref(info), ctypes.byref(size)
        )
        if rc == 0xFFFFFFFF or info.dwType != RIM_TYPEHID:
            return None
        if (info.hid.usUsagePage, info.hid.usUsage) not in ((1, 4), (1, 5)):
            return None
        n = wintypes.UINT()
        self.user32.GetRawInputDeviceInfoW(ctypes.c_void_p(handle), RIDI_DEVICENAME, None, ctypes.byref(n))
        name = ctypes.create_unicode_buffer(max(1, n.value + 1))
        rc = self.user32.GetRawInputDeviceInfoW(
            ctypes.c_void_p(handle), RIDI_DEVICENAME, name, ctypes.byref(n)
        )
        identity = name.value if rc != 0xFFFFFFFF and name.value else f"hid-handle:{handle:x}"
        return {
            "deviceId": identity,
            "usagePage": f"0x{info.hid.usUsagePage:02x}",
            "usage": f"0x{info.hid.usUsage:02x}",
            "vendorId": f"0x{info.hid.dwVendorId:04x}",
            "productId": f"0x{info.hid.dwProductId:04x}",
        }

    def _enumerate(self) -> None:
        count = wintypes.UINT()
        rc = self.user32.GetRawInputDeviceList(
            None, ctypes.byref(count), ctypes.sizeof(RAWINPUTDEVICELIST)
        )
        _checked(rc, "GetRawInputDeviceList(count)")
        if not count.value:
            return
        buffer = (RAWINPUTDEVICELIST * count.value)()
        rc = self.user32.GetRawInputDeviceList(
            buffer, ctypes.byref(count), ctypes.sizeof(RAWINPUTDEVICELIST)
        )
        _checked(rc, "GetRawInputDeviceList(devices)")
        for item in buffer[:rc]:
            handle = int(item.hDevice or 0)
            if item.dwType == RIM_TYPEHID:
                info = self._info(handle)
                if info is not None:
                    self._devices[handle] = info

    def _ppd(self, handle: int):
        if handle in self._preparsed:
            return self._preparsed[handle]
        size = wintypes.UINT(0)
        self.user32.GetRawInputDeviceInfoW(
            ctypes.c_void_p(handle), RIDI_PREPARSEDDATA, None, ctypes.byref(size)
        )
        if not size.value or size.value > 1024 * 1024:
            raise OSError("HID preparsed data unavailable or too large")
        buf = ctypes.create_string_buffer(size.value)
        rc = self.user32.GetRawInputDeviceInfoW(
            ctypes.c_void_p(handle), RIDI_PREPARSEDDATA, buf, ctypes.byref(size)
        )
        _checked(rc, "GetRawInputDeviceInfoW(preparsed)")
        self._preparsed[handle] = buf
        return buf

    def _pressed(self, handle: int, report: bytes) -> set[str]:
        preparsed = self._ppd(handle)
        caps = HIDP_CAPS()
        if self.hid.HidP_GetCaps(preparsed, ctypes.byref(caps)) < 0:
            raise OSError("HidP_GetCaps failed")
        pressed: set[str] = set()
        raw = ctypes.create_string_buffer(report, len(report))
        # Raw button identities: do not normalize into an Xbox layout.
        for page in (0x09, 0x01):
            usage_count = wintypes.ULONG(256)
            usages = (wintypes.USHORT * 256)()
            status = self.hid.HidP_GetUsages(
                0, page, 0, usages, ctypes.byref(usage_count),
                preparsed, raw, len(report)
            )
            if status >= 0:
                pressed.update(f"usage:0x{page:02x}:0x{u:02x}" for u in usages[:usage_count.value])
        # D-pad often appears as a hat switch rather than four button usages.
        hat = wintypes.ULONG()
        status = self.hid.HidP_GetUsageValue(
            0, 0x01, 0, 0x39, ctypes.byref(hat),
            preparsed, raw, len(report)
        )
        if status >= 0:
            pressed.add(f"hat:0x01:0x39:{hat.value}")
        return pressed

    def _on_input(self, lparam: int) -> None:
        size = wintypes.UINT()
        rc = self.user32.GetRawInputData(
            ctypes.c_void_p(lparam), RID_INPUT, None,
            ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER)
        )
        if rc == 0xFFFFFFFF or size.value < ctypes.sizeof(RAWINPUTHEADER) + 8:
            return
        raw = ctypes.create_string_buffer(size.value)
        rc = self.user32.GetRawInputData(
            ctypes.c_void_p(lparam), RID_INPUT, raw,
            ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER)
        )
        if rc == 0xFFFFFFFF:
            return
        header = RAWINPUTHEADER.from_buffer_copy(raw.raw)
        if header.dwType != RIM_TYPEHID:
            return
        handle = int(header.hDevice or 0)
        if handle not in self._devices:
            info = self._info(handle)
            if info is None:
                return
            self._devices[handle] = info
        data_offset = ctypes.sizeof(RAWINPUTHEADER)
        size_hid, report_count = struct.unpack_from("<II", raw.raw, data_offset)
        if not 0 < size_hid <= 4096 or not 0 < report_count <= 64:
            return
        start = data_offset + 8
        if start + size_hid * report_count > rc:
            return
        device_id = str(self._devices[handle]["deviceId"])
        for i in range(report_count):
            report = raw.raw[start + size_hid * i:start + size_hid * (i + 1)]
            try:
                pressed = self._pressed(handle, report)
                edges = self._tracker.update(device_id, pressed, _now())
                space = MAX_EVENTS - len(self._events)
                self._events.extend(edges[:max(0, space)])
            except (OSError, ValueError):
                self._decode_failures += 1

    def probe(self, seconds: float) -> BackendResult:
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        self._enumerate()
        # ctypes.WINFUNCTYPE is only present on Windows.
        wndproc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_void_p, wintypes.UINT,
            ctypes.c_size_t, ctypes.c_ssize_t,
        )

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT), ("lpfnWndProc", wndproc_type),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", ctypes.c_void_p), ("hIcon", ctypes.c_void_p),
                ("hCursor", ctypes.c_void_p), ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
            ]

        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", ctypes.c_void_p), ("message", wintypes.UINT),
                ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                ("time", wintypes.DWORD), ("pt", POINT),
                ("lPrivate", wintypes.DWORD),
            ]

        def on_message(hwnd, message, wparam, lparam):
            if message == WM_INPUT:
                self._on_input(lparam)
            return self.user32.DefWindowProcW(hwnd, message, wparam, lparam)

        callback = wndproc_type(on_message)
        cls_name = f"D4PlannerRawProbe_{os.getpid()}"
        instance = self.kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = callback
        wc.hInstance = instance
        wc.lpszClassName = cls_name
        atom = self.user32.RegisterClassW(ctypes.byref(wc))
        if not atom:
            raise OSError(f"RegisterClassW failed: {ctypes.get_last_error()}")
        hwnd = None
        registered = False
        try:
            hwnd = self.user32.CreateWindowExW(
                0, cls_name, "D4Planner Probe (hidden)", 0,
                0, 0, 0, 0, None, None, instance, None
            )
            if not hwnd:
                raise OSError(f"CreateWindowExW failed: {ctypes.get_last_error()}")
            devices = (RAWINPUTDEVICE * 2)(
                RAWINPUTDEVICE(1, 4, RIDEV_INPUTSINK, hwnd),
                RAWINPUTDEVICE(1, 5, RIDEV_INPUTSINK, hwnd),
            )
            if not self.user32.RegisterRawInputDevices(
                devices, 2, ctypes.sizeof(RAWINPUTDEVICE)
            ):
                raise OSError(f"RegisterRawInputDevices failed: {ctypes.get_last_error()}")
            registered = True
            deadline = time.monotonic() + seconds
            msg = MSG()
            while time.monotonic() < deadline:
                handled = False
                while self.user32.PeekMessageW(ctypes.byref(msg), hwnd, 0, 0, PM_REMOVE):
                    self.user32.TranslateMessage(ctypes.byref(msg))
                    self.user32.DispatchMessageW(ctypes.byref(msg))
                    handled = True
                if not handled:
                    time.sleep(0.01)
        finally:
            if registered:
                remove = (RAWINPUTDEVICE * 2)(
                    RAWINPUTDEVICE(1, 4, RIDEV_REMOVE, None),
                    RAWINPUTDEVICE(1, 5, RIDEV_REMOVE, None),
                )
                self.user32.RegisterRawInputDevices(
                    remove, 2, ctypes.sizeof(RAWINPUTDEVICE)
                )
            if hwnd:
                self.user32.DestroyWindow(hwnd)
            self.user32.UnregisterClassW(cls_name, instance)

        status = (
            ProbeStatus.EVENTS_OBSERVED if self._events else
            ProbeStatus.DEVICE_PRESENT_BUT_NO_EVENTS if self._devices else
            ProbeStatus.NO_DEVICE
        )
        return BackendResult(
            backend=self.name, status=status, devices=list(self._devices.values()),
            events=self._events,
            detail=f"hidDecodeFailures={self._decode_failures}; cappedEvents={MAX_EVENTS}",
        )
