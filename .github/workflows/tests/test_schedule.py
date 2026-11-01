import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

spec=importlib.util.spec_from_file_location('schedule',Path(__file__).parents[1]/'script/schedule.py')
schedule=importlib.util.module_from_spec(spec);spec.loader.exec_module(schedule)

class Maintenance(unittest.TestCase):
    def test_dispatch_policy(self):
        self.assertTrue(schedule.mode('local',True))
        self.assertTrue(schedule.mode('workflow_dispatch',True))
        self.assertFalse(schedule.mode('workflow_dispatch',False))
        self.assertFalse(schedule.mode('schedule',True))
        for event,dry in [('pull_request',True),('local',False)]:
            with self.assertRaises(ValueError):schedule.mode(event,dry)

    def test_mocked_modes_counts_and_no_credential_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            event=Path(tmp)/'event.json'
            event.write_text(json.dumps({'repository':{'default_branch':'master'}}))
            env={'DIAGNOSTIC_RELEASE_ID':'1','DIAGNOSTIC_BOT_ID':'2','GITHUB_TOKEN':'PRIVATE_CANARY',
                 'GITHUB_REF':'refs/heads/master','GITHUB_EVENT_PATH':str(event)}
            for name,dry,expected in [('local',True,True),('workflow_dispatch',True,True),
                                      ('workflow_dispatch',False,False),('schedule',True,False)]:
                env['GITHUB_EVENT_NAME']=name
                domain=SimpleNamespace(GitHub=Mock(),cleanup=Mock(return_value=[{'action':'WOULD_DELETE' if expected else 'DELETED'}]))
                output=Path(tmp)/'result.json'
                self.assertEqual(schedule.run(name,dry,output,domain=domain,env=env,preflight=lambda:None),0)
                self.assertEqual(domain.cleanup.call_args.kwargs['dry_run'],expected)
                self.assertNotIn('PRIVATE_CANARY',output.read_text())
                self.assertEqual(json.loads(output.read_text())['status'],'PASS')

    def test_untrusted_ref_and_missing_config_never_call_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            domain=Mock()
            for env in ({},{'GITHUB_REF':'refs/pull/1/merge','GITHUB_EVENT_NAME':'workflow_dispatch'}):
                self.assertEqual(schedule.run('workflow_dispatch',False,Path(tmp)/'r.json',domain=domain,env=env,preflight=lambda:None),1)
                domain.cleanup.assert_not_called()

if __name__=='__main__':unittest.main()
