"""Single Release workflow support. No Actions dispatch/query or implicit release.

Public runtime build inputs are checksum-addressed and content-allowlisted.
The runner never downloads/mounts Maxroll snapshots. Build-only validates artifacts without publication gates. Publication refuses an
existing GitHub Release; unknown API outcomes fail closed.
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

ROOT = Path(__file__).resolve().parents[4]
LOCK = ROOT / 'utility/d4planner/d4planner-be/release1/release-runtime-lock.json'
PRODUCT_PLAN = ROOT / 'utility/d4planner/d4planner-be/release1/package-plan.json'


def require(condition, error):
    if not condition: raise ValueError(error)


def validate_source(value):
    require(bool(re.fullmatch('[0-9a-f]{40}', value)), 'INVALID_SOURCE_SHA')


def github_document(endpoint):
    """Return JSON or None for an explicit HTTP 404; never infer absence on errors."""
    result = subprocess.run(['gh', 'api', '--include', endpoint],
                            capture_output=True, text=True, timeout=30)
    statuses = re.findall(r'^HTTP/\S+ (\d{3})\b', result.stdout, re.MULTILINE)
    status = statuses[-1] if statuses else None
    if result.returncode != 0 and status == '404':
        return None
    require(result.returncode == 0 and status == '200', 'GITHUB_LOOKUP_FAILED')
    try:
        document = json.loads(re.split(r'\r?\n\r?\n', result.stdout, maxsplit=1)[1])
    except (ValueError, IndexError):
        raise ValueError('GITHUB_LOOKUP_FAILED') from None
    require(isinstance(document, dict), 'GITHUB_LOOKUP_FAILED')
    return document


def require_release_absent(repo, tag):
    require(github_document(f'repos/{repo}/releases/tags/{tag}') is None,
            'RELEASE_ALREADY_EXISTS')


def ensure_source_tag(repo, tag, head):
    # A pre-existing tag is not a Release. Reuse it only if it resolves to the
    # exact build source; never move or overwrite a tag to publish other bytes.
    document = github_document(f'repos/{repo}/git/ref/tags/{tag}')
    if document is None:
        run(['gh', 'api', f'repos/{repo}/git/refs', '--method', 'POST',
             '-f', f'ref=refs/tags/{tag}', '-f', f'sha={head}'])
        return
    obj = document.get('object', {})
    for _ in range(8):
        if obj.get('type') != 'tag':
            break
        sha = obj.get('sha', '')
        validate_source(sha)
        document = github_document(f'repos/{repo}/git/tags/{sha}')
        require(document is not None, 'TAG_SOURCE_UNVERIFIED')
        obj = document.get('object', {})
    require(obj.get('type') == 'commit' and obj.get('sha') == head,
            'TAG_SOURCE_MISMATCH')


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


def prepare_upload(directory, head, release_version):
    # Integrity and content checks apply equally to build-only and publication.
    metadata=delivery.load_json(directory/'release-metadata.json')
    metadata,artifact=verify_built_artifact(directory,head,release_version,metadata['sha256'])
    require(metadata.get('runtimeHealth')=='PASS','RUNTIME_HEALTH_REQUIRED')
    metadata.update(productVersion=release_version,encryption='none',
                    ciRunId=os.environ.get('GITHUB_RUN_ID'))
    (directory/'release-metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    (directory/'SHA256SUMS').write_text(f"{metadata['sha256']}  {artifact.name}\n",encoding='utf-8')
    (directory/'UAT.md').write_text('D4Planner R1 UAT, chưa phải production approval.\nKiểm tra SHA256SUMS rồi chạy '+artifact.name+'. Không cần age/decrypt cho Application.\nSnapshot .zip.age được provision riêng qua Rule Kit; không chứa trong Setup. T20–T23 chờ Owner MAN.\n',encoding='utf-8')
    return metadata


def verify_upload(directory, head, release_version, expected_sha):
    metadata,artifact=verify_built_artifact(directory,head,release_version,expected_sha)
    require(metadata.get('runtimeHealth')=='PASS','RUNTIME_HEALTH_REQUIRED')
    require(metadata.get('encryption')=='none','PLAINTEXT_APPLICATION_REQUIRED')
    require({p.name for p in directory.iterdir()}=={artifact.name,'release-metadata.json','SHA256SUMS','UAT.md'},'UNEXPECTED_PUBLIC_ASSET')
    require(not any(p.is_symlink() for p in directory.iterdir()),'PUBLIC_ASSET_SYMLINK')
    require((directory/'SHA256SUMS').read_text(encoding='utf-8')==f"{expected_sha}  {artifact.name}\n",'CHECKSUM_FILE_MISMATCH')
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
    frontend=ROOT/'utility/d4planner/d4planner-hud'
    npm='npm.cmd'
    for module in ('browser-infra','providers/maxroll','snapshot-management'):
        run([npm,'ci','--omit=dev','--ignore-scripts'],cwd=ROOT/'utility/d4planner/d4planner-rulekit'/module)
    require(delivery.load_json(ROOT/'utility/d4planner/d4planner-rulekit/providers/maxroll/node_modules/playwright-core/package.json')['version']=='1.64.1','PLAYWRIGHT_PIN')
    run([npm,'ci','--ignore-scripts'],cwd=frontend)
    run([npm,'test'],cwd=frontend); run([npm,'run','build'],cwd=frontend)
    prepare_frontend_native_assets(frontend, npm)
    # The CI runner has VC runtimes; the user's clean machine need not.
    # Apply the same static CRT policy already used by the root launcher.
    run(['cargo','build','--release','--locked','--manifest-path',frontend/'src-tauri/Cargo.toml'],
        env={**os.environ, 'RUSTFLAGS': '-C target-feature=+crt-static'})
    launcher=ROOT/'utility/d4planner/d4planner-launcher'
    run(['cargo','build','--release','--locked','--manifest-path',launcher/'Cargo.toml'], cwd=launcher)
    run(['cargo','test','--release','--locked','--manifest-path',launcher/'Cargo.toml'], cwd=launcher)
    # Backend wheel from the current source, dependencies are pinned above.
    wheel=output/'wheel'; wheel.mkdir()
    run([sys.executable,'-m','pip','wheel','--no-deps','--no-build-isolation',ROOT/'utility/d4planner/d4planner-be','--wheel-dir',wheel])
    site=output/'site-packages'
    run([sys.executable,'-m','pip','install','--no-compile','--target',site,'-r',ROOT/'utility/d4planner/d4planner-be/release1/requirements-release.txt'])
    for path in wheel.glob('*.whl'):
        run([sys.executable,'-m','pip','install','--no-compile','--no-deps','--target',site,path])
        run([sys.executable,'-m','pip','install','--no-deps',path])
    run([sys.executable,'-m','pytest','-q','utility/d4planner/d4planner-be/tests/contracts/test_release1_contract.py',
         'utility/d4planner/d4planner-be/tests/test_windows_install.py','utility/d4planner/d4planner-be/tests/test_release_ci.py',
         'utility/d4planner/d4planner-be/tests/test_package_entrypoint.py'])
    tools=ROOT/'utility/d4planner/d4planner-be/tools'
    stage=output/'stage'
    run([sys.executable,tools/'build_release1_stage.py','--launcher-exe',Path(os.environ.get('CARGO_TARGET_DIR',launcher/'target'))/'release/D4Planner.exe',
         '--frontend-exe',Path(os.environ.get('CARGO_TARGET_DIR',frontend/'src-tauri/target'))/'release/d4planner-overlay-poc.exe',
         '--python-root',inputs/'python','--python-site-packages',site,'--node-root',inputs/'node',
         '--chromium-root',inputs/'chromium','--output',stage])
    package=output/f'D4Planner-{release_version}.zip'
    run([sys.executable,tools/'release1_delivery.py','build','--plan',ROOT/'utility/d4planner/d4planner-be/release1/package-plan.json',
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
    launch_report = output/'runtime-launch.json'
    try:
        run([health_app/'D4Planner.exe','--runtime-health','--health-report',health],
            env={**os.environ, 'D4PLANNER_LAUNCH_REPORT': str(launch_report)})
    except subprocess.CalledProcessError:
        if launch_report.exists():
            print(launch_report.read_text(encoding='utf-8'), file=sys.stderr)
        raise
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
    parser.add_argument('command',choices=('validate','build','verify','publish','validate-upload','prepare-upload'))
    parser.add_argument('--version',required=True)
    parser.add_argument('--source',required=True)
    parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args()
    product_version(args.version);validate_source(args.source)
    if args.command=='validate':
        build_only = os.environ.get('D4_BUILD_ONLY', 'true')
        require(build_only in {'true', 'false', ''}, 'INVALID_BUILD_ONLY')
        if build_only != 'false':
            return 0
        tag = f'v{args.version}'
        require_release_absent(os.environ['GITHUB_REPOSITORY'], tag)
    elif args.command=='build':
        inputs=args.directory/'public-runtime-inputs'; inputs.parent.mkdir(parents=True,exist_ok=True)
        if os.environ.get('D4_LOCAL_RUNTIME_CACHE'):
            # Optional local builder cache; the same manifest/tree pins remain mandatory.
            cache=Path(os.environ['D4_LOCAL_RUNTIME_CACHE'])/delivery.sha256_file(LOCK)
            if not cache.exists():
                partial=cache.with_name(cache.name+'.partial')
                if partial.exists(): shutil.rmtree(partial)
                partial.parent.mkdir(parents=True,exist_ok=True)
                prepare_upstream_inputs(partial)
                partial.rename(cache)
            validate_inputs(cache)
            inputs=cache
        elif os.environ.get('D4_PUBLIC_RUNTIME_INPUT_URL'):
            download_inputs(os.environ['D4_PUBLIC_RUNTIME_INPUT_URL'],os.environ.get('D4_PUBLIC_RUNTIME_INPUT_SHA256',''),inputs)
        else:prepare_upstream_inputs(inputs)
        metadata=build(inputs,args.directory/'build',args.source,args.version)
        with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as output:
            output.write(f"setup_sha256={metadata['sha256']}\n")
    elif args.command=='prepare-upload':
        metadata=prepare_upload(args.directory,args.source,args.version)
    else:
        metadata,artifact=verify_upload(args.directory,args.source,args.version,os.environ.get('D4_BUILT_SETUP_SHA256'))
        if args.command=='verify': return 0
        if args.command=='validate-upload':return 0
        repo=os.environ['GITHUB_REPOSITORY'];tag=f'v{args.version}'
        require_release_absent(repo, tag)
        ensure_source_tag(repo, tag, args.source)
        run(['gh','release','create',tag,str(artifact),str(args.directory/'SHA256SUMS'),str(args.directory/'release-metadata.json'),
             '--repo',repo,'--verify-tag','--title',f'D4Planner {args.version}','--notes',f"Source {args.source}; SHA-256 {metadata['sha256']}"])
    return 0

if __name__=='__main__': raise SystemExit(main())
