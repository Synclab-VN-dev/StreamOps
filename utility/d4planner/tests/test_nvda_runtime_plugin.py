from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_nvda_runtime_plugin_uses_filter_hook_not_pre_speech_action():
    source = (
        ROOT
        / "nvda-addon"
        / "addon"
        / "globalPlugins"
        / "d4plannerCapture"
        / "__init__.py"
    ).read_text(encoding="utf-8")

    assert "filter_speechSequence.register" in source
    assert "filter_speechSequence.unregister" in source
    assert "pre_speech.register" not in source
    assert "return [] if decision.suppress else original" in source


def test_addon_manifest_matches_runtime_version():
    manifest = (ROOT / "nvda-addon" / "manifest.ini").read_text(encoding="utf-8")
    assert 'version = "0.2.0"' in manifest


def test_runtime_plugin_has_fail_open_lease_guard():
    source = (
        ROOT
        / "nvda-addon"
        / "addon"
        / "globalPlugins"
        / "d4plannerCapture"
        / "__init__.py"
    ).read_text(encoding="utf-8")
    assert "leaseUntilUnix" in source
    assert "lease_until <= time.time()" in source


def test_runtime_plugin_uses_live_win32_pid_and_never_rejected_speech_text_in_diagnostics():
    source = (
        ROOT
        / "nvda-addon"
        / "addon"
        / "globalPlugins"
        / "d4plannerCapture"
        / "__init__.py"
    ).read_text(encoding="utf-8")
    assert "winUser.getForegroundWindow()" in source
    assert "winUser.getWindowThreadProcessID(hwnd)" in source
    assert 'context_source="win32Foreground"' in source
    diagnostic_body = source.split("def _write_rejection_diagnostic", 1)[1].split(
        "def _filter_speech", 1
    )[0]
    assert "speechSequence" not in diagnostic_body


def test_nvda_action_probe_is_debug_only_and_fail_open():
    source = (
        ROOT
        / "nvda-addon"
        / "addon"
        / "globalPlugins"
        / "d4plannerCapture"
        / "__init__.py"
    ).read_text(encoding="utf-8")

    for handler in (
        "event_gainFocus",
        "event_stateChange",
        "event_nameChange",
        "event_valueChange",
        "event_descriptionChange",
        "event_UIA_notification",
    ):
        assert handler in source

    assert "nvda-action-probe.json" in source
    assert "nvda-action-probe.jsonl" in source
    assert "nextHandler()" in source
    assert 'config.get("enabled")' in source
    assert "D4Planner: NVDA action probe failed" in source

    probe_body = source.split(
        "def _write_action_probe_event", 1
    )[1].split("def _filter_speech", 1)[0]
    assert "character.db" not in probe_body
