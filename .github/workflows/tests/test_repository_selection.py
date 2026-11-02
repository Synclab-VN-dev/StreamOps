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

if __name__=='__main__':unittest.main()
