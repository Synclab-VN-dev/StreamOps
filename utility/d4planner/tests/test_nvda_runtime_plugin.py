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
