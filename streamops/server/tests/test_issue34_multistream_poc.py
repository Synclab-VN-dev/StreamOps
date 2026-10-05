from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "e2e" / "issue34_multistream_poc.py"
spec = importlib.util.spec_from_file_location("issue34_multistream_poc", SCRIPT)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def targets():
    return (
        m.Target("issue34-a", "rtmp://127.0.0.1:19351/live", "secret-a"),
        m.Target("issue34-b", "rtmp://127.0.0.1:19352/live", "secret-b"),
    )


def test_independent_mapping_preserves_unrelated():
    a, b = targets()
    original = {
        "targets": [{"id": "keep"}, {"id": "issue34-old"}],
        "video_configs": [{"id": "keep-v"}],
        "audio_configs": [{"id": "keep-a"}],
        "other": 1,
    }
    result = m.build_config(original, a, b, mode="independent", encoder="obs_nvenc_h264_tex")
    assert original["targets"][1]["id"] == "issue34-old"
    assert result["other"] == 1
    assert [x["id"] for x in result["targets"] if not x["id"].startswith("issue34-")] == ["keep"]
    assert m.validate_mapping(result, "independent")
    videos = [x for x in result["video_configs"] if x["id"].startswith("issue34-")]
    assert {x["encoder"] for x in videos} == {"obs_nvenc_h264_tex"}


def test_shared_mapping_reuses_obs_encoder():
    a, b = targets()
    result = m.build_config({"targets": [], "video_configs": [], "audio_configs": []}, a, b, mode="shared")
    assert m.validate_mapping(result, "shared")
    managed = [x for x in result["targets"] if x["id"].startswith("issue34-")]
    assert {x["video-config"] for x in managed} == {m.OBS_ENCODER}


def test_bad_shared_mapping_fails():
    a, b = targets()
    result = m.build_config({"targets": [], "video_configs": [], "audio_configs": []}, a, b, mode="shared")
    result["targets"][1]["video-config"] = "bad"
    assert not m.validate_mapping(result, "shared")


def test_ffprobe_eval_pass_and_fail():
    good = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "r_frame_rate": "60/1"},
            {"codec_type": "audio", "codec_name": "aac"},
        ]
    }
    assert all(x.status == "PASS" for x in m.eval_ffprobe(good, 1920, 1080, 60.0))

    bad = {
        "streams": [
            {"codec_type": "video", "codec_name": "hevc", "width": 1280, "height": 720, "r_frame_rate": "30/1"}
        ]
    }
    checks = {x.name: x for x in m.eval_ffprobe(bad, 1920, 1080, 60.0)}
    assert checks["AUDIO_PRESENT"].status == "FAIL"
    assert checks["VIDEO_CODEC"].status == "FAIL"
    assert checks["VIDEO_RESOLUTION"].status == "FAIL"
    assert checks["VIDEO_FPS"].status == "FAIL"


def test_sanitize_redacts_secret_fields_and_strings():
    result = m.sanitize(
        {"key": "secret-a", "url": "rtmp://x/secret-a", "nested": [{"token": "abc"}, "secret-b"]},
        ["secret-a", "secret-b"],
    )
    assert result["key"] == "[REDACTED]"
    assert "secret-a" not in result["url"]
    assert result["nested"][0]["token"] == "[REDACTED]"
    assert result["nested"][1] == "[REDACTED]"


def test_metrics_summary():
    samples = [
        m.Sample(0, 10, 100 * 1024 * 1024, 1_000_000, 20, None),
        m.Sample(1, 10.8, 120 * 1024 * 1024, 2_000_000, 30, 40),
        m.Sample(2, 11.6, 110 * 1024 * 1024, 3_000_000, 40, 50),
    ]
    result = m.summarize(samples, cpus=8)
    assert result["obs_cpu_percent"]["avg"] == 10.0
    assert result["network_tx_mbps"]["avg"] == 8.0
    assert result["gpu_util_percent"]["avg"] == 30.0
    assert result["encoder_util_percent"]["avg"] == 45.0


def test_load_config_bom_and_missing():
    assert m.load_config(None) == {"targets": [], "video_configs": [], "audio_configs": []}
    raw = ("\ufeff" + '{"targets":[],"video_configs":[],"audio_configs":[]}').encode()
    assert m.load_config(raw)["targets"] == []


def test_target_path():
    target = m.Target("x", "rtmp://127.0.0.1:19351/live", "abc")
    assert target.path == "live/abc"
    assert target.url == "rtmp://127.0.0.1:19351/live/abc"


def test_strip_managed_preserves_foreign():
    original = {
        "targets": [{"id": "keep"}, {"id": "issue34-old"}],
        "video_configs": [{"id": "keep-v"}, {"id": "issue34-v"}],
        "audio_configs": [{"id": "keep-a"}, {"id": "issue34-a"}],
    }
    result = m.strip_managed(original)
    assert result["targets"] == [{"id": "keep"}]
    assert result["video_configs"] == [{"id": "keep-v"}]
    assert result["audio_configs"] == [{"id": "keep-a"}]
    assert len(original["targets"]) == 2


def test_publisher_snapshot_detects_zero_one_duplicate_and_ignores_other_paths():
    assert m.publisher_snapshot({"items": []}, "live/a") == {"count": 0, "bytes": 0}
    assert m.publisher_snapshot(
        {"items": [{"state": "publish", "path": "live/a", "bytesReceived": 100}]},
        "live/a",
    ) == {"count": 1, "bytes": 100}

    payload = {
        "items": [
            {"state": "publish", "path": "live/a", "bytesReceived": 100},
            {"state": "publish", "path": "/live/a/", "bytesReceived": 200},
            {"state": "publish", "path": "live/b", "bytesReceived": 300},
            {"state": "read", "path": "live/a", "bytesReceived": 999},
        ]
    }
    assert m.publisher_snapshot(payload, "live/a") == {"count": 2, "bytes": 300}


def test_fault_isolation_requires_a_to_continue_and_media_to_stay_valid():
    passing = [m.Result("VIDEO_PRESENT", "PASS", "ok"), m.Result("AUDIO_PRESENT", "PASS", "ok")]
    failing = [m.Result("VIDEO_PRESENT", "FAIL", "missing")]
    assert m.fault_isolation_ok({"count": 1, "bytes": 100}, {"count": 1, "bytes": 200}, passing)
    assert not m.fault_isolation_ok({"count": 1, "bytes": 100}, {"count": 0, "bytes": 200}, passing)
    assert not m.fault_isolation_ok({"count": 1, "bytes": 100}, {"count": 1, "bytes": 100}, passing)
    assert not m.fault_isolation_ok({"count": 1, "bytes": 100}, {"count": 1, "bytes": 200}, failing)


def test_restore_file_restores_existing_and_removes_new_file(tmp_path):
    path = tmp_path / "obs-multi-rtmp.json"
    m.restore_file(path, b'{"baseline":true}')
    assert path.read_bytes() == b'{"baseline":true}'
    m.restore_file(path, None)
    assert not path.exists()


def test_runner_failure_path_still_calls_restore():
    runner = object.__new__(m.Runner)
    runner.results = []
    runner.secrets = ()
    calls = []
    runner.baseline = lambda: (_ for _ in ()).throw(m.PocError("boom"))
    runner.restore = lambda: calls.append("restore")
    runner.write = lambda: 1
    assert runner.run() == 1
    assert calls == ["restore"]
    assert runner.results[-1].name == "UNEXPECTED_ERROR"


def test_sample_tolerates_missing_optional_system_metrics(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise OSError("tool unavailable")
    monkeypatch.setattr(m.subprocess, "run", unavailable)
    result = m.sample()
    assert result.gpu is None
    assert result.enc is None


def test_overall_status_ignores_optional_skip_but_honors_limitation_and_fail():
    assert m.overall_status([m.Result("optional", "SKIP", "not required")]) == "PASS"
    assert m.overall_status([m.Result("share", "LIMITATION", "unsupported")]) == "PASS WITH LIMITATION"
    assert m.overall_status([
        m.Result("share", "LIMITATION", "unsupported"),
        m.Result("core", "FAIL", "broken"),
    ]) == "FAIL"


def test_shared_mode_failure_is_limitation_when_obs_remains_healthy():
    class Http:
        @staticmethod
        def get(_path):
            return {"state": "READY", "websocket": {"connected": True}}

    runner = object.__new__(m.Runner)
    runner.results = []
    runner.secrets = ()
    runner.args = type("Args", (), {"cycles": 3})()
    runner.http = Http()
    runner.check_identity = lambda: None

    def fail_shared(_mode, _cycles):
        runner.results.append(m.Result("shared_1_VIDEO_PRESENT", "FAIL", "shared output invalid"))
        raise m.PocError("encoder reuse unavailable")

    runner.mode = fail_shared
    runner.shared_mode()

    assert runner.results[0].status == "LIMITATION"
    assert runner.results[-1].name == "AC-A-09_ENCODER_SHARE"
    assert runner.results[-1].status == "LIMITATION"
    assert m.overall_status(runner.results) == "PASS WITH LIMITATION"


def test_fixture_restore_preserves_unrelated_plugin_and_scene_state(tmp_path):
    a, b = targets()
    scene_dir = tmp_path / "scenes"
    scene_dir.mkdir()
    scene_file = scene_dir / "Untitled.json"
    scene_file.write_text('{"scene":"baseline"}', encoding="utf-8")
    scene_before = m.hashes(scene_dir)

    baseline = {
        "targets": [{"id": "keep-target", "name": "operator"}],
        "video_configs": [{"id": "keep-video", "encoder": "keep"}],
        "audio_configs": [{"id": "keep-audio", "encoder": "keep"}],
        "operator_metadata": {"profile": "Untitled", "nested": [1, 2, 3]},
    }
    raw = json.dumps(baseline, sort_keys=True).encode("utf-8")
    config_path = tmp_path / "obs-multi-rtmp.json"
    config_path.write_bytes(raw)

    generated = m.build_config(baseline, a, b, mode="independent")
    assert generated["operator_metadata"] == baseline["operator_metadata"]
    assert any(x.get("id") == "keep-target" for x in generated["targets"])

    config_path.write_text(json.dumps(generated), encoding="utf-8")
    m.restore_file(config_path, raw)

    assert config_path.read_bytes() == raw
    assert m.hashes(scene_dir) == scene_before


def test_config_snapshot_sanitize_redacts_stream_keys():
    a, b = targets()
    config = m.build_config(
        {"targets": [], "video_configs": [], "audio_configs": []},
        a,
        b,
        mode="independent",
    )
    sanitized = m.sanitize(config, ("secret-a", "secret-b"))
    serialized = json.dumps(sanitized)
    assert "secret-a" not in serialized
    assert "secret-b" not in serialized
    assert serialized.count("[REDACTED]") >= 2


def test_write_reports_all_resource_modes_and_redacts_outputs(tmp_path, capsys):
    secret = "issue34-super-secret"
    runner = object.__new__(m.Runner)
    runner.args = type("Args", (), {"evidence": tmp_path})()
    runner.results = []
    runner.secrets = (secret,)
    runner.metrics = {
        "idle": {"marker": secret, "obs_cpu_percent": {"avg": 1}},
        "main-only": {"rtmp_output_mbps": 6.0},
        "independent": [{"rtmp_output_mbps": 26.0}],
        "shared": [{"rtmp_output_mbps": 25.0}],
    }
    runner.identity = {"profile": secret, "collection": "Untitled"}
    runner.probes = {
        "shared-1-a": {
            "streams": [{"codec_type": "video", "codec_name": "h264"}],
            "url": f"rtmp://127.0.0.1/live/{secret}",
            "key": secret,
        }
    }
    runner.record("ERROR_PATH", "PASS", f"error detail contained {secret}")

    assert runner.write() == 0

    captured = capsys.readouterr()
    result_text = (tmp_path / "result.json").read_text(encoding="utf-8")
    report_text = (tmp_path / "report.md").read_text(encoding="utf-8")
    probe_text = (tmp_path / "ffprobe-shared-1-a.json").read_text(encoding="utf-8")
    combined = result_text + report_text + probe_text + captured.out + captured.err

    assert secret not in combined
    for mode in ("idle", "main-only", "independent", "shared"):
        assert f"- {mode}:" in report_text

    payload = json.loads(result_text)
    assert set(payload["metrics"]) == {"idle", "main-only", "independent", "shared"}
    assert payload["identity"]["profile"] == "[REDACTED]"


def test_http_error_path_redacts_secret(monkeypatch):
    secret = "issue34-http-secret"

    def fail(*_args, **_kwargs):
        raise m.URLError(f"network failed for {secret}")

    monkeypatch.setattr(m, "urlopen", fail)
    client = m.Http("http://127.0.0.1:1", (secret,), 0.1)

    with pytest.raises(m.PocError) as exc:
        client.get("/failure")

    assert secret not in str(exc.value)
    assert "[REDACTED]" in str(exc.value)


def test_failure_evidence_survives_cleanup_result():
    runner = object.__new__(m.Runner)
    runner.results = []
    runner.secrets = ()
    runner.baseline = lambda: (_ for _ in ()).throw(m.PocError("primary failure"))
    runner.restore = lambda: runner.record("AC-A-12_RESTORE", "PASS", "cleanup succeeded")
    runner.write = lambda: 1

    assert runner.run() == 1

    by_name = {item.name: item for item in runner.results}
    assert by_name["UNEXPECTED_ERROR"].status == "FAIL"
    assert by_name["AC-A-12_RESTORE"].status == "PASS"
    assert m.overall_status(runner.results) == "FAIL"
