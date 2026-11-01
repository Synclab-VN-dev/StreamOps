"""Release workflow safety/validation tests. Not a dispatched Actions run."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import release_ci as ci

HEAD='a'*40


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
    assert 'environment: d4planner-release' not in text
    assert '_APPROVAL_JSON' not in text and 'D4_RELEASE_GATES' not in text
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


def test_uat_context_and_snapshot_format_remain_explicit(tmp_path, monkeypatch):
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
    result=ci.prepare_upload(folder,HEAD,'1.0.3')
    assert (folder/meta['artifact']).read_bytes()==original
    assert result['sha256']==meta['sha256'] and result['encryption']=='none'
    assert result['releaseTag']=='d4planner-uat/v1.0.3-r2'
    ci.verify_upload(folder,HEAD,'1.0.3',meta['sha256'])
    (folder/'SHA256SUMS').write_text('wrong')
    with pytest.raises(ValueError,match='CHECKSUM_FILE_MISMATCH'):ci.verify_upload(folder,HEAD,'1.0.3',meta['sha256'])


@pytest.mark.parametrize('name',['private.zip.age','snapshot.json','key.pem'])
def test_upload_rejects_unlisted_private_assets(tmp_path,monkeypatch,name):
    folder,meta=upload_fixture(tmp_path,monkeypatch);ci.prepare_upload(folder,HEAD,'1.0.3')
    (folder/name).write_bytes(b'private-test-canary')
    with pytest.raises(ValueError,match='UNEXPECTED_PUBLIC_ASSET'):ci.verify_upload(folder,HEAD,'1.0.3',meta['sha256'])


def test_hud_source_ownership_keeps_installed_identity_and_package_paths():
    import tomllib
    project=ci.ROOT/'utility/d4planner'
    hud=project/'d4planner-hud'
    launcher=project/'d4planner-launcher'
    assert {p.name for p in project.iterdir() if p.is_dir()} == {
        'd4planner-launcher','d4planner-be','d4planner-hud','d4planner-rulekit'}
    for component in [hud/'src-tauri',launcher]:
        cargo=tomllib.loads((component/'Cargo.toml').read_text())
        dependency=cargo['dependencies']['d4planner-runtime-logging']['path']
        assert (component/dependency).resolve()==(hud/'runtime-logging').resolve()
    native=tomllib.loads((hud/'src-tauri/Cargo.toml').read_text())
    assert native['package']['name']=='d4planner-overlay-poc'
    assert json.loads((hud/'src-tauri/tauri.conf.json').read_text())['identifier']=='vn.synclab.d4planner.overlaypoc'
    root=tomllib.loads((launcher/'Cargo.toml').read_text())
    assert root['bin'][0]['name']=='D4Planner'
    stage=(project/'d4planner-be/tools/build_release1_stage.py').read_text()
    assert 'app/d4planner-fe.exe' in stage
    workflow=(ci.ROOT/'.github/workflows/d4-overlay-poc.yml').read_text()
    assert 'utility/d4planner/d4planner-hud/**' in workflow
    assert 'd4planner-overlay-poc-win-x64' in workflow


def cli(monkeypatch, folder, command, channel='stable'):
    monkeypatch.setattr(sys, 'argv', ['release_ci.py', command, '--channel', channel,
        '--version', '1.0.3', '--source', HEAD, '--directory', str(folder)])
    monkeypatch.setenv('GITHUB_REPOSITORY', 'isolated/test')
    monkeypatch.setenv('GITHUB_REF_NAME', 'd4planner-uat/v1.0.3-r2')
    monkeypatch.setenv('GITHUB_ACTOR', 'synclab-automation-system')
    for name in ('D4_DISTRIBUTION_APPROVAL','D4_RELEASE_GATES','D4_UAT_RELEASE_APPROVAL'):
        monkeypatch.setenv(name, 'invalid stale secret must not be read')


def response(status, document=None, code=None):
    from types import SimpleNamespace
    return SimpleNamespace(returncode=(0 if status == 200 else 1) if code is None else code,
        stdout=f'HTTP/2.0 {status} Test\r\ncontent-type: application/json\r\n\r\n'+json.dumps(document or {}),
        stderr='')


def test_build_only_validate_prepare_verify_never_checks_github_or_approval(tmp_path, monkeypatch):
    folder, meta = upload_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv('D4_BUILD_ONLY', 'true')
    monkeypatch.setenv('D4_BUILT_SETUP_SHA256', meta['sha256'])
    def forbidden(*a, **kw):
        pytest.fail('build-only must not query or mutate GitHub')
    monkeypatch.setattr(ci.subprocess, 'run', forbidden)
    monkeypatch.setattr(ci.subprocess, 'check_output', forbidden)
    monkeypatch.setattr(ci, 'run', forbidden)
    for command in ('validate', 'prepare-upload', 'validate-upload', 'verify'):
        cli(monkeypatch, folder, command)
        assert ci.main() == 0
    assert (folder / meta['artifact']).is_file()


@pytest.mark.parametrize('status,error', [(200,'RELEASE_ALREADY_EXISTS'),(401,'GITHUB_LOOKUP_FAILED'),
    (403,'GITHUB_LOOKUP_FAILED'),(429,'GITHUB_LOOKUP_FAILED'),(500,'GITHUB_LOOKUP_FAILED')])
def test_publish_preflight_blocks_existing_release_and_api_errors(tmp_path, monkeypatch, status, error):
    folder, _ = upload_fixture(tmp_path, monkeypatch)
    cli(monkeypatch, folder, 'validate')
    monkeypatch.setenv('D4_BUILD_ONLY', 'false')
    calls=[]
    monkeypatch.setattr(ci.subprocess, 'run', lambda args, **kw: calls.append(args) or response(status))
    with pytest.raises(ValueError, match=error):
        ci.main()
    assert calls == [['gh','api','--include','repos/isolated/test/releases/tags/v1.0.3']]


def test_release_lookup_fails_closed_on_network_or_malformed_response(monkeypatch):
    from types import SimpleNamespace
    for result in [SimpleNamespace(returncode=1,stdout='',stderr='network failure HTTP 404'),
                   SimpleNamespace(returncode=0,stdout='HTTP/2.0 200 OK\n\nnot JSON',stderr='')]:
        monkeypatch.setattr(ci.subprocess, 'run', lambda *a, **kw: result)
        with pytest.raises(ValueError, match='GITHUB_LOOKUP_FAILED'):
            ci.require_release_absent('isolated/test', 'v1.0.3')
    def timeout(*a, **kw):
        raise ci.subprocess.TimeoutExpired('gh',30)
    monkeypatch.setattr(ci.subprocess,'run',timeout)
    with pytest.raises(ci.subprocess.TimeoutExpired):
        ci.require_release_absent('isolated/test','v1.0.3')


@pytest.mark.parametrize('channel,existing_tag', [('stable',False),('stable',True),('uat',True)])
def test_publish_absent_release_uses_original_artifact_and_never_overwrites(tmp_path, monkeypatch, channel, existing_tag):
    folder, meta = upload_fixture(tmp_path, monkeypatch)
    ci.prepare_upload(folder,HEAD,'1.0.3')
    monkeypatch.setenv('D4_BUILT_SETUP_SHA256',meta['sha256'])
    monkeypatch.setenv('D4_BUILD_ONLY','false')
    tag = 'v1.0.3' if channel == 'stable' else 'd4planner-uat/v1.0.3-r2'
    queries=[];writes=[]
    def lookup(args, **kw):
        queries.append(args[-1])
        if '/releases/tags/' in args[-1]: return response(404)
        return response(200,{'object':{'type':'commit','sha':HEAD}}) if existing_tag else response(404)
    monkeypatch.setattr(ci.subprocess,'run',lookup)
    monkeypatch.setattr(ci,'run',lambda args,**kw:writes.append(args))
    cli(monkeypatch,folder,'validate',channel)
    assert ci.main()==0
    cli(monkeypatch,folder,'publish' if channel=='stable' else 'publish-uat',channel)
    assert ci.main()==0
    assert queries.count(f'repos/isolated/test/releases/tags/{tag}')==2
    assert len(writes)==(1 if existing_tag else 2)
    assert writes[-1][:4]==['gh','release','create',tag]
    assert str(folder/meta['artifact']) in writes[-1]
    assert ci.delivery.sha256_file(folder/meta['artifact'])==meta['sha256']
    # Another publisher winning after preflight must block all new writes.
    before=list(writes)
    monkeypatch.setattr(ci.subprocess,'run',lambda *a,**kw:response(200,{'tag_name':tag}))
    with pytest.raises(ValueError,match='RELEASE_ALREADY_EXISTS'):ci.main()
    assert writes==before


def test_existing_tag_must_resolve_to_build_head_without_rewriting(monkeypatch):
    writes=[]
    monkeypatch.setattr(ci,'run',lambda *a,**kw:writes.append(a))
    monkeypatch.setattr(ci.subprocess,'run',lambda *a,**kw:response(200,{'object':{'type':'commit','sha':'b'*40}}))
    with pytest.raises(ValueError,match='TAG_SOURCE_MISMATCH'):
        ci.ensure_source_tag('isolated/test','v1.0.3',HEAD)
    assert writes==[]
    replies=iter([response(200,{'object':{'type':'tag','sha':'b'*40}}),
                  response(200,{'object':{'type':'commit','sha':HEAD}})])
    monkeypatch.setattr(ci.subprocess,'run',lambda *a,**kw:next(replies))
    ci.ensure_source_tag('isolated/test','v1.0.3',HEAD)
    assert writes==[]


@pytest.mark.parametrize('tampered',[False,True])
def test_local_runtime_cache_revalidates_before_build(tmp_path,monkeypatch,tampered):
    lock=tmp_path/'runtime-lock.json'; lock.write_text('pin')
    monkeypatch.setattr(ci,'LOCK',lock)
    root=tmp_path/'cache'; cached=root/ci.delivery.sha256_file(lock); cached.mkdir(parents=True)
    (cached/'marker').write_text('tampered' if tampered else 'valid')
    checks=[]; builds=[]
    def validate(path):
        checks.append(path)
        if (path/'marker').read_text()!='valid': raise ValueError('PRIVATE_INPUT_INTEGRITY')
    monkeypatch.setattr(ci,'validate_inputs',validate)
    monkeypatch.setattr(ci,'prepare_upstream_inputs',lambda *_:pytest.fail('Validated cache must be reused'))
    monkeypatch.setattr(ci,'product_version',lambda *_:None)
    monkeypatch.setattr(ci,'build',lambda inputs,*args:builds.append(inputs) or {'sha256':'a'*64})
    monkeypatch.setenv('D4_LOCAL_RUNTIME_CACHE',str(root)); monkeypatch.setenv('GITHUB_OUTPUT',str(tmp_path/'output'))
    monkeypatch.setattr(sys,'argv',['release_ci.py','build','--channel','stable','--version','1.2.8','--source',HEAD,'--directory',str(tmp_path/'run')])
    if tampered:
        with pytest.raises(ValueError,match='PRIVATE_INPUT_INTEGRITY'): ci.main()
        assert not builds
    else:
        ci.main(); assert builds==[cached]
    assert checks==[cached]
