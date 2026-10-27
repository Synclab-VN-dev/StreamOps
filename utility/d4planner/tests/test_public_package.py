"""Distribution boundary tests; synthetic bytes never qualify native acceptance."""
import json,sys,zipfile
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import public_package as public
import release1_delivery as delivery

@pytest.mark.parametrize('name,payload',[
 ('runtime/snapshots/secret/manifest.json',b'private'),
 ('utility/d4-rulekit/providers/maxroll/hidden.enc',b'encrypted-private'),
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
        public.inspect_bytes('utility/d4-rulekit/application/src/helper.js',data)


def test_public_plan_excludes_snapshot_and_profile_and_pins_management_contract():
    plan=json.loads((public.ROOT/'utility/d4planner/release1/package-plan.json').read_text())
    assert plan['ruleKit']['snapshotIncluded'] is False
    assert 'snapshotId' not in plan['ruleKit'] and 'snapshotManifestSha256' not in plan['ruleKit']
    assert not any(row['path'].startswith(('runtime/snapshots','config/maxroll')) for row in plan['artifacts'])
    allowlist=public.policy()['sourceAllowlist']
    assert 'utility/d4-rulekit/snapshot-management/manage.js' in allowlist
    assert not any('/tests/' in name or '/fixtures/' in name or '/node_modules/' in name for name in allowlist)


def test_unreviewed_runtime_content_is_rejected_before_assembly(tmp_path):
    root=tmp_path/'node';root.mkdir();(root/'node.exe').write_bytes(b'unit-only-unreviewed-runtime')
    with pytest.raises(public.PublicContentError,match='UNREVIEWED_PUBLIC_INPUT_TREE'):
        public.validate_tree(root,'runtime/node')
