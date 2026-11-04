"""Local snapshot product/core tests. No production capture or release mutation."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
import stat

ROOT=Path(__file__).resolve().parents[3]
HERE=ROOT/'utility/d4planner/d4planner-rulekit/snapshot-management/release'
def load(name, filename):
    spec=importlib.util.spec_from_file_location(name,filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
p=load('snapshot_pipeline_test',HERE/'pipeline.py')
ci=load('snapshot_engine_test',ROOT/'.github/workflows/ci.py')

class SnapshotRelease(unittest.TestCase):
    def test_discovery_and_separate_permission_matrices(self):
        specs=ci.discover(ROOT)
        self.assertIn('d4planner-snapshots',specs)
        self.assertIn('d4planner-release',specs)
        spec=specs['d4planner-snapshots']
        self.assertEqual([j['capability'] for j in spec['jobs']],['private-build','publish'])
        document=ci.plan(ROOT,dirty=True,product='d4planner-snapshots',operation='build')
        matrix=ci.matrices(document)
        self.assertEqual(len(matrix['private_build']['include']),1)
        self.assertFalse(matrix['publish']['include'])
        self.assertFalse(matrix['read']['include'])

    def test_wrapper_keeps_only_public_operations_and_gates_private_job(self):
        wrapper=(ROOT/'.github/workflows/main.yml').read_text()
        header=wrapper.split('jobs:',1)[0]
        self.assertNotIn('    - private_build',header)
        job=wrapper.split('\n  private_build:\n',1)[1].split('\n  fixture:\n',1)[0]
        self.assertIn("github.ref == 'refs/heads/master'",job)
        self.assertIn("github.event_name == 'workflow_dispatch'",job)
        self.assertIn('contents: read',job)
        self.assertNotIn('contents: write',job)

    def test_private_build_cannot_be_test_or_publish(self):
        for operation,kind in [('test','test'),('publish','release')]:
            spec={'version':1,'id':'example','jobs':[{'id':'job','profile':'linux','timeout':10,
                'operation':operation,'capability':'private-build'}]}
            with self.assertRaises(ci.ContractError):
                ci.metadata('CI_SPEC = '+repr(spec)+'\ndef run(ctx): pass',f'example/ci.{kind}.py')

    def test_actions_private_build_requires_manual_master_and_exact_source(self):
        with tempfile.TemporaryDirectory() as temp:
            event=Path(temp)/'event.json'
            event.write_text(json.dumps({'inputs':{'operation':'build','product':'example','version':'1.0.0'}}))
            env={'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_REF':'refs/heads/master',
                 'GITHUB_EVENT_PATH':str(event),'GITHUB_SHA':'a'*40}
            with patch.dict(os.environ,env,clear=True):
                ci.authorize_private_build({'head':'a'*40,'dirty':False},'1.0.0','example')
                for key,value in [('GITHUB_EVENT_NAME','pull_request'),('GITHUB_REF','refs/heads/feature'),('GITHUB_SHA','b'*40)]:
                    with patch.dict(os.environ,{key:value}):
                        with self.assertRaises(ci.ContractError):ci.authorize_private_build({'head':'a'*40},'1.0.0','example')
                with self.assertRaises(ci.ContractError):ci.authorize_private_build({'head':'a'*40,'dirty':True},'1.0.0','example')

    def test_config_does_not_invent_authorization(self):
        with self.assertRaisesRegex(p.ReleaseBlocked,'BLOCKED_CAPTURE_AUTHORIZATION'):
            p.load_config(SimpleNamespace(env={}),HERE)

    def test_zip_is_deterministic_and_roundtrip_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.mkdir();(source/'manifest.json').write_text('{}')
            files=p.pack(source,root/'one.zip');p.pack(source,root/'two.zip')
            self.assertEqual(p.file_sha(root/'one.zip'),p.file_sha(root/'two.zip'))
            output=p.unpack(root/'one.zip',root/'extracted',files)
            self.assertEqual(p.inventory(source),p.inventory(output))
            files['manifest.json']['sha256']='0'*64
            with self.assertRaisesRegex(p.ReleaseBlocked,'BLOCKED_ARCHIVE_HASH'):
                p.unpack(root/'one.zip',root/'bad',files)

    def test_archive_traversal_duplicates_symlinks_and_limit_rejected(self):
        cases=[('../outside',None),('file',stat.S_IFLNK|0o777)]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for i,(name,mode) in enumerate(cases):
                archive=root/f'{i}.zip'
                with zipfile.ZipFile(archive,'w') as z:
                    info=zipfile.ZipInfo(name)
                    if mode: info.external_attr=mode<<16
                    z.writestr(info,b'x')
                with self.assertRaises(p.ReleaseBlocked):p.unpack(archive,root/f'out{i}',{name:{'bytes':1,'sha256':p.sha(b'x')}})
            archive=root/'duplicate.zip'
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                with zipfile.ZipFile(archive,'w') as z:z.writestr('x','a');z.writestr('x','b')
            with self.assertRaisesRegex(p.ReleaseBlocked,'INVENTORY'):p.unpack(archive,root/'duplicates',{'x':{}})
            source=root/'source';source.mkdir();(source/'a').write_text('xx')
            with patch.object(p,'MAX_BYTES',1):
                with self.assertRaisesRegex(p.ReleaseBlocked,'LIMIT'):p.pack(source,root/'limit.zip')

    def test_candidate_checks_exact_outer_inventory_and_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);assets={}
            for kind in ('calculation','ui'):
                name=f'{kind}-snapshot-1.0.0.zip.age';(root/name).write_bytes(b'ciphertext')
                assets[name]={'bytes':10,'sha256':p.file_sha(root/name)}
            p.write(root/'snapshot-pair.json',{'version':'1.0.0','sourceSha':'a'*40,'assets':assets})
            (root/'SHA256SUMS').write_text(''.join(f'{p.file_sha(f)}  {f.name}\n' for f in sorted(root.iterdir()) if f.name!='SHA256SUMS'))
            p.verify_candidate(root,'1.0.0','a'*40)
            (root/'plain.zip').write_bytes(b'private')
            with self.assertRaisesRegex(p.ReleaseBlocked,'INVENTORY'):p.verify_candidate(root,'1.0.0','a'*40)
            (root/'plain.zip').unlink();(root/'ui-snapshot-1.0.0.zip.age').write_bytes(b'corrupt')
            with self.assertRaisesRegex(p.ReleaseBlocked,'HASH'):p.verify_candidate(root,'1.0.0','a'*40)

    def test_commands_do_not_leak_private_output(self):
        completed=SimpleNamespace(returncode=1,stdout=b'private data',stderr=b'password secret raw URL')
        with patch.object(p.subprocess,'run',return_value=completed):
            with self.assertRaisesRegex(p.ReleaseBlocked,'^BLOCKED_COMMAND_NODE$'):p.command(['node','private.js'])

if __name__=='__main__':unittest.main()
