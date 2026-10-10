"""Fail-closed tests for the one-file manual-only managed plugin release policy.

Do not confuse the unapproved PR/push candidate with a published GitHub Release.
These checks deliberately use the standard library (no workflow YAML parser).
"""
from __future__ import annotations

from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[3]
    / ".github" / "workflows" / "obs-multi-rtmp-build.yml"
)


def workflow_parts() -> tuple[str, str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    build, separator, publish = text.partition("\n  publish:\n")
    assert separator, "Manual-only publish job is missing."
    assert "\n  windows-build:\n" in build
    return build, publish


def test_manual_release_must_be_explicit_and_publish_gate_fail_closed():
    build, publish = workflow_parts()
    assert "workflow_dispatch:" in build
    assert "publish_release:" in build
    assert "type: boolean" in build
    assert "default: false" in build
    assert "expected_version:" in build
    gate = (
        "github.event_name == 'workflow_dispatch' && "
        "inputs.publish_release == true"
    )
    assert "if: ${{ " + gate + " && (" in publish
    assert "refs/heads/feat/issue-47-obs-plugin-manager" in publish
    assert "refs/heads/master" in publish
    assert "environment: obs-plugin-release" in publish


def test_pr_and_push_never_get_release_token_or_publish_artifacts():
    build, publish = workflow_parts()
    assert "pull_request:" in build
    assert "push:" in build
    assert "permissions:\n  contents: read" in build
    assert "secrets.SYNCLAB_OBS_RELEASE_TOKEN" not in build
    assert "gh release create" not in build
    assert "gh release edit" not in build
    assert "secrets.SYNCLAB_OBS_RELEASE_TOKEN" in publish
    assert "gh release create" in publish
    assert "gh release edit" in publish
    assert "--draft" in publish
    assert "--draft=false" in publish


def test_manual_reviewed_manifest_provenance_and_roundtrip_integrity():
    build, publish = workflow_parts()
    guard = (
        "if: ${{ github.event_name == 'workflow_dispatch' && "
        "inputs.publish_release == true }}"
    )
    assert build.count(guard) == 3
    assert "--release-approved" in build
    assert "--require-approved" in build
    assert "obs-multi-rtmp-managed-candidate-" in build
    assert "obs-multi-rtmp-reviewed-candidate-" in build
    assert "obs-multi-rtmp-reviewed-candidate-" in publish
    assert "--require-approved" in publish
    assert "--expected-commit" in publish
    assert "cmp -s" in publish
    assert 'file | wc -l' in publish
    assert 'gh release view "$tag"' in publish


def test_legacy_two_step_publisher_workflows_are_retired():
    workflow_dir = WORKFLOW.parent
    assert not (workflow_dir / "obs-plugin-managed-release.yml").exists()
    assert not (workflow_dir / "obs-plugin-promote-release.yml").exists()
