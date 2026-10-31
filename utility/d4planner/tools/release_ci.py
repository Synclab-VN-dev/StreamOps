"""Single Release workflow support. No Actions dispatch/query or implicit release.

Public runtime build inputs are checksum-addressed and content-allowlisted.
The runner never downloads/mounts Maxroll snapshots. Application dependency
redistribution approval is independent from snapshot rights. Publishing additionally needs
the protected environment and exact-artifact acceptance attestation.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile

import release1_delivery as delivery
import public_package as public
from windows_install import version, InstallError

ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / 'utility/d4planner/release1/release-runtime-lock.json'
PRODUCT_PLAN = ROOT / 'utility/d4planner/release1/package-plan.json'
UAT_POLICY = ROOT / 'utility/d4planner/release1/uat-encryption-policy.json'
GATES = tuple(f'PKG-{n:02}' for n in range(1,9)) + ('HUD-03', 'VISUAL_GOLDEN') + tuple(f'SNAP-{n:02}' for n in range(1,8))


def require(condition, error):
    if not condition: raise ValueError(error)


def validate_source(value):
    require(bool(re.fullmatch('[0-9a-f]{40}', value)), 'INVALID_SOURCE_SHA')


def distribution_approved(document, head, release_version):
    require(document.get('approvedBy') == 'TrdHuy' and document.get('approvalRef'), 'OWNER_DISTRIBUTION_APPROVAL_REQUIRED')
    require(document.get('sourceHead') == head and document.get('version') == release_version, 'DISTRIBUTION_APPROVAL_BINDING')
    require(document.get('publicDistributionApproved') is True and document.get('licensesVerified') is True, 'PRIVATE_RESOURCE_DISTRIBUTION_NOT_APPROVED')
    require(document.get('artifactClass') == 'D4PLANNER_APPLICATION_NO_SNAPSHOT', 'APPLICATION_DISTRIBUTION_APPROVAL_REQUIRED')
    require(document.get('distributionFormat') == 'PLAINTEXT_EXE', 'PLAINTEXT_DISTRIBUTION_APPROVAL_REQUIRED')
    require(document.get('runtimeLockSha256') == delivery.sha256_file(LOCK), 'DISTRIBUTION_RUNTIME_BINDING')


def release_approved(document, metadata):
    for key in ('sourceHead','version','sha256'):
        require(document.get(key) == metadata[key], 'RELEASE_APPROVAL_BINDING:' + key)
    require(document.get('approvedBy') == 'TrdHuy' and document.get('approvalRef'), 'OWNER_RELEASE_APPROVAL_REQUIRED')
    require(all(document.get('gates',{}).get(gate) == 'PASS' or (gate=='VISUAL_GOLDEN' and document.get('gates',{}).get(gate)=='OWNER_WAIVED' and document.get('releaseId')=='R1-EQUIPMENT-20261025' and document.get('visualWaiver')=='ISSUE158_R1_VISUAL_WAIVER_20261030') for gate in GATES), 'MANDATORY_RELEASE_GATES_NOT_PASS')


def protected_environment(document):
    rules = document.get('protection_rules',[])
    required = [rule for rule in rules if rule.get('type') == 'required_reviewers']
    # GitHub accepts any one reviewer; accept exactly the Owner, never a broader
    # list that would let automation approve its own publication.
    require(any(rule.get('prevent_self_review') is True and
                [(entry.get('type'),entry.get('reviewer',{}).get('login')) for entry in rule.get('reviewers',[])] == [('User','TrdHuy')]
                for rule in required), 'PROTECTED_OWNER_ENVIRONMENT_REQUIRED')


def download_inputs(url, expected_sha, destination):
    require(urllib.parse.urlparse(url).scheme == 'https', 'HTTPS_PRIVATE_INPUT_REQUIRED')
    require(bool(re.fullmatch('[0-9a-f]{64}', expected_sha)), 'PINNED_INPUT_SHA256_REQUIRED')
    require(expected_sha == delivery.load_json(LOCK).get('publicInputsArchiveSha256'), 'PUBLIC_RUNTIME_ARCHIVE_PIN_REQUIRED')
    archive_path = destination.with_suffix('.zip')
    try:
        with urllib.request.urlopen(url, timeout=120) as source, archive_path.open('wb') as output:
            require(urllib.parse.urlparse(source.geturl()).scheme=='https','HTTPS_INPUT_REDIRECT_REQUIRED')
            shutil.copyfileobj(source,output,1024*1024)
    except Exception:
        raise ValueError('PRIVATE_BUILD_INPUT_UNAVAILABLE') from None  # never expose a signed URL
    require(delivery.sha256_file(archive_path) == expected_sha, 'PRIVATE_INPUT_SHA256_MISMATCH')
    with zipfile.ZipFile(archive_path) as archive:
        names=set()
        for info in archive.infolist():
            if info.is_dir(): continue
            relative=delivery.safe_relative(info.filename)
            require(info.filename.lower() not in names, 'DUPLICATE_PRIVATE_INPUT')
            names.add(info.filename.lower())
            require((info.external_attr >> 16) & 0o170000 != 0o120000, 'SYMLINK_PRIVATE_INPUT')
            target=delivery._contained_destination(destination,relative.as_posix())
            target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(info) as source,target.open('wb') as output: shutil.copyfileobj(source,output)
    return validate_inputs(destination)


def prepare_upstream_inputs(destination, *, archive_directory=None):
    """Reconstruct the already-reviewed runtime tree from exact upstream ZIPs.

    This is build-time only. Launch/install never download runtimes. Existing
    manifest/tree pins remain authoritative, including the Python path config.
    """
    lock=delivery.load_json(LOCK)
    destination.mkdir(parents=True,exist_ok=False)
    for name,entry in lock['upstreamArchives'].items():
        require(name in {'python','node','chromium','nsis'},'UNREVIEWED_INPUT_ROOT')
        archive_path=(archive_directory/name).with_suffix('.zip') if archive_directory else destination.parent/(name+'.zip')
        if archive_directory is None:
            require(urllib.parse.urlparse(entry['url']).scheme=='https','HTTPS_INPUT_REQUIRED')
            with urllib.request.urlopen(entry['url'],timeout=120) as source,archive_path.open('wb') as output:
                require(urllib.parse.urlparse(source.geturl()).scheme=='https','HTTPS_INPUT_REDIRECT_REQUIRED')
                shutil.copyfileobj(source,output,1024*1024)
        require(delivery.sha256_file(archive_path)==entry['sha256'],'UPSTREAM_ARCHIVE_INTEGRITY:'+name)
        seen=set()
        with zipfile.ZipFile(archive_path) as archive:
            for item in archive.infolist():
                if item.is_dir():continue
                require(item.filename.startswith(entry['prefix']),'UPSTREAM_PREFIX_MISMATCH')
                relative=delivery.safe_relative(item.filename[len(entry['prefix']):])
                if not public.included(relative):continue
                require(relative.as_posix().lower() not in seen,'DUPLICATE_PRIVATE_INPUT')
                seen.add(relative.as_posix().lower())
                require((item.external_attr>>16)&0o170000 != 0o120000,'SYMLINK_PRIVATE_INPUT')
                target=delivery._contained_destination(destination/name,relative.as_posix())
                target.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(item) as source,target.open('wb') as output:shutil.copyfileobj(source,output)
    (destination/'python/python312._pth').write_bytes(b'python312.zip\n.\n../../backend/site-packages\nimport site\n')
    manifest={'schemaVersion':'d4planner-public-build-inputs/v1','snapshotIncluded':False,'versions':lock['versions'],
              'files':[{'path':path.relative_to(destination).as_posix(),'sha256':delivery.sha256_file(path)}
                       for path in sorted(destination.rglob('*'),key=lambda p:p.relative_to(destination).parts) if path.is_file()]}
    (destination/'inputs-manifest.json').write_bytes((json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode())
    return validate_inputs(destination)


def product_version(release_version):
    version(release_version)
    require(delivery.load_json(PRODUCT_PLAN)['version']==release_version,'PRODUCT_VERSION_MISMATCH')
    return release_version


def uat_tag(release_version, policy=None):
    product_version(release_version)
    policy = delivery.load_json(UAT_POLICY) if policy is None else policy
    revision = policy.get('uatRevision')
    require(type(revision) is int and revision > 0, 'INVALID_UAT_REVISION')
    return f'd4planner-uat/v{release_version}-r{revision}'


def uat_context(tag, release_version, actor):
    require(tag==uat_tag(release_version),'INVALID_UAT_TAG')
    require(actor in {'TrdHuy','synclab-automation-system'},'UAT_ACTOR_NOT_AUTHORIZED')


def uat_approved(document, metadata):
    require(document.get('schemaVersion')=='d4planner-uat-distribution-policy/v2' and
            document.get('scope')=='D4PLANNER_R1_UAT','UAT_SCOPE_REQUIRED')
    require(document.get('applicationFormat')=='PLAINTEXT_EXE' and metadata.get('encryption')=='none', 'PLAINTEXT_APPLICATION_REQUIRED')
    require(document.get('snapshotFormat')=='AGE_ZIP_SEPARATE','SNAPSHOT_SEPARATION_REQUIRED')
    require(metadata.get('releaseTag')==uat_tag(metadata.get('version'),document),'UAT_VERSION_NOT_AUTHORIZED')
    require(metadata.get('uatRevision')==document['uatRevision'],'UAT_REVISION_MISMATCH')
    require(metadata.get('runtimeHealth')=='PASS','UAT_RUNTIME_HEALTH_REQUIRED')


def prepare_upload(directory, head, release_version, approval):
    # Authorize public upload only after explicit plaintext distribution permission.
    distribution_approved(approval, head, release_version)
    metadata=delivery.load_json(directory/'release-metadata.json')
    metadata,artifact=verify_built_artifact(directory,head,release_version,metadata['sha256'])
    policy=delivery.load_json(UAT_POLICY)
    metadata.update(productVersion=release_version,uatRevision=policy['uatRevision'],
                    releaseTag=uat_tag(release_version,policy),encryption='none',
                    ciRunId=os.environ.get('GITHUB_RUN_ID'),ownerManual='T20-T23_PENDING',visualR1='OWNER_WAIVED')
    uat_approved(policy,metadata)
    (directory/'release-metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    (directory/'SHA256SUMS').write_text(f"{metadata['sha256']}  {artifact.name}\n",encoding='utf-8')
    (directory/'UAT.md').write_text('D4Planner R1 UAT, chưa phải production approval.\nKiểm tra SHA256SUMS rồi chạy '+artifact.name+'. Không cần age/decrypt cho Application.\nSnapshot .zip.age được provision riêng qua Rule Kit; không chứa trong Setup. T20–T23 chờ Owner MAN.\n',encoding='utf-8')
    return metadata


def verify_upload(directory, head, release_version, expected_sha, approval):
    distribution_approved(approval,head,release_version)
    metadata,artifact=verify_built_artifact(directory,head,release_version,expected_sha)
    uat_approved(delivery.load_json(UAT_POLICY),metadata)
    require({p.name for p in directory.iterdir()}=={artifact.name,'release-metadata.json','SHA256SUMS','UAT.md'},'UNEXPECTED_PUBLIC_ASSET')
    require(not any(p.is_symlink() for p in directory.iterdir()),'PUBLIC_ASSET_SYMLINK')
    require((directory/'SHA256SUMS').read_text(encoding='utf-8')==f"{expected_sha}  {artifact.name}\n",'CHECKSUM_FILE_MISMATCH')
    return metadata,artifact


def uat_release_approved(document, metadata):
    require(document.get('approvedBy')=='TrdHuy' and document.get('approvalRef'), 'OWNER_UAT_PUBLICATION_APPROVAL_REQUIRED')
    require(document.get('publicationApproved') is True,'OWNER_UAT_PUBLICATION_APPROVAL_REQUIRED')
    for key in ('sourceHead','version','sha256','releaseTag'):
        require(document.get(key)==metadata.get(key),'UAT_PUBLICATION_BINDING:'+key)


def verify_encrypted_artifact(directory, head, release_version, expected_sha):
    metadata=delivery.load_json(directory/'release-metadata.json')
    require(metadata.get('schemaVersion')=='d4planner-encrypted-setup/v1' and metadata.get('encryption')=='age/v1','ENCRYPTED_UAT_REQUIRED')
    require(metadata.get('sourceHead')==head and metadata.get('version')==release_version,'PUBLISH_SOURCE_VERSION_MISMATCH')
    require(metadata.get('snapshotIncluded') is False and metadata.get('artifactClass')=='D4PLANNER_APPLICATION_NO_SNAPSHOT','PUBLIC_ARTIFACT_CLASS_MISMATCH')
    artifact=directory/f'D4Planner-Setup-{release_version}.exe.age'
    require(metadata.get('artifact')==artifact.name and metadata.get('sha256')==expected_sha,'BUILD_ARTIFACT_BINDING')
    require(artifact.is_file() and artifact.stat().st_size==metadata['bytes'] and delivery.sha256_file(artifact)==expected_sha,'PUBLISH_ARTIFACT_INTEGRITY')
    require(artifact.open('rb').read(len(b'age-encryption.org/v1\n'))==b'age-encryption.org/v1\n','AGE_CIPHERTEXT_REQUIRED')
    require({p.name for p in directory.iterdir()}=={artifact.name,'release-metadata.json','SHA256SUMS','UAT.md'},'UNEXPECTED_PUBLIC_ASSET')
    return metadata,artifact


def validate_inputs(root):
    lock=delivery.load_json(LOCK)
    require(delivery.sha256_file(root/'inputs-manifest.json') == lock.get('publicInputsManifestSha256'), 'PUBLIC_INPUT_MANIFEST_PIN_MISMATCH')
    manifest=delivery.load_json(root/'inputs-manifest.json')
    require(manifest.get('schemaVersion')=='d4planner-public-build-inputs/v1', 'PRIVATE_INPUT_MANIFEST_VERSION')
    require(manifest.get('versions')==lock['versions'],'PRIVATE_INPUT_VERSION_MISMATCH')
    require(manifest.get('files'), 'EMPTY_PRIVATE_INPUT_MANIFEST')
    listed={entry['path']:entry['sha256'] for entry in manifest['files']}
    require(len(listed)==len(manifest['files']), 'DUPLICATE_PRIVATE_INPUT')
    actual={path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file() and path.name!='inputs-manifest.json'}
    require(actual==set(listed), 'UNLISTED_PRIVATE_INPUT')
    for name,digest in listed.items():
        require(delivery.sha256_file(delivery._contained_destination(root,name))==digest,'PRIVATE_INPUT_INTEGRITY:'+name)
    for name,digest in lock['files'].items(): require(listed.get(name)==digest,'RUNTIME_PIN_MISMATCH:'+name)
    require(manifest.get('snapshotIncluded') is False, 'PUBLIC_INPUT_SNAPSHOT_SEPARATION_REQUIRED')
    require(all(Path(name).parts[0] in {'python','node','chromium','nsis'} for name in listed), 'PRIVATE_OR_UNREVIEWED_INPUT_ROOT')
    for key in ('python','node','chromium'):
        public.validate_tree(root/key,'runtime/'+key)
    public.validate_tree(root/'nsis','build-tools/nsis')
    for name in ('nsis/makensis.exe','python/python312._pth','python/python312.zip'):
        require(name in listed,'REQUIRED_BUILD_INPUT:'+name)
    return manifest


def run(command, *, cwd=ROOT, **kwargs):
    subprocess.run(list(map(str,command)),cwd=cwd,check=True,timeout=1200,**kwargs)


def prepare_frontend_native_assets(frontend, npm):
    # Icons are generated/ignored assets; a clean checkout only contains the SVG.
    run([npm, 'run', 'icon'], cwd=frontend)
    icon = frontend/'src-tauri/icons/icon.ico'
    require(icon.is_file() and icon.stat().st_size > 6, 'WINDOWS_ICON_MISSING')
    require(icon.read_bytes()[:4] == b'\x00\x00\x01\x00', 'WINDOWS_ICON_INVALID')


def build(inputs, output, head, release_version):
    product_version(release_version); validate_source(head)
    require(subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()==head,'CHECKOUT_SOURCE_MISMATCH')
    require(sys.platform=='win32','WINDOWS_BUILD_REQUIRED')
    validate_inputs(inputs)
    os.environ['NSISDIR']=str(inputs/'nsis')
    require(subprocess.check_output([str(inputs/'node/node.exe'),'--version'],text=True).strip()=='v22.22.1','NODE_RUNTIME_VERSION')
    require(subprocess.check_output([str(inputs/'python/python.exe'),'--version'],text=True).strip()=='Python 3.12.10','PYTHON_RUNTIME_VERSION')
    require('v3.09' in subprocess.check_output([str(inputs/'nsis/makensis.exe'),'/VERSION'],text=True),'NSIS_VERSION')
    require(subprocess.check_output(['rustc','--version'],text=True).split()[1]=='1.90.0','RUST_VERSION')
    output.mkdir(parents=True,exist_ok=False)
    frontend=ROOT/'utility/d4planner-overlay-poc'
    npm='npm.cmd'
    for module in ('browser-infra','providers/maxroll','snapshot-management'):
        run([npm,'ci','--omit=dev','--ignore-scripts'],cwd=ROOT/'utility/d4-rulekit'/module)
    require(delivery.load_json(ROOT/'utility/d4-rulekit/providers/maxroll/node_modules/playwright-core/package.json')['version']=='1.64.1','PLAYWRIGHT_PIN')
    run([npm,'ci','--ignore-scripts'],cwd=frontend)
    run([npm,'test'],cwd=frontend); run([npm,'run','build'],cwd=frontend)
    prepare_frontend_native_assets(frontend, npm)
    # The CI runner has VC runtimes; the user's clean machine need not.
    # Apply the same static CRT policy already used by the root launcher.
    run(['cargo','build','--release','--locked','--manifest-path',frontend/'src-tauri/Cargo.toml'],
        env={**os.environ, 'RUSTFLAGS': '-C target-feature=+crt-static'})
    launcher=ROOT/'utility/d4planner/release1/native-launcher'
    run(['cargo','build','--release','--locked','--manifest-path',launcher/'Cargo.toml'], cwd=launcher)
    run(['cargo','test','--release','--locked','--manifest-path',launcher/'Cargo.toml'], cwd=launcher)
    # Backend wheel from the current source, dependencies are pinned above.
    wheel=output/'wheel'; wheel.mkdir()
    run([sys.executable,'-m','pip','wheel','--no-deps','--no-build-isolation',ROOT/'utility/d4planner','--wheel-dir',wheel])
    site=output/'site-packages'
    run([sys.executable,'-m','pip','install','--no-compile','--target',site,'-r',ROOT/'utility/d4planner/release1/requirements-release.txt'])
    for path in wheel.glob('*.whl'):
        run([sys.executable,'-m','pip','install','--no-compile','--no-deps','--target',site,path])
        run([sys.executable,'-m','pip','install','--no-deps',path])
    run([sys.executable,'-m','pytest','-q','utility/d4planner/tests/contracts/test_release1_contract.py',
         'utility/d4planner/tests/test_windows_install.py','utility/d4planner/tests/test_release_ci.py',
         'utility/d4planner/tests/test_package_entrypoint.py'])
    tools=ROOT/'utility/d4planner/tools'
    stage=output/'stage'
    run([sys.executable,tools/'build_release1_stage.py','--launcher-exe',launcher/'target/release/D4Planner.exe',
         '--frontend-exe',frontend/'src-tauri/target/release/d4planner-overlay-poc.exe',
         '--python-root',inputs/'python','--python-site-packages',site,'--node-root',inputs/'node',
         '--chromium-root',inputs/'chromium','--output',stage])
    package=output/f'D4Planner-{release_version}.zip'
    run([sys.executable,tools/'release1_delivery.py','build','--plan',ROOT/'utility/d4planner/release1/package-plan.json',
         '--source',stage,'--version',release_version,'--output',package],stdout=subprocess.DEVNULL)
    run([sys.executable,tools/'build_windows_installer.py','--package',package,'--python-root',inputs/'python',
         '--output',output/'setup','--makensis',inputs/'nsis/makensis.exe'])
    delivery.verify_package(package,public_only=True)
    metadata=delivery.load_json(output/'setup/setup-build.json')
    require(metadata['sourceHead']==head and metadata['version']==release_version,'BUILD_METADATA_BINDING')
    setup=Path(metadata['artifact'])
    public=output/'verified-artifact';public.mkdir()
    shutil.copyfile(setup,public/setup.name)
    # Actual private runtime health, independent of the static package verifier.
    health=output/'runtime-health.json'
    health_app=output/'health-install'
    delivery.install_package(package,health_app,output/'health-data')
    run([health_app/'D4Planner.exe','--runtime-health','--health-report',health])
    require(delivery.load_json(health).get('runtimeReady') is True,'BUILD_RUNTIME_HEALTH_NOT_READY')
    require(delivery.load_json(health).get('calculationAvailability')=='UNAVAILABLE','NO_SNAPSHOT_CALCULATION_NOT_UNAVAILABLE')
    require(metadata.get('snapshotIncluded') is False and metadata.get('artifactClass')=='D4PLANNER_APPLICATION_NO_SNAPSHOT','PUBLIC_ARTIFACT_CLASS_MISMATCH')
    metadata['artifact']=setup.name
    metadata['backendWheelSha256']={path.name:delivery.sha256_file(path) for path in wheel.glob('*.whl')}
    metadata['runtimeHealth']='PASS'
    metadata['sha256']=delivery.sha256_file(public/setup.name)
    (public/'release-metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    (public/'SHA256SUMS').write_text(f"{metadata['sha256']}  {setup.name}\n",encoding='utf-8')
    return metadata


def verify_built_artifact(directory, head, release_version, expected_sha):
    metadata=delivery.load_json(directory/'release-metadata.json')
    require(metadata.get('schemaVersion')=='d4planner-setup-build/v1','SETUP_METADATA_VERSION')
    require(metadata.get('snapshotIncluded') is False and metadata.get('artifactClass')=='D4PLANNER_APPLICATION_NO_SNAPSHOT','PUBLIC_ARTIFACT_CLASS_MISMATCH')
    require(metadata.get('sourceHead')==head and metadata.get('version')==release_version,'PUBLISH_SOURCE_VERSION_MISMATCH')
    require(metadata.get('sha256')==expected_sha,'BUILD_ARTIFACT_BINDING')
    artifact=directory/f'D4Planner-Setup-{release_version}.exe'
    require(artifact.name==metadata.get('artifact') and artifact.is_file(),'SETUP_ARTIFACT_NAME')
    require(artifact.stat().st_size==metadata.get('bytes') and delivery.sha256_file(artifact)==expected_sha,'PUBLISH_ARTIFACT_INTEGRITY')
    return metadata,artifact


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=('validate','build','verify','publish','publish-uat','validate-upload','prepare-upload'))
    parser.add_argument('--channel',choices=('stable','uat'),default='stable')
    parser.add_argument('--version',required=True)
    parser.add_argument('--source',required=True)
    parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args()
    product_version(args.version);validate_source(args.source)
    if args.channel=='uat':
        uat_context(os.environ.get('GITHUB_REF_NAME',''),args.version,os.environ.get('GITHUB_ACTOR',''))
    if args.command=='validate':
        if args.channel=='uat':return 0  # build allowed; public upload has a separate license gate
        distribution_approved(json.loads(os.environ.get('D4_DISTRIBUTION_APPROVAL','{}')),args.source,args.version)
        if os.environ.get('D4_BUILD_ONLY')=='false':
            environment=json.loads(subprocess.check_output(['gh','api',f"repos/{os.environ['GITHUB_REPOSITORY']}/environments/d4planner-release"],text=True))
            protected_environment(environment)
    elif args.command=='build':
        inputs=args.directory/'public-runtime-inputs'; inputs.parent.mkdir(parents=True,exist_ok=True)
        if os.environ.get('D4_PUBLIC_RUNTIME_INPUT_URL'):
            download_inputs(os.environ['D4_PUBLIC_RUNTIME_INPUT_URL'],os.environ.get('D4_PUBLIC_RUNTIME_INPUT_SHA256',''),inputs)
        else:prepare_upstream_inputs(inputs)
        metadata=build(inputs,args.directory/'build',args.source,args.version)
        with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as output:
            output.write(f"setup_sha256={metadata['sha256']}\n")
    elif args.command=='prepare-upload':
        metadata=prepare_upload(args.directory,args.source,args.version,json.loads(os.environ.get('D4_DISTRIBUTION_APPROVAL','{}')))
    else:
        metadata,artifact=verify_upload(args.directory,args.source,args.version,os.environ.get('D4_BUILT_SETUP_SHA256'),json.loads(os.environ.get('D4_DISTRIBUTION_APPROVAL','{}')))
        if args.command=='verify': return 0
        if args.command in {'publish-uat','validate-upload'}:
            if args.command=='publish-uat':require(args.channel=='uat','UAT_CHANNEL_REQUIRED')
            document=delivery.load_json(UAT_POLICY)
            uat_approved(document,metadata)
            if args.command=='validate-upload':return 0
            uat_release_approved(json.loads(os.environ.get('D4_UAT_RELEASE_APPROVAL','{}')),metadata)
            repo=os.environ['GITHUB_REPOSITORY'];tag=uat_tag(args.version,document)
            actual=subprocess.check_output(['gh','api',f'repos/{repo}/git/ref/tags/{tag}','--jq','.object.sha'],text=True).strip()
            require(actual==args.source,'UAT_TAG_SOURCE_MISMATCH')
            existing=subprocess.run(['gh','api','--include',f'repos/{repo}/releases/tags/{tag}'],capture_output=True,text=True,timeout=30)
            require(existing.returncode!=0 and 'HTTP 404' in existing.stderr,'RELEASE_EXISTS_OR_UNVERIFIED')
            run(['gh','release','create',tag,str(artifact),str(args.directory/'SHA256SUMS'),str(args.directory/'release-metadata.json'),str(args.directory/'UAT.md'),
                 '--repo',repo,'--verify-tag','--prerelease','--title',f"D4Planner {args.version} UAT r{document['uatRevision']}",
                 '--notes',f'UAT prerelease, not production approval. Owner T20-T23 pending. R1 Visual OWNER_WAIVED. Source {args.source}; SHA-256 {metadata["sha256"]}. No snapshot included.'])
            return 0
        distribution_approved(json.loads(os.environ.get('D4_DISTRIBUTION_APPROVAL','{}')),args.source,args.version)
        release_approved(json.loads(os.environ.get('D4_RELEASE_GATES','{}')),metadata)
        protected_environment(json.loads(subprocess.check_output(['gh','api',f"repos/{os.environ['GITHUB_REPOSITORY']}/environments/d4planner-release"],text=True)))
        repo=os.environ['GITHUB_REPOSITORY'];tag=f'v{args.version}'
        for endpoint in (f'repos/{repo}/git/ref/tags/{tag}', f'repos/{repo}/releases/tags/{tag}'):
            existing=subprocess.run(['gh','api','--include',endpoint],capture_output=True,text=True,timeout=30)
            require(existing.returncode!=0 and 'HTTP 404' in existing.stderr,'RELEASE_OR_TAG_EXISTS_OR_UNVERIFIED')
        # Atomic create-ref refuses races/overwrite; no force and no rebuild.
        run(['gh','api',f'repos/{repo}/git/refs','--method','POST','-f',f'ref=refs/tags/{tag}','-f',f'sha={args.source}'])
        run(['gh','release','create',tag,str(artifact),str(args.directory/'SHA256SUMS'),str(args.directory/'release-metadata.json'),
             '--repo',repo,'--verify-tag','--title',f'D4Planner {args.version}','--notes',f"Source {args.source}; SHA-256 {metadata['sha256']}"])
    return 0

if __name__=='__main__': raise SystemExit(main())
