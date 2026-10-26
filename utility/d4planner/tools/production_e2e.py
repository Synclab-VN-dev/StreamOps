"""Real-process Release 1 E2E scenarios for an installed production package."""
from __future__ import annotations

import argparse
import asyncio
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
import traceback
import uuid

from websockets.asyncio.client import connect
sys.path.insert(0, str(Path(__file__).resolve().parent))
import release1_delivery as delivery
from d4planner.rulekit import RuleKitRuntimeService

ORIGIN = "tauri://localhost"
PROTOCOL = "d4planner-ws/v1"


class E2EFailure(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wait_for(predicate, timeout: float, description: str):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.1)
    raise E2EFailure(f"timed out waiting for {description}")


def _native_window(pid: int) -> dict | None:
    if sys.platform != "win32":
        raise E2EFailure("native HUD evidence requires Windows")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    found: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(int(hwnd))
        return True
    callback = callback_type(visit)
    user32.EnumWindows(callback, 0)
    if not found:
        return None
    hwnd = found[0]
    rectangle = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rectangle)):
        raise E2EFailure("GetWindowRect failed for owned HUD window")
    length = user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, title, len(title))
    session = wintypes.DWORD()
    ctypes.WinDLL("kernel32", use_last_error=True).ProcessIdToSessionId(pid, ctypes.byref(session))
    return {
        "hwnd": hwnd, "pid": pid, "sessionId": int(session.value), "title": title.value,
        "visible": True,
        "bounds": {"left": rectangle.left, "top": rectangle.top,
                   "width": rectangle.right - rectangle.left,
                   "height": rectangle.bottom - rectangle.top},
    }


def _capture_window(window: dict, destination: Path) -> None:
    bounds = window["bounds"]
    if bounds["width"] <= 0 or bounds["height"] <= 0:
        raise E2EFailure("native HUD has empty visible bounds")
    destination.parent.mkdir(parents=True, exist_ok=True)
    escaped = str(destination).replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Drawing;"
        f"$b=New-Object Drawing.Bitmap({bounds['width']},{bounds['height']});"
        "$g=[Drawing.Graphics]::FromImage($b);try{"
        f"$g.CopyFromScreen({bounds['left']},{bounds['top']},0,0,$b.Size);"
        f"$b.Save('{escaped}',[Drawing.Imaging.ImageFormat]::Png)"
        "}finally{$g.Dispose();$b.Dispose()}"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if completed.returncode != 0 or not destination.is_file() or destination.stat().st_size < 100:
        raise E2EFailure(f"native screenshot capture failed: {completed.stderr[-500:]}")


def _visual_diff(before: Path, after: Path, destination: Path) -> int:
    paths = [str(item).replace("'", "''") for item in (before, after, destination)]
    script = (
        "Add-Type -AssemblyName System.Drawing;"
        f"$a=[Drawing.Bitmap]::FromFile('{paths[0]}');$b=[Drawing.Bitmap]::FromFile('{paths[1]}');"
        "if($a.Width-ne$b.Width-or$a.Height-ne$b.Height){throw 'image dimensions differ'};"
        "$d=New-Object Drawing.Bitmap($a.Width,$a.Height);$n=0;try{"
        "for($y=0;$y-lt$a.Height;$y++){for($x=0;$x-lt$a.Width;$x++){"
        "$ca=$a.GetPixel($x,$y);$cb=$b.GetPixel($x,$y);"
        "if($ca.ToArgb()-ne$cb.ToArgb()){$d.SetPixel($x,$y,[Drawing.Color]::Magenta);$n++}"
        "else{$d.SetPixel($x,$y,[Drawing.Color]::FromArgb(40,$ca))}}};"
        f"$d.Save('{paths[2]}',[Drawing.Imaging.ImageFormat]::Png);Write-Output $n"
        "}finally{$a.Dispose();$b.Dispose();$d.Dispose()}"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=90, check=False,
    )
    if completed.returncode != 0 or not destination.is_file():
        raise E2EFailure(f"native visual comparison failed: {completed.stderr[-500:]}")
    try:
        return int(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise E2EFailure("native visual comparison returned no changed-pixel count") from exc


def _sqlite_evidence(database: Path, private_copy: Path, state_json: Path) -> dict:
    if not database.is_file():
        raise E2EFailure("HUD SQLite database is missing")
    private_copy.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{database.as_posix()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source, sqlite3.connect(private_copy) as target:
        source.backup(target)
    with sqlite3.connect(f"file:{private_copy.as_posix()}?mode=ro", uri=True) as db:
        row = db.execute("SELECT hud_revision,payload_json FROM hud_current WHERE singleton=1").fetchone()
        if row is None:
            raise E2EFailure("HUD SQLite current state is empty")
        payload = json.loads(row[1])
        committed = db.execute(
            "SELECT committed_at,published FROM hud_snapshot WHERE hud_revision=?", (row[0],)
        ).fetchone()
    value = {"hudRevision": row[0], "payload": payload,
             "committedAt": committed[0], "published": bool(committed[1]),
             "backupSha256": _sha(private_copy)}
    state_json.parent.mkdir(parents=True, exist_ok=True)
    state_json.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return value


def _assert_ui_matches_db(ui: dict, db: dict) -> None:
    payload = db["payload"]
    expected = {
        "hudRevision": payload["hudRevision"],
        "characterId": payload["context"]["character"]["characterId"],
        "currentRevision": payload["context"]["character"]["currentRevision"],
        "targetId": payload["context"]["target"]["targetId"],
        "targetSha256": payload["context"]["target"]["contentSha256"],
        "selectionRevision": payload["context"]["target"]["selectionRevision"],
        "scoreStatus": payload["score"]["status"], "score": payload["score"]["value"],
        "failIssueCount": payload["score"]["failIssueCount"],
        "warnCount": payload["score"]["warnCount"],
        "itemsPassing": payload["score"]["itemsPassing"],
        "itemsTargeted": payload["score"]["itemsTargeted"],
    }
    actual = {key: ui.get(key) for key in expected}
    if actual != expected:
        raise E2EFailure(f"visible HUD render does not match durable DB: expected={expected!r} actual={actual!r}")


async def _select_target(endpoint: dict, credential: str, instance: str, generation: int,
                         target_id: str) -> dict:
    uri = f"ws://{endpoint['host']}:{endpoint['port']}"
    async with connect(uri, origin=ORIGIN, ping_interval=None) as ws:
        await ws.send(json.dumps(_msg("hud-e2e-hello", "hello", generation,
                                      credential=credential, origin=ORIGIN,
                                      lastSeen={"hudRevision": None})))
        accepted = json.loads(await ws.recv())
        if accepted.get("type") != "hello.accepted" or accepted.get("runtimeInstanceId") != instance:
            raise E2EFailure("HUD evidence socket authentication failed")
        await ws.send(json.dumps(_msg("hud-e2e-list", "target.list.request", generation)))
        listing = await _recv_type(ws, "target.list.result")
        target = next((item for item in listing["targets"] if item["targetId"] == target_id), None)
        if target is None or target.get("validation") != "VALID":
            raise E2EFailure("HUD evidence Target B is not valid")
        await ws.send(json.dumps(_msg("hud-e2e-select", "target.select.request", generation,
            targetId=target_id, expectedSha256=target["contentSha256"],
            expectedListRevision=listing["listRevision"])))
        update = None
        selected = None
        for _ in range(6):
            message = json.loads(await asyncio.wait_for(ws.recv(), 5))
            if message.get("type") == "target.select.result": selected = message
            if message.get("type") == "hud.update": update = message
            if selected and update: break
        if selected is None or selected.get("status") != "ACTIVATED" or update is None:
            raise E2EFailure("HUD evidence Target B activation/update was incomplete")
        return update["hud"]


def _prepare(install: Path, data: Path) -> tuple[Path, Path, str]:
    target_source = install / "examples/target.synthetic.json"
    evidence = install / "examples/equipment.recorded.synthetic.json"
    if not target_source.is_file() or not evidence.is_file():
        raise E2EFailure("packaged E2E inputs are missing")
    targets = data / "targets"; state = data / "state"
    targets.mkdir(parents=True, exist_ok=True); state.mkdir(parents=True, exist_ok=True)
    target = targets / "target-a.json"
    shutil.copyfile(target_source, target)
    document = json.loads(target.read_text(encoding="utf-8"))
    digest = _sha(target)
    selection = {
        "targetId": document["targetId"], "contentSha256": digest,
        "selectionRevision": 1,
        "policyVersion": document["assessmentPolicy"]["version"] + "+" +
            document["assessmentPolicy"]["weightProfile"]["profileId"],
    }
    (state / "selected-target.json").write_text(
        json.dumps(selection, separators=(",", ":"), sort_keys=True), encoding="utf-8"
    )
    return targets, evidence, digest


def _runtime_env(install: Path, bootstrap: Path, evidence: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update({
        "D4PLANNER_BOOTSTRAP_FILE": str(bootstrap),
        "PYTHONPATH": str(install / "backend/site-packages"),
        "D4PLANNER_RULEKIT_EXECUTABLE": str(install / "runtime/node/node.exe"),
        "D4PLANNER_RULEKIT_WORKER": str(install / "utility/d4planner/rulekit-worker/worker.js"),
        "D4PLANNER_RULEKIT_WORKING_DIR": str(install / "utility/d4planner/rulekit-worker"),
        "D4_RULEKIT_PROFILE_JSON": str(install / "config/maxroll-profile.json"),
        "D4_RULEKIT_SNAPSHOT_ROOT": str(install / "runtime/snapshots"),
        "D4_RULEKIT_CHROMIUM_EXECUTABLE": str(install / "runtime/chromium/chrome-win64/chrome.exe"),
        "D4PLANNER_EQUIPMENT_EVIDENCE_FILE": str(evidence),
        "D4PLANNER_REPOSITORY_ROOT": str(install),
    })
    return env


def _msg(message_id: str, kind: str, generation: int, **extra) -> dict:
    return {"protocolVersion": PROTOCOL, "messageId": message_id, "type": kind,
            "correlationId": None, "backendGeneration": generation, **extra}


def _windows_descendants(pid: int) -> list[dict]:
    if sys.platform != "win32":
        return []
    script = (
        "$p=Get-CimInstance Win32_Process|Select-Object ProcessId,ParentProcessId,Name;"
        f"$ids=@({pid});$out=@();do{{$n=@($p|?{{$ids -contains $_.ParentProcessId -and "
        "$out.ProcessId -notcontains $_.ProcessId});$out+=$n;$ids=@($n.ProcessId)}while($n.Count);"
        "$out|ConvertTo-Json -Compress"
    )
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, timeout=15, check=False)
    if result.returncode != 0:
        raise E2EFailure(
            f"cannot inspect owned Windows process tree exit={result.returncode}: {result.stderr[-500:]}"
        )
    value = json.loads(result.stdout.strip() or "[]")
    return value if isinstance(value, list) else [value]


async def _recv_type(ws, expected: str, count: int = 4) -> dict:
    for _ in range(count):
        message = json.loads(await asyncio.wait_for(ws.recv(), 5))
        if message.get("type") == expected:
            return message
    raise E2EFailure(f"WebSocket did not produce {expected}")


async def _socket_flow(endpoint: dict, credential: str, instance: str, generation: int,
                       targets: Path, target_a_hash: str) -> dict:
    uri = f"ws://{endpoint['host']}:{endpoint['port']}"
    async def open_socket(last_revision=None):
        ws = await connect(uri, origin=ORIGIN, ping_interval=None)
        await ws.send(json.dumps(_msg("hello", "hello", generation, credential=credential,
                                      origin=ORIGIN, lastSeen={"hudRevision": last_revision})))
        accepted = json.loads(await ws.recv())
        if accepted.get("type") != "hello.accepted" or accepted.get("runtimeInstanceId") != instance:
            raise E2EFailure("authenticated hello identity mismatch")
        return ws

    ws = await open_socket()
    try:
        await ws.send(json.dumps(_msg("snap-a", "hud.snapshot.request", generation,
            requestContext={"mode":"DISCOVER_ACTIVE_CONTEXT","reason":"INITIAL_CONNECTION",
                            "attempt":1,"runtimeInstanceId":instance,"minimumHudRevision":0})))
        snap_a = await _recv_type(ws, "hud.snapshot")
        hud_a = snap_a["hud"]
        if (hud_a["context"]["state"], hud_a["score"]["value"],
            hud_a["context"]["target"]["contentSha256"]) != ("BOUND", 100.0, target_a_hash):
            raise E2EFailure("initial durable assessment does not match independent expected values")
        await ws.send(json.dumps(_msg("list", "target.list.request", generation)))
        listing = await _recv_type(ws, "target.list.result")

        source = json.loads((targets / "target-a.json").read_text(encoding="utf-8"))
        source["targetId"] = "synthetic-target-b"
        source["displayName"] = "Synthetic Target B"
        target_b_path = targets / "target-b.json"
        target_b_path.write_text(json.dumps(source, separators=(",", ":")), encoding="utf-8")
        await ws.send(json.dumps(_msg("list-b", "target.list.request", generation)))
        listing_b = await _recv_type(ws, "target.list.result")
        target_b = next(item for item in listing_b["targets"] if item["targetId"] == "synthetic-target-b")
        await ws.send(json.dumps(_msg("select-b", "target.select.request", generation,
            targetId=target_b["targetId"], expectedSha256=target_b["contentSha256"],
            expectedListRevision=listing_b["listRevision"])))
        received = {}
        for _ in range(4):
            message = json.loads(await asyncio.wait_for(ws.recv(), 5))
            if message.get("type") in {"target.select.result", "hud.update"}:
                received[message["type"]] = message
            if len(received) == 2:
                break
        selected = received.get("target.select.result")
        update = received.get("hud.update")
        if selected is None or update is None:
            raise E2EFailure("Target activation result/update pair was incomplete")
        hud_b = update["hud"]
        if selected.get("status") != "ACTIVATED" or hud_b["context"]["target"]["targetId"] != "synthetic-target-b":
            raise E2EFailure("Target A to B activation did not update authoritative binding")
        if hud_b["context"]["binding"]["targetId"] != "synthetic-target-b":
            raise E2EFailure("old Target assessment was relabelled")
        revision = hud_b["hudRevision"]
    finally:
        await ws.close()

    ws = await open_socket(revision)
    try:
        await ws.send(json.dumps(_msg("resync", "hud.snapshot.request", generation,
            requestContext={"mode":"RESYNC_KNOWN_CONTEXT","runtimeInstanceId":instance,
                            "minimumHudRevision":revision, "expectedContext":{
                                "state":"BOUND",
                                "characterId":hud_b["context"]["character"]["characterId"],
                                "targetId":"synthetic-target-b",
                                "selectionRevision":hud_b["context"]["target"]["selectionRevision"],
                            }})))
        resync = await _recv_type(ws, "hud.snapshot")
        if resync["hud"]["hudRevision"] < revision or resync["hud"]["context"]["target"]["targetId"] != "synthetic-target-b":
            raise E2EFailure("reconnect resync rolled back the HUD")
    finally:
        await ws.close()
    return {"initialRevision": hud_a["hudRevision"], "finalRevision": revision,
            "score": hud_a["score"], "targetCountBeforeSwitch": len(listing["targets"]),
            "finalTargetId": "synthetic-target-b"}


def run_backend(args: argparse.Namespace) -> dict:
    install = args.install_root.resolve(); data = args.data_root.resolve()
    targets, evidence, target_hash = _prepare(install, data)
    owner, child, generation = str(uuid.uuid4()), str(uuid.uuid4()), 1
    credential = secrets.token_hex(32)
    bootstrap = data / "private-bootstrap.json"
    bootstrap.write_text(json.dumps({
        "protocol":"d4planner-managed/v1", "contractVersion":"d4planner-r1-contract/1.0.0-candidate.5",
        "ownerInstanceId":owner, "childInstanceId":child, "generation":generation,
        "dataDir":str(data / "state"), "targetFolder":str(targets),
        "wsEndpoint":{"host":"127.0.0.1","port":0}, "credential":credential,
    }), encoding="utf-8")
    python = install / "runtime/python/python.exe"
    started = time.perf_counter()
    process = subprocess.Popen([str(python), "-m", "d4planner.managed_backend"], cwd=install,
        env=_runtime_env(install, bootstrap, evidence), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert process.stdout is not None and process.stdin is not None
    try:
        ready_line = process.stdout.readline()
        if not ready_line:
            raise E2EFailure("Backend exited before READY: " + process.stderr.read())
        ready = json.loads(ready_line)
        if ready.get("event") != "READY" or ready.get("pid") != process.pid:
            raise E2EFailure("managed READY ownership mismatch")
        health = ready.get("health", {})
        for name in ("ruleKitWorker", "targetRepository", "durableState", "wsTransport"):
            if health.get(name) != "READY":
                raise E2EFailure(f"required service is not READY: {name}")
        descendants = _windows_descendants(process.pid)
        names = {str(item.get("Name", "")).lower() for item in descendants}
        if sys.platform == "win32" and not any(name == "node.exe" for name in names):
            raise E2EFailure("owned Rule Kit Node process not found")
        if sys.platform == "win32" and not any("chrome" in name for name in names):
            raise E2EFailure("owned Chromium process not found")
        socket = asyncio.run(_socket_flow(ready["wsEndpoint"], credential, child,
                                          generation, targets, target_hash))
        database = data / "state/hud.sqlite3"
        with sqlite3.connect(database) as connection:
            rows = connection.execute("select count(*) from hud_snapshot").fetchone()[0]
        if rows < 2:
            raise E2EFailure("durable assessment commits were not persisted")
        process.stdin.write(json.dumps({"type":"shutdown","ownerInstanceId":owner,
            "childInstanceId":child,"generation":generation}) + "\n")
        process.stdin.flush()
        exit_code = process.wait(timeout=15)
        if exit_code != 0:
            raise E2EFailure(f"Backend graceful shutdown returned {exit_code}")
        time.sleep(.25)
        remaining = _windows_descendants(process.pid)
        if remaining:
            raise E2EFailure("owned child process remained after cleanup")
        return {"schemaVersion":"d4planner-production-e2e/v1", "ok":True,
                "classification":"REAL_PROCESS_E2E_WITH_SYNTHETIC_INPUT",
                "backendPid":process.pid, "ready":ready, "ownedProcesses":descendants,
                "socket":socket, "sqliteAssessmentRows":rows,
                "durationSeconds":round(time.perf_counter()-started, 3)}
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=5)
        bootstrap.unlink(missing_ok=True)


def run_native(args: argparse.Namespace) -> dict:
    install = args.install_root.resolve(); data = args.data_root.resolve()
    _, evidence, _ = _prepare(install, data)
    report = args.output.resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["D4PLANNER_EQUIPMENT_EVIDENCE_FILE"] = str(evidence)
    env["D4_HUD_PIPELINE_REPORT"] = str(report)
    launcher = install / "app/start-d4planner.ps1"
    started = time.perf_counter()
    completed = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
        "-File", str(launcher), "-InstallRoot", str(install), "-DataRoot", str(data)],
        env=env, capture_output=True, text=True, timeout=120, check=False)
    if completed.returncode != 0 or not report.is_file():
        raise E2EFailure(f"native HUD pipeline failed exit={completed.returncode}: {completed.stderr[-1000:]}")
    value = json.loads(report.read_text(encoding="utf-8"))
    if value.get("ok") is not True or value.get("contextState") != "BOUND" or value.get("score") != 100.0:
        raise E2EFailure("native HUD report did not prove the production binding")
    value.update({"classification":"NATIVE_UI_REAL_PROCESS_WITH_SYNTHETIC_INPUT",
                  "nativeExitCode":completed.returncode,
                  "durationSeconds":round(time.perf_counter()-started, 3)})
    return value


def run_native_hud(args: argparse.Namespace) -> dict:
    """Collect private HUD-01/HUD-02 evidence from an interactive Windows desktop."""
    if sys.platform != "win32":
        raise E2EFailure("native HUD acceptance requires Windows")
    if not 1 <= args.approved_port <= 65535:
        raise E2EFailure("an Owner-approved static UAT port is required")
    install = args.install_root.resolve(); data = args.data_root.resolve()
    targets, evidence, _ = _prepare(install, data)
    target_b_document = json.loads((targets / "target-a.json").read_text(encoding="utf-8"))
    target_b_document["targetId"] = "synthetic-target-b"
    target_b_document["displayName"] = "Synthetic Target B Visible Change"
    (targets / "target-b.json").write_text(
        json.dumps(target_b_document, separators=(",", ":")), encoding="utf-8"
    )
    run_id = str(uuid.uuid4())
    root = args.output.resolve().parent / args.scenario
    root.mkdir(parents=True, exist_ok=True)
    bootstrap = data / "private" / f"bootstrap-{run_id}.json"
    bootstrap.parent.mkdir(parents=True, exist_ok=True)
    owner = str(uuid.uuid4()); child = str(uuid.uuid4()); generation = 1
    credential = secrets.token_hex(32)
    descriptor = {
        "protocol":"d4planner-managed/v1", "contractVersion":"d4planner-r1-contract/1.0.0-candidate.5",
        "ownerInstanceId":owner, "childInstanceId":child, "generation":generation,
        "dataDir":str(data / "state"), "targetFolder":str(targets),
        "wsEndpoint":{"host":"127.0.0.1","port":args.approved_port}, "credential":credential,
    }
    bootstrap.write_text(json.dumps(descriptor, separators=(",", ":")), encoding="utf-8")
    render_report = root / "render-state.json"
    env = _runtime_env(install, bootstrap, evidence)
    env.update({
        "D4PLANNER_BACKEND_PYTHON": str(install / "runtime/python/python.exe"),
        "D4_HUD_PIPELINE_REPORT": str(render_report),
        "D4_HUD_PIPELINE_CONTINUOUS": "1",
    })
    executable = install / "app/d4planner-fe.exe"
    started = datetime.now(timezone.utc).isoformat()
    process = subprocess.Popen([str(executable)], cwd=install, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    window = None
    before_state = None
    try:
        window = _wait_for(lambda: _native_window(process.pid), 45, "visible native HUD window")
        before_ui = _wait_for(
            lambda: json.loads(render_report.read_text(encoding="utf-8"))
                if render_report.is_file() else None,
            90, "HUD render acknowledgment",
        )
        before_root = root / "before" if args.scenario == "HUD-02" else root
        before_image = before_root / ("native-hud.png" if args.scenario == "HUD-02" else "screenshot-native.png")
        _capture_window(window, before_image)
        database = data / "state/hud.sqlite3"
        before_db = _sqlite_evidence(
            database, before_root / "sqlite-snapshot.db",
            before_root / ("sqlite-state.json" if args.scenario == "HUD-02" else "sqlite-snapshot.json"),
        )
        _assert_ui_matches_db(before_ui, before_db)
        before_state = {"ui": before_ui, "db": before_db, "screenshot": before_image}
        (before_root / ("native-window.json" if args.scenario == "HUD-02" else "window-info.json")).write_text(
            json.dumps(window, indent=2) + "\n", encoding="utf-8"
        )
        if args.scenario == "HUD-02":
            (before_root / "ws-state.json").write_text(json.dumps(before_ui, indent=2) + "\n", encoding="utf-8")
            previous_revision = int(before_ui["hudRevision"])
            ws_after = asyncio.run(_select_target(
                descriptor["wsEndpoint"], credential, child, generation, "synthetic-target-b"
            ))
            def changed_render():
                if not render_report.is_file(): return None
                value = json.loads(render_report.read_text(encoding="utf-8"))
                return value if value.get("hudRevision", -1) > previous_revision and value.get("targetId") == "synthetic-target-b" else None
            after_ui = _wait_for(changed_render, 30, "Target B visible HUD render")
            after_root = root / "after"; after_root.mkdir(exist_ok=True)
            after_image = after_root / "native-hud.png"
            _capture_window(window, after_image)
            after_db = _sqlite_evidence(
                database, after_root / "sqlite-snapshot.db", after_root / "sqlite-state.json"
            )
            _assert_ui_matches_db(after_ui, after_db)
            if ws_after["hudRevision"] != after_ui["hudRevision"]:
                raise E2EFailure("WS update and visible render revisions differ")
            (after_root / "ws-state.json").write_text(json.dumps(ws_after, indent=2) + "\n", encoding="utf-8")
            (after_root / "native-window.json").write_text(json.dumps(window, indent=2) + "\n", encoding="utf-8")
            compare = root / "compare"; compare.mkdir(exist_ok=True)
            changed_pixels = _visual_diff(before_image, after_image, compare / "visual-change.png")
            if changed_pixels == 0:
                raise E2EFailure("Target A to B produced no visible pixel change")
            delta = {
                "beforeRevision": before_ui["hudRevision"], "afterRevision": after_ui["hudRevision"],
                "beforeTargetId": before_ui["targetId"], "afterTargetId": after_ui["targetId"],
                "changedPixels": changed_pixels,
            }
            (compare / "actual-ui-delta.json").write_text(json.dumps(delta, indent=2) + "\n", encoding="utf-8")
            (compare / "expected-db-delta.json").write_text(json.dumps({
                "beforeRevision": before_db["hudRevision"], "afterRevision": after_db["hudRevision"],
                "beforeTargetId": before_db["payload"]["context"]["target"]["targetId"],
                "afterTargetId": after_db["payload"]["context"]["target"]["targetId"],
            }, indent=2) + "\n", encoding="utf-8")
            (compare / "assertion-report.json").write_text(json.dumps({"ok":True, **delta}, indent=2) + "\n", encoding="utf-8")
        owned_before_close = [{"ProcessId":process.pid,"Name":executable.name}, *_windows_descendants(process.pid)]
        (root / "process-tree-before.json").write_text(json.dumps(owned_before_close, indent=2) + "\n", encoding="utf-8")
        ctypes.WinDLL("user32", use_last_error=True).PostMessageW(window["hwnd"], 0x0010, 0, 0)
        process.wait(timeout=20)
        time.sleep(.5)
        remaining = _windows_descendants(process.pid)
        if process.returncode != 0 or remaining:
            raise E2EFailure(f"native HUD cleanup failed exit={process.returncode} remaining={remaining!r}")
        stdout, stderr = process.communicate(timeout=1)
        (root / "execution.log").write_text(
            (stdout or "") + (stderr or ""), encoding="utf-8", errors="replace"
        )
        (root / "process-tree-after.json").write_text(json.dumps(remaining, indent=2) + "\n", encoding="utf-8")
        manifest = {
            "schemaVersion":"d4planner-native-hud-evidence/v1", "ok":True,
            "scenario":args.scenario, "runId":run_id, "sourceHead":args.source_head,
            "packageSha256":_sha(args.package.resolve()), "startedAt":started,
            "screenshotSha256":_sha(before_state["screenshot"]),
            "screenshotTimestamp":datetime.fromtimestamp(before_state["screenshot"].stat().st_mtime, timezone.utc).isoformat(),
            "viewport":window["bounds"], "hwnd":window["hwnd"], "pid":window["pid"],
            "sessionId":window["sessionId"], "databaseSnapshotSha256":before_db["backupSha256"],
            "databaseSnapshotTimestamp":datetime.now(timezone.utc).isoformat(),
            "hudRevision":before_ui["hudRevision"], "contextState":before_ui["contextState"],
            "scoreStatus":before_ui["scoreStatus"], "backendInstance":child,
            "backendGeneration":generation, "expected":"native window and durable state match",
            "actual":"verified", "classification":"NATIVE_UI_REAL_PROCESS_WITH_SYNTHETIC_INPUT",
        }
        (root / "evidence-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return manifest
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=10)
        bootstrap.unlink(missing_ok=True)


def run_owner(args: argparse.Namespace) -> dict:
    install = args.install_root.resolve(); data = args.data_root.resolve()
    targets, evidence, _ = _prepare(install, data)
    bootstrap = data / "native-owner-bootstrap.json"
    descriptor = {
        "protocol":"d4planner-managed/v1", "contractVersion":"d4planner-r1-contract/1.0.0-candidate.5",
        "ownerInstanceId":str(uuid.uuid4()), "childInstanceId":str(uuid.uuid4()), "generation":1,
        "dataDir":str(data / "state"), "targetFolder":str(targets),
        "wsEndpoint":{"host":"127.0.0.1","port":0}, "credential":secrets.token_hex(32),
    }
    bootstrap.write_text(json.dumps(descriptor), encoding="utf-8")
    native_report = args.output.with_suffix(".native.json").resolve()
    native_report.parent.mkdir(parents=True, exist_ok=True)
    env = _runtime_env(install, bootstrap, evidence)
    env["D4PLANNER_BACKEND_PYTHON"] = str(install / "runtime/python/python.exe")
    env["D4_BACKEND_SMOKE_REPORT"] = str(native_report)
    started = time.perf_counter()
    try:
        completed = subprocess.run([str(install / "app/d4planner-fe.exe"), "--backend-self-test"],
            cwd=install, env=env, capture_output=True, text=True, timeout=90, check=False)
        if completed.returncode != 0 or not native_report.is_file():
            raise E2EFailure(
                f"native Backend owner smoke failed exit={completed.returncode}; "
                f"stdout={completed.stdout[-1000:]!r}; stderr={completed.stderr[-1000:]!r}"
            )
        value = json.loads(native_report.read_text(encoding="utf-8"))
        ready = value.get("ready", {})
        restarted = value.get("restartedReady", {})
        if (value.get("ok") is not True or ready.get("pid") is None
            or ready.get("wsEndpoint", {}).get("port", 0) == 0
            or restarted.get("pid") is None
            or restarted.get("pid") == ready.get("pid")
            or restarted.get("generation") != ready.get("generation", 0) + 1
            or restarted.get("wsEndpoint", {}).get("port", 0) == 0
            or value.get("finalState") != "EXITED"):
            raise E2EFailure("native owner report did not prove READY, restart, and cleanup")
        value.update({"classification":"NATIVE_FE_OWNS_REAL_BACKEND",
                      "nativeExitCode":completed.returncode,
                      "durationSeconds":round(time.perf_counter()-started, 3)})
        return value
    finally:
        bootstrap.unlink(missing_ok=True)


def run_package_cycle(args: argparse.Namespace) -> dict:
    root = args.staging_root.resolve() / "package-cycle"
    app = root / "app"; data = root / "data"
    if root.exists():
        shutil.rmtree(root)
    (data / "targets").mkdir(parents=True)
    (data / "state").mkdir()
    target_sentinel = data / "targets/user-target.json"
    state_sentinel = data / "state/user-state.sqlite"
    target_sentinel.write_text("user-target", encoding="utf-8")
    state_sentinel.write_bytes(b"user-state")
    first = delivery.install_package(args.package.resolve(), app, data)
    marker = app / "upgrade-marker.txt"; marker.write_text("previous-version", encoding="utf-8")
    second = delivery.install_package(args.package.resolve(), app, data)
    if marker.exists() or not (app.with_name("app.previous") / marker.name).is_file():
        raise E2EFailure("upgrade did not atomically retain the previous install")
    if target_sentinel.read_text() != "user-target" or state_sentinel.read_bytes() != b"user-state":
        raise E2EFailure("upgrade changed persistent user data")
    delivery.rollback_install(app, data)
    if (app / marker.name).read_text() != "previous-version":
        raise E2EFailure("rollback did not restore the previous install")
    return {"schemaVersion":"d4planner-package-cycle/v1", "ok":True,
            "packageSha256":delivery.sha256_file(args.package), "first":first, "second":second,
            "persistentTargetsPreserved":True, "persistentStatePreserved":True,
            "rollback":"APPLIED"}


def run_rulekit(args: argparse.Namespace) -> dict:
    install = args.install_root.resolve()
    environment = _runtime_env(install, install / "unused-bootstrap.json",
                               install / "examples/equipment.recorded.synthetic.json")
    async def scenario():
        service = RuleKitRuntimeService.from_environment(environment)
        started = time.perf_counter()
        try:
            health = await service.start()
            client = service.client
            assert client is not None
            providers = await client.list_providers()
            provider = next(item for item in providers if item["id"] == "maxroll")
            request = {
                "contractVersion":"d4-rulekit-application/v1", "providerId":"maxroll",
                "providerVersion":provider["version"], "expectedGamePatch":"3.2.1.73552",
                "snapshotId":"maxroll-20261023T034150Z",
                "snapshotManifestSha256":"638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54",
                "buildSchemaVersion":"maxroll-build/rogue-l50-v1",
                "build":{"class":"Rogue","level":50,"difficulty":"Torment I",
                         "equipment":{"Helm":{"itemId":"runic-skullcap","modifiers":[]}}},
            }
            session = await client.create_session(request)
            baseline = await client.evaluate(session)
            changes = [{"type":"effect.set","effectId":"of-dampening","active":True}]
            preview = await client.preview_changes(session, {"expectedRevision":0,"changes":changes})
            committed = await client.commit_changes(session, {"expectedRevision":0,
                "changes":changes,"previewToken":preview["previewToken"]})
            current = await client.get_session(session)
            reset = await client.reset_session(session, {"expectedRevision":1})
            await client.close_session(session)
            return {"schemaVersion":"d4planner-rulekit-e2e/v1", "ok":True,
                    "classification":"REAL_WORKER_OFFLINE_SNAPSHOT",
                    "apis":["listProviders","createSession","evaluate","previewChanges",
                            "commitChanges","getSession","resetSession","closeSession"],
                    "workerHealth":health, "provider":provider,
                    "baselineMetricCount":len(baseline["metrics"]),
                    "committedRevision":committed["session"]["revision"],
                    "observedRevision":current["revision"], "resetRevision":reset["revision"],
                    "durationSeconds":round(time.perf_counter()-started, 3)}
        finally:
            await service.stop()
    return asyncio.run(scenario())


def run_crash_recovery(args: argparse.Namespace) -> dict:
    install = args.install_root.resolve(); data = args.data_root.resolve()
    _, evidence, _ = _prepare(install, data)
    bootstrap = data / "crash-bootstrap.json"
    bootstrap.write_text("{}", encoding="utf-8")
    previous = dict(os.environ)
    os.environ.update(_runtime_env(install, bootstrap, evidence))
    async def scenario() -> dict:
        service = RuleKitRuntimeService.from_environment()
        started = time.perf_counter()
        first_pid = second_pid = None
        try:
            first = await service.start()
            child = service.wrapper._child
            if child is None:
                raise E2EFailure("owned Rule Kit child is unavailable")
            first_pid = child.pid
            child.process.kill()
            await asyncio.wait_for(child.process.wait(), 5)
            for _ in range(50):
                failed = await service.wrapper.inspect_health()
                if not failed["ready"]:
                    break
                await asyncio.sleep(.02)
            else:
                raise E2EFailure("crashed worker remained READY")
            service.client = await service.wrapper.restart()
            providers = await service.client.list_providers()
            recovered = await service.wrapper.inspect_health()
            active = service.wrapper._child
            second_pid = active.pid if active is not None else None
            if (not recovered["ready"] or recovered["workerGeneration"] != first["workerGeneration"] + 1
                    or second_pid in (None, first_pid) or not providers):
                raise E2EFailure("bounded worker restart did not establish a new healthy generation")
            return {"schemaVersion":"d4planner-crash-recovery-e2e/v1", "ok":True,
                    "classification":"REAL_WORKER_CRASH_RECOVERY", "firstPid":first_pid,
                    "restartedPid":second_pid, "firstGeneration":first["workerGeneration"],
                    "restartedGeneration":recovered["workerGeneration"],
                    "restartBudget":service.wrapper.specification.max_restarts,
                    "durationSeconds":round(time.perf_counter()-started, 3)}
        finally:
            await service.stop()
            await asyncio.sleep(.25)
            remaining = []
            for pid in (first_pid, second_pid):
                if pid is not None:
                    remaining.extend(_windows_descendants(pid))
            if remaining:
                raise E2EFailure("owned worker descendants remained after crash cleanup")
    try:
        return asyncio.run(scenario())
    finally:
        os.environ.clear(); os.environ.update(previous)
        bootstrap.unlink(missing_ok=True)


def run_performance(args: argparse.Namespace) -> dict:
    samples = []
    for index in range(5):
        sample_args = argparse.Namespace(
            install_root=args.install_root,
            data_root=args.data_root / f"sample-{index + 1}",
            output=args.output,
        )
        samples.append(run_backend(sample_args)["durationSeconds"])
    ordered = sorted(samples)
    return {"schemaVersion":"d4planner-latency-evidence/v1", "ok":True,
            "classification":"REAL_PROCESS_END_TO_END_LATENCY",
            "sampleCount":len(samples), "samplesSeconds":samples,
            "p50Seconds":statistics.median(samples),
            "p95Seconds":statistics.quantiles(ordered, n=100, method="inclusive")[94],
            "sla":"NOT_DEFINED_AS_APPROVED"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    for name in ("backend", "native", "owner", "rulekit", "crash-recovery", "performance"):
        command = sub.add_parser(name)
        command.add_argument("--install-root", type=Path, required=True)
        command.add_argument("--data-root", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
    package = sub.add_parser("package-cycle")
    package.add_argument("--package", type=Path, required=True)
    package.add_argument("--staging-root", type=Path, required=True)
    package.add_argument("--output", type=Path, required=True)
    native_hud = sub.add_parser("native-hud")
    native_hud.add_argument("--install-root", type=Path, required=True)
    native_hud.add_argument("--data-root", type=Path, required=True)
    native_hud.add_argument("--output", type=Path, required=True)
    native_hud.add_argument("--package", type=Path, required=True)
    native_hud.add_argument("--source-head", required=True)
    native_hud.add_argument("--approved-port", type=int, required=True)
    native_hud.add_argument("--scenario", choices=("HUD-01", "HUD-02"), required=True)
    args = parser.parse_args(argv)
    try:
        result = (run_backend(args) if args.command == "backend" else
                  run_native(args) if args.command == "native" else
                  run_owner(args) if args.command == "owner" else
                  run_crash_recovery(args) if args.command == "crash-recovery" else
                  run_performance(args) if args.command == "performance" else
                  run_native_hud(args) if args.command == "native-hud" else
                  run_rulekit(args) if args.command == "rulekit" else run_package_cycle(args))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, sort_keys=True)); return 0
    except (E2EFailure, OSError, ValueError, subprocess.SubprocessError) as exc:
        traceback.print_exc()
        print(f"{type(exc).__name__}:{exc}", file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
