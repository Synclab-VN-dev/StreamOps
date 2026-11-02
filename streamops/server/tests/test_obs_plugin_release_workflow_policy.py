"""Manual publishing security spans the trusted wrapper and product-owned contract."""
from pathlib import Path
import ast
import yaml
import importlib.util
import json
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT/'.github/workflows/main.yml'
PRODUCT = ROOT/'util/obs-multi-rtmp-websocket/ci.release.py'

def test_manual_release_must_be_explicit_and_publish_gate_fail_closed():
    job=yaml.safe_load(WORKFLOW.read_text())['jobs']['external_publish']
    assert "github.event_name == 'workflow_dispatch'" in job['if']
    assert "inputs.operation == 'publish'" in job['if']
    assert "github.ref == 'refs/heads/master'" in job['if']
    assert ' || ' not in job['if']
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


def load_product():
    spec=importlib.util.spec_from_file_location('obs_release_policy',PRODUCT)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('event,ref,intent',[
    ('pull_request','refs/heads/master','publish'),
    ('push','refs/heads/master','publish'),
    ('workflow_dispatch','refs/heads/feature/topic','publish'),
    ('workflow_dispatch','refs/tags/v1.2.3','publish'),
    ('workflow_dispatch','refs/heads/master','build'),
])
def test_product_rejects_non_manual_master_before_build_or_artifact(event,ref,intent):
    ctx=SimpleNamespace(intent=intent,env={'GITHUB_EVENT_NAME':event,'GITHUB_REF':ref})
    with pytest.raises(ValueError,match='OBS_PUBLICATION_REQUIRES_MANUAL_MASTER'):
        load_product().validate_publication(ctx)


@pytest.mark.parametrize('version,obs,expected',[
    ('0.7.4.3','32.2.1',None),
    ('0.7.4','32.2.1','OBS_RELEASE_VERSION_REQUIRED'),
    ('0.7.4.4','32.2.1','OBS_RELEASE_VERSION_OR_COMPATIBILITY_MISMATCH'),
    ('0.7.4.3','31.0.0','OBS_RELEASE_VERSION_OR_COMPATIBILITY_MISMATCH'),
])
def test_product_validates_exact_version_and_obs_compatibility(tmp_path,version,obs,expected):
    path=tmp_path/'util/obs-multi-rtmp-websocket/buildspec.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'version':'0.7.4.3','dependencies':{'obs-studio':{'version':obs}}}))
    ctx=SimpleNamespace(root=tmp_path,version=version,intent='publish',
        env={'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_REF':'refs/heads/master'})
    product=load_product()
    if expected:
        with pytest.raises(ValueError,match=expected):product.validate_publication(ctx)
    else:product.validate_publication(ctx)


def test_wrapper_has_no_obs_regression_commands_and_owner_selects_suite():
    workflow=WORKFLOW.read_text()
    assert 'pytest' not in workflow
    assert 'streamops/server/tests/' not in workflow
    assert 'util/obs-multi-rtmp-websocket' not in workflow
    assert 'util/obs-multi-rtmp-websocket' not in (WORKFLOW.parent/'ci.py').read_text()
    contract=ROOT/'util/obs-multi-rtmp-websocket/ci.test.py'
    spec=importlib.util.spec_from_file_location('obs_test_owner',contract)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    calls=[]
    ctx=SimpleNamespace(job={'id':'regression'},isolated_python=lambda:None,
                        python=lambda *args:calls.append(args))
    module.run(ctx)
    assert calls[-1]==('-m','pytest','-q',
        'streamops/server/tests/test_obs_plugin_release_workflow_policy.py',
        'streamops/server/tests/test_obs_plugin_release_harness.py')
    assert str(Path(__file__).relative_to(ROOT)) in module.CI_SPEC['watch']
