"""Snapshot release adapter tests; transports are mocked, no live publication."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

ROOT=Path(__file__).resolve().parents[5]
HERE=ROOT/'utility/d4planner/d4planner-rulekit/snapshot-management/release'
def load(name, filename):
    spec=importlib.util.spec_from_file_location(name,filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
p=load('snapshot_pipeline_test',HERE/'pipeline.py')
ci=load('snapshot_engine_test',ROOT/'.github/workflows/ci.py')

class HostedContext(SimpleNamespace):
    def variable(self, name, default=None):
        return self.variables.get(name, default)

class SnapshotRelease(unittest.TestCase):
    def test_fetch_accepts_pinned_archive_above_old_limit_and_at_new_limit(self):
        # age v1.3.2 Linux archive is 19,405,817 bytes; no live network required.
        for size in (19_405_817, 32*1024*1024):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as temp:
                content=b'a'*size
                response=io.BytesIO(content);response.url='https://example.invalid/age.tar.gz'
                target=Path(temp)/'age.tar.gz'
                with patch.object(p.urllib.request,'urlopen',return_value=response):
                    p.fetch({'url':response.url,'sha256':p.sha(content)},target)
                self.assertEqual(target.read_bytes(),content)
                self.assertEqual(target.stat().st_mode & 0o777,0o600)

    def test_fetch_blocks_oversize_and_hash_mismatch_without_writing(self):
        for content,expected_hash,code in (
            (b'a'*(32*1024*1024+1),None,'BLOCKED_INPUT_SIZE'),
            (b'tampered archive','0'*64,'BLOCKED_INPUT_HASH'),
        ):
            for exists in (False,True):
                with self.subTest(code=code,exists=exists), tempfile.TemporaryDirectory() as temp:
                    response=io.BytesIO(content);response.url='https://example.invalid/age.tar.gz'
                    target=Path(temp)/'age.tar.gz'
                    if exists:target.write_bytes(b'existing')
                    with patch.object(p.urllib.request,'urlopen',return_value=response), \
                         patch.object(response,'read',wraps=response.read) as read:
                        with self.assertRaisesRegex(p.ReleaseBlocked,'^'+code+'$'):
                            p.fetch({'url':response.url,'sha256':expected_hash or p.sha(content)},target)
                        read.assert_called_once_with(32*1024*1024+1)
                    if exists:self.assertEqual(target.read_bytes(),b'existing')
                    else:self.assertFalse(target.exists())

    def test_discovery_routes_build_without_secrets(self):
        specs=ci.discover(ROOT)
        self.assertIn('d4planner-release',specs)
        jobs=specs['d4planner-snapshots']['jobs']
        self.assertEqual([job['capability'] for job in jobs],['read','publish'])
        self.assertFalse(any(job.get('secrets') for job in jobs))
        document=ci.plan(ROOT,dirty=True,product='d4planner-snapshots',operation='build')
        matrix=ci.matrices(document)
        self.assertEqual(len(matrix['read']['include']),1)
        self.assertFalse(matrix['publish']['include'])

    def config(self):
        return {'sourceUrl':'https://maxroll.gg/d4/planner/test123',
                'ageRecipient':p.RECIPIENT}

    def test_actions_json_variable_replaces_unconfigured_source_file(self):
        config=self.config()
        ctx=HostedContext(env={'GITHUB_ACTIONS':'true'},variables={
            'D4_SNAPSHOT_RELEASE_CONFIG':json.dumps(config, indent=2, ensure_ascii=False)})
        with patch.object(p,'read',side_effect=AssertionError('Actions must not read local config')):
            self.assertEqual(p.load_config(ctx,HERE),config)

    def test_actions_rejects_missing_invalid_or_ambiguous_config_without_fallback(self):
        cases=[({},'MISSING'),({'D4_SNAPSHOT_RELEASE_CONFIG':''},'MISSING'),
               ({'D4_SNAPSHOT_RELEASE_CONFIG':'{private-invalid-json'},'JSON'),
               ({'D4_SNAPSHOT_RELEASE_CONFIG':'[]'},'OBJECT'),
               ({'D4_SNAPSHOT_RELEASE_CONFIG':'null'},'OBJECT'),
               ({'D4_SNAPSHOT_RELEASE_CONFIG':'{"sourceUrl":"a","sourceUrl":"b"}'},'DUPLICATE_FIELD'),
               ({'D4_SNAPSHOT_RELEASE_CONFIG':'x'*16385},'SIZE')]
        for field,value,code in [('sourceUrl',None,'SOURCE_URL'),('sourceUrl','http://maxroll.gg/d4/planner/a','SOURCE_URL'),
            ('sourceUrl','https://evil.invalid/d4/planner/a','SOURCE_URL'),
            ('sourceUrl','https://maxroll.gg/d4/planner/a?token=private','SOURCE_URL'),
            ('ageRecipient','AGE-SECRET-KEY-private','AGE_RECIPIENT'),('ageRecipient',None,'AGE_RECIPIENT'),
            ('extra','private','FIELDS')]:
            config={**self.config(),field:value};cases.append(({'D4_SNAPSHOT_RELEASE_CONFIG':json.dumps(config)},code))
        for field,code in [('sourceUrl','SOURCE_URL'),('ageRecipient','AGE_RECIPIENT')]:
            config=self.config();del config[field]
            cases.append(({'D4_SNAPSHOT_RELEASE_CONFIG':json.dumps(config)},code))
        for values,code in cases:
            with self.subTest(code=code,fields=list(values)), patch.object(p,'read',side_effect=AssertionError('no fallback')):
                with self.assertRaisesRegex(p.ReleaseBlocked,'^BLOCKED_SNAPSHOT_CONFIG_'+code+'$'):
                    p.load_config(HostedContext(env={'GITHUB_ACTIONS':'true'},variables=values),HERE)
        with self.assertRaisesRegex(p.ReleaseBlocked,'BLOCKED_CI_LOCAL_CONFIG'):
            p.load_config(HostedContext(env={'GITHUB_ACTIONS':'true','SNAPSHOT_RELEASE_CONFIG':'local.json'},
                variables={'D4_SNAPSHOT_RELEASE_CONFIG':json.dumps(self.config())}),HERE)

    def test_local_config_file_remains_supported_and_validated(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'config.json';file.write_text(json.dumps(self.config()))
            ctx=SimpleNamespace(env={'SNAPSHOT_RELEASE_CONFIG':str(file)})
            self.assertEqual(p.load_config(ctx,HERE),self.config())
            file.write_text('{}')
            with self.assertRaisesRegex(p.ReleaseBlocked,'BLOCKED_SNAPSHOT_CONFIG_SOURCE_URL'):p.load_config(ctx,HERE)

    def test_hosted_config_does_not_fall_back_to_process_environment(self):
        ctx=HostedContext(env={'GITHUB_ACTIONS':'true','D4_SNAPSHOT_RELEASE_CONFIG':json.dumps(self.config())},variables={})
        with self.assertRaisesRegex(p.ReleaseBlocked,'BLOCKED_SNAPSHOT_CONFIG_MISSING'):
            p.load_config(ctx,HERE)

    def test_build_public_recipient_only_and_capture_failure_cleanup(self):
        for fail_capture, invalid_validation in ((False,False),(True,False),(False,True)):
            with self.subTest(fail_capture=fail_capture,invalid_validation=invalid_validation),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);(root/'chromium').touch();exports=root/'exports';exports.mkdir()
                calls=[]
                selected={**self.config(), 'ageRecipient':'age1u44phv85j8zjz24chh6q8ct73trkm5j9uf84pq96vnvp2jcl9u7qjhtwsj'}
                ctx=HostedContext(temp=root,env={'PATH':os.environ['PATH'],
                    'BROWSER_INFRA_CHROMIUM_PATH':str(root/'chromium'), 'GITHUB_ACTIONS':'true'},
                    variables={'D4_SNAPSHOT_RELEASE_CONFIG':json.dumps(selected)},job={'operation':'build'},
                    version='1.0.0',source={'head':'a'*40},
                    artifact=lambda file,name:shutil.copytree(file,exports/name))
                def transport(args,**kw):
                    args=list(map(str,args));calls.append(args)
                    self.assertNotIn('D4_SNAPSHOT_RELEASE_CONFIG', kw['env'])
                    if any(arg.endswith('/capture.js') for arg in args):
                        if fail_capture:raise p.ReleaseBlocked('BLOCKED_CAPTURE')
                        config=p.read(args[-2]);packages=[]
                        self.assertEqual(config['sourceUrl'], selected['sourceUrl'])
                        self.assertNotIn('authorizationRef', config)
                        # A later environment change must not split the pair's configuration.
                        ctx.variables['D4_SNAPSHOT_RELEASE_CONFIG']='invalid-after-config-load'
                        for kind in ('calculation','ui'):
                            store=Path(config[kind+'Root']);snapshot=store/kind;snapshot.mkdir(parents=True)
                            (snapshot/'blobs').mkdir();(snapshot/'blobs/data.bin').write_bytes(b'captured data')
                            p.write(snapshot/'manifest.json',{'resources':[{'blob':'blobs/data.bin'}]})
                            (snapshot/'manifest.sha256').write_text('a'*64)
                            (snapshot/'capture.log').write_text('private diagnostic')
                            if kind=='ui':
                                p.write(snapshot/'ui-coverage.json',{})
                                p.write(snapshot/'ui-validation.json',{'status':'FAILED' if invalid_validation else 'AUTOMATED_VALIDATED'})
                            packages.append({'kind':kind,'snapshotId':kind,'snapshotRoot':str(store),
                                'manifestSha256':'a'*64,'compatibility':'PATCH_DRIFT'})
                        p.write(args[-1],{'status':'COMPLETE','runId':'test-run','packages':packages})
                    if args[0]=='age':
                        self.assertEqual(args[1:4],['--encrypt','--recipient',selected['ageRecipient']])
                        with zipfile.ZipFile(args[-1]) as archive:
                            names=archive.namelist();kind=Path(args[-1]).stem
                            expected={f'{kind}/{name}' for name in ('manifest.json','manifest.sha256','blobs/data.bin')}
                            if kind=='ui':expected.update({'ui/ui-coverage.json','ui/ui-validation.json'})
                            self.assertEqual(set(names),expected)
                        Path(args[args.index('--output')+1]).write_bytes(b'simulated ciphertext')
                    return b''
                with patch.object(p.shutil,'which',return_value='/test/tool'),patch.object(p,'verify_recipient') as verify_recipient,patch.object(p,'command',side_effect=transport):
                    if fail_capture:
                        with self.assertRaisesRegex(p.ReleaseBlocked,'BLOCKED_CAPTURE'):p.run(ctx)
                    elif invalid_validation:
                        with self.assertRaisesRegex(p.ReleaseBlocked,'BLOCKED_UI_VALIDATION'):p.run(ctx)
                    else:p.run(ctx)
                verify_recipient.assert_called_once()
                self.assertEqual(verify_recipient.call_args.args[0], selected['ageRecipient'])
                self.assertFalse((root/'snapshot-private').exists())
                if fail_capture or invalid_validation:self.assertEqual(list(exports.iterdir()),[])
                else:
                    candidate=exports/'snapshots'
                    self.assertEqual({f.name for f in candidate.iterdir()}, {'snapshot-pair.json','SHA256SUMS',
                        'calculation-snapshot-1.0.0.zip.age','ui-snapshot-1.0.0.zip.age'})
                    metadata=p.read(candidate/'snapshot-pair.json')
                    self.assertEqual(metadata['captureRunId'],'test-run')
                    ui = metadata['assets']['ui-snapshot-1.0.0.zip.age']
                    self.assertEqual(ui['plannerProtocolVersion'], 'd4planner-local-planner/v1')
                    self.assertNotIn('authorizationRef', ui['uiTrust'])
                    self.assertEqual(ui['uiTrust']['coverageSha256'], p.sha(b'{}\n'))
                    self.assertEqual(ui['uiTrust']['validationSha256'], p.sha(
                        (json.dumps({'status':'AUTOMATED_VALIDATED'}, sort_keys=True, indent=2)+'\n').encode()))
                    self.assertNotIn('uiTrust', metadata['assets']['calculation-snapshot-1.0.0.zip.age'])
                    for name,record in metadata['assets'].items():
                        self.assertEqual(record['sha256'],p.file_sha(candidate/name))
                        self.assertEqual(record['bytes'],(candidate/name).stat().st_size)
                    self.assertEqual((candidate/'SHA256SUMS').read_text(),''.join(
                        f'{p.file_sha(f)}  {f.name}\n' for f in sorted(candidate.iterdir()) if f.name!='SHA256SUMS'))
                    self.assertEqual(sum(call[0]=='age' for call in calls),2)
                    publish=SimpleNamespace(root=ROOT,version=ctx.version,source=ctx.source,
                        env={'GITHUB_REPOSITORY':'example/repo','GITHUB_ACTIONS':'true',
                             'D4_SNAPSHOT_RELEASE_CONFIG':'invalid-after-build'},job={'operation':'publish'},
                        build_artifact=Mock(return_value=candidate),python=Mock(),run=Mock())
                    p.run(publish)
                    publish.build_artifact.assert_called_once_with('snapshots')
                    args=publish.run.call_args.args[0]
                    self.assertEqual(args[3], 'd4planner-snapshots/v1.0.0')
                    self.assertEqual(args[args.index('--title')+1], 'd4planner-snapshot-1.0.0')
                    self.assertTrue(all(Path(arg).is_file() for arg in args[4:8]))
                self.assertFalse(any('--decrypt' in call or call[0]=='age-keygen' for call in calls))

    def test_publish_uses_verified_build_and_existing_release_helpers(self):
        ctx=SimpleNamespace(root=ROOT,version='1.0.0',source={'head':'a'*40},
            env={'GITHUB_REPOSITORY':'example/repo'},
            build_artifact=Mock(return_value=Path('/candidate')),python=Mock(),run=Mock())
        p.publish(ctx)
        ctx.build_artifact.assert_called_once_with('snapshots')
        helper=ctx.python.call_args.args
        self.assertIn('from release_ci import require_release_absent, ensure_source_tag',helper[1])
        self.assertEqual(helper[-3:],('example/repo','d4planner-snapshots/v1.0.0','a'*40))
        command=ctx.run.call_args.args[0]
        self.assertEqual(command[:4],['gh','release','create','d4planner-snapshots/v1.0.0'])
        self.assertEqual(set(command[4:8]),{'/candidate/snapshot-pair.json','/candidate/SHA256SUMS',
            '/candidate/calculation-snapshot-1.0.0.zip.age','/candidate/ui-snapshot-1.0.0.zip.age'})
        self.assertIn('--verify-tag',command)
        self.assertEqual(command[command.index('--title')+1], 'd4planner-snapshot-1.0.0')
        ctx.run.reset_mock();ctx.python.side_effect=RuntimeError('existing release')
        with self.assertRaises(RuntimeError):p.publish(ctx)
        ctx.run.assert_not_called()

    def test_invalid_config_stops_before_tools_or_capture(self):
        for raw in ('', '{invalid', json.dumps({**self.config(), 'sourceUrl':'https://evil.invalid/'})):
            ctx=HostedContext(env={'GITHUB_ACTIONS':'true'},variables={'D4_SNAPSHOT_RELEASE_CONFIG':raw},job={'operation':'build'})
            with patch.object(p,'build') as build:
                with self.assertRaises(p.ReleaseBlocked):p.run(ctx)
                build.assert_not_called()

    def test_age_validates_checksum_before_capture_without_forwarding_raw_output(self):
        for status in (0,1):
            with self.subTest(status=status),patch.object(p.subprocess,'run',return_value=SimpleNamespace(
                returncode=status,stdout=b'encrypted empty input',stderr=b'private diagnostic')) as command:
                if status:
                    with self.assertRaisesRegex(p.ReleaseBlocked,'^BLOCKED_SNAPSHOT_CONFIG_AGE_RECIPIENT$'):
                        p.verify_recipient(p.RECIPIENT,{'PATH':'tools'})
                else:p.verify_recipient(p.RECIPIENT,{'PATH':'tools'})
                command.assert_called_once_with(['age','--encrypt','--recipient',p.RECIPIENT],
                    input=b'',capture_output=True,timeout=15,env={'PATH':'tools'})
        with tempfile.TemporaryDirectory() as temp, patch.object(p.shutil,'which',return_value='/test/age'), \
             patch.object(p,'verify_recipient',side_effect=p.ReleaseBlocked('BLOCKED_SNAPSHOT_CONFIG_AGE_RECIPIENT')), \
             patch.object(p,'command') as command:
            ctx=SimpleNamespace(env={},version='1.0.0',temp=Path(temp))
            with self.assertRaisesRegex(p.ReleaseBlocked,'AGE_RECIPIENT'):p.build(ctx,HERE,self.config())
            command.assert_not_called()
            self.assertFalse((Path(temp)/'snapshot-private').exists())

    def test_real_ci_context_preserves_json_variable_as_data(self):
        raw=json.dumps(self.config(),indent=2)
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,{
            'GITHUB_ACTIONS':'true','CI_VARIABLES_JSON':json.dumps({'D4_SNAPSHOT_RELEASE_CONFIG':raw})},clear=True):
            ctx=ci.Context(ROOT,{'capability':'read','timeout':30,'key':'d4planner-snapshots--pair'},
                Path(temp),{'head':'a'*40},version='1.0.0')
            try:self.assertEqual(p.load_config(ctx,HERE),self.config())
            finally:shutil.rmtree(ctx.temp)

    def test_commands_do_not_leak_private_output(self):
        completed=SimpleNamespace(returncode=1,stdout=b'private data',stderr=b'password secret raw URL')
        with patch.object(p.subprocess,'run',return_value=completed):
            with self.assertRaisesRegex(p.ReleaseBlocked,'^BLOCKED_COMMAND_NODE$'):p.command(['node','private.js'])

if __name__=='__main__':unittest.main()
