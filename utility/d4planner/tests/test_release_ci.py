"""Release workflow safety/validation tests. Not a dispatched Actions run."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import release_ci as ci

HEAD='a'*40


def distribution():
    return {'sourceHead':HEAD,'version':'1.0.3','approvedBy':'TrdHuy','approvalRef':'owner-approval-test',
            'publicDistributionApproved':True,'licensesVerified':True,
            'snapshotManifestSha256':ci.delivery.load_json(ci.LOCK)['files']['snapshots/maxroll-20261023T034150Z/manifest.json']}


def test_distribution_requires_explicit_exact_source_and_snapshot_permission():
    ci.distribution_approved(distribution(),HEAD,'1.0.3')
    for patch in ({'sourceHead':'b'*40},{'version':'1.0.1'},{'approvedBy':'synclab-automation-system'},
                  {'publicDistributionApproved':False},{'licensesVerified':False},{'snapshotManifestSha256':'0'*64}):
        with pytest.raises(ValueError): ci.distribution_approved({**distribution(),**patch},HEAD,'1.0.3')
    with pytest.raises(ValueError): ci.distribution_approved({},HEAD,'1.0.3')


def test_release_acceptance_attestation_is_exact_artifact_and_all_gates():
    metadata={'sourceHead':HEAD,'version':'1.0.3','sha256':'c'*64}
    approval={**metadata,'approvedBy':'TrdHuy','approvalRef':'owner-test','gates':dict.fromkeys(ci.GATES,'PASS')}
    ci.release_approved(approval,metadata)
    for gate in ci.GATES:
        with pytest.raises(ValueError,match='MANDATORY_RELEASE_GATES'):
            ci.release_approved({**approval,'gates':{**approval['gates'],gate:'BLOCKED'}},metadata)
    for field in metadata:
        with pytest.raises(ValueError,match='RELEASE_APPROVAL_BINDING'):
            ci.release_approved({**approval,field:'different'},metadata)


def test_environment_cannot_be_unprotected_or_approved_by_automation():
    rule={'type':'required_reviewers','prevent_self_review':True,'reviewers':[{'type':'User','reviewer':{'login':'TrdHuy'}}]}
    ci.protected_environment({'protection_rules':[rule]})
    for document in ({},{'protection_rules':[]},{'protection_rules':[{**rule,'prevent_self_review':False}]},
                     {'protection_rules':[{**rule,'reviewers':[{'type':'User','reviewer':{'login':'synclab-automation-system'}}]}]}):
        with pytest.raises(ValueError): ci.protected_environment(document)


@pytest.mark.parametrize('release_version',['1','v1.0.0','1.0.0-rc.1','01.0.0','1.2.3; echo bad','1.2.3\n'])
def test_versions_fail_before_build_or_publish(release_version):
    with pytest.raises(ci.InstallError,match='INVALID_RELEASE_VERSION'): ci.version(release_version)


def test_private_inputs_are_pinned_and_fail_on_tampering(tmp_path,monkeypatch):
    lock={'versions':{'test':'pinned'},'files':{}}
    required=('nsis/makensis.exe','config/maxroll-profile.json','python/python312._pth','python/python312.zip')
    entries=[]
    for name in required:
        file=tmp_path/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(b'unit-input-not-windows-acceptance')
        entries.append({'path':name,'sha256':ci.delivery.sha256_file(file)})
    manifest={'schemaVersion':'d4planner-private-build-inputs/v1','versions':lock['versions'],'files':entries}
    (tmp_path/'inputs-manifest.json').write_text(json.dumps(manifest))
    lock_path=tmp_path/'lock.json';lock_path.write_text(json.dumps(lock));monkeypatch.setattr(ci,'LOCK',lock_path)
    # Keep test lock outside the archive root, as production does.
    root=tmp_path/'input';root.mkdir()
    for name in required:
        dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((tmp_path/name).read_bytes())
    (root/'inputs-manifest.json').write_text(json.dumps(manifest))
    ci.validate_inputs(root)
    (root/'python/python312.zip').write_bytes(b'tampered')
    with pytest.raises(ValueError,match='PRIVATE_INPUT_INTEGRITY'):ci.validate_inputs(root)


def test_workflow_is_single_dispatch_build_without_unconditional_publish():
    text=(ci.ROOT/'.github/workflows/d4planner-release.yml').read_text()
    assert 'name: D4Planner Release' in text
    assert 'workflow_dispatch:' in text and 'default: true' in text
    assert 'environment: d4planner-release' in text
    assert 'if: ${{ !inputs.build_only }}' in text
    assert 'ref: ${{ github.sha }}' in text
    assert 'artifact-ids: ${{ needs.build.outputs.artifact_id }}' in text
    assert 'if-no-files-found: error' in text


def test_exact_artifact_verification_rejects_changes_and_wrong_source(tmp_path):
    artifact=tmp_path/'D4Planner-Setup-1.0.3.exe';artifact.write_bytes(b'unit-checksum-test-not-a-native-setup')
    metadata={'schemaVersion':'d4planner-setup-build/v1','artifact':artifact.name,'version':'1.0.3',
              'sourceHead':HEAD,'bytes':artifact.stat().st_size,'sha256':ci.delivery.sha256_file(artifact)}
    (tmp_path/'release-metadata.json').write_text(json.dumps(metadata))
    ci.verify_built_artifact(tmp_path,HEAD,'1.0.3',metadata['sha256'])
    with pytest.raises(ValueError,match='PUBLISH_SOURCE_VERSION_MISMATCH'):
        ci.verify_built_artifact(tmp_path,'b'*40,'1.0.3',metadata['sha256'])
    artifact.write_bytes(b'tampered')
    with pytest.raises(ValueError,match='PUBLISH_ARTIFACT_INTEGRITY'):
        ci.verify_built_artifact(tmp_path,HEAD,'1.0.3',metadata['sha256'])


@pytest.mark.parametrize('url,digest,error',[
    ('http://private.example/input.zip','0'*64,'HTTPS_PRIVATE_INPUT_REQUIRED'),
    ('https://private.example/input.zip','','PINNED_INPUT_SHA256_REQUIRED'),
])
def test_download_fails_before_network_without_transport_and_integrity_pin(tmp_path,url,digest,error):
    with pytest.raises(ValueError,match=error):ci.download_inputs(url,digest,tmp_path/'inputs')
