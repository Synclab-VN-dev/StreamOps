"""Acceptance reporter is strictly evidence-only: never certifies physical controller."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from d4planner.controller import load_profile
from d4planner.runtime.events.store import EventStore
from d4planner.runtime.store import RuntimePaths, atomic_write_json

REPORTER = Path(__file__).resolve().parents[1] / "tools" / "issue87_uat_evidence.py"
spec = importlib.util.spec_from_file_location("issue87_uat_evidence", REPORTER)
reporter = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(reporter)


def snapshots():
    common = {
        "sessionId":"s-87", "validForReview":True,
        "runtimeState":"RUNNING", "markerState":"ACTIVE",
        "layoutId":"xbox-steaminput-18-v1", "mode":"BLOCK",
        "backend":"keyboardHook", "droppedCount":0,
    }
    return (
        {**common, "maxSeq":3}, {**common, "maxSeq":36}
    )


def captured_rows():
    profile = load_profile("xbox16")
    rows = [{
        "eventSeq":4, "type":"speech.raw", "data":{"text":"850 Item Power"},
    }]
    sequence = 5
    for binding in profile.digital:
        for state in ("down", "up"):
            rows.append({
                "eventSeq":sequence, "type":"input.marker.raw",
                "data":{
                    "key":binding.key, "virtualKey":binding.virtual_key,
                    "state":state, "controlId":binding.control_id,
                    "layoutId":profile.layout_id,
                    "mappingSource":"configuredLayout", "suppressed":True,
                },
            })
            sequence += 1
    return rows


def test_reporter_maps_all_16_without_claiming_owner_physical_pass():
    start, end = snapshots()
    output = reporter.analyze(
        events=captured_rows(), start=start, end=end, quick_check="ok",
    )
    assert output["status"] == "PENDING_OWNER_REVIEW"
    assert output["physicallyVerified"] == 0
    assert output["summary"] == {
        "PASS":21, "FAIL":0, "BLOCKED":2, "SKIP":0,
    }
    assert all(entry["result"] == "PASS" for entry in output["matrix"])
    assert all(entry["physicalVerified"] is False for entry in output["matrix"])
    assert output["speechEvents"] == 1
    assert output["range"] == {"fromExclusive":3,"toInclusive":36}


def test_reporter_flags_missing_duplicate_and_wrong_vk():
    start,end=snapshots()
    bad = captured_rows()
    bad = [x for x in bad if not (
        x["type"] == "input.marker.raw"
        and x["data"]["controlId"] == "B"
        and x["data"]["state"] == "up"
    )]
    for row in bad:
        if row["type"]=="input.marker.raw" and row["data"]["controlId"]=="DPAD_UP":
            row["data"]["virtualKey"]=0x41
            break
    output = reporter.analyze(events=bad, start=start, end=end, quick_check="ok")
    assert output["status"] == "FAIL"
    results = {x["controlId"]:x["result"] for x in output["matrix"]}
    assert results["B"] == "FAIL" and results["DPAD_UP"] == "FAIL"
    assert output["physicallyVerified"] == 0


def test_reporter_rejects_stale_or_changed_session():
    start,end=snapshots()
    end["sessionId"]="different-session"
    result=reporter.analyze(events=[],start=start,end=end,quick_check="session changed")
    assert result["status"] == "BLOCKED"
    assert all(x["result"]=="BLOCKED" for x in result["matrix"])


def test_reporter_reads_canonical_sqlite_without_writing(tmp_path):
    paths=RuntimePaths(tmp_path / "home")
    store=EventStore.create(paths,silent=True,session_id="test-87")
    profile=load_profile("xbox16")
    store.emit("speech.raw",{"text":"850 Item Power"})
    store.emit("input.marker.raw",{
        "source":"steamInput","device":"keyboard","key":"F11",
        "virtualKey":122,"state":"down","process":"diablo iv",
        "processId":999,"contextSource":"win32Foreground",
        "windowTitle":"Diablo IV","controlId":"A",
        "layoutId":profile.layout_id,"mappingSource":"configuredLayout",
        "suppressed":True,
    })
    atomic_write_json(paths.runtime_state,{
        "state":"RUNNING", "sessionId":"test-87",
        "extras":{"inputMarker":{
            "state":"ACTIVE","layoutId":profile.layout_id,
            "mode":"BLOCK","backend":"keyboardHook",
            "configuredDigitalCount":16,"analogDisabledCount":2,
        }},
    })
    before=reporter.snapshot(paths)
    assert before["maxSeq"]==2
    assert before["validForReview"]
    rows, quick=reporter.read_evidence(paths,"test-87",0,before["maxSeq"])
    assert quick=="ok"
    assert [row["type"] for row in rows]==["speech.raw","input.marker.raw"]
    assert reporter.snapshot(paths)["maxSeq"]==before["maxSeq"]
    store.close()



def test_reporter_snapshot_refuses_hook_overflow_even_when_active(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    atomic_write_json(paths.runtime_state, {
        "state":"RUNNING", "sessionId":"overflow-test",
        "extras":{"inputMarker":{
            "state":"ACTIVE","layoutId":"xbox-steaminput-18-v1",
            "mode":"BLOCK","backend":"keyboardHook",
            "configuredDigitalCount":16,"analogDisabledCount":2,
            "droppedCount":1, "overflow":True,
            "error":"dropped marker before SQLite ingress",
        }},
    })
    state = reporter.snapshot(paths)
    assert state["droppedCount"] == 1
    assert state["overflow"]
    assert not state["validForReview"]


def test_reporter_accepts_multiple_complete_presses_without_false_fail():
    # Real-A #87 included several intentional taps for every button.
    # One clean pair is not the only valid capture: five clean pairs must pass.
    start, end = snapshots()
    profile = load_profile("xbox16")
    events = []
    seq = 4
    for binding in profile.digital:
        for _ in range(5):
            for state in ("down", "up"):
                events.append({
                    "eventSeq": seq, "type": "input.marker.raw",
                    "data": {
                        "key": binding.key, "virtualKey": binding.virtual_key,
                        "state": state, "controlId": binding.control_id,
                        "layoutId": profile.layout_id,
                        "mappingSource": "configuredLayout",
                        "suppressed": True,
                    },
                })
                seq += 1
    end["maxSeq"] = seq - 1
    output = reporter.analyze(events=events, start=start, end=end, quick_check="ok")
    assert output["status"] == "PENDING_OWNER_REVIEW"
    assert output["summary"]["FAIL"] == 0
    assert all(x["result"] == "PASS" and x["actual"]["pairCount"] == 5 for x in output["matrix"])
    assert output["physicallyVerified"] == 0


def test_reporter_rejects_duplicate_down_and_unsuppressed_edges_even_with_multiple_presses():
    start, end = snapshots()
    rows = captured_rows()
    profile = load_profile("xbox16")
    a = next(binding for binding in profile.digital if binding.control_id == "A")
    rows.extend([
        {"eventSeq": 40, "type": "input.marker.raw", "data": {
            "controlId": "A", "key": a.key, "virtualKey": a.virtual_key,
            "state": "down", "layoutId": profile.layout_id,
            "mappingSource": "configuredLayout", "suppressed": True}},
        {"eventSeq": 41, "type": "input.marker.raw", "data": {
            "controlId": "A", "key": a.key, "virtualKey": a.virtual_key,
            "state": "down", "layoutId": profile.layout_id,
            "mappingSource": "configuredLayout", "suppressed": True}},
        {"eventSeq": 42, "type": "input.marker.raw", "data": {
            "controlId": "A", "key": a.key, "virtualKey": a.virtual_key,
            "state": "up", "layoutId": profile.layout_id,
            "mappingSource": "configuredLayout", "suppressed": True}},
    ])
    end["maxSeq"] = 42
    result = reporter.analyze(events=rows, start=start, end=end, quick_check="ok")
    assert result["status"] == "FAIL"
    assert next(x for x in result["matrix"] if x["controlId"] == "A")["result"] == "FAIL"

    rows[-2]["data"]["state"] = "up"
    rows[-1]["data"]["state"] = "up"
    rows[-1]["data"]["suppressed"] = False
    result = reporter.analyze(events=rows, start=start, end=end, quick_check="ok")
    assert next(x for x in result["matrix"] if x["controlId"] == "A")["result"] == "FAIL"
