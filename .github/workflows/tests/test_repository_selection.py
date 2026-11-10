"""Acceptance matrix uses actual declared contracts with disposable source deltas."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('selection_engine',ROOT/'.github/workflows/ci.py')
ci=importlib.util.module_from_spec(spec);spec.loader.exec_module(ci)

class MigrationSelection(unittest.TestCase):
    def test_new_contract_covers_deleted_source_without_old_contract(self):
        # A parent PR includes migration while a child PR starts after migration.
        # Both comparisons must use their own base, and unknown paths stay blocked.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def git(*args):
                return subprocess.check_output(['git', '-C', temp, *args], text=True).strip()
            git('init', '-q')
            git('config', 'user.name', 'contract-test')
            git('config', 'user.email', 'contract-test@example.invalid')
            old = root/'legacy/runtime.py'
            old.parent.mkdir(); old.write_text('runtime = 1\n')
            git('add', '.'); git('commit', '-qm', 'before contracts')
            master = git('rev-parse', 'HEAD')
            contract = root/'component/ci.test.py'
            contract.parent.mkdir()
            metadata = {'version': 1, 'id': 'runtime',
                        'jobs': [{'id': 'unit', 'profile': 'linux', 'timeout': 60}]}
            def write_contract():
                contract.write_text('CI_SPEC = '+repr(metadata)+'\ndef run(ctx): pass\n')
            old.rename(contract.parent/'runtime.py')
            write_contract()
            with self.assertRaisesRegex(ci.ContractError, 'UNCOVERED_CHANGE: legacy/runtime.py'):
                ci.plan(root, base=master, dirty=True)
            metadata['watch'] = ['legacy/**']
            write_contract()
            git('add', '-A'); git('commit', '-qm', 'migrate with ownership')
            migrated = git('rev-parse', 'HEAD')
            parent = ci.plan(root, base=master)
            self.assertIn('legacy/runtime.py', parent['changes'])
            self.assertEqual([j['key'] for j in parent['jobs']], ['runtime--unit'])
            (contract.parent/'runtime.py').write_text('runtime = 2\n')
            git('add', '.'); git('commit', '-qm', 'child delta')
            child = ci.plan(root, base=migrated)
            self.assertEqual(child['changes'], ['component/runtime.py'])
            self.assertEqual([j['key'] for j in child['jobs']], ['runtime--unit'])
            (root/'unowned.py').write_text('unknown = True\n')
            with self.assertRaisesRegex(ci.ContractError, 'UNCOVERED_CHANGE: unowned.py'):
                ci.plan(root, base=migrated, dirty=True)

if __name__=='__main__':unittest.main()
