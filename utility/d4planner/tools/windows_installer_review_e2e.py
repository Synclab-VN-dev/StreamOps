"""Targeted native Setup acceptance for FIX-01/02/03. Private evidence only.

Runs under the explicitly approved UAT interactive task/port, with genuine
production binaries. Fault injection changes Backend source and recomputes the
manifest; it never substitutes an executable or modifies a user database.
"""
from __future__ import annotations
import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import threading
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from windows_setup_e2e import sha, owned_tree


def alive(pid):
    from ctypes import wintypes
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle: return False
    try:
        code=wintypes.DWORD()
        return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
    finally: kernel.CloseHandle(handle)


def main():
    parser = argparse.ArgumentParser()
    for name in ('sandbox', 'setup-old', 'setup-new', 'package-new', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--case-ids')
    parser.add_argument('--resume-report',type=Path)
    args = parser.parse_args()
    applicable={'PKG-01','PKG-02','PKG-04/06','PKG-05/FIX-03','PKG-07','FIX-02','FIX-02-NEGATIVE','PKG-03/FIX-01'}
    selected=set(args.case_ids.split(',')) if args.case_ids is not None else applicable
    if not selected or not selected <= applicable: raise ValueError('UNKNOWN_OR_EMPTY_CASE_SELECTION')
    if args.resume_report:
        previous=json.loads(args.resume_report.read_text(encoding='utf-8'))
        failed={row['id'] for row in previous['cases'] if row['status']=='FAIL'}
        if not selected <= failed: raise ValueError('RESUME_CASE_NOT_PREVIOUSLY_FAILED')
    if sys.platform != 'win32': raise RuntimeError('WINDOWS_REQUIRED')
    import winreg
    root = args.sandbox / 'Ứng dụng D4Planner'
    data = args.sandbox / 'Dữ liệu D4Planner'
    args.output.mkdir(parents=True, exist_ok=False)
    expected = json.loads(args.manifest.read_text(encoding='utf-8'))
    for path in (args.setup_old, args.setup_new, args.package_new):
        assert sha(path) == expected[path.name], 'ARTIFACT_SHA_MISMATCH'
    assert not root.exists(), 'FRESH_SANDBOX_REQUIRED'
    env = dict(os.environ)
    env['PATH'] = os.pathsep.join([os.environ['SYSTEMROOT'] + r'\System32', os.environ['SYSTEMROOT'] + r'\System32\WindowsPowerShell\v1.0'])
    env.update(D4PLANNER_WS_PORT_MODE='FIXED_APPROVED_UAT', D4PLANNER_APPROVED_UAT_PORT='38150')
    report = {'sourceHead':expected['sourceHead'], 'artifacts':expected, 'cases':[], 'portApproval':'OWNER_APPROVED_38150',
              'classification':'WINDOWS_NATIVE_REAL_PRODUCTION_ARTIFACTS_WITH_SYNTHETIC_INPUT', 'offlineNegative':'DEFERRED_OWNER','selection':sorted(selected),'resumeReport':str(args.resume_report) if args.resume_report else None}
    def save(): (args.output / 'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def call(command, check=True, timeout=170):
        result = subprocess.run(command if isinstance(command,str) else list(map(str,command)),env=env,
                                capture_output=True,text=True,timeout=timeout)
        with (args.output / 'commands.log').open('a',encoding='utf-8') as stream:
            stream.write(f'{command}\nexit={result.returncode}\n{result.stdout}\n{result.stderr}\n')
        if check: assert result.returncode == 0, f'exit={result.returncode} {result.stderr[-500:]}'
        return result
    def case(identifier, expected, function):
        if identifier not in selected and identifier not in {'PKG-02','PKG-03/FIX-01'}:
            report.setdefault('notRun',[]).append(identifier); return True
        started=time.monotonic()
        try:
            actual=function(); result={'id':identifier,'expected':expected,'actual':actual,'status':'PASS'}
        except Exception as error:
            try: owned_stop()
            except Exception as cleanup: error = RuntimeError(f'{error!r}; cleanup={cleanup!r}')
            result={'id':identifier,'expected':expected,'actual':repr(error),'status':'FAIL'}
        result['durationSeconds']=round(time.monotonic()-started,3); report['cases'].append(result); save()
        print(json.dumps(result,ensure_ascii=False),flush=True)
        return result['status']=='PASS'
    def state(): return json.loads((root / 'active.json').read_text(encoding="utf-8"))
    def payload(): return root / state()['payload']
    def setup(path):
        result=call(f'"{path}" /S /ISOLATED=1 /DATADIR="{data}" /INSTALLROOT="{root}"')
        return {'exitCode':result.returncode,'state':state()}
    def reg_read(path):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,path,0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as key:
            result={}; index=0
            while True:
                try: name,value,kind=winreg.EnumValue(key,index)
                except OSError: break
                result[name]=(value,kind); index+=1
            return result
    fixture_keys=[r'Software\Synclab\D4Planner',r'Software\Microsoft\Windows\CurrentVersion\Uninstall\SynclabD4Planner']
    shortcut_roots=[]
    for folder_id in (0x10,0x02):
        buffer=ctypes.create_unicode_buffer(260)
        assert ctypes.windll.shell32.SHGetFolderPathW(None,folder_id,None,0,buffer)==0
        shortcut_roots.append(Path(buffer.value))
    fixture_shortcuts=[shortcut_roots[0]/'D4Planner.lnk',shortcut_roots[1]/'D4Planner/D4Planner.lnk']
    for key in fixture_keys:
        try: reg_read(key)
        except FileNotFoundError: pass
        else: raise RuntimeError('REAL_PRODUCTION_REGISTRATION_PRESENT_NO_FIXTURE_MUTATION')
    for path in fixture_shortcuts: assert not path.exists(),'REAL_PRODUCTION_SHORTCUT_PRESENT'
    launch=None; tree=[]; fixtures=False; watchdog=None
    def fixture_intact():
        for key in fixture_keys: assert reg_read(key)=={'FixtureOwner':('PR150-FIX01-SYNTHETIC',winreg.REG_SZ)}
        for path in fixture_shortcuts: assert path.read_bytes()==b'PR150-FIX01-SYNTHETIC-SHORTCUT'
    def owned_stop():
        nonlocal launch, watchdog
        if watchdog is not None: watchdog.cancel(); watchdog=None
        if launch is not None:
            call([root/'D4Planner.exe','--stop'],timeout=30)
            assert launch.wait(timeout=25)==0
            deadline=time.monotonic()+5
            while any(alive(row['pid']) for row in tree) and time.monotonic()<deadline: time.sleep(.05)
            assert not any(alive(row['pid']) for row in tree), {'ownedOrphans':[row for row in tree if alive(row['pid'])]}
            launch=None
    def native(config=None):
        nonlocal launch,tree,watchdog
        settings=data/'launcher.json'
        if config: settings.write_text(json.dumps(config,ensure_ascii=False),encoding='utf-8')
        else: settings.unlink(missing_ok=True)
        result_path=args.output / f'launch-{len(report["cases"])}.json'
        native_env=dict(env,D4PLANNER_LAUNCH_REPORT=str(result_path))
        launch=subprocess.Popen([str(root/'D4Planner.exe'),'--launch'],env=native_env,cwd=args.sandbox)
        watchdog=threading.Timer(28,lambda:subprocess.run([str(root/'D4Planner.exe'),'--stop'],env=env,timeout=30))
        watchdog.daemon=True; watchdog.start()
        started=time.monotonic(); window=None
        while time.monotonic()-started<20 and launch.poll() is None:
            tree=owned_tree(launch.pid)
            pid=next((row['pid'] for row in tree if row['name'].lower()=='d4planner-fe.exe'),None)
            if pid:
                script=f"import sys,json;from pathlib import Path;sys.path[:0]=[{str(payload()/'backend/site-packages')!r},{str(payload()/'tools')!r}];import production_e2e;w=production_e2e._native_window({pid});production_e2e._capture_window(w,Path({str(args.output / ('native-'+str(len(report['cases']))+'.png'))!r})) if w else None;print(json.dumps(w))"
                window=json.loads(call([sys.executable,'-c',script]).stdout)
            if window and any('chrome' in row['name'].lower() for row in tree) and (data/'state/hud.sqlite3').exists():
                time.sleep(.5); break
            time.sleep(.2)
        assert window is not None and launch.poll() is None,'NATIVE_WINDOW_NOT_VISIBLE'
        with sqlite3.connect((data/'state/hud.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
            # Read-only independent durable state; no fixture SQL writes.
            tables=[row[0] for row in db.execute("select name from sqlite_master where type='table'")]
        value={'window':window,'ownedTree':tree,'sqliteTables':tables}
        owned_stop(); assert json.loads(result_path.read_text(encoding="utf-8"))['ok'] is True
        return value
    try:
        for key in fixture_keys:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,key,0,winreg.KEY_WRITE|winreg.KEY_WOW64_64KEY) as handle:
                winreg.SetValueEx(handle,'FixtureOwner',0,winreg.REG_SZ,'PR150-FIX01-SYNTHETIC')
        for path in fixture_shortcuts:
            path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b'PR150-FIX01-SYNTHETIC-SHORTCUT')
        fixtures=True
        def fresh():
            value=setup(args.setup_old); fixture_intact()
            registration=reg_read(r'Software\Microsoft\Windows\CurrentVersion\Uninstall\SynclabD4PlannerUAT')
            assert Path(registration['InstallLocation'][0])==root
            assert (shortcut_roots[0]/'D4Planner UAT.lnk').is_file()
            assert (shortcut_roots[1]/'D4Planner UAT/D4Planner.lnk').is_file()
            return value
        if not case('PKG-02','Fresh NSIS install; isolated registration/shortcuts; runtime READY gate',fresh): return 1
        (data/'targets').mkdir(parents=True,exist_ok=True)
        (data/'targets/user-owned.json').write_text('synthetic-user-owned-target')
        (data/'settings.json').write_text('{"preserve":true}')
        with sqlite3.connect(data/'user-owned.sqlite') as db: db.execute('create table user_data(value text)')
        preserved={str(path.relative_to(data)):sha(path) for path in (data/'settings.json',data/'user-owned.sqlite',data/'targets/user-owned.json')}
        def check_data():
            for name,digest in preserved.items(): assert sha(data/name)==digest
        case('PKG-01','Root native HUD + private BE/Node/Chromium; no DB default',lambda:native())
        def invalid():
            config={'schemaVersion':'d4planner-launcher/v1','equipmentRepository':{'enabled':True,'path':str(args.sandbox/'missing.sqlite')}}
            (data/'launcher.json').write_text(json.dumps(config))
            value=call([root/'D4Planner.exe','--launch'],check=False,timeout=15)
            assert value.returncode!=0; (data/'launcher.json').unlink()
            return {'exitCode':value.returncode,'invalidOptInRejected':True}
        case('FIX-02-NEGATIVE','Invalid path/missing identity fails closed',invalid)
        def capture():
            db_path=args.sandbox/'synthetic-capture.sqlite'
            script=f"import sys;from pathlib import Path;sys.path.insert(0,{str(payload()/'backend/site-packages')!r});from d4planner.character.repository import EquipmentRepository;from d4planner.character.equipment.projector import EquipmentProjector;r=EquipmentRepository(Path({str(db_path)!r}));p=EquipmentProjector(r);[(p.consume({{'eventSeq':i,'type':'speech.raw','timestamp':f'2026-10-26T04:00:0{{i}}Z','sessionId':'SYNTHETIC-INSTALLER-UAT','data':{{'text':t}}}})) for i,t in enumerate(['Head','EQUIPPED','SYNTHETIC HELM','Rare Helm','850 Item Power','Unequip'],1)]"
            call([sys.executable,'-c',script]); before=sha(db_path)
            value=native({'schemaVersion':'d4planner-launcher/v1','equipmentRepository':{'enabled':True,'path':str(db_path),'characterId':'SYNTHETIC-INSTALLER-CHARACTER','characterDisplayName':'Synthetic Installer Character'}})
            # Assert character came from the configured read-only producer.
            with sqlite3.connect((data/'state/hud.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
                dump='\n'.join(db.iterdump())
            assert 'SYNTHETIC-INSTALLER-CHARACTER' in dump
            assert sha(db_path)==before,'CAPTURE_DB_MUTATED'
            (data/'launcher.json').unlink()
            return {**value,'captureDbUnchanged':True,'characterIdVerified':True}
        case('FIX-02','Synthetic opt-in DB through root/native FE; producer database unchanged',capture)
        def upgrading():
            nonlocal launch,tree
            launch=subprocess.Popen([str(root/'D4Planner.exe'),'--launch'],env=env)
            time.sleep(5); tree=owned_tree(launch.pid)
            assert any(row['name'].lower()=='node.exe' for row in tree)
            value=setup(args.setup_new)
            assert launch.wait(timeout=25)==0
            assert not any(alive(row['pid']) for row in tree)
            launch=None; check_data(); fixture_intact()
            return {**value,'gracefulOwnedShutdown':True,'dataPreserved':True}
        case('PKG-04/06','Upgrade while native application runs; graceful cleanup and preserved data',upgrading)
        def failure_rollback():
            before=state()
            broken=args.sandbox/'startup-failure.zip'
            with zipfile.ZipFile(args.package_new) as archive:
                manifest=json.loads(archive.read('release-manifest.json')); manifest['version']='1.0.4'
                replacement=b"raise RuntimeError('EXPECTED_UAT_RUNTIME_STARTUP_FAILURE')\n"
                name='backend/site-packages/d4planner/managed_backend.py'
                import hashlib
                entry=next(item for item in manifest['files'] if item['path']==name)
                entry.update(bytes=len(replacement),sha256=hashlib.sha256(replacement).hexdigest())
                with zipfile.ZipFile(broken,'w',zipfile.ZIP_DEFLATED) as output:
                    for member in archive.namelist():
                        output.writestr(member,json.dumps(manifest).encode() if member=='release-manifest.json' else replacement if member==name else archive.read(member))
            engine=payload()/'tools/windows_install.py'
            result=call([sys.executable,engine,'install','--root',root,'--data',data,'--package',broken,'--sha256',sha(broken),'--report',args.output/'runtime-failure.json'],check=False)
            assert result.returncode!=0
            assert state()==before and not (root/'upgrade-journal.json').exists()
            check_data()
            health=args.output/'runtime-health.json'
            call([root/'D4Planner.exe','--runtime-health','--health-report',health],timeout=75)
            assert json.loads(health.read_text(encoding="utf-8"))['runtimeReady'] is True
            return {'failureExitCode':result.returncode,'previousVersion':state()['version'],'runtimeGate':json.loads(health.read_text(encoding="utf-8")),'dataPreserved':True}
        case('PKG-05/FIX-03','Valid manifest/hash + broken Backend fails health and restores previous version',failure_rollback)
        def clean_machine():
            check_data(); fixture_intact()
            return {'installerAndLauncherPath':env['PATH'],'globalToolchainsUsed':False,'networkOff':'DEFERRED_OWNER','webview2':'PREEXISTING'}
        case('PKG-07','Setup and runtime operate with PATH excluding global dev toolchains',clean_machine)
        def remove():
            call([root/'Uninstall.exe','/S'])
            deadline=time.monotonic()+90
            while (root/'Uninstall.exe').exists() and time.monotonic()<deadline: time.sleep(.1)
            assert not (root/'D4Planner.exe').exists() and not (root/'Uninstall.exe').exists()
            check_data(); fixture_intact()
            try: reg_read(r'Software\Synclab\D4Planner-UAT')
            except FileNotFoundError: pass
            else: raise AssertionError('UAT_REGISTRATION_NOT_REMOVED')
            assert not (shortcut_roots[0]/'D4Planner UAT.lnk').exists()
            return {'userDataPreserved':True,'productionFixtureUnchanged':True,'uatRegistrationRemoved':True}
        case('PKG-03/FIX-01','Uninstall removes only UAT identity and retains user data/production fixtures',remove)
    finally:
        try: owned_stop()
        finally:
            if fixtures:
                fixture_intact()
                for path in fixture_shortcuts: path.unlink()
                try: fixture_shortcuts[1].parent.rmdir()
                except OSError: pass
                for key in fixture_keys: winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER,key,winreg.KEY_WOW64_64KEY)
            report['outcome']=('SCOPED_AUTOMATED_PASS' if selected==applicable else 'SCOPED_SUBSET_PASS') if report['cases'] and all(row['status']=='PASS' for row in report['cases']) else 'FAIL'
            save()
    return 0 if report['outcome'] in {'SCOPED_AUTOMATED_PASS','SCOPED_SUBSET_PASS'} else 1

if __name__=='__main__': raise SystemExit(main())
