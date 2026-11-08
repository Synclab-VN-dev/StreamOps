"""Issue 184: actual Windows launcher error dialog must not outlive Setup stop.

Run on an isolated Windows VM. Uses a copied real launcher and disposable data,
never production registration. Reports native evidence even on assertion failure.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

import windows_install as engine


def inventory(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def dialog_for(pid):
    from ctypes import wintypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    found = []
    @callback_type
    def visit(hwnd, unused):
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        name = ctypes.create_unicode_buffer(256)
        user.GetClassNameW(hwnd, name, len(name))
        if owner.value == pid and name.value == '#32770':
            found.append(int(hwnd))
        return True
    user.EnumWindows(visit, 0)
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launcher', required=True, type=Path)
    parser.add_argument('--sandbox', required=True, type=Path)
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Windows native execution is required')
    args.sandbox = args.sandbox.resolve()
    args.sandbox.mkdir(parents=True, exist_ok=False)
    from storage_native_smoke import secure_new_sandbox
    secure_new_sandbox(args.sandbox)
    root = args.sandbox / 'app'
    root.mkdir()
    launcher = root / 'D4Planner.exe'
    shutil.copyfile(args.launcher, launcher)
    local = args.sandbox / 'local'
    legacy = local / 'd4planner'
    (legacy / 'state').mkdir(parents=True)
    with closing(sqlite3.connect(legacy / 'state/hud.sqlite3')) as db, db:
        db.execute('CREATE TABLE equipment(revision INTEGER)')
        db.execute('INSERT INTO equipment VALUES(42)')
    for name in ('targets', 'rulekit'):
        (legacy / name).mkdir()
        (legacy / name / 'preserve.bin').write_bytes(b'issue184-preserve')
    before = inventory(legacy)
    launch_report = args.sandbox / 'launch.json'
    environment = {k: v for k, v in os.environ.items()
                   if not k.startswith(('D4PLANNER_', 'D4_RULEKIT_', 'D4_LOG_', 'D4_HUD_'))}
    environment.update(LOCALAPPDATA=str(local), D4PLANNER_LAUNCH_REPORT=str(launch_report))
    report = {'case': 'migration-error-dialog-stop', 'status': 'RUNNING',
              'launcherSha256': inventory(root)['D4Planner.exe'], 'before': before}
    child = None
    try:
        child = subprocess.Popen([str(launcher)], env=environment)
        report['pid'] = child.pid
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and child.poll() is None:
            if launch_report.exists() and dialog_for(child.pid):
                break
            time.sleep(.05)
        assert child.poll() is None, 'HARNESS: launcher exited before error dialog'
        error = json.loads(launch_report.read_text())
        report['launch'] = error
        assert 'MIGRATION_REQUIRED' in error.get('error', ''), 'HARNESS: wrong launcher failure'
        report['dialogHandles'] = dialog_for(child.pid)
        assert report['dialogHandles'], 'HARNESS: error dialog was not observed'
        engine.stop_owned(root)
        report['aliveAfterStop'] = child.poll() is None
        shutil.copyfile(args.launcher, root / 'D4Planner.next.exe')
        try:
            os.replace(root / 'D4Planner.next.exe', launcher)
        except OSError as error:
            report['replaceError'] = {'type': type(error).__name__, 'winerror': error.winerror}
        # Exit 0 from --stop is insufficient: the image must actually be gone.
        assert child.poll() is not None, 'PRODUCT: Setup stop returned while error dialog still holds EXE'
        assert 'replaceError' not in report, 'PRODUCT: launcher replacement failed after stop'
        assert inventory(legacy) == before
        report['status'] = 'PASS'
    except Exception as exc:
        report.update(status='FAIL', error=str(exc))
    finally:
        if child is not None:
            if child.poll() is None:
                # Only the process object created by this test is terminated.
                child.terminate()
            child.wait(timeout=10)
            report['exit'] = child.returncode
            report['ownedCleanup'] = child.poll() is not None
        report['after'] = inventory(legacy)
        with closing(sqlite3.connect((legacy / 'state/hud.sqlite3').as_uri() + '?mode=ro', uri=True)) as db, db:
            report['sqlite'] = {'integrity': db.execute('PRAGMA integrity_check').fetchone()[0],
                                'revision': db.execute('SELECT revision FROM equipment').fetchone()[0]}
        (args.sandbox / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
