from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "utility/d4planner/tools/production_e2e.py"
spec = importlib.util.spec_from_file_location("production_e2e", TOOL)
production = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(production)


def test_performance_requires_native_capture_to_visible_evidence(tmp_path):
    args = argparse.Namespace(native_latency=tmp_path / "missing.json")
    with pytest.raises(production.E2EFailure, match="latency evidence is missing"):
        production.run_performance(args)


def test_performance_accepts_all_five_measured_stages(tmp_path):
    stages = {
        name: {
            "sampleCount": 2, "samplesMilliseconds": [1.0, 2.0],
            "p50Milliseconds": 1.5, "p95Milliseconds": 1.95,
        }
        for name in (
            "captureToAssessment", "assessmentToSqliteCommit", "commitToWsDelivery",
            "wsToHudModel", "hudModelToVisibleRender",
        )
    }
    source = tmp_path / "latency.json"
    source.write_text(json.dumps({
        "schemaVersion":"d4planner-latency-evidence/v1", "ok":True,
        "sla":"NOT_DEFINED_AS_APPROVED", **stages,
    }))
    result = production.run_performance(argparse.Namespace(native_latency=source))
    assert result["ok"] is True
    assert result["classification"] == "NATIVE_CAPTURE_TO_VISIBLE_STAGE_LATENCY"
    assert result["hudModelToVisibleRender"]["sampleCount"] == 2


def test_native_evidence_timestamp_parser_is_timezone_aware():
    value = production._parse_timestamp("2026-10-26T06:00:00Z")
    assert value.utcoffset().total_seconds() == 0
