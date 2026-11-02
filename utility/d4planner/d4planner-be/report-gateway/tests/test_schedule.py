"""Gateway orchestration tests: fake transport only, never real GitHub mutation."""
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

GATEWAY=Path(__file__).resolve().parents[1]
ROOT=GATEWAY.parents[3]
spec=importlib.util.spec_from_file_location('gateway_schedule',GATEWAY/'ci.schedule.py')
schedule=importlib.util.module_from_spec(spec);spec.loader.exec_module(schedule)

class GatewaySchedule(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        self.event=self.folder/'event.json'
        self.event.write_text(json.dumps({'repository':{'default_branch':'master'},'inputs':{'dry_run':'true'}}))
        self.ctx=SimpleNamespace(maintenance_event='local',dry_run=True,source={'head':'a'*40},temp=self.folder,
            env={'GITHUB_TOKEN':'PRIVATE_CANARY','DIAGNOSTIC_RELEASE_ID':'77','DIAGNOSTIC_BOT_ID':'2',
                 'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_REF':'refs/heads/master','GITHUB_EVENT_PATH':str(self.event)},
            artifact=Mock(),python=Mock())
        self.domain=SimpleNamespace(GitHub=Mock(),cleanup=Mock(return_value=[{'action':'WOULD_DELETE'}]))

    def test_modes_and_public_counts(self):
        for event,dry in [('local',True),('schedule',False),('workflow_dispatch',True),('workflow_dispatch',False)]:
            self.ctx.maintenance_event=event;self.ctx.dry_run=dry;self.ctx.env['GITHUB_EVENT_NAME']=event
            self.event.write_text(json.dumps({'repository':{'default_branch':'master'},'inputs':{'dry_run':str(dry).lower()}}))
            self.domain.cleanup.return_value=[{'action':'WOULD_DELETE' if dry else 'DELETED'}]
            schedule.run(self.ctx,domain=self.domain,preflight=lambda:None)
            self.assertEqual(self.domain.cleanup.call_args.kwargs['dry_run'],dry)
            report=(self.folder/'maintenance.json').read_text()
            self.assertNotIn('PRIVATE_CANARY',report)
            self.assertEqual(json.loads(report)['counts']['deleted'],0 if dry else 1)

    def test_invalid_context_config_preflight_and_domain_fail_closed(self):
        cases=['local-execute','event','ref','config','preflight','domain']
        for case in cases:
            with self.subTest(case=case):
                self.setUp()
                preflight=Mock()
                if case=='local-execute':self.ctx.dry_run=False
                if case=='event':self.ctx.maintenance_event='pull_request'
                if case=='ref':self.ctx.maintenance_event='workflow_dispatch';self.ctx.env['GITHUB_REF']='refs/heads/feature'
                if case=='config':self.ctx.env.pop('DIAGNOSTIC_RELEASE_ID')
                if case=='preflight':preflight.side_effect=RuntimeError('PRIVATE_CANARY')
                if case=='domain':self.domain.cleanup.side_effect=RuntimeError('PRIVATE_CANARY')
                with self.assertRaisesRegex(RuntimeError,'CONTEXT_PREFLIGHT_OR_GITHUB_FAILURE'):
                    schedule.run(self.ctx,domain=self.domain,preflight=preflight)
                report=(self.folder/'maintenance.json').read_text()
                self.assertNotIn('PRIVATE_CANARY',report)
                self.assertEqual(json.loads(report)['status'],'BLOCKED')
                if case!='domain':self.domain.cleanup.assert_not_called()

    def test_preflight_has_no_token_and_calls_domain_business_suite(self):
        def preflight(*args):
            self.assertNotIn('GITHUB_TOKEN',self.ctx.env)
            self.assertIn('test_reports.py',args)
        self.ctx.python=preflight
        schedule.run(self.ctx,domain=self.domain)
        self.assertEqual(self.ctx.env['GITHUB_TOKEN'],'PRIVATE_CANARY')

    def test_local_dry_run_through_generic_engine_with_mocked_transport(self):
        spec=importlib.util.spec_from_file_location('schedule_engine_integration',ROOT/'.github/workflows/ci.py')
        ci=importlib.util.module_from_spec(spec);spec.loader.exec_module(ci)
        original=ci.importlib.util.spec_from_file_location
        def instrument(name,path,*args,**kwargs):
            result=original(name,path,*args,**kwargs)
            if str(path).endswith('ci.schedule.py'):
                execute=result.loader.exec_module
                def load(module):
                    execute(module)
                    run=module.run
                    module.run=lambda ctx:run(ctx,domain=self.domain)
                result.loader.exec_module=load
            return result
        with patch.dict(os.environ,{'CI_MAINTENANCE_TOKEN':'PRIVATE_CANARY','DIAGNOSTIC_RELEASE_ID':'77',
                                    'DIAGNOSTIC_BOT_ID':'2'},clear=True),patch.object(ci.importlib.util,'spec_from_file_location',side_effect=instrument),contextlib.redirect_stdout(io.StringIO()):
            output=self.folder/'engine'
            code=ci.main(['run','--root',str(ROOT),'--schedule','report-gateway-maintenance',
                          '--changed','--base','HEAD','--output',str(output)])
        self.assertEqual(code,0)
        self.assertTrue(self.domain.cleanup.call_args.kwargs['dry_run'])
        report=json.loads((output/'report-gateway-maintenance--cleanup/result.json').read_text())
        self.assertEqual(report['status'],'PASS')
        self.assertNotIn('PRIVATE_CANARY',json.dumps(report))
        self.assertEqual(json.loads((output/'aggregate.json').read_text())['status'],'PASS')
