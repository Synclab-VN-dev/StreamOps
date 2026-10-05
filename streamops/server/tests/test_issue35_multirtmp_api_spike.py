from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "e2e" / "issue35_multirtmp_api_spike.py"
spec = importlib.util.spec_from_file_location("issue35_multirtmp_api_spike", SCRIPT)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def test_sanitize_redacts_credentials_and_strings():
    secret = "issue35-secret-value"
    value = {
        "streamKey": secret,
        "newStreamKey": secret,
        "server": f"rtmp://local/live/{secret}",
        "nested": [{"password": secret}],
    }
    safe = m.sanitize(value, (secret,))
    text = json.dumps(safe)
    assert secret not in text
    assert safe["streamKey"] == "[REDACTED]"
    assert safe["newStreamKey"] == "[REDACTED]"
    assert safe["nested"][0]["password"] == "[REDACTED]"


def test_normalize_vendor_target_accepts_actual_candidate_fields():
    raw = {
        "id": "42",
        "name": "A",
        "isRunning": True,
        "status": "00:00:05  2.5 Mbps  60 FPS",
        "bitrateValue": 2_500_000,
        "fpsValue": 60,
        "syncStart": False,
        "syncStop": True,
    }
    value = m.normalize_vendor_target(raw)
    assert value["running"] is True
    assert value["bitrate_bps"] == 2_500_000
    assert value["fps"] == 60
    assert value["sync_stop"] is True


def test_normalize_vendor_target_accepts_readme_alias_fields():
    raw = {"id": "42", "name": "A", "streaming": True, "bitrate_bps": 1_000_000, "fps": 30}
    value = m.normalize_vendor_target(raw)
    assert value["running"] is True
    assert value["bitrate_bps"] == 1_000_000
    assert value["fps"] == 30


def test_stable_identity_requires_same_ids_for_named_targets():
    before = [{"id": "11", "name": "issue35-a"}, {"id": "22", "name": "issue35-b"}]
    after = [{"id": "22", "name": "issue35-b"}, {"id": "11", "name": "issue35-a"}]
    assert m.stable_identity(before, after, {"issue35-a", "issue35-b"})
    after[0]["id"] = "99"
    assert not m.stable_identity(before, after, {"issue35-a", "issue35-b"})


def test_duplicate_names_are_detected():
    targets = [
        {"id": "1", "name": "same"},
        {"id": "2", "name": "same"},
        {"id": "3", "name": "other"},
    ]
    assert m.duplicate_names(targets) == {"same"}


def test_native_output_groups_exposes_output_name_collision():
    outputs = [
        {"outputName": "multi-output", "outputKind": "multi-output"},
        {"outputName": "multi-output", "outputKind": "multi-output"},
        {"outputName": "adv_stream", "outputKind": "rtmp_output"},
    ]
    groups = m.native_output_groups(outputs)
    assert list(groups) == ["multi-output"]
    assert len(groups["multi-output"]) == 2


def test_build_native_fixture_preserves_unrelated_data_and_disables_sync():
    base = {
        "targets": [{"id": "keep", "name": "operator"}, {"id": "issue35-old"}],
        "video_configs": [{"id": "keep-v"}, {"id": "issue35-video-old"}],
        "audio_configs": [{"id": "keep-a"}],
        "metadata": {"preserve": True},
    }
    result = m.build_native_fixture(
        base,
        server_a="rtmp://127.0.0.1:19351/live",
        server_b="rtmp://127.0.0.1:19352/live",
        key_a="secret-a",
        key_b="secret-b",
    )
    assert result["metadata"] == {"preserve": True}
    assert any(x.get("id") == "keep" for x in result["targets"])
    owned = [x for x in result["targets"] if x.get("id", "").startswith("issue35-")]
    assert len(owned) == 2
    assert all(x["sync-start"] is False and x["sync-stop"] is False for x in owned)


def test_capability_template_is_complete():
    assert set(m.capability_template()) == {
        "list",
        "stable_target_identity",
        "start_one",
        "stop_one",
        "start_all",
        "stop_all",
        "add",
        "update",
        "delete",
        "live_failed_state",
        "stats_error",
        "credential_update",
        "secret_safe_response",
    }


def test_load_config_defaults_missing_arrays():
    value = m.load_config(b'{"metadata":1}')
    assert value["targets"] == []
    assert value["video_configs"] == []
    assert value["audio_configs"] == []
