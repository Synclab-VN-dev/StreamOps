"""Distribution boundary tests; synthetic bytes never qualify native acceptance."""
import json,sys,zipfile
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import public_package as public
import release1_delivery as delivery

@pytest.mark.parametrize('name,payload',[
 ('runtime/snapshots/secret/manifest.json',b'private'),
 ('utility/d4planner/d4planner-rulekit/providers/maxroll/hidden.enc',b'encrypted-private'),
 ('backend/site-packages/renamed.json',b'{"schemaVersion":"web-snapshot/v1","resources":[]}'),
 ('backend/site-packages/profile.json',b'{"snapshotId":"secret","runtimeKind":"maxroll-ui-cdp-v1"}'),
 ('app/captured.json',b'{"ciphertext":"not-public"}'),
 ('app/renamed.txt',b'PK\x03\x04synthetic-encrypted-container'),
 ('backend/site-packages/user.sqlite',b'synthetic-user-db'),
])
def test_public_inspection_rejects_private_formats_even_when_renamed(name,payload):
    with pytest.raises(public.PublicContentError):public.inspect_bytes(name,payload)


def test_known_private_payload_cannot_be_hidden_under_an_allowed_source_name(monkeypatch):
    import hashlib
    data=b'synthetic private payload fingerprint test only'
    settings=public.policy();settings['knownPrivatePayloadSha256']=[hashlib.sha256(data).hexdigest()]
    monkeypatch.setattr(public,'policy',lambda:settings)
    with pytest.raises(public.PublicContentError,match='KNOWN_PRIVATE_PAYLOAD'):
        public.inspect_bytes('utility/d4planner/d4planner-rulekit/application/src/helper.js',data)


def test_public_plan_excludes_snapshot_and_profile_and_pins_management_contract():
    plan=json.loads((public.ROOT/'utility/d4planner/d4planner-be/release1/package-plan.json').read_text())
    assert plan['ruleKit']['snapshotIncluded'] is False
    assert 'snapshotId' not in plan['ruleKit'] and 'snapshotManifestSha256' not in plan['ruleKit']
    assert not any(row['path'].startswith(('runtime/snapshots','config/maxroll')) for row in plan['artifacts'])
    allowlist=public.policy()['sourceAllowlist']
    assert 'utility/d4planner/d4planner-rulekit/snapshot-management/manage.js' in allowlist
    assert not any('/tests/' in name or '/fixtures/' in name or '/node_modules/' in name for name in allowlist)


def test_unreviewed_runtime_content_is_rejected_before_assembly(tmp_path):
    root=tmp_path/'node';root.mkdir();(root/'node.exe').write_bytes(b'unit-only-unreviewed-runtime')
    with pytest.raises(public.PublicContentError,match='UNREVIEWED_PUBLIC_INPUT_TREE'):
        public.validate_tree(root,'runtime/node')


def test_public_sources_preserve_trusted_execution_inventory():
    """A package must contain every byte the approved loader verifies."""
    index_path = 'utility/d4planner/d4planner-rulekit/snapshot-management/compatibility/compatibility-index.json'
    inventory = json.loads((public.ROOT / index_path).read_text())
    required = {index_path, *('utility/d4planner/d4planner-rulekit/' + row['path'] for row in inventory['files'])}
    assert required <= set(public.policy()['sourceAllowlist'])
    for relative in required:
        public.inspect_bytes(relative, (public.ROOT / relative).read_bytes())


def test_missing_policy_at_shallow_install_path_is_typed_error(monkeypatch):
    # Installed maintenance helpers may live directly below a drive root;
    # they must not assume the source checkout's ancestor depth.
    monkeypatch.setattr(public, '__file__', str(Path.cwd().anchor + 'public_package.py'))
    with pytest.raises(public.PublicContentError, match='PUBLIC_CONTENT_POLICY_MISSING'):
        public.policy()


def test_installed_helper_uses_colocated_policy(tmp_path, monkeypatch):
    expected = public.policy()
    (tmp_path / 'public-content-policy.json').write_text(json.dumps(expected), encoding='utf-8')
    monkeypatch.setattr(public, '__file__', str(tmp_path / 'public_package.py'))
    assert public.policy() == expected


def test_maintenance_module_import_at_windows_drive_root():
    from pathlib import PureWindowsPath
    from unittest.mock import patch

    source = Path(public.__file__).read_text(encoding='utf-8')
    installed = PureWindowsPath('C:/D4App/maintenance/public_package.py')
    namespace = {'__file__': str(installed), '__name__': 'installed_public_package'}
    with patch.object(Path, 'resolve', return_value=installed):
        exec(compile(source, str(installed), 'exec'), namespace)
    assert callable(namespace['inspect_directory'])


def test_runtime_tree_digest_uses_case_sensitive_component_order_on_windows(tmp_path):
    import hashlib,json
    (tmp_path/'Z.dll').write_bytes(b'z')
    (tmp_path/'a.exe').write_bytes(b'a')
    (tmp_path/'a-dir').mkdir();(tmp_path/'a-dir/runtime.bin').write_bytes(b'r')
    records=[('Z.dll',hashlib.sha256(b'z').hexdigest()),
             ('a-dir/runtime.bin',hashlib.sha256(b'r').hexdigest()),
             ('a.exe',hashlib.sha256(b'a').hexdigest())]
    expected=hashlib.sha256(json.dumps(records,separators=(',',':')).encode()).hexdigest()
    assert public.tree_digest(tmp_path)==expected
