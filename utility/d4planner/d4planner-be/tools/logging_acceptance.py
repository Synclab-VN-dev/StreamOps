"""LOG-09/10 observations shared by the opt-in Windows acceptance runners.

No production switches: the disabled baseline uses the existing fail-open path
by placing a file at logs/ in a NEW, disposable DataDir. Both arms run the same
installed bytes. Never point these runners at an operator's DataDir.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import time


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def percentiles(values):
    if not values or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("nonempty finite nonnegative measurements required")
    return {"count": len(values), "p50": statistics.median(values),
            "p95": statistics.quantiles(values, n=100, method="inclusive")[94] if len(values) > 1 else values[0],
            "min": min(values), "max": max(values), "samples": values}


def comparison(baseline, enabled):
    result = {"baseline": percentiles(baseline), "INFO": percentiles(enabled)}
    for quantile in ("p50", "p95"):
        before, after = result["baseline"][quantile], result["INFO"][quantile]
        result[quantile + "Overhead"] = after - before
        result[quantile + "OverheadPercent"] = (after - before) / before * 100 if before else None
    return result


def log_evidence(data, run_name=None):
    runs = [p for p in (Path(data) / "logs").iterdir() if p.is_dir() and not p.name.startswith(".")]
    if run_name is not None:
        runs = [p for p in runs if p.name == run_name]
    if len(runs) != 1:
        raise AssertionError("expected exactly one run in fresh DataDir")
    folder = runs[0]
    if sorted(p.name for p in folder.iterdir()) != ["be.log", "fe.log", "rulekit.log"]:
        raise AssertionError("expected exactly three named files")
    result = {}; ids = set()
    for filename, component in (("fe.log", "FE"), ("be.log", "BE"), ("rulekit.log", "RULEKIT")):
        path = folder / filename
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert rows and rows[0]["event"] == "SESSION_HEADER"
        assert all(row["component"] == component and row["schemaVersion"] == "d4planner-runtime-log/v1" for row in rows)
        ids.update(row["runId"] for row in rows)
        result[filename] = {"bytes": path.stat().st_size, "records": len(rows),
                            "events": sorted({row["event"] for row in rows}),
                            "readyAt": next((row["ts"] for row in rows if row["event"] == "READY"), None),
                            "lossMarkers": [row["fields"] for row in rows if row["event"] in {"LOG_DROPPED", "LOG_TRIMMED"}]}
    assert len(ids) == 1, "cross-component runId mismatch"
    assert "READY" in result["be.log"]["events"] and "READY" in result["rulekit.log"]["events"]
    return {"runId": ids.pop(), "files": result}


RESOURCE_COUNTERS = ("KernelModeTime", "UserModeTime", "WorkingSetSize", "ReadTransferCount", "WriteTransferCount")


def verify_resource_snapshots(root_pid, candidate_pids, snapshots, *, root_alive):
    """Admit only stable identities with a live, chronological chain to Launcher.

    Toolhelp PIDs are discovery hints, not ownership. CIM creation timestamps
    have microsecond precision. Missing ancestors/identity/counters fail closed;
    raw snapshots remain available even when only a subset can be measured.
    """
    result = {"schemaVersion": "d4planner-resource-evidence/v1", "status": "NOT_MEASURED",
              "rootPid": root_pid, "rawSnapshots": snapshots, "accepted": [], "rejected": [], "totals": None,
              "scope": "Previously discovered, still-live descendants; excludes Launcher, exited and later descendants"}
    candidates = sorted(set(candidate_pids) - {root_pid})
    if not root_alive:
        result["reason"] = "ROOT_NOT_ALIVE"
        return result

    def created(row):
        try:
            value = datetime.fromisoformat(row["CreatedUtc"].replace("Z", "+00:00"))
            return value if value.tzinfo is not None else None
        except (KeyError, TypeError, AttributeError, ValueError):
            return None

    try:
        before = {int(row["ProcessId"]): row for row in snapshots["identity"]}
        after = {int(row["ProcessId"]): row for row in snapshots["counters"]}
        if len(before) != len(snapshots["identity"]) or len(after) != len(snapshots["counters"]):
            raise ValueError("duplicate PID")
    except (KeyError, TypeError, ValueError):
        result["reason"] = "INVALID_SNAPSHOT"
        return result
    root_created = created(before.get(root_pid, {}))
    if root_created is None or root_created != created(after.get(root_pid, {})):
        result["reason"] = "ROOT_IDENTITY_UNVERIFIED"
        return result
    result["rootCreatedUtc"] = before[root_pid]["CreatedUtc"]

    def ownership(pid, visiting):
        if pid == root_pid:
            return None
        if pid in visiting:
            return "ANCESTRY_CYCLE"
        first, last = before.get(pid), after.get(pid)
        if first is None or last is None:
            return "PROCESS_OR_ANCESTOR_MISSING"
        birth = created(first)
        if birth is None or created(last) is None:
            return "CREATION_TIME_UNAVAILABLE"
        if birth != created(last):
            return "PID_REUSED"
        if birth < root_created:
            return "PREDATES_RUN"
        parent = first.get("ParentProcessId")
        if not isinstance(parent, int) or parent != last.get("ParentProcessId"):
            return "PARENT_IDENTITY_UNVERIFIED"
        reason = ownership(parent, visiting | {pid})
        if reason:
            return reason
        if birth < created(before[parent]):
            return "PARENT_PID_REUSED"
        return None

    for pid in candidates:
        reason = ownership(pid, set())
        if reason is None:
            try:
                values = [int(after[pid][key]) for key in RESOURCE_COUNTERS]
                if any(value < 0 for value in values):
                    raise ValueError("negative counter")
            except (KeyError, TypeError, ValueError):
                reason = "COUNTERS_UNAVAILABLE"
        if reason:
            result["rejected"].append({"pid": pid, "reason": reason})
        else:
            result["accepted"].append(dict(after[pid]))
    if result["accepted"]:
        result["status"] = "PARTIAL" if result["rejected"] else "MEASURED"
        result["totals"] = {key: sum(int(row[key]) for row in result["accepted"]) for key in RESOURCE_COUNTERS}
    else:
        result["reason"] = "NO_VERIFIED_DESCENDANTS"
    return result


def collect_resource_evidence(process, tree):
    """Read-only, after all timed operations; Popen liveness anchors root identity."""
    ids = sorted({process.pid, *(int(row["pid"]) for row in tree)})
    snapshots = {"identity": [], "counters": []}
    if process.poll() is not None:
        return verify_resource_snapshots(process.pid, ids, snapshots, root_alive=False)
    # Two independent CIM observations detect PID reuse during collection. The
    # original Popen handle must remain alive throughout; its PID cannot then
    # refer to a different root. Names are diagnostic only, never an allowlist.
    script = ("$ErrorActionPreference='Stop'; function Observe { @(Get-CimInstance Win32_Process -ErrorAction Stop | "
              f"Where-Object {{$_.ProcessId -in @({','.join(map(str, ids))})}} | "
              "Select-Object ProcessId,ParentProcessId,Name,@{Name='CreatedUtc';Expression={"
              "if ($null -ne $_.CreationDate) {$_.CreationDate.ToUniversalTime().ToString('o')}}},"
              + ",".join(RESOURCE_COUNTERS) + ") }; "
              "$identity=@(Observe); $counters=@(Observe); "
              "@{identity=$identity;counters=$counters}|ConvertTo-Json -Depth 4 -Compress")
    try:
        completed = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script],
                                   capture_output=True, text=True, timeout=30)
        if completed.returncode != 0:
            result = verify_resource_snapshots(process.pid, ids, snapshots, root_alive=False)
            result.update(reason="CIM_QUERY_FAILED", exitCode=completed.returncode,
                          rawStdout=completed.stdout, rawStderr=completed.stderr)
            return result
        snapshots = json.loads(completed.stdout)
        return verify_resource_snapshots(process.pid, ids, snapshots, root_alive=process.poll() is None)
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError) as error:
        result = verify_resource_snapshots(process.pid, ids, snapshots, root_alive=False)
        result.update(reason="RESOURCE_COLLECTION_UNAVAILABLE", error=type(error).__name__)
        return result


def native_sample(install, payload, data, output, *, mode="INFO", samples=20):
    """Reuse production E2E producer, native window, DB and render assertions."""
    import production_e2e as e2e
    from d4planner.character.repository import EquipmentRepository
    from windows_setup_e2e import owned_tree
    from windows_installer_review_e2e import alive

    data.mkdir(parents=True, exist_ok=True)
    assert not any((data / name).exists() for name in ("logs", "launcher.json", "recorded-producer.sqlite3")), "fresh workload DataDir required"
    output.mkdir(parents=True, exist_ok=False)
    targets, fixture, _ = e2e._prepare(payload, data)
    target_b = e2e._native_target_b(read_json(targets / "target-a.json"))
    write_json(targets / "target-b.json", target_b)
    recorded = read_json(fixture)
    producer = EquipmentRepository(data / "recorded-producer.sqlite3")
    revision = e2e._record_equipment_sample(producer, recorded, 1)
    write_json(data / "launcher.json", {"schemaVersion": "d4planner-launcher/v1", "equipmentRepository": {
        "enabled": True, "path": str(producer.path), "characterId": recorded["characterId"],
        "characterDisplayName": recorded["characterDisplayName"]}})
    if mode == "disabled":
        (data / "logs").write_text("LOG-09 disposable fail-open baseline\n")
    elif mode != "INFO":
        raise ValueError("unknown logging mode")
    render = output / "render.json"
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("D4PLANNER_", "D4_RULEKIT_", "D4_HUD_", "D4_LOG_"))}
    env.update(D4PLANNER_STORAGE_ISOLATED="1", D4PLANNER_DATA_ROOT=str(data), D4_HUD_PIPELINE_REPORT=str(render),
               D4_HUD_PIPELINE_CONTINUOUS="1", D4PLANNER_LATENCY_TRACE=str(output / "latency.jsonl"),
               WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--force-renderer-accessibility")
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    process = subprocess.Popen([str(install / "D4Planner.exe")], env=env, cwd=output)
    tree = []; measurements = []; report = {"mode": mode, "startedAt": started_at.isoformat()}
    def rendered(wanted):
        if process.poll() is not None:
            raise AssertionError(f"launcher exited early: {process.returncode}")
        try:
            value = read_json(render)
            return value if value["currentRevision"] == wanted else None
        except (OSError, ValueError):
            return None
    def db(index):
        return e2e._sqlite_evidence(data / "state/hud.sqlite3", output / f"db-{index}.sqlite3", output / f"db-{index}.json")
    try:
        first = e2e._wait_for(lambda: rendered(revision), 90, "initial native render")
        report["startupToRenderMs"] = (e2e._parse_timestamp(first["visibleRenderedAt"]) - started_at).total_seconds() * 1000
        e2e._assert_ui_matches_db(first, db("initial"))
        tree = owned_tree(process.pid)
        for name in ("d4planner-fe.exe", "python.exe", "node.exe"):
            assert len([row for row in tree if row["name"].lower() == name]) == 1, (name, tree)
        fe = next(row for row in tree if row["name"].lower() == "d4planner-fe.exe")
        window = e2e._wait_for(lambda: e2e._native_window(fe["pid"]), 10, "native window")
        assert window["visible"] and window["sessionId"] != 0
        report["nativeWindow"] = window
        e2e._capture_window(window, output / "native.png")
        for index in range(samples):
            at = datetime.now(timezone.utc)
            tick = time.perf_counter()
            revision = e2e._record_equipment_sample(producer, recorded, index + 2)
            ui = e2e._wait_for(lambda: rendered(revision), 20, "capture revision visible")
            elapsed = (time.perf_counter() - tick) * 1000
            e2e._assert_ui_matches_db(ui, db(index))
            measurements.append({"producerStartedAt": at.isoformat(), "observerElapsedMs": elapsed, "ui": ui})
        report.update(first=first, samples=measurements, ownedTree=tree)
        # Actual FE-origin operation through Tauri managed control and DB/render.
        before_target = db("before-target")
        e2e._invoke_hud_button(window, "Open target menu")
        target_started = datetime.now(timezone.utc)
        e2e._invoke_hud_button(window, target_b["displayName"])
        def selected():
            value = rendered(revision)
            return value if value and value["targetId"] == target_b["targetId"] else None
        target_ui = e2e._wait_for(selected, 30, "FE Target activation rendered")
        after_target = db("after-target")
        e2e._assert_ui_matches_db(target_ui, after_target)
        e2e._assert_native_delta(before_target["payload"], after_target["payload"])
        report["targetActivationMs"] = (e2e._parse_timestamp(target_ui["visibleRenderedAt"]) - target_started).total_seconds() * 1000
        report["targetSelected"] = target_ui
        # Identity checks/counters stay AFTER timed operations, outside latency.
        report["resourceEvidence"] = collect_resource_evidence(process, tree)
        report["resources"] = report["resourceEvidence"]["accepted"]
    finally:
        # Root owns a Windows job. Always stop it even when an assertion fails.
        stopped = subprocess.run([str(install / "D4Planner.exe"), "--stop"], env=env, timeout=25)
        process.wait(timeout=25)
        assert stopped.returncode == 0 and process.returncode == 0
        e2e._wait_for(lambda: not any(alive(row["pid"]) for row in tree), 10, "owned processes exit")
        report.update(durationSeconds=time.perf_counter() - started, exitCode=process.returncode, ownedProcessesAfter=0)
        write_json(output / "sample.json", report)
    if mode == "INFO":
        report["logging"] = log_evidence(data)
        for filename, key in (("be.log", "beReadyMs"), ("rulekit.log", "rulekitReadyMs")):
            report[key] = (e2e._parse_timestamp(report["logging"]["files"][filename]["readyAt"]) - started_at).total_seconds() * 1000
    else:
        assert (data / "logs").is_file() and not list(data.rglob("*.log"))
    traces = [json.loads(line) for line in (output / "latency.jsonl").read_text().splitlines()]
    stages = {name: [] for name in ("endToEndMs", "captureToAssessmentMs", "assessmentToCommitMs", "commitToWsMs", "wsToModelMs", "modelToRenderMs")}
    for sample in measurements:
        ui = sample["ui"]
        trace = next(row for row in traces if row["hudRevision"] == ui["hudRevision"])
        delta = lambda a, b: (e2e._parse_timestamp(a) - e2e._parse_timestamp(b)).total_seconds() * 1000
        stages["endToEndMs"].append(delta(ui["visibleRenderedAt"], sample["producerStartedAt"]))
        stages["captureToAssessmentMs"].append(e2e._capture_to_assessment_ms(trace, sample["producerStartedAt"]))
        stages["assessmentToCommitMs"].append(trace["assessmentToCommitNs"] / 1_000_000)
        stages["commitToWsMs"].append(delta(ui["wsReceivedAt"], trace["captureReceivedAt"]) - (trace["captureToAssessmentNs"] + trace["assessmentToCommitNs"]) / 1_000_000)
        stages["wsToModelMs"].append(delta(ui["modelUpdatedAt"], ui["wsReceivedAt"]))
        stages["modelToRenderMs"].append(delta(ui["visibleRenderedAt"], ui["modelUpdatedAt"]))
    report["stages"] = {name: percentiles(values) for name, values in stages.items()}
    write_json(output / "sample.json", report)
    return report
