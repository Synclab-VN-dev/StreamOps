"""Product adapter tests use fake transports, not builds or publication."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[3]

class ReleaseAdapter(unittest.TestCase):
    def test_build_only_orders_verification_before_export_without_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp)
            contract=temp/'adapter.py'
            shutil.copyfile(ROOT/'utility/d4planner/ci.release.py',contract)
            spec=importlib.util.spec_from_file_location('adapter',contract)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            calls=[]
            output=temp/'output';output.write_text('setup_sha256='+'a'*64+'\n')
            ctx=SimpleNamespace(root=ROOT,version='1.2.8',temp=temp,intent='build',
                source={'head':'a'*40},job={'operation':'build'},env={'GITHUB_OUTPUT':str(output)},
                isolated_python=lambda:None,tool=lambda *a:None,shell=lambda *a,**k:None,
                python=lambda *a,**k:calls.append(tuple(map(str,a))),
                artifact=lambda *a:calls.append(('artifact',)))
            # A tag ref must not override the explicit manual version.
            from unittest.mock import patch
            import os
            with patch.dict(os.environ,{'GITHUB_REF_TYPE':'tag','GITHUB_REF_NAME':'d4planner-uat/v9.9.9'}):
                module.run(ctx)
            self.assertTrue(all(c[c.index('--version')+1]=='1.2.8' for c in calls if '--version' in c))
            operations=[c[1] for c in calls if c[0].endswith('release_ci.py')]
            self.assertEqual(operations,['validate','build','prepare-upload','validate-upload'])
            self.assertEqual(ctx.env['D4_BUILD_ONLY'],'true')
            self.assertEqual(calls[-1],('artifact',))
            self.assertNotIn('publish',operations)

    def test_failed_verification_exports_no_setup(self):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);contract=temp/'adapter.py';shutil.copyfile(ROOT/'utility/d4planner/ci.release.py',contract)
            spec=importlib.util.spec_from_file_location('adapter_fail',contract);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            output=temp/'out';output.write_text('setup_sha256='+'a'*64+'\n')
            exports=[]
            def run(*args):
                if args[1]=='validate-upload':raise RuntimeError('integrity rejected')
            ctx=SimpleNamespace(root=ROOT,version='1.2.8',temp=temp,intent='build',
                source={'head':'a'*40},job={'operation':'build'},env={'GITHUB_OUTPUT':str(output)},
                isolated_python=lambda:None,tool=lambda *a:None,shell=lambda *a,**k:None,
                python=run,artifact=lambda *a:exports.append(a))
            with self.assertRaisesRegex(RuntimeError,'integrity rejected'):module.run(ctx)
            self.assertFalse(exports)

if __name__=='__main__':unittest.main()
