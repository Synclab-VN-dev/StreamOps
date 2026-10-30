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
            'artifactClass':'D4PLANNER_APPLICATION_NO_SNAPSHOT','distributionFormat':'PLAINTEXT_EXE',
            'runtimeLockSha256':ci.delivery.sha256_file(ci.LOCK)}


def test_distribution_requires_explicit_application_permission_for_exact_source():
    ci.distribution_approved(distribution(),HEAD,'1.0.3')
    for patch in ({'sourceHead':'b'*40},{'version':'1.0.1'},{'approvedBy':'synclab-automation-system'},
                  {'publicDistributionApproved':False},{'licensesVerified':False},{'artifactClass':'PRIVATE_SNAPSHOT_BUNDLE'}):
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


def test_public_inputs_are_pinned_and_fail_on_tampering(tmp_path,monkeypatch):
    lock={'versions':{'test':'pinned'},'files':{}}
    required=('nsis/makensis.exe','python/python312._pth','python/python312.zip')
    entries=[]
    for name in required:
        file=tmp_path/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(b'unit-input-not-windows-acceptance')
        entries.append({'path':name,'sha256':ci.delivery.sha256_file(file)})
    manifest={'schemaVersion':'d4planner-public-build-inputs/v1','snapshotIncluded':False,'versions':lock['versions'],'files':entries}
    (tmp_path/'inputs-manifest.json').write_text(json.dumps(manifest))
    lock['publicInputsManifestSha256']=__import__('hashlib').sha256(json.dumps(manifest).encode()).hexdigest()
    lock_path=tmp_path/'lock.json';lock_path.write_text(json.dumps(lock));monkeypatch.setattr(ci,'LOCK',lock_path)
    # Keep test lock outside the archive root, as production does.
    root=tmp_path/'input';root.mkdir()
    for name in required:
        dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((tmp_path/name).read_bytes())
    (root/'inputs-manifest.json').write_text(json.dumps(manifest))
    # Isolate this test's file-integrity boundary; real runtime tree pin checks
    # run independently against the prepared production public inputs.
    monkeypatch.setattr(ci.public,'validate_tree',lambda *args,**kwargs:None)
    ci.validate_inputs(root)
    (root/'python/python312.zip').write_bytes(b'tampered')
    with pytest.raises(ValueError,match='PRIVATE_INPUT_INTEGRITY'):ci.validate_inputs(root)


def test_workflow_is_single_dispatch_build_without_unconditional_publish():
    text=(ci.ROOT/'.github/workflows/d4planner-release.yml').read_text()
    assert 'name: D4Planner Release' in text
    assert 'workflow_dispatch:' in text and 'default: true' in text
    assert 'environment: d4planner-release' in text
    assert "if: ${{ github.event_name == 'workflow_dispatch' && !inputs.build_only }}" in text
    assert 'd4planner-uat/v*' in text
    assert 'prepare-upload --channel' in text
    assert 'd4-release/build/verified-artifact/D4Planner-Setup-${{ env.RELEASE_VERSION }}.exe' in text
    assert 'if: always()' in text
    assert 'publish-uat --channel uat' in text
    assert 'ref: ${{ github.sha }}' in text
    assert 'artifact-ids: ${{ needs.build.outputs.artifact_id }}' in text
    assert 'if-no-files-found: error' in text


def test_exact_artifact_verification_rejects_changes_and_wrong_source(tmp_path):
    artifact=tmp_path/'D4Planner-Setup-1.0.3.exe';artifact.write_bytes(b'unit-checksum-test-not-a-native-setup')
    metadata={'schemaVersion':'d4planner-setup-build/v1','artifactClass':'D4PLANNER_APPLICATION_NO_SNAPSHOT','snapshotIncluded':False,'artifact':artifact.name,'version':'1.0.3',
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


def test_uat_is_explicit_and_does_not_bypass_distribution_or_stable_gates(tmp_path, monkeypatch):
    plan=tmp_path/"plan.json";plan.write_text(json.dumps({"version":"1.0.3"}))
    policy=tmp_path/"policy.json";policy.write_text(json.dumps({"uatRevision":1}))
    monkeypatch.setattr(ci,"PRODUCT_PLAN",plan);monkeypatch.setattr(ci,"UAT_POLICY",policy)
    ci.uat_context('d4planner-uat/v1.0.3-r1','1.0.3','synclab-automation-system')
    for tag,actor in [('v1.0.3','TrdHuy'),('d4planner-uat/v1.0.3-r1','untrusted')]:
        with pytest.raises(ValueError):ci.uat_context(tag,'1.0.3',actor)
    meta={'sourceHead':HEAD,'version':'1.0.3','sha256':'c'*64,'runtimeHealth':'PASS','encryption':'none','uatRevision':1,'releaseTag':'d4planner-uat/v1.0.3-r1'}
    policy={'schemaVersion':'d4planner-uat-distribution-policy/v2','scope':'D4PLANNER_R1_UAT',
            'applicationFormat':'PLAINTEXT_EXE','snapshotFormat':'AGE_ZIP_SEPARATE','uatRevision':1}
    ci.uat_approved(policy,meta)
    for change in ({'applicationFormat':'AGE_EXE'},{'snapshotFormat':'PLAINTEXT'},{'uatRevision':2},{'scope':'STABLE'}):
        with pytest.raises(ValueError):ci.uat_approved({**policy,**change},meta)
    with pytest.raises(ValueError):ci.uat_approved(policy,{**meta,'encryption':'age/v1'})
    with pytest.raises(ValueError):ci.release_approved(policy,meta)


def test_r1_visual_waiver_never_waives_other_stable_gates_or_releases():
    meta={'sourceHead':HEAD,'version':'1.0.3','sha256':'c'*64}
    approval={**meta,'approvedBy':'TrdHuy','approvalRef':'owner-test','releaseId':'R1-EQUIPMENT-20261025',
              'visualWaiver':'ISSUE158_R1_VISUAL_WAIVER_20261030','gates':{**dict.fromkeys(ci.GATES,'PASS'),'VISUAL_GOLDEN':'OWNER_WAIVED'}}
    ci.release_approved(approval,meta)
    for change in ({'releaseId':'R2'},{'gates':{**approval['gates'],'HUD-03':'OWNER_WAIVED'}},
                   {'gates':{**approval['gates'],'PKG-08':'NOT_RUN'}}):
        with pytest.raises(ValueError):ci.release_approved({**approval,**change},meta)


def test_encrypted_artifact_verifier_rejects_plaintext_and_extra_assets(tmp_path):
    import hashlib
    artifact=tmp_path/'D4Planner-Setup-1.0.3.exe.age'
    artifact.write_bytes(b'age-encryption.org/v1\nunit-test-ciphertext-not-native-evidence')
    digest=hashlib.sha256(artifact.read_bytes()).hexdigest()
    metadata={'schemaVersion':'d4planner-encrypted-setup/v1','encryption':'age/v1','artifact':artifact.name,
              'sourceHead':HEAD,'version':'1.0.3','sha256':digest,'bytes':artifact.stat().st_size,
              'snapshotIncluded':False,'artifactClass':'D4PLANNER_APPLICATION_NO_SNAPSHOT'}
    (tmp_path/'release-metadata.json').write_text(json.dumps(metadata))
    (tmp_path/'SHA256SUMS').write_text(digest);(tmp_path/'UAT.md').write_text('safe instructions')
    ci.verify_encrypted_artifact(tmp_path,HEAD,'1.0.3',digest)
    plain=tmp_path/'Setup.exe';plain.write_bytes(b'MZplaintext')
    with pytest.raises(ValueError,match='UNEXPECTED_PUBLIC_ASSET'):ci.verify_encrypted_artifact(tmp_path,HEAD,'1.0.3',digest)
    plain.unlink();artifact.write_bytes(b'MZtampered')
    with pytest.raises(ValueError,match='PUBLISH_ARTIFACT_INTEGRITY'):ci.verify_encrypted_artifact(tmp_path,HEAD,'1.0.3',digest)


def test_frontend_native_assets_generated_from_tracked_svg(tmp_path, monkeypatch):
    calls=[]
    def invoke(command, *, cwd):
        calls.append((command, cwd))
        icon=tmp_path/'src-tauri/icons/icon.ico'
        icon.parent.mkdir(parents=True)
        icon.write_bytes(b'\x00\x00\x01\x00\x01\x00' + b'icon-content')
    monkeypatch.setattr(ci, 'run', invoke)
    ci.prepare_frontend_native_assets(tmp_path, 'npm.cmd')
    assert calls == [(['npm.cmd', 'run', 'icon'], tmp_path)]
    (tmp_path/'src-tauri/icons/icon.ico').unlink()
    monkeypatch.setattr(ci, 'run', lambda *a, **kw: None)
    with pytest.raises(ValueError, match='WINDOWS_ICON_MISSING'):
        ci.prepare_frontend_native_assets(tmp_path, 'npm.cmd')


def test_product_version_and_uat_revision_are_independent(tmp_path, monkeypatch):
    plan=tmp_path/'plan.json';plan.write_text(json.dumps({'version':'1.2.8'}))
    monkeypatch.setattr(ci,'PRODUCT_PLAN',plan)
    assert ci.uat_tag('1.2.8',{'uatRevision':1})=='d4planner-uat/v1.2.8-r1'
    assert ci.uat_tag('1.2.8',{'uatRevision':2})=='d4planner-uat/v1.2.8-r2'
    with pytest.raises(ValueError,match='PRODUCT_VERSION_MISMATCH'):
        ci.uat_tag('1.2.9',{'uatRevision':1})
    for invalid in [0,-1,True,'1']:
        with pytest.raises(ValueError,match='INVALID_UAT_REVISION'):
            ci.uat_tag('1.2.8',{'uatRevision':invalid})


def test_plaintext_upload_requires_explicit_format_approval():
    # Existing ciphertext approval must never authorize a public executable.
    with pytest.raises(ValueError, match='PLAINTEXT'):
        ci.distribution_approved({k:v for k,v in distribution().items() if k!='distributionFormat'}, HEAD, '1.0.3')


def test_application_workflow_uploads_exe_only_after_gate():
    text=(ci.ROOT/'.github/workflows/d4planner-release.yml').read_text()
    assert 'prepare-upload --channel' in text
    assert 'validate-upload --channel' in text
    assert '.exe.age' not in text
    assert text.index('validate-upload --channel') < text.index('uses: actions/upload-artifact@')


def upload_fixture(tmp_path,monkeypatch):
    plan=tmp_path/'plan.json';plan.write_text(json.dumps({'version':'1.0.3'}));monkeypatch.setattr(ci,'PRODUCT_PLAN',plan)
    policy=tmp_path/'policy.json';policy.write_text(json.dumps({'schemaVersion':'d4planner-uat-distribution-policy/v2','scope':'D4PLANNER_R1_UAT','applicationFormat':'PLAINTEXT_EXE','snapshotFormat':'AGE_ZIP_SEPARATE','uatRevision':2}));monkeypatch.setattr(ci,'UAT_POLICY',policy)
    folder=tmp_path/'artifact';folder.mkdir()
    artifact=folder/'D4Planner-Setup-1.0.3.exe';artifact.write_bytes(b'unit-only-binary-integrity-not-native-evidence')
    meta={'schemaVersion':'d4planner-setup-build/v1','artifactClass':'D4PLANNER_APPLICATION_NO_SNAPSHOT','snapshotIncluded':False,'artifact':artifact.name,'version':'1.0.3','sourceHead':HEAD,'bytes':artifact.stat().st_size,'sha256':ci.delivery.sha256_file(artifact),'runtimeHealth':'PASS'}
    (folder/'release-metadata.json').write_text(json.dumps(meta))
    return folder,meta


def test_prepare_and_verify_direct_exe_exact_bytes(tmp_path,monkeypatch):
    folder,meta=upload_fixture(tmp_path,monkeypatch);original=(folder/meta['artifact']).read_bytes()
    result=ci.prepare_upload(folder,HEAD,'1.0.3',distribution())
    assert (folder/meta['artifact']).read_bytes()==original
    assert result['sha256']==meta['sha256'] and result['encryption']=='none'
    assert result['releaseTag']=='d4planner-uat/v1.0.3-r2'
    ci.verify_upload(folder,HEAD,'1.0.3',meta['sha256'],distribution())
    (folder/'SHA256SUMS').write_text('wrong')
    with pytest.raises(ValueError,match='CHECKSUM_FILE_MISMATCH'):ci.verify_upload(folder,HEAD,'1.0.3',meta['sha256'],distribution())


@pytest.mark.parametrize('patch',[{}, {'distributionFormat':'AGE_EXE'},{'runtimeLockSha256':'0'*64},{'licensesVerified':False},{'sourceHead':'b'*40}])
def test_upload_gate_rejects_missing_or_stale_approval_before_mutation(tmp_path,monkeypatch,patch):
    folder,meta=upload_fixture(tmp_path,monkeypatch)
    approval={} if not patch else {**distribution(),**patch}
    before={p.name:p.read_bytes() for p in folder.iterdir()}
    with pytest.raises(ValueError):ci.prepare_upload(folder,HEAD,'1.0.3',approval)
    assert before=={p.name:p.read_bytes() for p in folder.iterdir()}


@pytest.mark.parametrize('name',['private.zip.age','snapshot.json','key.pem'])
def test_upload_rejects_unlisted_private_assets(tmp_path,monkeypatch,name):
    folder,meta=upload_fixture(tmp_path,monkeypatch);ci.prepare_upload(folder,HEAD,'1.0.3',distribution())
    (folder/name).write_bytes(b'private-test-canary')
    with pytest.raises(ValueError,match='UNEXPECTED_PUBLIC_ASSET'):ci.verify_upload(folder,HEAD,'1.0.3',meta['sha256'],distribution())


def test_uat_publication_is_separate_from_format_and_distribution(tmp_path,monkeypatch):
    folder,meta=upload_fixture(tmp_path,monkeypatch);meta=ci.prepare_upload(folder,HEAD,'1.0.3',distribution())
    with pytest.raises(ValueError,match='OWNER_UAT_PUBLICATION'):ci.uat_release_approved(distribution(),meta)
    approval={**meta,'approvedBy':'TrdHuy','approvalRef':'isolated-test','publicationApproved':True}
    ci.uat_release_approved(approval,meta)
    for key in ['sourceHead','version','sha256','releaseTag']:
        with pytest.raises(ValueError,match='UAT_PUBLICATION_BINDING'):ci.uat_release_approved({**approval,key:'wrong'},meta)


@pytest.mark.parametrize('command',['validate-upload','publish-uat'])
def test_cli_blocks_without_permission_before_any_github_call(tmp_path,monkeypatch,command):
    folder,meta=upload_fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(sys,'argv',['release_ci.py',command,'--channel','uat','--version','1.0.3','--source',HEAD,'--directory',str(folder)])
    monkeypatch.setenv('GITHUB_REF_NAME','d4planner-uat/v1.0.3-r2');monkeypatch.setenv('GITHUB_ACTOR','synclab-automation-system')
    monkeypatch.delenv('D4_DISTRIBUTION_APPROVAL',raising=False)
    def forbidden(*a,**k):pytest.fail('No GitHub/network call allowed without distribution gate')
    monkeypatch.setattr(ci.subprocess,'check_output',forbidden);monkeypatch.setattr(ci,'run',forbidden)
    with pytest.raises(ValueError,match='OWNER_DISTRIBUTION'):ci.main()


def test_publish_uses_original_exe_after_separate_owner_approval(tmp_path,monkeypatch):
    from types import SimpleNamespace
    folder,meta=upload_fixture(tmp_path,monkeypatch);meta=ci.prepare_upload(folder,HEAD,'1.0.3',distribution())
    monkeypatch.setattr(sys,'argv',['release_ci.py','publish-uat','--channel','uat','--version','1.0.3','--source',HEAD,'--directory',str(folder)])
    for key,value in {'GITHUB_REF_NAME':meta['releaseTag'],'GITHUB_ACTOR':'synclab-automation-system','GITHUB_REPOSITORY':'isolated/test','D4_BUILT_SETUP_SHA256':meta['sha256'],'D4_DISTRIBUTION_APPROVAL':json.dumps(distribution())}.items():monkeypatch.setenv(key,value)
    calls=[]
    monkeypatch.setattr(ci,'run',lambda command,**kw:calls.append(command))
    monkeypatch.setattr(ci.subprocess,'check_output',lambda *a,**k:HEAD+'\n')
    monkeypatch.setattr(ci.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1,stderr='HTTP 404'))
    monkeypatch.delenv('D4_UAT_RELEASE_APPROVAL',raising=False)
    with pytest.raises(ValueError,match='OWNER_UAT_PUBLICATION'):ci.main()
    assert calls==[]
    monkeypatch.setenv('D4_UAT_RELEASE_APPROVAL',json.dumps({**meta,'approvedBy':'TrdHuy','approvalRef':'isolated-only','publicationApproved':True}))
    assert ci.main()==0
    assert len(calls)==1 and calls[0][:4]==['gh','release','create',meta['releaseTag']]
    assert str(folder/meta['artifact']) in calls[0]
    assert not any(str(arg).endswith('.age') for arg in calls[0])
    assert ci.delivery.sha256_file(folder/meta['artifact'])==meta['sha256']
    # Existing release cannot be overwritten, even with an approval.
    monkeypatch.setattr(ci.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stderr=''))
    with pytest.raises(ValueError,match='RELEASE_EXISTS_OR_UNVERIFIED'):ci.main()
    assert len(calls)==1


def test_hud_source_ownership_keeps_installed_identity_and_package_paths():
    import tomllib
    hud=ci.ROOT/'utility/d4planner-hud'
    assert hud.is_dir()
    for obsolete in ['utility/d4planner-overlay-poc','utility/d4planner/release1/native-launcher','utility/d4planner/runtime-logging']:
        assert not (ci.ROOT/obsolete).exists()
    for component in ['src-tauri','native-launcher']:
        cargo=tomllib.loads((hud/component/'Cargo.toml').read_text())
        dependency=cargo['dependencies']['d4planner-runtime-logging']['path']
        assert (hud/component/dependency).resolve()==(hud/'runtime-logging').resolve()
    native=tomllib.loads((hud/'src-tauri/Cargo.toml').read_text())
    assert native['package']['name']=='d4planner-hud'
    assert json.loads((hud/'src-tauri/tauri.conf.json').read_text())['identifier']=='vn.synclab.d4planner.overlaypoc'
    root=tomllib.loads((hud/'native-launcher/Cargo.toml').read_text())
    assert root['bin'][0]['name']=='D4Planner'
    stage=(ci.ROOT/'utility/d4planner/tools/build_release1_stage.py').read_text()
    assert 'app/d4planner-fe.exe' in stage
    workflow=(ci.ROOT/'.github/workflows/d4-overlay-poc.yml').read_text()
    assert 'utility/d4planner-hud/**' in workflow
    assert 'd4planner-overlay-poc-win-x64' in workflow  # existing artifact consumer contract
