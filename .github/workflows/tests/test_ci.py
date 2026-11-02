"""Planner/executor acceptance using disposable Git repositories, never remote APIs."""
import contextlib
import io
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('engine', Path(__file__).parents[1] / 'ci.py')
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)

class Contracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'repo'
        self.root.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'contract-test')
        self.git('config', 'user.email', 'contract-test@example.invalid')
        self.write('.gitignore', '__pycache__/\n')
        self.commit()
        self.base = self.git('rev-parse', 'HEAD').strip()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True)

    def write(self, path, text):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')

    def contract(self, path='widget/ci.test.py', name='widget', **extra):
        data = dict(version=1, id=name, jobs=[dict(id='unit', profile='linux', timeout=20)])
        data.update(extra)
        self.write(path, 'CI_SPEC = ' + repr(data) + '\ndef run(ctx):\n    ctx.python("-c", "print(\'2 passed in 0.01s\')")\n')

    def plan(self, **kwargs):
        return ci.plan(self.root, base=self.base, dirty=True, **kwargs)

    def test_zero_config_discovery_multiple_jobs_and_execution(self):
        self.contract(jobs=[dict(id=x,profile='linux',timeout=20) for x in ('unit','integration')])
        p = self.plan()
        reports = [ci.execute(self.root,p,j,Path(self.tmp.name)/j['key']) for j in p['jobs']]
        self.assertEqual([r['status'] for r in reports], ['PASS','PASS'])
        self.assertEqual(ci.aggregate(p,reports)['status'],'PASS')
        self.assertEqual(reports[0]['testCounts'], {'passed':2})

    def test_committed_plan_preserves_contract_bytes(self):
        self.contract(); self.commit()
        p = ci.plan(self.root,component='widget')
        r = ci.execute(self.root,p,p['jobs'][0],Path(self.tmp.name)/'result')
        self.assertEqual(r['status'],'PASS',r)

    def test_planner_does_not_import(self):
        self.contract()
        with (self.root/'widget/ci.test.py').open('a') as f: f.write('\nraise RuntimeError("must not run at plan time")\n')
        self.assertEqual(len(self.plan()['jobs']),1)

    def test_nested_watch_and_reverse_dependencies(self):
        self.contract()
        self.contract('widget/child/ci.test.py','child')
        self.contract('consumer/ci.test.py','consumer',depends_on=['child'])
        self.commit(); self.base=self.git('rev-parse','HEAD').strip()
        self.write('widget/child/a.py','changed')
        self.assertEqual({j['component'] for j in self.plan()['jobs']},{'child','consumer'})

    def test_unknown_file_fails_closed(self):
        self.contract();self.write('unknown/source.py','')
        with self.assertRaisesRegex(ci.ContractError,'UNCOVERED_CHANGE'):self.plan()

    def test_deleted_contract_fails_closed(self):
        self.contract();self.commit();self.base=self.git('rev-parse','HEAD').strip()
        (self.root/'widget/ci.test.py').unlink()
        with self.assertRaisesRegex(ci.ContractError,'REMOVED_CONTRACT'):self.plan()

    def test_missing_history_fails_closed(self):
        with self.assertRaises(ci.ContractError):ci.changed_paths(self.root,'deadbeef','HEAD')

    def test_dirty_source_change_blocks_execution(self):
        self.contract();p=self.plan();self.write('widget/other.py','changed')
        r=ci.execute(self.root,p,p['jobs'][0],Path(self.tmp.name)/'result')
        self.assertEqual(r['status'],'BLOCKED')
        self.assertIn('SOURCE_CHANGED',r['error'])

    def test_contract_cannot_be_modified_in_saved_plan_to_gain_secrets(self):
        self.contract();p=self.plan();p['jobs'][0]['capability']='fixture'
        with patch.dict(os.environ,{'CI_TRUSTED_EXECUTION':'1'}):
            r=ci.execute(self.root,p,p['jobs'][0],Path(self.tmp.name)/'result')
        self.assertEqual(r['status'],'BLOCKED')
        self.assertIn('CAPABILITY_MISMATCH',r['error'])

    def test_missing_duplicate_or_wrong_source_report_fails(self):
        self.contract();p=self.plan()
        r={'key':p['jobs'][0]['key'],'planId':p['planId'],'source':p['source'],'status':'PASS'}
        for reports in ([],[r,r],[dict(r,source={})],[dict(r,status='BLOCKED')],[dict(r,status='NOT_RUN')]):
            with self.subTest(reports=reports):self.assertEqual(ci.aggregate(p,reports)['status'],'FAIL')

    def test_new_product_build_publish_isolation(self):
        self.contract('product/ci.release.py','product',jobs=[
            dict(id='build',profile='linux',timeout=20,operation='build'),
            dict(id='publish',profile='linux',timeout=20,operation='publish',capability='publish')])
        p=self.plan(product='product',operation='build')
        self.assertEqual([j['operation'] for j in p['jobs']],['build'])
        p=self.plan(product='product',operation='publish')
        with patch.dict(os.environ,{},clear=True):
            r=ci.execute(self.root,p,p['jobs'][1],Path(self.tmp.name)/'result')
        self.assertEqual(r['status'],'BLOCKED')

    def test_invalid_metadata_and_graph(self):
        invalid=[dict(version=2),dict(id='BAD'),dict(depends_on=['missing']),
                 dict(jobs=[dict(id='unit',profile='self-hosted',timeout=2)]),
                 dict(jobs=[dict(id='unit',profile='linux',timeout=2,secrets={'TOKEN':'KEY'})])]
        for extra in invalid:
            with self.subTest(extra=extra):
                self.contract(**extra)
                with self.assertRaises(ci.ContractError):self.plan()
        self.contract(depends_on=['widget'])
        with self.assertRaisesRegex(ci.ContractError,'CYCLIC'):self.plan()

    def test_isolated_checkout_does_not_mutate_callers_branch_or_files(self):
        self.contract();self.commit()
        path=self.root/'widget/ci.test.py'
        path.write_text(path.read_text()+"    (ctx.root/'widget/new.txt').write_text('owned')\n")
        branch=self.git('symbolic-ref','HEAD');p=self.plan()
        r=ci.execute(self.root,p,p['jobs'][0],Path(self.tmp.name)/'result')
        self.assertEqual(r['status'],'PASS',r)
        self.assertFalse((self.root/'widget/new.txt').exists())
        self.assertEqual(self.git('symbolic-ref','HEAD'),branch)

    def test_static_secret_alias_cannot_select_another_repository_secret(self):
        self.contract(jobs=[dict(id='fixture',profile='linux',timeout=20,manual=True,
                                capability='fixture',secrets={'AGE_IDENTITY_SECRET':'OTHER_SECRET'})])
        with self.assertRaisesRegex(ci.ContractError,'UNAPPROVED_SECRET'):self.plan()

    def test_rename_selects_old_and_new_owners(self):
        self.contract();self.contract('other/ci.test.py','other')
        self.write('widget/a.py','a');self.commit();self.base=self.git('rev-parse','HEAD').strip()
        self.git('mv','widget/a.py','other/a.py')
        self.assertEqual({j['component'] for j in self.plan()['jobs']},{'widget','other'})

    def test_duplicate_ids_are_rejected(self):
        self.contract();self.contract('other/ci.test.py')
        with self.assertRaisesRegex(ci.ContractError,'DUPLICATE_COMPONENT'):self.plan()

    def test_push_does_not_use_pr_merge_base(self):
        self.contract();self.write('widget/a.py','base');self.commit()
        parent=self.git('rev-parse','HEAD').strip()
        self.git('checkout','-qb','side')
        self.write('widget/side.py','side');self.commit();side=self.git('rev-parse','HEAD').strip()
        self.git('checkout','--detach',parent)
        self.write('widget/head.py','head');self.commit()
        pr,_=ci.changed_paths(self.root,side,'HEAD')
        push,_=ci.changed_paths(self.root,side,'HEAD',push=True)
        self.assertEqual(pr,['widget/head.py'])
        self.assertEqual(push,['widget/head.py','widget/side.py'])

    def test_timeout_fails_and_cleans_owned_checkout(self):
        self.contract(jobs=[dict(id='unit',profile='linux',timeout=1)])
        path=self.root/'widget/ci.test.py'
        path.write_text(path.read_text().replace("print(\'2 passed in 0.01s\')",'import time; time.sleep(30)'))
        p=self.plan();r=ci.execute(self.root,p,p['jobs'][0],Path(self.tmp.name)/'result')
        self.assertEqual(r['status'],'FAIL',r)
        self.assertIn('OPERATION_TIMEOUT',r['error'])
        self.assertLess(r['seconds'],5)
        self.assertFalse(Path(r['commands'][0]['cwd']).exists())

    def test_secret_binding_order_survives_sorted_plan_serialization(self):
        self.contract('product/ci.release.py','product',jobs=[dict(id='build',profile='linux',timeout=20,
            operation='build',capability='public-inputs',secrets={
                'D4_PUBLIC_RUNTIME_INPUT_URL':'D4PLANNER_PUBLIC_RUNTIME_INPUTS_URL',
                'D4_PUBLIC_RUNTIME_INPUT_SHA256':'D4PLANNER_PUBLIC_RUNTIME_INPUTS_SHA256'})])
        p=self.plan(product='product',operation='build')
        restored=json.loads(json.dumps(p,sort_keys=True))
        self.assertEqual(ci.matrices(p),ci.matrices(restored))
        row=ci.matrices(p)['build']['include'][0]
        values={'D4PLANNER_PUBLIC_RUNTIME_INPUTS_URL':'https://example.invalid/public',
                'D4PLANNER_PUBLIC_RUNTIME_INPUTS_SHA256':'a'*64}
        output=Path(self.tmp.name)/'out';output.mkdir()
        with patch.dict(os.environ,{'CI_BOUND_SECRET_1':values[row['secret_1']],
                                  'CI_BOUND_SECRET_2':values[row['secret_2']]},clear=True):
            ctx=ci.Context(self.root,restored['jobs'][0],output,p['source'])
            try:
                self.assertEqual(ctx.env['D4_PUBLIC_RUNTIME_INPUT_URL'],values['D4PLANNER_PUBLIC_RUNTIME_INPUTS_URL'])
                self.assertEqual(ctx.env['D4_PUBLIC_RUNTIME_INPUT_SHA256'],'a'*64)
            finally:ctx.close()

    def test_initial_master_push_selects_all_regular_tests_without_publish(self):
        self.contract();self.contract('second/ci.test.py','second');self.commit()
        event=Path(self.tmp.name)/'event.json'
        event.write_text(json.dumps({'created':True,'before':'0'*40,'after':self.git('rev-parse','HEAD').strip()}))
        output=Path(self.tmp.name)/'plan'
        with patch.dict(os.environ,{'GITHUB_EVENT_PATH':str(event),'GITHUB_EVENT_NAME':'push',
                                    'GITHUB_REF':'refs/heads/master'}):
            code=ci.main(['actions-plan','--root',str(self.root),'--output',str(output)])
        self.assertEqual(code,0)
        document=json.loads((output/'plan.json').read_text())
        self.assertEqual({j['component'] for j in document['jobs']},{'widget','second'})
        self.assertTrue(all(j['operation']=='test' and j['capability']=='read' for j in document['jobs']))
        self.assertTrue(all('new branch push' in j['reasons'][0] for j in document['jobs']))

    def test_zero_before_without_created_flag_still_fails_closed(self):
        self.contract();self.commit()
        event=Path(self.tmp.name)/'event.json';event.write_text(json.dumps({'before':'0'*40,'created':False}))
        with patch.dict(os.environ,{'GITHUB_EVENT_PATH':str(event),'GITHUB_EVENT_NAME':'push','GITHUB_REF':'refs/heads/existing'}):
            self.assertEqual(ci.main(['actions-plan','--root',str(self.root),'--output',str(Path(self.tmp.name)/'plan')]),2)

    def test_unicode_child_output_on_cp1252_console_keeps_exit_and_utf8_log(self):
        self.contract();job=self.plan()['jobs'][0];out=Path(self.tmp.name)/'out';out.mkdir()
        ctx=ci.Context(self.root,job,out,ci.snapshot(self.root))
        ctx.redactions=['PRIVATE_CANARY']
        buffer=io.BytesIO();console=io.TextIOWrapper(buffer,encoding='cp1252')
        try:
            with contextlib.redirect_stdout(console):
                ctx.python('-c', "print(chr(0x2713)+chr(0x25a0)+' PRIVATE_CANARY')")
            console.flush()
            self.assertEqual(ctx.commands[-1]['exitCode'],0)
            log=(out/'commands.log').read_text(encoding='utf-8')
            self.assertIn(chr(0x2713)+chr(0x25a0)+' ***',log)
            self.assertNotIn('PRIVATE_CANARY',log)
            self.assertNotIn(b'PRIVATE_CANARY',buffer.getvalue())
            self.assertIn(b'\\u2713',buffer.getvalue())
        finally:ctx.close()

    def test_cleanup_removes_owned_readonly_git_pack_without_touching_source(self):
        self.contract();job=self.plan()['jobs'][0];out=Path(self.tmp.name)/'out';out.mkdir()
        ctx=ci.Context(self.root,job,out,ci.snapshot(self.root))
        pack=ctx.temp/'pack.idx';pack.write_bytes(b'owned');pack.chmod(0o444)
        original=self.root/'original.idx';original.write_bytes(b'caller');original.chmod(0o444)
        real_rmtree=ci.shutil.rmtree
        def exercise(path, *, onexc):
            onexc(os.unlink,str(pack),PermissionError('read-only'))
            with self.assertRaises(PermissionError):
                onexc(os.unlink,str(original),PermissionError('outside ownership'))
            real_rmtree(path)
        with patch.object(ci.shutil,'rmtree',side_effect=exercise):ctx.close()
        self.assertFalse(ctx.temp.exists())
        self.assertTrue(original.exists())
        original.chmod(0o644)

    def test_publish_context_rejects_pr_feature_push_build_and_wrong_identity(self):
        self.contract('product/ci.release.py','product',jobs=[dict(id='publish',profile='linux',timeout=20,operation='publish',capability='publish')])
        self.commit();p=ci.plan(self.root,product='product',operation='publish')
        event=Path(self.tmp.name)/'event.json'
        base={'GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'workflow_dispatch',
              'GITHUB_REF':'refs/heads/master','GITHUB_SHA':p['source']['head'],
              'GITHUB_EVENT_PATH':str(event),'CI_TRUSTED_EXECUTION':'1',
              'CI_PUBLISH_TOKEN':'PRIVATE_PUBLISH_CANARY'}
        cases=[({'GITHUB_EVENT_NAME':'pull_request'},'publish'),
               ({'GITHUB_REF':'refs/heads/feature'},'publish'),
               ({'GITHUB_REF':'refs/tags/v1.2.8'},'publish'),
               ({'GITHUB_EVENT_NAME':'push'},'publish'),({},'build'),
               ({'GITHUB_SHA':'f'*40},'publish'),({'GITHUB_ACTIONS':'false'},'publish')]
        for index,(change,operation) in enumerate(cases):
            event.write_text(json.dumps({'inputs':{'operation':operation,'product':'product','version':'1.2.8'}}))
            with patch.dict(os.environ,{**base,**change},clear=True):
                result=ci.execute(self.root,p,p['jobs'][0],Path(self.tmp.name)/str(index),version='1.2.8')
            self.assertEqual(result['status'],'BLOCKED',result)
            self.assertEqual(result['commands'],[])
            self.assertNotIn('PRIVATE_PUBLISH_CANARY',json.dumps(result))
        event.write_text(json.dumps({'inputs':{'operation':'publish','product':'product','version':'1.2.8'}}))
        base.pop('CI_PUBLISH_TOKEN')
        with patch.dict(os.environ,base,clear=True):
            result=ci.execute(self.root,p,p['jobs'][0],Path(self.tmp.name)/'missing-token',version='1.2.8')
        self.assertEqual(result['error'],'PUBLISH_CREDENTIAL_NOT_PROVIDED')

    def test_manual_master_context_binds_ephemeral_token_without_publishing(self):
        self.contract('product/ci.release.py','product',jobs=[dict(id='publish',profile='linux',timeout=20,operation='publish',capability='publish')])
        self.commit();p=ci.plan(self.root,product='product',operation='publish')
        event=Path(self.tmp.name)/'event.json'
        event.write_text(json.dumps({'inputs':{'operation':'publish','product':'product','version':'1.2.8'}}))
        env={'GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'workflow_dispatch',
             'GITHUB_REF':'refs/heads/master','GITHUB_SHA':p['source']['head'],
             'GITHUB_EVENT_PATH':str(event),'CI_PUBLISH_TOKEN':'SYNTHETIC_EPHEMERAL_TOKEN'}
        out=Path(self.tmp.name)/'context';out.mkdir()
        with patch.dict(os.environ,env,clear=True):
            ctx=ci.Context(self.root,p['jobs'][0],out,p['source'],version='1.2.8')
        try:
            self.assertEqual(ctx.env['GH_TOKEN'],'SYNTHETIC_EPHEMERAL_TOKEN')
            self.assertEqual(ctx.redact('token=SYNTHETIC_EPHEMERAL_TOKEN'),'token=***')
            self.assertEqual(ctx.commands,[])  # No transport or publication is executed.
            self.assertNotIn('SYNTHETIC_EPHEMERAL_TOKEN',json.dumps(p))
        finally:ctx.close()

    def test_read_execution_strips_production_credentials_from_child_and_evidence(self):
        self.contract()
        path=self.root/'widget/ci.test.py'
        path.write_text(path.read_text().replace("print(\'2 passed in 0.01s\')", "import os; assert not any(\'CANARY\' in v for v in os.environ.values()); print(2)"))
        p=self.plan()
        with patch.dict(os.environ,{'CI_PUBLISH_TOKEN':'PRODUCTION_CANARY','CI_MAINTENANCE_TOKEN':'MAINTENANCE_CANARY','GH_TOKEN':'GH_CANARY',
                                  'CI_BOUND_SECRET_1':'BOUND_CANARY','GITHUB_TOKEN':'GITHUB_CANARY'}):
            result=ci.execute(self.root,p,p['jobs'][0],Path(self.tmp.name)/'secret-negative')
        self.assertEqual(result['status'],'PASS',result)
        for payload in (json.dumps(p),json.dumps(ci.matrices(p)),json.dumps(result),
                        (Path(self.tmp.name)/'secret-negative/commands.log').read_text()):
            for value in ('PRODUCTION_CANARY','MAINTENANCE_CANARY','GH_CANARY','BOUND_CANARY','GITHUB_CANARY'):
                self.assertNotIn(value,payload)

    def test_feature_and_tag_push_are_rejected_by_actions_planner(self):
        self.contract();self.commit()
        event=Path(self.tmp.name)/'event.json';event.write_text(json.dumps({'before':self.base,'after':self.git('rev-parse','HEAD').strip()}))
        for index,ref in enumerate(('refs/heads/feature','refs/tags/v1.2.8')):
            with patch.dict(os.environ,{'GITHUB_EVENT_PATH':str(event),'GITHUB_EVENT_NAME':'push','GITHUB_REF':ref}):
                self.assertEqual(ci.main(['actions-plan','--root',str(self.root),'--output',str(Path(self.tmp.name)/str(index))]),2)

    def test_actions_master_push_and_pr_cannot_request_publish_via_cli(self):
        self.contract();self.commit()
        head=self.git('rev-parse','HEAD').strip()
        for index,name in enumerate(('push','pull_request')):
            event=Path(self.tmp.name)/'event.json'
            event.write_text(json.dumps({'before':self.base,'after':head,
                'pull_request':{'head':{'sha':head},'base':{'sha':self.base}}}))
            env={'GITHUB_EVENT_PATH':str(event),'GITHUB_EVENT_NAME':name,'GITHUB_REF':'refs/heads/master'}
            with patch.dict(os.environ,env):
                output=Path(self.tmp.name)/('normal'+str(index))
                self.assertEqual(ci.main(['actions-plan','--root',str(self.root),'--output',str(output)]),0)
                document=json.loads((output/'plan.json').read_text())
                self.assertEqual(document['operation'],'test')
                self.assertTrue(all(j['capability']=='read' for j in document['jobs']))
                self.assertEqual(ci.main(['actions-plan','--root',str(self.root),'--operation','publish',
                                         '--product','widget','--output',str(Path(self.tmp.name)/('bad'+str(index)))]),2)

    def test_verified_build_report_and_bytes_required_before_publish_adapter(self):
        self.contract();p=self.plan();out=Path(self.tmp.name)/'out';out.mkdir()
        ctx=ci.Context(self.root,p['jobs'][0],out,p['source'])
        self.addCleanup(ctx.close);ctx.plan_id=p['planId']
        inputs=Path(self.tmp.name)/'inputs';artifact=inputs/'build/artifacts/setup/file.exe'
        artifact.parent.mkdir(parents=True);artifact.write_bytes(b'synthetic-test-only')
        ctx.inputs=inputs
        report={'component':'widget','operation':'build','status':'PASS','source':p['source'],
                'planId':p['planId'],'artifactManifest':{'setup/file.exe':ci.digest(artifact.read_bytes())}}
        ci.write_json(inputs/'build/result.json',report)
        self.assertEqual(ctx.build_artifact('setup'),artifact.parent)
        artifact.write_bytes(b'tampered')
        with self.assertRaisesRegex(ci.ContractError,'BUILD_ARTIFACT_INTEGRITY'):ctx.build_artifact('setup')
        report['source']={};ci.write_json(inputs/'build/result.json',report)
        with self.assertRaisesRegex(ci.ContractError,'BUILD_REPORT_IDENTITY'):ctx.build_artifact('setup')

    def test_clean_no_change(self):
        self.contract();self.commit();self.base=self.git('rev-parse','HEAD').strip()
        p=self.plan()
        self.assertEqual(ci.aggregate(p,[])['status'],'NO_CHANGE')

if __name__ == '__main__':unittest.main()
