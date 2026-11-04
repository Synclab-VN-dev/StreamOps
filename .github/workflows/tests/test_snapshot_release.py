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
                name=f'{kind}-snapshot-1.0.0.zip.age';(root/name).write_bytes(b'age-encryption.org/v1\nciphertext')
                assets[name]={'bytes':len(b'age-encryption.org/v1\nciphertext'),'sha256':p.file_sha(root/name)}
            p.write(root/'snapshot-pair.json',{'version':'1.0.0','sourceSha':'a'*40,'assets':assets})
            (root/'SHA256SUMS').write_text(''.join(f'{p.file_sha(f)}  {f.name}\n' for f in sorted(root.iterdir()) if f.name!='SHA256SUMS'))
            p.verify_candidate(root,'1.0.0','a'*40)
            (root/'plain.zip').write_bytes(b'private')
            with self.assertRaisesRegex(p.ReleaseBlocked,'INVENTORY'):p.verify_candidate(root,'1.0.0','a'*40)
            (root/'plain.zip').unlink();(root/'ui-snapshot-1.0.0.zip.age').write_bytes(b'corrupt')
            with self.assertRaisesRegex(p.ReleaseBlocked,'PLAINTEXT_ASSET'):p.verify_candidate(root,'1.0.0','a'*40)

    def test_publish_download_verification_precedes_visibility_and_never_clobbers(self):
        for mismatch in (False,True):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as temp:
                root=Path(temp);candidate=root/'candidate';candidate.mkdir();assets={}
                for kind in ('calculation','ui'):
                    name=f'{kind}-snapshot-1.0.0.zip.age';(candidate/name).write_bytes(b'age-encryption.org/v1\nciphertext')
                    assets[name]={'bytes':len(b'age-encryption.org/v1\nciphertext'),'sha256':p.file_sha(candidate/name)}
                p.write(candidate/'snapshot-pair.json',{'version':'1.0.0','sourceSha':'a'*40,
                    'assets':assets,'distribution':{'permission':'PUBLIC_APPROVED'}})
                (candidate/'SHA256SUMS').write_text(''.join(f'{p.file_sha(f)}  {f.name}\n' for f in sorted(candidate.iterdir()) if f.name!='SHA256SUMS'))
                calls=[];exported=[]
                def transport(args,**kw):
                    args=list(map(str,args));calls.append(args)
                    if args[:3]==['gh','api','repos/example/repo/releases']:return b'[[]]'
                    if 'matching-refs' in args[2]:return b'[]'
                    if '/git/ref/' in args[2]:return json.dumps({'object':{'type':'commit','sha':'a'*40}}).encode()
                    if args[:3]==['gh','release','download']:
                        import shutil
                        destination=Path(args[args.index('--dir')+1])
                        for file in candidate.iterdir():shutil.copyfile(file,destination/file.name)
                        if mismatch:(destination/'ui-snapshot-1.0.0.zip.age').write_bytes(b'wrong')
                    return b''
                ctx=SimpleNamespace(version='1.0.0',source={'head':'a'*40},temp=root,intent='publish',
                    env={'GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_REF':'refs/heads/master','GITHUB_REPOSITORY':'example/repo'},
                    build_artifact=lambda name:candidate,artifact=lambda *args:exported.append(args))
                config={'distribution':{'permission':'PUBLIC_APPROVED','version':'1.0.0','reference':'owner-reviewed-pair'}}
                with patch.object(p,'command',side_effect=transport):
                    if mismatch:
                        with self.assertRaises(p.ReleaseBlocked):p.publish(ctx,HERE,config)
                    else:p.publish(ctx,HERE,config)
                visible=any('--draft=false' in call for call in calls)
                self.assertEqual(visible,not mismatch)
                self.assertEqual(bool(exported),not mismatch)
                self.assertFalse(any('--clobber' in call for call in calls))

    def test_build_cleanup_and_no_candidate_on_capture_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);env={'PATH':os.environ['PATH'],'AGE_IDENTITY_SECRET':'isolated-test-placeholder',
                              'BROWSER_INFRA_CHROMIUM_PATH':str(root/'chromium')}
            (root/'chromium').touch();exports=[]
            ctx=SimpleNamespace(temp=root,env=env,version='1.0.0',source={'head':'a'*40},
                artifact=lambda file,name:exports.append(name),log=lambda value:None)
            def tool(args,**kw):
                args=list(map(str,args))
                self.assertNotIn('AGE_IDENTITY_SECRET',kw.get('env',{}))
                if args[0]=='age-keygen':return p.RECIPIENT.encode()
                if any(arg.endswith('/capture.js') for arg in args):
                    p.write(Path(args[-1]),{'runId':'test-run','status':'FAILED','error':'UI_VALIDATION_FAILED','packages':[]})
                    raise p.ReleaseBlocked('BLOCKED_CAPTURE')
                return b''
            with patch.object(p.shutil,'which',return_value='/test/tool'),patch.object(p,'command',side_effect=tool):
                with self.assertRaisesRegex(p.ReleaseBlocked,'BLOCKED_CAPTURE'):
                    p.build(ctx,HERE,{'sourceUrl':'https://maxroll.gg/d4/planner/test','authorizationRef':'test'})
            self.assertEqual(exports,['capture-receipt.json'])
            self.assertFalse((root/'snapshot-private').exists())

    def test_build_orchestration_exports_only_after_all_roundtrip_gates(self):
        # Simulated provider/crypto transports test ordering, not real-provider acceptance.
        with tempfile.TemporaryDirectory() as temp:
            import shutil
            root=Path(temp);here=root/'rulekit/snapshot-management/release';here.mkdir(parents=True)
            provider=root/'rulekit/providers/maxroll';(provider/'artifacts').mkdir(parents=True)
            (root/'chromium').touch();exports=root/'exports';exports.mkdir();calls=[]
            ctx=SimpleNamespace(temp=root,env={'PATH':os.environ['PATH'],'AGE_IDENTITY_SECRET':'test',
                'BROWSER_INFRA_CHROMIUM_PATH':str(root/'chromium')},version='1.0.0',source={'head':'a'*40},
                log=lambda text:None)
            def artifact(file,name):
                if Path(file).is_dir():shutil.copytree(file,exports/name)
                else:shutil.copyfile(file,exports/name)
            ctx.artifact=artifact
            verified={'coverageSha256':'a'*64,'validationSha256':'b'*64,'distribution':{'permission':'PRIVATE_ONLY'}}
            def transport(args,**kw):
                args=list(map(str,args));calls.append(args)
                self.assertNotIn('AGE_IDENTITY_SECRET',kw.get('env',{}))
                if args[0]=='age-keygen':return p.RECIPIENT.encode()
                if args[0]=='age':
                    data=Path(args[-1]).read_bytes()
                    data=b'age-encryption.org/v1\n'+data if '--encrypt' in args else data.removeprefix(b'age-encryption.org/v1\n')
                    Path(args[args.index('--output')+1]).write_bytes(data);return b''
                if any(arg.endswith('/capture.js') for arg in args):
                    config=p.read(args[-2]);packages=[]
                    for kind in ('calculation','ui'):
                        store=Path(config[kind+'Root']);snapshot=store/kind;snapshot.mkdir(parents=True)
                        p.write(snapshot/'manifest.json',{'resources':[]})
                        (snapshot/'manifest.sha256').write_text('a'*64)
                        if kind=='ui':
                            p.write(snapshot/'ui-coverage.json',{})
                            p.write(snapshot/'ui-validation.json',{'referenceReportSha256':'a'*64})
                        packages.append({'kind':kind,'snapshotId':kind,'snapshotRoot':str(store),
                            'manifestSha256':'a'*64,'runId':'test-run'})
                    p.write(args[-1],{'status':'COMPLETE','runId':'test-run','packages':packages})
                elif any(arg.endswith('/verify.js') for arg in args):p.write(args[-1],verified)
                elif args[:3]==['npm','run','test:real']:
                    p.write(provider/'artifacts/real-acceptance.json',{'status':'PASS','applicationApis':list(range(8)),
                        'transportOfflineEveryEvaluation':True})
                elif any(arg.endswith('/full-acceptance.js') for arg in args):
                    config=p.read(args[-1]);out=Path(config['output']);out.mkdir()
                    p.write(out/'acceptance.json',{'status':'AUTOMATED_PASS'})
                return b''
            def fetch_input(descriptor,target):p.write(target,{})
            with patch.object(p.shutil,'which',return_value='/test/tool'),patch.object(p,'command',side_effect=transport),patch.object(p,'fetch',side_effect=fetch_input):
                p.build(ctx,here,{'sourceUrl':'https://maxroll.gg/d4/planner/test','authorizationRef':'test',
                    'entryId':'approved-example','realProfileId':'existing-profile'})
            self.assertFalse((root/'snapshot-private').exists())
            metadata=p.verify_candidate(exports/'snapshots','1.0.0','a'*40)
            self.assertEqual(len(metadata['assets']),2)
            self.assertEqual(sum(call[:3]==['npm','run','test:real'] for call in calls),2)
            self.assertFalse(any(call[0]=='gh' for call in calls))

    def test_commands_do_not_leak_private_output(self):
        completed=SimpleNamespace(returncode=1,stdout=b'private data',stderr=b'password secret raw URL')
        with patch.object(p.subprocess,'run',return_value=completed):
            with self.assertRaisesRegex(p.ReleaseBlocked,'^BLOCKED_COMMAND_NODE$'):p.command(['node','private.js'])

if __name__=='__main__':unittest.main()
