"""Single Release workflow support. No Actions dispatch/query or implicit release.

Private build inputs are checksum-addressed, supplied by an authorized secret
URL. A public repository cannot upload the private-containing Setup without an
explicit exact-source redistribution attestation. Publishing additionally needs
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
from windows_install import version, InstallError

ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / 'utility/d4planner/release1/release-runtime-lock.json'
GATES = tuple(f'PKG-{n:02}' for n in range(1,9)) + ('HUD-03', 'VISUAL_GOLDEN')


def require(condition, error):
    if not condition: raise ValueError(error)


def validate_source(value):
    require(bool(re.fullmatch('[0-9a-f]{40}', value)), 'INVALID_SOURCE_SHA')


def distribution_approved(document, head, release_version):
    require(document.get('approvedBy') == 'TrdHuy' and document.get('approvalRef'), 'OWNER_DISTRIBUTION_APPROVAL_REQUIRED')
    require(document.get('sourceHead') == head and document.get('version') == release_version, 'DISTRIBUTION_APPROVAL_BINDING')
    require(document.get('publicDistributionApproved') is True and document.get('licensesVerified') is True, 'PRIVATE_RESOURCE_DISTRIBUTION_NOT_APPROVED')
    require(document.get('snapshotManifestSha256') == delivery.load_json(LOCK)['files']['snapshots/maxroll-20261023T034150Z/manifest.json'], 'DISTRIBUTION_SNAPSHOT_MISMATCH')


def release_approved(document, metadata):
    for key in ('sourceHead','version','sha256'):
        require(document.get(key) == metadata[key], 'RELEASE_APPROVAL_BINDING:' + key)
    require(document.get('approvedBy') == 'TrdHuy' and document.get('approvalRef'), 'OWNER_RELEASE_APPROVAL_REQUIRED')
    require(all(document.get('gates',{}).get(gate) == 'PASS' for gate in GATES), 'MANDATORY_RELEASE_GATES_NOT_PASS')


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


def validate_inputs(root):
    lock=delivery.load_json(LOCK)
    manifest=delivery.load_json(root/'inputs-manifest.json')
    require(manifest.get('schemaVersion')=='d4planner-private-build-inputs/v1', 'PRIVATE_INPUT_MANIFEST_VERSION')
    require(manifest.get('versions')==lock['versions'],'PRIVATE_INPUT_VERSION_MISMATCH')
    require(manifest.get('files'), 'EMPTY_PRIVATE_INPUT_MANIFEST')
    listed={entry['path']:entry['sha256'] for entry in manifest['files']}
    require(len(listed)==len(manifest['files']), 'DUPLICATE_PRIVATE_INPUT')
    actual={path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file() and path.name!='inputs-manifest.json'}
    require(actual==set(listed), 'UNLISTED_PRIVATE_INPUT')
    for name,digest in listed.items():
        require(delivery.sha256_file(delivery._contained_destination(root,name))==digest,'PRIVATE_INPUT_INTEGRITY:'+name)
    for name,digest in lock['files'].items(): require(listed.get(name)==digest,'RUNTIME_PIN_MISMATCH:'+name)
    for name in ('nsis/makensis.exe','config/maxroll-profile.json','python/python312._pth','python/python312.zip'):
        require(name in listed,'REQUIRED_BUILD_INPUT:'+name)
    return manifest


def run(command, *, cwd=ROOT, **kwargs):
    subprocess.run(list(map(str,command)),cwd=cwd,check=True,timeout=1200,**kwargs)


def build(inputs, output, head, release_version):
    version(release_version); validate_source(head)
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
    for module in ('browser-infra','providers/maxroll'):
        run([npm,'ci','--omit=dev','--ignore-scripts'],cwd=ROOT/'utility/d4-rulekit'/module)
    require(delivery.load_json(ROOT/'utility/d4-rulekit/providers/maxroll/node_modules/playwright-core/package.json')['version']=='1.64.1','PLAYWRIGHT_PIN')
    run([npm,'ci','--ignore-scripts'],cwd=frontend)
    run([npm,'test'],cwd=frontend); run([npm,'run','build'],cwd=frontend)
    run(['cargo','build','--release','--locked','--manifest-path',frontend/'src-tauri/Cargo.toml'])
    launcher=ROOT/'utility/d4planner/release1/native-launcher'
    run(['cargo','build','--release','--locked','--manifest-path',launcher/'Cargo.toml'])
    run(['cargo','test','--release','--locked','--manifest-path',launcher/'Cargo.toml'])
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
         '--chromium-root',inputs/'chromium','--snapshot-root',inputs/'snapshots/maxroll-20261023T034150Z',
         '--profile',inputs/'config/maxroll-profile.json','--output',stage])
    package=output/f'D4Planner-{release_version}.zip'
    run([sys.executable,tools/'release1_delivery.py','build','--plan',ROOT/'utility/d4planner/release1/package-plan.json',
         '--source',stage,'--version',release_version,'--output',package],stdout=subprocess.DEVNULL)
    run([sys.executable,tools/'build_windows_installer.py','--package',package,'--python-root',inputs/'python',
         '--output',output/'setup','--makensis',inputs/'nsis/makensis.exe'])
    metadata=delivery.load_json(output/'setup/setup-build.json')
    require(metadata['sourceHead']==head and metadata['version']==release_version,'BUILD_METADATA_BINDING')
    setup=Path(metadata['artifact'])
    public=output/'verified-artifact';public.mkdir()
    shutil.copyfile(setup,public/setup.name)
    # Actual private runtime health, independent of the static package verifier.
    health=output/'runtime-health.json'
    run([stage/'D4Planner.exe','--runtime-health','--health-report',health])
    require(delivery.load_json(health).get('runtimeReady') is True,'BUILD_RUNTIME_HEALTH_NOT_READY')
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
    require(metadata.get('sourceHead')==head and metadata.get('version')==release_version,'PUBLISH_SOURCE_VERSION_MISMATCH')
    require(metadata.get('sha256')==expected_sha,'BUILD_ARTIFACT_BINDING')
    artifact=directory/f'D4Planner-Setup-{release_version}.exe'
    require(artifact.name==metadata.get('artifact') and artifact.is_file(),'SETUP_ARTIFACT_NAME')
    require(artifact.stat().st_size==metadata.get('bytes') and delivery.sha256_file(artifact)==expected_sha,'PUBLISH_ARTIFACT_INTEGRITY')
    return metadata,artifact


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=('validate','build','verify','publish'))
    parser.add_argument('--version',required=True)
    parser.add_argument('--source',required=True)
    parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args()
    version(args.version);validate_source(args.source)
    if args.command=='validate':
        distribution_approved(json.loads(os.environ.get('D4_DISTRIBUTION_APPROVAL','{}')),args.source,args.version)
        if os.environ.get('D4_BUILD_ONLY')=='false':
            environment=json.loads(subprocess.check_output(['gh','api',f"repos/{os.environ['GITHUB_REPOSITORY']}/environments/d4planner-release"],text=True))
            protected_environment(environment)
    elif args.command=='build':
        inputs=args.directory/'private-inputs'; inputs.parent.mkdir(parents=True,exist_ok=True)
        download_inputs(os.environ.get('D4_PRIVATE_INPUT_URL',''),os.environ.get('D4_PRIVATE_INPUT_SHA256',''),inputs)
        metadata=build(inputs,args.directory/'build',args.source,args.version)
        with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as output:
            output.write(f"setup_sha256={metadata['sha256']}\n")
    else:
        metadata,artifact=verify_built_artifact(args.directory,args.source,args.version,os.environ.get('D4_BUILT_SETUP_SHA256'))
        if args.command=='verify': return 0
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
