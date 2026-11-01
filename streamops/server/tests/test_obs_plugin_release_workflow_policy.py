"""Manual publishing security spans the trusted wrapper and product-owned contract."""
from pathlib import Path
import ast
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT/'.github/workflows/main.yml'
PRODUCT = ROOT/'util/obs-multi-rtmp-websocket/ci.release.py'

def test_manual_release_must_be_explicit_and_publish_gate_fail_closed():
    job=yaml.safe_load(WORKFLOW.read_text())['jobs']['external_publish']
    assert "github.event_name == 'workflow_dispatch'" in job['if']
    assert "inputs.operation == 'publish'" in job['if']
    for ref in ('refs/heads/master','refs/heads/feat/issue-47-obs-plugin-manager'):
        assert ref in job['if']
    assert job['environment']=='obs-plugin-release'
    assert job['permissions']=={'contents':'read'}
    assert 'read' in job['needs']

def test_pr_and_push_never_get_release_token_or_publish_artifacts():
    data=yaml.safe_load(WORKFLOW.read_text())
    assert data['permissions']=={'contents':'read'}
    read=str(data['jobs']['read'])
    assert 'secrets.' not in read and 'CI_PUBLISH_TOKEN' not in read
    assert 'SYNCLAB_OBS_RELEASE_TOKEN' not in read
    publisher=str(data['jobs']['external_publish'])
    assert 'secrets.SYNCLAB_OBS_RELEASE_TOKEN' in publisher
    assert 'pull_request_target' not in WORKFLOW.read_text()
    source=PRODUCT.read_text()
    assert "ctx.intent=='publish'" in source
    assert source.index("ctx.intent=='publish'") < source.index('--release-approved')

def test_manual_reviewed_manifest_provenance_and_roundtrip_integrity():
    source=PRODUCT.read_text()
    for requirement in ('--release-approved','--require-approved','--expected-commit','--expected-version',
                        'cmp -s','-type f | wc -l','gh release view "$tag"','--draft','--draft=false',
                        "ctx.build_artifact('reviewed')",'Synclab-VN-dev/StreamOps-OBS-Plugins'):
        assert requirement in source
    assert source.index('cmp -s') < source.index('--draft=false')
    assert source.index('Verify release source and payload before credentials') < source.index('gh release create')
    declaration=next(n for n in ast.parse(source).body if isinstance(n,ast.Assign))
    jobs=ast.literal_eval(declaration.value)['jobs']
    assert jobs[0].get('capability','read')=='read'
    assert jobs[1]['capability']=='external-publish'

def test_legacy_two_step_publisher_workflows_are_retired():
    for name in ('obs-plugin-managed-release.yml','obs-plugin-promote-release.yml','obs-multi-rtmp-build.yml'):
        assert not (WORKFLOW.parent/name).exists()
