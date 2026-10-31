"""S7 distribution boundary, not Rule Kit compatibility logic.

Only reviewed public runtime/source/dependency inputs enter the application.
Known private payload fingerprints are metadata only; public CI never downloads
or mounts the snapshot in order to inspect/remove it.
"""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path

_MODULE = Path(__file__).resolve()
# Source-tool metadata only; packaged maintenance need not have this ancestor.
ROOT = _MODULE.parents[4] if len(_MODULE.parents) > 4 else None

SKIP_PARTS={'.git','.github','.bin','__pycache__','test','tests','spec','specs','fixtures','examples','docs','benchmarks','benchmark'}
MODULES=('application','browser-infra','providers/maxroll','snapshot-management')


class PublicContentError(RuntimeError): pass


def included(relative: Path):
    return not any(part.lower() in SKIP_PARTS for part in relative.parts) and relative.name!='.package-lock.json'


def tree_digest(root: Path,*,dependencies=False):
    records=[]
    for path in sorted(root.rglob('*'), key=lambda p:p.relative_to(root).parts):
        relative=path.relative_to(root)
        if not included(relative):continue
        if dependencies and relative.parts[:2]==('@streamops','browser-infrastructure'):continue
        if path.is_symlink():raise PublicContentError('PUBLIC_INPUT_SYMLINK')
        if path.is_file():
            data=path.read_bytes()
            if dependencies and path.suffix.lower() in {'.js','.json','.ts','.md','.txt','.yml','.yaml'}:data=data.replace(b'\r\n',b'\n')
            records.append((relative.as_posix(),hashlib.sha256(data).hexdigest()))
    return hashlib.sha256(json.dumps(records,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def policy():
    module = Path(__file__).resolve()
    # Installed maintenance has no source checkout and may be at C:\App.
    # Keep the colocated reviewed policy authoritative; source-tree fallbacks
    # are only meaningful when the corresponding ancestor actually exists.
    candidates = [module.with_name('public-content-policy.json')]
    for depth in (4, 1):
        if len(module.parents) > depth:
            candidates.append(module.parents[depth]/'utility/d4planner/d4planner-be/release1/public-content-policy.json')
            candidates.append(module.parents[depth]/'utility/d4planner/release1/public-content-policy.json')
    for candidate in candidates:
        if candidate.is_file():return json.loads(candidate.read_text(encoding='utf-8'))
    raise PublicContentError('PUBLIC_CONTENT_POLICY_MISSING')


def validate_tree(root: Path,key: str,*,dependencies=False):
    expected=policy()['inputTreeSha256'].get(key)
    if not expected or tree_digest(root,dependencies=dependencies)!=expected:raise PublicContentError('UNREVIEWED_PUBLIC_INPUT_TREE:'+key)


def inspect_bytes(name: str,data: bytes):
    lower=name.lower();parts=lower.split('/')
    if lower.startswith('runtime/snapshots/') or lower=='config/maxroll-profile.json' or any(part in {'snapshots','private-snapshots','.artifacts','artifacts'} for part in parts):
        raise PublicContentError('PRIVATE_SNAPSHOT_PATH:'+name)
    if lower.endswith(('.db','.sqlite','.sqlite3')):raise PublicContentError('USER_DATABASE_IN_PUBLIC_PACKAGE:'+name)
    if lower.endswith(('.enc','.aes','.gpg','.age','.tgz','.7z','.rar')):raise PublicContentError('PRIVATE_OR_UNREVIEWED_ARCHIVE:'+name)
    digest=hashlib.sha256(data).hexdigest()
    if digest in policy()['knownPrivatePayloadSha256']:raise PublicContentError('KNOWN_PRIVATE_PAYLOAD:'+name)
    if data.startswith((b'PK\x03\x04',b'\x1f\x8b',b'7z\xbc\xaf\x27\x1c')):
        if policy()['publicArchiveSha256'].get(name)!=digest:raise PublicContentError('UNREVIEWED_EMBEDDED_ARCHIVE:'+name)
    if re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/]',data):raise PublicContentError('PRIVATE_KEY_CONTENT:'+name)
    if name.endswith('.json'):
        try:value=json.loads(data)
        except (ValueError,UnicodeError):return
        if isinstance(value,dict):
            if value.get('schemaVersion') in {'web-snapshot/v1','web-snapshot-draft/v1','d4-rulekit-snapshot-package/v1','d4-rulekit-registry-envelope/v1'}:raise PublicContentError('PRIVATE_RESOURCE_DOCUMENT:'+name)
            if 'snapshotId' in value and ('realRuntime' in value or 'runtimeKind' in value):raise PublicContentError('PRIVATE_PROFILE_DOCUMENT:'+name)
            if 'ciphertext' in value or 'encryptedSnapshot' in value:raise PublicContentError('ENCRYPTED_PRIVATE_RESOURCE:'+name)


def inspect_directory(root: Path):
    count=0
    for path in root.rglob('*'):
        if path.is_symlink():raise PublicContentError('PUBLIC_PACKAGE_SYMLINK')
        if path.is_file():inspect_bytes(path.relative_to(root).as_posix(),path.read_bytes());count+=1
    return {'snapshotIncluded':False,'filesInspected':count,'inspectionPolicy':'d4planner-public-content/v1'}
