"""Acceptance matrix uses actual declared contracts with disposable source deltas."""
import ast
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('selection_engine',ROOT/'.github/workflows/ci.py')
ci=importlib.util.module_from_spec(spec);spec.loader.exec_module(ci)

class RepositorySelection(unittest.TestCase):
    def test_owner_requested_component_matrix(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            def git(*args):return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()
            git('init','-q');git('config','user.name','contract-test');git('config','user.email','contract-test@example.invalid')
            for contract in ci.discover(ROOT).values():
                path=root/contract['path'];path.parent.mkdir(parents=True,exist_ok=True)
                data={k:v for k,v in contract.items() if k not in ('kind','path','root','sha256')}
                path.write_text('CI_SPEC = '+repr(data)+'\ndef run(ctx): pass\n')
            git('add','.');git('commit','-qm','contracts');base=git('rev-parse','HEAD')
            cases=[
                ('utility/d4planner/d4planner-launcher/src/main.rs',{'d4planner-launcher','d4planner-be'}, {'streamops','obs-plugin'}),
                ('utility/d4planner/d4planner-hud/src/App.tsx',{'d4planner-hud','d4planner-be','streamops','game-manager-visual'}, {'obs-plugin'}),
                ('utility/d4planner/d4planner-be/src/d4planner/production.py',{'d4planner-be'}, {'streamops','d4planner-launcher'}),
                ('utility/d4planner/d4planner-rulekit/application/src/index.js',{'d4planner-rulekit','d4planner-be'}, {'streamops','d4planner-launcher'}),
                ('streamops/server/main.py',{'streamops','game-manager-visual'}, {'d4planner-launcher','d4planner-be','obs-plugin'}),
                ('.github/workflows/main.yml',{'ci-engine','d4planner-launcher','d4planner-hud','d4planner-be','d4planner-rulekit','streamops','obs-plugin'},set()),
            ]
            for name,required,forbidden in cases:
                with self.subTest(path=name):
                    path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('changed')
                    plan=ci.plan(root,base=base,dirty=True)
                    actual={j['component'] for j in plan['jobs']}
                    self.assertLessEqual(required,actual);self.assertFalse(forbidden & actual)
                    self.assertFalse(any(j['capability']!='read' for j in plan['jobs']))
                    path.unlink()

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
