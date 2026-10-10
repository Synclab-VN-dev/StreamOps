"""Pinned MagicPath originals are immutable, version-checked source references.

This suite is independent of React/Vite and runs as part of normal pytest.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "visual_magicpath"
MANIFEST = ROOT / "manifest.json"
EXPECTED_REVISIONS = {
    "steam": ("459507753589833728", "459530030574370816"),
    "games": ("459507767749795840", "459530038539325440"),
}
EXPECTED_VIEWPORTS = {(360, 800), (390, 844), (768, 1024), (1440, 900)}


def git_blob_sha1(content: bytes) -> str:
    return hashlib.sha1(f"blob {len(content)}\0".encode("ascii") + content).hexdigest()


def test_pinned_magicpath_originals_and_revisions() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["approved"] is False or manifest["approval"]["approved_by"] is not None
    assert manifest["approval"]["reference"]
    assert {(v["width"], v["height"]) for v in manifest["viewports"]} == EXPECTED_VIEWPORTS
    assert set(manifest["scenarios"]) == set(EXPECTED_REVISIONS)
    assert set(manifest["scenarios"]["steam"]) >= {"normal", "empty", "multi", "offline", "error"}
    assert set(manifest["scenarios"]["games"]) >= {"default", "multi", "empty", "offline", "loading", "stopTimeout"}

    assert len(manifest["references"]) == 2
    for ref in manifest["references"]:
        assert (ref["component_id"], ref["revision_id"]) == EXPECTED_REVISIONS[ref["name"]]
        for suffix in ("source", "preview"):
            path = ROOT.parents[3] / ref[f"{suffix}_path"]
            # ROOT is streamops/server/tests/visual_magicpath, so use repository root.
            assert path.exists(), path
            payload = path.read_bytes()
            assert git_blob_sha1(payload) == ref[f"{suffix}_git_blob_sha1"]
            assert len(payload) > (10000 if suffix == "preview" else 5000)
        assert "Diablo IV" in (ROOT.parents[3] / ref["source_path"]).read_text(encoding="utf-8")

    css = ROOT.parents[3] / manifest["css_path"]
    assert git_blob_sha1(css.read_bytes()) == manifest["css_git_blob_sha1"]


def test_design_reference_is_not_generated_from_production_ui() -> None:
    source = ROOT / "reference_source"
    assert (source / "src" / "SteamManager.tsx").is_file()
    assert (source / "src" / "GameManager.tsx").is_file()
    assert not (source / "src" / "games.js").exists()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert "single compressed preview" in manifest["intended_usage"] or "design-source reference" in manifest["intended_usage"]
    assert manifest["approved"] in (True, False)
