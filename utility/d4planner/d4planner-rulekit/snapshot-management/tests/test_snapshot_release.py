"""Snapshot release adapter tests; transports are mocked, no live publication."""
import importlib.util
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

class SnapshotRelease(unittest.TestCase):
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

    def test_build_public_recipient_only_and_capture_failure_cleanup(self):
        for fail_capture in (False,True):
            with self.subTest(fail_capture=fail_capture),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);(root/'chromium').touch();exports=root/'exports';exports.mkdir()
                calls=[]
                ctx=SimpleNamespace(temp=root,env={'PATH':os.environ['PATH'],
                    'BROWSER_INFRA_CHROMIUM_PATH':str(root/'chromium')},
                    version='1.0.0',source={'head':'a'*40},
                    artifact=lambda file,name:shutil.copytree(file,exports/name))
                def transport(args,**kw):
                    args=list(map(str,args));calls.append(args)
                    if any(arg.endswith('/capture.js') for arg in args):
                        if fail_capture:raise p.ReleaseBlocked('BLOCKED_CAPTURE')
                        config=p.read(args[-2]);packages=[]
                        for kind in ('calculation','ui'):
                            store=Path(config[kind+'Root']);snapshot=store/kind;snapshot.mkdir(parents=True)
                            (snapshot/'blobs').mkdir();(snapshot/'blobs/data.bin').write_bytes(b'captured data')
                            p.write(snapshot/'manifest.json',{'resources':[{'blob':'blobs/data.bin'}]})
                            (snapshot/'manifest.sha256').write_text('a'*64)
                            (snapshot/'capture.log').write_text('private diagnostic')
                            if kind=='ui':
                                p.write(snapshot/'ui-coverage.json',{})
                                p.write(snapshot/'ui-validation.json',{'status':'AUTOMATED_VALIDATED'})
                            packages.append({'kind':kind,'snapshotId':kind,'snapshotRoot':str(store),
                                'manifestSha256':'a'*64,'compatibility':'PATCH_DRIFT'})
                        p.write(args[-1],{'status':'COMPLETE','runId':'test-run','packages':packages})
                    if args[0]=='age':
                        self.assertEqual(args[1:4],['--encrypt','--recipient',p.RECIPIENT])
                        with zipfile.ZipFile(args[-1]) as archive:
                            names=archive.namelist();kind=Path(args[-1]).stem
                            expected={f'{kind}/{name}' for name in ('manifest.json','manifest.sha256','blobs/data.bin')}
                            if kind=='ui':expected.update({'ui/ui-coverage.json','ui/ui-validation.json'})
                            self.assertEqual(set(names),expected)
                        Path(args[args.index('--output')+1]).write_bytes(b'simulated ciphertext')
                    return b''
                with patch.object(p.shutil,'which',return_value='/test/tool'),patch.object(p,'command',side_effect=transport):
                    config={'sourceUrl':'https://maxroll.gg/d4/planner/test','authorizationRef':'test','ageRecipient':p.RECIPIENT}
                    if fail_capture:
                        with self.assertRaisesRegex(p.ReleaseBlocked,'BLOCKED_CAPTURE'):p.build(ctx,HERE,config)
                    else:p.build(ctx,HERE,config)
                self.assertFalse((root/'snapshot-private').exists())
                if fail_capture:self.assertEqual(list(exports.iterdir()),[])
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
        ctx.run.reset_mock();ctx.python.side_effect=RuntimeError('existing release')
        with self.assertRaises(RuntimeError):p.publish(ctx)
        ctx.run.assert_not_called()

    def test_commands_do_not_leak_private_output(self):
        completed=SimpleNamespace(returncode=1,stdout=b'private data',stderr=b'password secret raw URL')
        with patch.object(p.subprocess,'run',return_value=completed):
            with self.assertRaisesRegex(p.ReleaseBlocked,'^BLOCKED_COMMAND_NODE$'):p.command(['node','private.js'])

if __name__=='__main__':unittest.main()
