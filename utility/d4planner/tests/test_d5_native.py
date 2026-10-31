"""Opt-in real Windows launcher/FE/BE smoke; recorded input, never live-game evidence."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_root_launcher_committed_db_notification_native_reader_and_target_ipc(tmp_path):
    configured = os.environ.get("D5_NATIVE_INSTALL_ROOT")
    if sys.platform != "win32" or not configured:
        pytest.skip("requires an explicitly staged isolated Windows installation")
    install = Path(configured).resolve()
    spec = importlib.util.spec_from_file_location("d5_native_e2e", ROOT / "utility/d4planner/tools/production_e2e.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    from d4planner.character.repository import EquipmentRepository
    data = tmp_path / "data"
    targets, evidence, _ = tool._prepare(install, data)
    target_b = tool._native_target_b(json.loads((targets / "target-a.json").read_text()))
    (targets / "target-b.json").write_text(json.dumps(target_b), encoding="utf-8")
    recorded = json.loads(evidence.read_text())
    producer = EquipmentRepository(data / "recorded-producer.sqlite3")
    first_revision = tool._record_equipment_sample(producer, recorded, 1)
    (data / "launcher.json").write_text(json.dumps({
        "schemaVersion": "d4planner-launcher/v1", "equipmentRepository": {
            "enabled": True, "path": str(producer.path), "characterId": recorded["characterId"],
            "characterDisplayName": recorded["characterDisplayName"]}}))
    report = tmp_path / "render.json"
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("D4PLANNER_", "D4_RULEKIT_", "D4_HUD_"))}
    env.update(D4PLANNER_DATA_ROOT=str(data), D4_HUD_PIPELINE_REPORT=str(report),
               D4_HUD_PIPELINE_CONTINUOUS="1", WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--force-renderer-accessibility")
    process = subprocess.Popen([str(install / "D4Planner.exe")], env=env, cwd=tmp_path)
    def rendered(predicate):
        if process.poll() is not None:
            raise AssertionError(f"root launcher exited {process.returncode}")
        try:
            value = json.loads(report.read_text())
            return value if predicate(value) else None
        except (OSError, json.JSONDecodeError):
            return None
    def database():
        return tool._sqlite_evidence(data / "state/hud.sqlite3", tmp_path / "snapshot.db", tmp_path / "snapshot.json")
    try:
        first = tool._wait_for(lambda: rendered(lambda row: row["currentRevision"] == first_revision), 90, "initial native HUD")
        before = database()
        tool._assert_ui_matches_db(first, before)
        children = tool._windows_descendants(process.pid)
        fe = [row for row in children if row["Name"].lower() == "d4planner-fe.exe"]
        assert len(fe) == 1, children
        window = tool._wait_for(lambda: tool._native_window(fe[0]["ProcessId"]), 10, "owned native FE window")
        assert window["visible"]
        # Producer capture update does not invoke any FE refresh/command. The
        # committed notification must trigger the Rust SQLite read and React render.
        second_revision = tool._record_equipment_sample(producer, recorded, 2)
        second = tool._wait_for(lambda: rendered(lambda row: row["currentRevision"] == second_revision), 20, "notification-triggered SQLite reread")
        assert second["hudRevision"] > first["hudRevision"] and second["wsReceivedAt"]
        tool._assert_ui_matches_db(second, database())
        tool._invoke_hud_button(window, "Open target menu")
        tool._invoke_hud_button(window, target_b["displayName"])
        selected = tool._wait_for(lambda: rendered(lambda row: row["targetId"] == target_b["targetId"]), 30, "Target IPC committed render")
        after = database()
        tool._assert_ui_matches_db(selected, after)
        tool._assert_native_delta(before["payload"], after["payload"])
        current = tool._windows_descendants(process.pid)
        for name in ("python.exe", "node.exe"):
            assert {r["ProcessId"] for r in children if r["Name"].lower() == name} == {r["ProcessId"] for r in current if r["Name"].lower() == name}
        print(json.dumps({"classification": "WINDOWS_NATIVE_RECORDED_INPUT", "launcherPid": process.pid,
                          "fePid": fe[0]["ProcessId"], "first": first, "captureUpdated": second, "targetSelected": selected}))
    finally:
        subprocess.run([str(install / "D4Planner.exe"), "--stop"], env=env, timeout=20, check=True)
        process.wait(timeout=20)
        assert process.returncode == 0
