"""Read-only Windows choices for a scene editor, including an empty OBS collection."""
import ctypes
from ctypes import wintypes
from pathlib import PureWindowsPath
import re
import shutil
import subprocess
import sys


def _escape(value):
    return value.replace('#', '#22').replace(':', '#3A')


def windows_inventory():
    result = {'windows': [], 'capture': [], 'render': [], 'cameras': [], 'errors': []}
    if sys.platform != 'win32':
        result['errors'].append('Native device discovery is available on Windows.')
        return result
    from .session import desktop_session_info
    if desktop_session_info().is_interactive:
        try: result['windows'] = _windows()
        except OSError as exc: result['errors'].append(f'Window discovery: {exc}')
    else:
        result['errors'].append('Window discovery requires the active desktop session.')
    for flow in ('Capture', 'Render'):
        try: result[flow.lower()] = _audio_endpoints(flow)
        except OSError as exc: result['errors'].append(f'{flow} device discovery: {exc}')
    ffmpeg = shutil.which('ffmpeg')
    if ffmpeg:
        try:
            completed = subprocess.run([ffmpeg, '-hide_banner', '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=8, creationflags=0x08000000)
            name = None
            for line in completed.stderr.splitlines():
                found = re.search(r'"(.*)" \((video|none)\)', line)
                if found: name = found.group(1)
                alternative = re.search(r'Alternative name "(.*)"', line)
                if alternative and name:
                    path = alternative.group(1).removeprefix('@device_pnp_')
                    result['cameras'].append({'label': name, 'value': _escape(name) + ':' + _escape(path)})
                    name = None
        except (OSError, subprocess.TimeoutExpired) as exc:
            result['errors'].append(f'Camera discovery: {exc}')
    else:
        result['errors'].append('Camera discovery without an existing OBS input requires ffmpeg.')
    return result


def _audio_endpoints(flow):
    import winreg
    prefix = '{0.0.1.00000000}.' if flow == 'Capture' else '{0.0.0.00000000}.'
    result = [{'label': 'Default device', 'value': 'default'}]
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf'SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\{flow}') as root:
        for i in range(winreg.QueryInfoKey(root)[0]):
            device = winreg.EnumKey(root, i)
            with winreg.OpenKey(root, device) as key:
                if winreg.QueryValueEx(key, 'DeviceState')[0] != 1:
                    continue
                with winreg.OpenKey(key, 'Properties') as props:
                    try: name = winreg.QueryValueEx(props, '{a45c254e-df1c-4efd-8020-67d146a850e0},14')[0]
                    except OSError: name = device
            result.append({'label': name, 'value': prefix + device})
    return result


def _windows():
    user, kernel = ctypes.windll.user32, ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    result = []
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        if not user.IsWindowVisible(hwnd): return True
        length = user.GetWindowTextLengthW(hwnd)
        if not length: return True
        title, klass = ctypes.create_unicode_buffer(length+1), ctypes.create_unicode_buffer(256)
        user.GetWindowTextW(hwnd, title, length+1)
        user.GetClassNameW(hwnd, klass, 256)
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel.OpenProcess(0x1000, False, pid.value)
        if handle:
            try:
                path, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
                if kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                    exe = PureWindowsPath(path.value).name
                    result.append({'label': f'{title.value} ({exe})', 'value': ':'.join(map(_escape, [title.value, klass.value, exe]))})
            finally: kernel.CloseHandle(handle)
        return True
    user.EnumWindows(callback, 0)
    return result
