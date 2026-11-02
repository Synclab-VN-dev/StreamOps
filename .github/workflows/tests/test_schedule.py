"""Generic schedule taxonomy/capability tests; no domain transport or mutation."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import test_ci

ci=test_ci.ci

class ScheduleContracts(unittest.TestCase):
    setUp=test_ci.Contracts.setUp
    git=test_ci.Contracts.git
    write=test_ci.Contracts.write
    commit=test_ci.Contracts.commit

    def schedule(self, name='maintenance', path='owner/ci.schedule.py', **extra):
        spec=dict(version=1,id=name,jobs=[dict(id='audit',profile='linux',timeout=20,
                  operation='schedule',capability='maintenance')]);spec.update(extra)
        self.write(path,'CI_SPEC = '+repr(spec)+'\ndef run(ctx):\n    ctx.log("dry="+str(ctx.dry_run))\n')

    def document(self):
        return ci.plan(self.root,schedule='maintenance',dirty=True)

    def test_discovery_static_kind_selection_and_no_registry(self):
        self.schedule();self.schedule('other','another/ci.schedule.py')
        with (self.root/'owner/ci.schedule.py').open('a') as out:out.write('\nraise RuntimeError("planner must not import")\n')
        specs=ci.discover(self.root)
        self.assertEqual(specs['maintenance']['kind'],'schedule')
        p=self.document();self.assertEqual([j['component'] for j in p['jobs']],['maintenance'])
        self.assertEqual(p['operation'],'schedule')
        all_jobs=ci.plan(self.root,operation='schedule',all_jobs=True,dirty=True)
        self.assertEqual(len(ci.matrices(all_jobs)['maintenance']['include']),2)
        self.assertEqual(ci.matrices(all_jobs)['read']['include'],[])
        with self.assertRaisesRegex(ci.ContractError,'CONTRACT_KIND_MISMATCH'):
            ci.plan(self.root,component='maintenance',dirty=True)

    def test_invalid_metadata_duplicate_and_privilege_escalation(self):
        job=dict(id='audit',profile='linux',timeout=20,operation='schedule',capability='maintenance')
        for change in ({'operation':'publish'},{'capability':'read'},{'capability':'publish'},
                       {'profile':'self-hosted'},{'permissions':{'contents':'write'}},
                       {'environment':'production'}, {'manual':True},
                       {'secrets':{'TOKEN':'ARBITRARY_SECRET'}}):
            self.schedule(jobs=[{**job,**change}])
            with self.subTest(change=change),self.assertRaises(ci.ContractError):self.document()
        self.schedule(unknown=True)
        with self.assertRaises(ci.ContractError):self.document()
        self.schedule();self.schedule('maintenance','another/ci.schedule.py')
        with self.assertRaisesRegex(ci.ContractError,'DUPLICATE_COMPONENT'):self.document()

    def test_local_dry_run_cli_and_local_execute_blocked(self):
        self.schedule()
        with patch.dict(os.environ,{'CI_MAINTENANCE_TOKEN':'MOCK_SECRET'},clear=True):
            out=Path(self.tmp.name)/'dry'
            self.assertEqual(ci.main(['run','--root',str(self.root),'--schedule','maintenance',
                                     '--changed','--base',self.base,'--output',str(out)]),0)
            report=json.loads((out/'maintenance--audit/result.json').read_text())
            self.assertEqual(report['status'],'PASS')
            self.assertNotIn('MOCK_SECRET',json.dumps(report))
            self.assertIn('dry=True',(out/'maintenance--audit/commands.log').read_text())
            p=self.document()
            result=ci.execute(self.root,p,p['jobs'][0],Path(self.tmp.name)/'execute',dry_run=False)
            self.assertEqual(result['status'],'BLOCKED')
            self.assertEqual(result['error'],'LOCAL_EXECUTION_NOT_AUTHORIZED')
            self.assertEqual(result['commands'],[])

    def test_github_context_modes_and_negatives(self):
        self.schedule();self.commit();p=ci.plan(self.root,schedule='maintenance')
        event=Path(self.tmp.name)/'event.json'
        env={'GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_REF':'refs/heads/master',
             'GITHUB_SHA':p['source']['head'],'GITHUB_EVENT_PATH':str(event),'CI_MAINTENANCE_TOKEN':'MOCK_SECRET'}
        for index,(name,dry,expected) in enumerate([('schedule',True,False),('workflow_dispatch',True,True),('workflow_dispatch',False,False)]):
            event.write_text(json.dumps({'repository':{'default_branch':'master'},'inputs':{'dry_run':str(dry).lower()}}))
            with patch.dict(os.environ,{**env,'GITHUB_EVENT_NAME':name},clear=True):
                r=ci.execute(self.root,p,p['jobs'][0],Path(self.tmp.name)/str(index),dry_run=dry)
            self.assertEqual(r['status'],'PASS',r)
            self.assertIn('dry='+str(expected),(Path(self.tmp.name)/str(index)/'commands.log').read_text())
        for index,change in enumerate([{'GITHUB_EVENT_NAME':'pull_request'}, {'GITHUB_EVENT_NAME':'push'},
            {'GITHUB_REF':'refs/heads/feature'}, {'GITHUB_REF':'refs/tags/master'}, {'GITHUB_SHA':'b'*40},
            {'CI_MAINTENANCE_TOKEN':''}]):
            with patch.dict(os.environ,{**env,**change},clear=True):
                r=ci.execute(self.root,p,p['jobs'][0],Path(self.tmp.name)/('bad'+str(index)),dry_run=False)
            self.assertEqual(r['status'],'BLOCKED',r)

    def test_schedule_source_change_and_rename_delete_fail_closed(self):
        self.schedule();p=self.document();self.write('owner/x','changed')
        with patch.dict(os.environ,{'CI_MAINTENANCE_TOKEN':'fake'},clear=True):
            r=ci.execute(self.root,p,p['jobs'][0],Path(self.tmp.name)/'out')
        self.assertIn('SOURCE_CHANGED',r['error'])
        self.commit();self.git('mv','owner/ci.schedule.py','owner/ci.release.py')
        with self.assertRaisesRegex(ci.ContractError,'INVALID_OPERATION'):ci.discover(self.root)
        (self.root/'owner/ci.release.py').unlink()
        with self.assertRaisesRegex(ci.ContractError,'UNKNOWN_COMPONENT'):self.document()

    def test_schedule_metadata_tampering_and_failed_report_rejected(self):
        self.schedule();p=self.document()
        p['jobs'][0]['secrets']={'TOKEN':'OTHER_SECRET'}
        with patch.dict(os.environ,{'CI_MAINTENANCE_TOKEN':'fake'},clear=True):
            r=ci.execute(self.root,p,p['jobs'][0],Path(self.tmp.name)/'tampered')
        self.assertEqual(r['status'],'BLOCKED')
        self.assertIn('SECRET_BINDINGS_MISMATCH',r['error'])
        p=self.document()
        r={'key':p['jobs'][0]['key'],'planId':p['planId'],'source':p['source'],'status':'FAIL'}
        self.assertEqual(ci.aggregate(p,[r])['status'],'FAIL')
        self.assertEqual(ci.aggregate(p,[])['status'],'FAIL')
        text="CI_SPEC = "+repr(dict(version=1,id='read-job',jobs=[dict(id='test',profile='linux',timeout=20,capability='maintenance')]))+"\ndef run(ctx):pass\n"
        with self.assertRaisesRegex(ci.ContractError,'MAINTENANCE_CAPABILITY_REQUIRED'):
            ci.metadata(text,'other/ci.test.py')

    def test_actions_schedule_plan_discovers_all_or_manual_selection(self):
        self.schedule();self.schedule('second','second/ci.schedule.py');self.commit()
        event=Path(self.tmp.name)/'event.json';head=self.git('rev-parse','HEAD').strip()
        env={'GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'schedule','GITHUB_REF':'refs/heads/master',
             'GITHUB_SHA':head,'GITHUB_EVENT_PATH':str(event)}
        event.write_text(json.dumps({'repository':{'default_branch':'master'}}))
        output=Path(self.tmp.name)/'scheduled-plan'
        with patch.dict(os.environ,env,clear=True):
            self.assertEqual(ci.main(['actions-plan','--root',str(self.root),'--operation','schedule','--output',str(output)]),0)
        matrix=json.loads((output/'matrix.json').read_text())
        self.assertEqual(len(matrix['maintenance']['include']),2)
        event.write_text(json.dumps({'repository':{'default_branch':'master'},'inputs':{'schedule':'second','dry_run':'true'}}))
        output=Path(self.tmp.name)/'manual-plan'
        with patch.dict(os.environ,{**env,'GITHUB_EVENT_NAME':'workflow_dispatch'},clear=True):
            self.assertEqual(ci.main(['actions-plan','--root',str(self.root),'--operation','schedule','--output',str(output)]),0)
        self.assertEqual([j['component'] for j in json.loads((output/'plan.json').read_text())['jobs']],['second'])

    def test_dispatch_intent_mismatch_and_invalid_inputs_are_blocked(self):
        self.schedule();self.commit();source=ci.snapshot(self.root,'HEAD')
        event=Path(self.tmp.name)/'event.json'
        env={'GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_REF':'refs/heads/master',
             'GITHUB_SHA':source['head'],'GITHUB_EVENT_PATH':str(event)}
        for value in ('true',1,'yes',{}):
            event.write_text(json.dumps({'repository':{'default_branch':'master'},'inputs':{'dry_run':value}}))
            with patch.dict(os.environ,env,clear=True),self.assertRaises(ci.Blocked):
                ci.maintenance_context(False,source)

    def test_wrapper_is_generic_and_has_reviewed_grants(self):
        text=(Path(__file__).parents[1]/'schedule.yml').read_text()
        for forbidden in ('report-gateway','cleanup.py','unittest','pytest','script/schedule.py'):
            self.assertNotIn(forbidden,text)
        for required in ('17 * * * *','default: true','contents: write','issues: read',
                         'CI_MAINTENANCE_TOKEN: ${{ github.token }}','vars.D4PLANNER_DIAGNOSTIC_RELEASE_ID',
                         'vars.D4PLANNER_DIAGNOSTIC_BOT_ID','ci.py actions-plan','ci.py run','ci.py aggregate'):
            self.assertIn(required,text)
