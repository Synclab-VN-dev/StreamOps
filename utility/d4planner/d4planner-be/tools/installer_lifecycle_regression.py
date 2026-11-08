"""Windows-native installer engine/migration matrix, using a real launcher.

Health is a fixture callback: this tests transactional activation, actual Win32
locks/ACLs and the production migration engine, not the full packaged FE/Setup UI.
The separate dialog regression and packaged Setup acceptance cover those layers.
"""
from __future__ import annotations
import argparse
from contextlib import closing
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import threading
import time
import zipfile

import windows_install as engine
from installer_native_regression import inventory, dialog_for
from storage_native_smoke import secure_new_sandbox
from d4planner.runtime import migration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launcher', required=True, type=Path)
    parser.add_argument('--sandbox', required=True, type=Path)
    args = parser.parse_args()
    if os.name != 'nt': parser.error('Windows required')
    sandbox = args.sandbox.resolve()
    sandbox.mkdir(parents=True, exist_ok=False)
    secure_new_sandbox(sandbox)
    os.environ['LOCALAPPDATA'] = str(sandbox / 'local')
    for key in list(os.environ):
        if key.startswith(('D4PLANNER_', 'D4_RULEKIT_')): del os.environ[key]
    data = sandbox / 'local/StreamOps/D4Planner'
    legacy = sandbox / 'local/d4planner'
    root = sandbox / 'app'
    report = {'status': 'RUNNING', 'cases': [], 'limits': ['engine fixture health, not full Setup/FE acceptance']}
    def case(name, fn):
        result = fn()
        report['cases'].append({'id': name, 'status': 'PASS', 'result': result})
    def package(version):
        files = {'D4Planner.exe': args.launcher.read_bytes(), 'version.txt': version.encode()}
        manifest = {'schemaVersion': engine.delivery.MANIFEST_VERSION, 'applicationId': engine.APP_ID,
                    'version': version, 'hudSchemaCompatibility': {'minimum': 2, 'maximum': 2},
                    'files': [{'path': name, 'bytes': len(raw), 'sha256': engine.delivery.hashlib.sha256(raw).hexdigest()}
                              for name, raw in files.items()]}
        path = sandbox / (version + '.zip')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('release-manifest.json', json.dumps(manifest))
            for name, raw in files.items(): archive.writestr(name, raw)
        return path
    old, new = package('1.2.8'), package('1.2.9')
    def install(package, **kwargs):
        return engine.install(package, root, data, engine.delivery.sha256_file(package),
                              health_check=lambda path: None, **kwargs)
    def answer_confirmation(plan, button):
        """Exercise the production MessageBox, selecting its actual Yes/No button."""
        observed = []
        def answer():
            user = ctypes.WinDLL('user32', use_last_error=True)
            user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
            user.GetDlgItem.restype = wintypes.HWND
            user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                for hwnd in dialog_for(os.getpid()):
                    title = ctypes.create_unicode_buffer(256)
                    user.GetWindowTextW(hwnd, title, len(title))
                    if title.value == 'D4Planner Setup - Transfer legacy data':
                        control = user.GetDlgItem(hwnd, button)
                        if control:
                            observed.append({'hwnd': hwnd, 'button': button})
                            user.PostMessageW(control, 0xF5, 0, 0)  # BM_CLICK
                            return
                time.sleep(.05)
        worker = threading.Thread(target=answer, daemon=True)
        worker.start()
        decision = engine.confirm_migration(plan)
        worker.join(timeout=20)
        assert observed and decision == (button == 6), 'confirmation UI did not obey choice'
        report.setdefault('confirmationDialogs', []).extend(observed)
        return decision
    try:
        def fresh():
            result = install(old, migration_confirm=lambda plan: (_ for _ in ()).throw(AssertionError('fresh prompted')))
            assert result['storageMigration']['status'] == 'NOT_NEEDED'
        case('fresh-install', fresh)
        (legacy / 'state').mkdir(parents=True)
        with closing(sqlite3.connect(legacy / 'state/hud.sqlite3')) as db, db:
            db.execute("CREATE TABLE schema_meta(component TEXT,version INTEGER)")
            db.execute("INSERT INTO schema_meta VALUES('release1-hud',2)")
            db.execute('CREATE TABLE equipment(revision INTEGER)')
            db.execute('INSERT INTO equipment VALUES(42)')
        for name in ('targets', 'rulekit'):
            (legacy / name).mkdir()
            (legacy / name / 'preserve.bin').write_bytes(b'preserve')
        baseline = inventory(legacy)
        report['before'] = baseline
        def declined():
            previous = engine.read_state(root)
            try: install(new, migration_confirm=lambda plan: answer_confirmation(plan, 7))
            except engine.InstallError as error: assert 'MIGRATION_CANCELLED' in str(error)
            else: raise AssertionError('cancel did not stop install')
            assert engine.read_state(root) == previous and not data.exists()
        case('migration-cancel', declined)
        def busy():
            db = sqlite3.connect(legacy / 'state/hud.sqlite3')
            try:
                db.execute('BEGIN IMMEDIATE'); db.execute('UPDATE equipment SET revision=99')
                try: install(new, migration_confirm=lambda plan: True)
                except migration.StorageError as error: assert 'BLOCKED' in str(error) or 'BUSY' in str(error)
                else: raise AssertionError('busy database accepted')
            finally: db.rollback(); db.close()
            assert inventory(legacy) == baseline
        case('migration-db-busy', busy)
        def conflict():
            (data / 'targets').mkdir(parents=True)
            canary = data / 'targets/preserve.bin'; canary.write_bytes(b'newer')
            try:
                try: install(new, migration_confirm=lambda plan: True)
                except migration.StorageError as error: assert 'CONFLICT' in str(error)
                else: raise AssertionError('conflict accepted')
                assert canary.read_bytes() == b'newer'
            finally: canary.unlink()  # exact fixture created above
        case('migration-conflict', conflict)
        def migrate():
            result = install(new, migration_confirm=lambda plan: answer_confirmation(plan, 6))
            assert result['storageMigration']['status'] == 'VERIFIED'
            for name, sha in baseline.items(): assert inventory(data)[name] == sha
        case('confirmed-migration-upgrade', migrate)
        with closing(sqlite3.connect(data / 'state/hud.sqlite3')) as db, db:
            db.execute('UPDATE equipment SET revision=43')
        retained = inventory(data)
        def reinstall():
            result = install(new, migration_confirm=lambda plan: (_ for _ in ()).throw(AssertionError('reinstall prompted')))
            assert result['storageMigration']['status'] == 'NOT_NEEDED'
            assert inventory(data) == retained
        case('same-version-reinstall-new-data', reinstall)
        def locked():
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                          wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            kernel.CreateFileW.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.CreateFileW(str(root / 'D4Planner.exe'), 0x80000000, 1, None, 3, 0, None)
            assert handle != ctypes.c_void_p(-1).value
            previous = engine.read_state(root)
            try:
                try: install(new)
                except engine.InstallError as error:
                    assert 'LAUNCHER_FILE_LOCKED' in str(error), str(error)
                else: raise AssertionError('locked image replaced')
                assert engine.read_state(root) == previous and inventory(data) == retained
            finally: kernel.CloseHandle(handle)
            engine.recover(root)
        case('native-file-lock', locked)
        def acl():
            # Deny DELETE on this test's exact image, then restore its saved DACL.
            image = root / 'D4Planner.exe'
            saved = sandbox / 'image-acl.txt'
            subprocess.run(['icacls.exe', str(image), '/save', str(saved)], check=True, capture_output=True)
            sid = subprocess.check_output(['whoami.exe', '/user', '/fo', 'csv', '/nh'], text=True)
            import csv
            sid = next(csv.reader(sid.splitlines()))[1]
            previous = engine.read_state(root)
            try:
                subprocess.run(['icacls.exe', str(image), '/deny', '*'+sid+':(D)'], check=True, capture_output=True)
                try: install(new)
                except engine.InstallError as error: assert 'LAUNCHER_ACCESS_DENIED' in str(error)
                else: raise AssertionError('ACL-denied image replaced')
                assert engine.read_state(root) == previous and inventory(data) == retained
            finally:
                subprocess.run(['icacls.exe', str(root), '/restore', str(saved)], check=True, capture_output=True)
            engine.recover(root)
        case('native-acl-access-denied', acl)
        def interrupted():
            previous = engine.read_state(root)
            def interrupt(phase):
                if phase == 'ACTIVATED': raise SystemExit(137)
            try: install(new, checkpoint=interrupt)
            except SystemExit as error: assert error.code == 137
            else: raise AssertionError('interruption missing')
            assert (root / 'upgrade-journal.json').exists()
            child = subprocess.Popen([str(root / 'D4Planner.exe')])
            try:
                deadline = time.monotonic() + 20
                while not dialog_for(child.pid) and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(.05)
                assert child.poll() is None and dialog_for(child.pid), 'recovery dialog not observed'
                report['recoveryDialogPid'] = child.pid
                assert engine.recover(root)['recovery'] == 'RESTORED_PREVIOUS'
                assert child.poll() is not None, 'recovery left launcher running'
            finally:
                if child.poll() is None: child.terminate()
                child.wait(timeout=10)
                report['recoveryOwnedCleanup'] = child.poll() is not None
            assert engine.read_state(root) == previous and inventory(data) == retained
        case('interrupted-recovery', interrupted)
        def rollback():
            engine.rollback(root)
            assert inventory(data) == retained
            manifest = json.loads((data / 'private/storage-origin.json').read_text())
            try: migration.rollback(manifest)
            except migration.StorageError as error: assert 'post-switch writes' in str(error)
            else: raise AssertionError('migration rollback destroyed newer database')
            assert inventory(data) == retained
        case('rollback-preserves-newer-data', rollback)
        report['after'] = {name: inventory(legacy)[name] for name in baseline}
        assert report['before'] == report['after']
        with closing(sqlite3.connect((data / 'state/hud.sqlite3').as_uri()+'?mode=ro', uri=True)) as db, db:
            report['sqlite'] = {'integrity': db.execute('PRAGMA integrity_check').fetchone()[0],
                                'revision': db.execute('SELECT revision FROM equipment').fetchone()[0]}
        report['status'] = 'PASS'
    except Exception as error:
        import traceback
        report.update(status='FAIL', error=repr(error), traceback=traceback.format_exc())
    finally:
        (sandbox / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
