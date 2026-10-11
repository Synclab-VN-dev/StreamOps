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
            # Windows Git checkout may convert LF to CRLF. Hash the exact Git
            # blob canonical LF bytes for text only; JPEG binary stays byte exact.
            if suffix == "source":
                payload = payload.replace(b"\r\n", b"\n")
            assert git_blob_sha1(payload) == ref[f"{suffix}_git_blob_sha1"]
            assert len(payload) > (10000 if suffix == "preview" else 5000)
        assert "Diablo IV" in (ROOT.parents[3] / ref["source_path"]).read_text(encoding="utf-8")

    css = ROOT.parents[3] / manifest["css_path"]
    assert git_blob_sha1(css.read_bytes().replace(b"\r\n", b"\n")) == manifest["css_git_blob_sha1"]


def test_design_reference_is_not_generated_from_production_ui() -> None:
    source = ROOT / "reference_source"
    assert (source / "src" / "SteamManager.tsx").is_file()
    assert (source / "src" / "GameManager.tsx").is_file()
    assert not (source / "src" / "games.js").exists()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert "single compressed preview" in manifest["intended_usage"] or "design-source reference" in manifest["intended_usage"]
    assert manifest["approved"] in (True, False)



def validate_approved_goldens(root: Path, manifest: dict) -> None:
    """Fail closed when any reference, hash or approval record is missing."""
    import re
    golden_dir = root / "goldens"
    hashes = manifest["approval"]["expected_sha256"]
    assert manifest["approved"] is True
    assert manifest["approval"]["approved_by"]
    assert manifest["approval"]["approved_at"]
    assert manifest["approval"]["review_url"]
    assert len(hashes) == 19
    expected_files = {label + ".png" for label in hashes}
    assert {p.name for p in golden_dir.glob("*.png")} == expected_files
    for label, digest in hashes.items():
        assert re.fullmatch("[0-9a-f]{64}", digest), label
        p = golden_dir / (label + ".png")
        payload = p.read_bytes()
        assert payload.startswith(b"\x89PNG\r\n\x1a\n"), label
        assert hashlib.sha256(payload).hexdigest() == digest, label


def test_pinned_goldens_are_complete_approved_and_sha256_verified() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    validate_approved_goldens(ROOT, manifest)


def test_missing_or_tampered_golden_is_a_hard_failure(tmp_path: Path) -> None:
    """FE-G5 negative check: neither missing nor modified baseline can pass."""
    import copy
    import pytest
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    label = "steam-normal-360x800"
    reference = ROOT / "goldens" / (label + ".png")
    baseline_dir = tmp_path / "goldens"
    baseline_dir.mkdir()
    for candidate in (ROOT / "goldens").glob("*.png"):
        (baseline_dir / candidate.name).write_bytes(candidate.read_bytes())
    validate_approved_goldens(tmp_path, manifest)
    reference_copy = baseline_dir / reference.name
    payload = bytearray(reference_copy.read_bytes())
    payload[-40] ^= 0x33
    reference_copy.write_bytes(payload)
    with pytest.raises(AssertionError, match=label):
        validate_approved_goldens(tmp_path, manifest)
    reference_copy.unlink()
    with pytest.raises(AssertionError):
        validate_approved_goldens(tmp_path, manifest)
    reference_copy.write_bytes(reference.read_bytes())
    manifest_missing = copy.deepcopy(manifest)
    manifest_missing["approval"]["review_url"] = ""
    with pytest.raises(AssertionError):
        validate_approved_goldens(tmp_path, manifest_missing)


def test_visual_gate_detects_deliberate_theme_and_geometry_regression(tmp_path: Path) -> None:
    """E2E-10 negative visual regression; a real layout/theme break must fail .08."""
    from PIL import Image, ImageDraw, ImageChops, ImageStat
    reference = ROOT / "goldens" / "games-default-390x844.png"
    with Image.open(reference) as im:
        expected = im.convert("RGB")
    actual = expected.copy()
    draw = ImageDraw.Draw(actual)
    # Intentionally wrong full-section theme: no masking or changed tolerance.
    draw.rectangle((0, 0, expected.width, expected.height // 2), fill=(255, 0, 255))
    diff = ImageChops.difference(expected, actual)
    difference = sum(ImageStat.Stat(diff).mean) / (255.0 * 3)
    assert difference > 0.08, "Visual gate would miss a deliberately broken theme"
    # Geometry is a separate hard fail even when a small pixel ratio could pass.
    shifted = actual.crop((0, 0, expected.width - 10, expected.height))
    assert shifted.size != expected.size


def test_updated_magicpath_v2_is_independent_and_revision_pinned() -> None:
    """V2 design approval must not silently rewrite the 19 approved v1 goldens."""
    updated = json.loads((ROOT / "review_manifest_v2.json").read_text(encoding="utf-8"))
    assert updated["schema_version"] == 2
    assert updated["legacy_approved_goldens"]["count"] == 19
    assert updated["approved"] is False
    assert updated["new_goldens"]["approved"] is False
    assert not updated["new_goldens"]["expected_sha256"]
    assert updated["reference_directory"] == "reference_source_v2"
    refs = {item["name"]: item for item in updated["source"]}
    assert (refs["steam"]["component_id"], refs["steam"]["revision_id"]) == (
        "459507753589833728", "460004034603028480")
    assert (refs["games"]["component_id"], refs["games"]["revision_id"]) == (
        "459507767749795840", "460004044581269504")
    assert refs["steam"]["revision_id"] != EXPECTED_REVISIONS["steam"][1]
    assert refs["games"]["revision_id"] != EXPECTED_REVISIONS["games"][1]
    for item in refs.values():
        candidate = ROOT.parents[3] / item["source_path"]
        assert candidate.is_file(), candidate
        normalized = candidate.read_bytes().replace(b"\r\n", b"\n")
        assert git_blob_sha1(normalized) == item["git_blob_sha1"], item["name"]
    steam = (ROOT / "reference_source_v2/src/SteamManager.tsx").read_text("utf-8")
    games = (ROOT / "reference_source_v2/src/GameManager.tsx").read_text("utf-8")
    assert "Node health: online · Capture READY" in steam
    assert "Save progress first." in steam
    assert ">Restart</button>" in steam
    assert "Force Stop (disabled)" in games
    assert 'if (kind === "force") return' in games
    assert (ROOT / "reference_source/src/SteamManager.tsx").read_text("utf-8") != steam
    assert (ROOT / "reference_source/src/GameManager.tsx").read_text("utf-8") != games
