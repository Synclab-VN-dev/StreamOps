"""Windows-native PKG acceptance against real production Setup artifacts.

Must run in an explicitly approved isolated interactive desktop. This driver
never operates game/OBS processes or installs a global runtime. Its fault mode
terminates only its own engine process after a durable journal checkpoint.
"""
from __future__ import annotations
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()


def run(command, **kwargs):
    completed = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=150, **kwargs)
    if completed.returncode:
        raise RuntimeError(f"exit={completed.returncode} command={command[0]} stderr={completed.stderr[-1000:]}")
    return completed


def load_engine(root):
    sys.path.insert(0, str(root / "maintenance"))
    import windows_install
    return windows_install


def owned_tree(pid):
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    class Entry(ctypes.Structure):
        _fields_ = [("dwSize",wintypes.DWORD),("cntUsage",wintypes.DWORD),("th32ProcessID",wintypes.DWORD),
                    ("th32DefaultHeapID",ctypes.c_size_t),("th32ModuleID",wintypes.DWORD),("cntThreads",wintypes.DWORD),
                    ("th32ParentProcessID",wintypes.DWORD),("pcPriClassBase",wintypes.LONG),
                    ("dwFlags",wintypes.DWORD),("szExeFile",wintypes.WCHAR*260)]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE,ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE,ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2,0)
    entry = Entry(); entry.dwSize = ctypes.sizeof(entry); rows = []
    try:
        more = kernel.Process32FirstW(snapshot,ctypes.byref(entry))
        while more:
            rows.append({"pid":entry.th32ProcessID,"parentPid":entry.th32ParentProcessID,"name":entry.szExeFile})
            more = kernel.Process32NextW(snapshot,ctypes.byref(entry))
    finally: kernel.CloseHandle(snapshot)
    ids = {pid}; selected = []
    while True:
        children = [row for row in rows if row["parentPid"] in ids and row["pid"] not in ids]
        if not children: break
        selected.extend(children); ids.update(row["pid"] for row in children)
    return selected


def alive(pid):
    kernel = ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x1000,False,pid)
    if not handle: return False
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle(handle); return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sandbox",type=Path,required=True)
    parser.add_argument("--setup-old",type=Path,required=True)
    parser.add_argument("--setup-new",type=Path,required=True)
    parser.add_argument("--package-new",type=Path,required=True)
    parser.add_argument("--package-sha",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--fault-install",action="store_true")
    args = parser.parse_args()
    sandbox = args.sandbox.resolve(); root = sandbox / "Ứng dụng D4Planner"; data = sandbox / "Dữ liệu D4Planner"
    if args.fault_install:
        engine = load_engine(root)
        engine.install(args.package_new,root,data,args.package_sha,
                       checkpoint=lambda phase: os._exit(88) if phase == "ACTIVATED" else None)
        return 1
    if sys.platform != "win32": raise RuntimeError("WINDOWS_REQUIRED")
    if args.output.exists(): raise RuntimeError("NEW_EVIDENCE_PATH_REQUIRED")
    sandbox.mkdir(parents=True,exist_ok=True)
    report = {"schemaVersion":"d4planner-setup-e2e/v1","startedAt":datetime.now(timezone.utc).isoformat(),
              "artifacts":{str(path.name):sha(path) for path in (args.setup_old,args.setup_new,args.package_new)},"cases":[]}
    def case(identifier, expected, action):
        started = time.monotonic()
        try:
            actual = action()
            result = {"id":identifier,"expected":expected,"actual":actual,"status":"PASS"}
        except Exception as error:
            result = {"id":identifier,"expected":expected,"actual":str(error),"status":"FAIL","classification":"PRODUCT_OR_HARNESS_FAILURE"}
        result["durationSeconds"] = round(time.monotonic()-started,3)
        report["cases"].append(result)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        return result["status"] == "PASS"
    def state(): return json.loads((root / "active.json").read_text(encoding="utf-8"))
    def setup(path):
        run([path,"/S",f"/DATADIR={data}",f"/D={root}"])
        return state()
    def initial():
        value = setup(args.setup_old)
        assert value["version"] == "1.0.0"
        assert (root / "D4Planner.exe").is_file() and (root / "Uninstall.exe").is_file()
        run([root / "D4Planner.exe","--installation-health"])
        (data / "targets").mkdir(parents=True,exist_ok=True); (data / "state").mkdir(exist_ok=True)
        (data / "targets/user.json").write_text("user-owned-test-target",encoding="utf-8")
        (data / "settings.json").write_text('{"userSetting":"preserve"}',encoding="utf-8")
        with sqlite3.connect(data / "state/user-data.sqlite") as db:
            db.execute("create table user_data(value text)"); db.execute("insert into user_data values('preserve')")
        return {"version":value["version"],"root":str(root),"data":str(data),"rootHealthExit":0}
    if not case("PKG-02","Real NSIS fresh install; root executable and uninstaller present",initial): return 1
    original = {str(path.relative_to(data)):sha(path) for path in data.rglob("*") if path.is_file()}
    def preserved():
        for relative,digest in original.items(): assert sha(data / relative) == digest,relative
    engine = load_engine(root)
    def negatives():
        current = engine.owned_payload(root,state()); node = current / "runtime/node/node.exe"
        backup = node.with_name("node.exe.test-backup"); node.rename(backup)
        try: assert subprocess.run([str(root / "D4Planner.exe"),"--installation-health"],timeout=30).returncode != 0
        finally: backup.rename(node)
        assert subprocess.run([str(root / "D4Planner.exe"),"--installation-health"],timeout=30).returncode == 0
        return {"missingRuntimeRejected":True,"restoredRuntimeHealth":True}
    case("NEG-INTEGRITY","Missing runtime fails closed",negatives)

    # FE executable is untouched; actual HWND helper is reused from production E2E.
    current = engine.owned_payload(root,state())
    sys.path.insert(0,str(current / "backend/site-packages")); sys.path.insert(0,str(current / "tools"))
    import production_e2e
    environment = dict(os.environ)
    environment["PATH"] = os.pathsep.join([str(Path(os.environ["SYSTEMROOT"]) / "System32"),str(Path(os.environ["SYSTEMROOT"]) / "System32/WindowsPowerShell/v1.0")])
    environment.update({"D4PLANNER_WS_PORT_MODE":"FIXED_APPROVED_UAT","D4PLANNER_APPROVED_UAT_PORT":"38150"})
    launcher = None; tree = []
    def launch():
        nonlocal launcher,tree
        launcher = subprocess.Popen([str(root / "D4Planner.exe")],cwd=sandbox,env=environment)
        deadline = time.monotonic()+22; window = None
        while time.monotonic()<deadline and launcher.poll() is None:
            tree = owned_tree(launcher.pid)
            for row in tree:
                if row["name"].lower() == "d4planner-fe.exe": window = production_e2e._native_window(row["pid"])
            if window and any(row["name"].lower()=="node.exe" for row in tree): break
            time.sleep(.15)
        assert window is not None,"Native HWND did not appear"
        assert any(row["name"].lower()=="node.exe" for row in tree),"Owned Node absent"
        assert any("chrome" in row["name"].lower() for row in tree),"Owned Chromium absent"
        run([root / "D4Planner.exe"],env=environment)
        assert len([row for row in owned_tree(launcher.pid) if row["name"].lower()=="d4planner-fe.exe"]) == 1
        production_e2e._capture_window(window,args.output.parent / "root-launcher-native.png")
        return {"window":window,"ownedTree":tree,"duplicateBackendPrevented":True,"screenshotSha256":sha(args.output.parent / "root-launcher-native.png")}
    try:
        native_ok = case("PKG-01","Root EXE owns one visible native FE, BE, Node and Chromium",launch)
        def upgrade():
            value = setup(args.setup_new)
            if launcher is not None: assert launcher.wait(timeout=20) == 0
            assert all(not alive(row["pid"]) for row in tree),"Owned orphan after graceful upgrade"
            assert value["version"] == "1.0.1"; preserved()
            return {"version":value["version"],"ownedTreeClean":True,"dataPreserved":True}
        case("PKG-06" if native_ok else "PKG-04","Real Setup upgrades while app running; owned tree exits and data preserved",upgrade)
    finally:
        if launcher is not None and launcher.poll() is None:
            subprocess.run([str(root / "D4Planner.exe"),"--stop"],timeout=25)
            launcher.wait(timeout=5)
    def reinstall():
        assert setup(args.setup_new)["version"] == "1.0.1"; preserved()
        previous = state()
        completed = subprocess.run([str(args.setup_old),"/S",f"/DATADIR={data}",f"/D={root}"],timeout=90)
        assert completed.returncode != 0
        assert state() == previous
        return {"sameVersionReinstall":True,"downgradeRejected":True,"dataPreserved":True}
    case("PKG-04","Upgrade, same-version reinstall and downgrade refusal",reinstall)
    def recovery():
        args_list = [sys.executable,__file__,"--sandbox",str(sandbox),"--setup-old",str(args.setup_old),
            "--setup-new",str(args.setup_new),"--package-new",str(args.package_new),"--package-sha",args.package_sha,
            "--output",str(args.output),"--fault-install"]
        assert subprocess.run(args_list,timeout=120).returncode == 88
        assert (root / "upgrade-journal.json").is_file()
        value = engine.recover(root)
        assert value["recovery"] == "RESTORED_PREVIOUS"
        run([root / "D4Planner.exe","--installation-health"]); preserved()
        return {"interruptedProcessExit":88,"journalRecovered":True,"dataPreserved":True}
    case("PKG-05","Interrupted real engine activation recovers verified previous payload",recovery)
    def clean():
        assert "node" not in environment["PATH"].lower() and "python" not in environment["PATH"].lower()
        run([root / "D4Planner.exe","--installation-health"],env=environment)
        return {"path":environment["PATH"],"privateRuntimeIntegrity":True,"nativeLaunchProven":native_ok,
                "networkDisabled":"NOT_ENFORCED"}
    case("PKG-07-PARTIAL","Private runtime verification with PATH excluding development toolchains",clean)
    def uninstall():
        # NSIS uninstaller self-copies unless _?= is provided. Waiting with the
        # exact path keeps completion observable; only the sandbox is owned.
        run([root / "Uninstall.exe","/S",f"_?={root}"])
        assert not (root / "D4Planner.exe").exists(); preserved()
        return {"dataPreserved":True,"rootLauncherRemoved":True}
    case("PKG-03","Real Uninstall.exe removes app and retains SQLite/Targets/Settings",uninstall)
    report["finishedAt"] = datetime.now(timezone.utc).isoformat()
    report["outcome"] = "PASS" if all(item["status"]=="PASS" for item in report["cases"]) else "FAIL"
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return 0 if report["outcome"]=="PASS" else 1


if __name__ == "__main__": raise SystemExit(main())
