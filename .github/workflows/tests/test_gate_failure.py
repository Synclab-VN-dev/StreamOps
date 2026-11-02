"""The always-run audit must not replace the command that actually failed."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

spec=importlib.util.spec_from_file_location('streamops_contract',Path(__file__).resolve().parents[3]/'streamops/ci.test.py')
contract=importlib.util.module_from_spec(spec);spec.loader.exec_module(contract)

class GateFailure(unittest.TestCase):
    def test_preserve_primary_failure_and_record_audit_failure(self):
        original=RuntimeError('original command failure')
        ctx=SimpleNamespace(env={},shell=Mock(side_effect=RuntimeError('audit not_run')),log=Mock())
        with patch.object(contract,'_run',side_effect=original):
            with self.assertRaises(RuntimeError) as caught:contract.run(ctx)
        self.assertIs(caught.exception,original)
        ctx.shell.assert_called_once()
        self.assertTrue(ctx.log.called)

    def test_audit_failure_alone_still_fails_the_job(self):
        ctx=SimpleNamespace(env={},shell=Mock(side_effect=RuntimeError('audit not_run')),log=Mock())
        with patch.object(contract,'_run',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'audit not_run'):contract.run(ctx)

if __name__=='__main__':unittest.main()
