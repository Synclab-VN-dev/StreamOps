"""Run the actual Windows workflow detector under PowerShell with a fake git diff.

No GitHub calls, repository mutations, services or third-party Python packages.
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/tests.yml'


def detector():
    source = WORKFLOW.read_text(encoding='utf-8')
    block = source.split('      - name: Detect changed components\n', 1)[1]
    block = block.split('\n      - ', 1)[0].split('        run: |\n', 1)[1]
    return '\n'.join(line[10:] for line in block.splitlines())


def detect(files, event='pull_request'):
    script = detector().replace('${{ github.event_name }}', event)
    script = script.replace('${{ github.event.pull_request.base.sha }}', 'BASE')
    script = script.replace('${{ github.event.pull_request.head.sha }}', 'HEAD')
    with tempfile.TemporaryDirectory(prefix='streamops-detector-') as directory:
        output = Path(directory) / 'outputs.txt'
        harness = Path(directory) / 'detector.ps1'
        harness.write_text(
            "$ErrorActionPreference = 'Stop'\n"
            "function git {\n"
            "  if (($args -join ' ') -ne 'diff --name-only BASE...HEAD') { throw 'Unexpected git call' }\n"
            "  ConvertFrom-Json $env:TEST_CHANGED_FILES\n"
            "}\n" + script, encoding='utf-8')
        result = subprocess.run(
            [shutil.which('pwsh') or 'pwsh', '-NoProfile', '-File', str(harness)],
            env={**os.environ, 'GITHUB_OUTPUT': str(output),
                 'TEST_CHANGED_FILES': json.dumps(files)},
            capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return dict(line.split('=', 1) for line in output.read_text(encoding='utf-8-sig').splitlines())


class ChangeDetectionTests(unittest.TestCase):
    def test_component_matrix(self):
        # Expected D4Planner, Launcher, Server flags; execute production PS logic.
        cases = [
            ('launcher', ['utility/d4planner/d4planner-launcher/src/main.rs'], ('true','true','false')),
            ('launcher-config', ['utility/d4planner/d4planner-launcher/.cargo/config.toml'], ('true','true','false')),
            ('hud', ['utility/d4planner/d4planner-hud/src/App.tsx'], ('true','false','true')),
            ('be', ['utility/d4planner/d4planner-be/src/d4planner/production.py'], ('true','false','false')),
            ('rulekit', ['utility/d4planner/d4planner-rulekit/application/src/index.js'], ('true','false','false')),
            ('server', ['streamops/server/app.py'], ('false','false','true')),
            ('workflow', ['.github/workflows/tests.yml'], ('true','true','true')),
            ('workflow-and-server', ['.github/workflows/tests.yml','streamops/server/app.py'], ('true','true','true')),
            ('detector-test', ['scripts/ci/test_changed_components.py'], ('true','true','false')),
            ('hud-workflow', ['.github/workflows/d4-overlay-poc.yml'], ('true','false','true')),
            ('unrelated-doc', ['README.md'], ('false','false','false')),
        ]
        for name, files, expected in cases:
            with self.subTest(name=name):
                result = detect(files)
                actual = tuple(result[key] for key in ('d4planner','launcher','server'))
                self.assertEqual(actual, expected)
                print(f'{name}: expected={expected}; actual={actual}; PASS')

    def test_master_push_validates_launcher(self):
        result = detect([], event='push')
        self.assertEqual(result, {'launcher':'true','d4planner':'true','server':'true','gameui':'false'})

    def test_launcher_flag_gates_real_build_and_tests(self):
        source = WORKFLOW.read_text(encoding='utf-8')
        for name in ('Set up pinned Rust for Launcher validation', 'Build and test D4Planner Launcher'):
            step = source.split('      - name: ' + name + '\n', 1)[1].split('\n      - ', 1)[0]
            self.assertIn("if: steps.changes.outputs.launcher == 'true'", step)
        self.assertIn('working-directory: utility/d4planner/d4planner-launcher', step)
        self.assertIn('cargo test --locked --release', step)
        self.assertIn('cargo build --locked --release', step)
        self.assertIn('target/release/D4Planner.exe', step)
        self.assertIn('run: python scripts/ci/test_changed_components.py', source)
        self.assertIn('  pull_request:', source.split('jobs:', 1)[0])
        # Existing independent HUD/Rule Kit workflows must still accept their paths.
        for workflow, component in [('d4-overlay-poc.yml','d4planner-hud'), ('d4-rulekit.yml','d4planner-rulekit')]:
            triggers = (ROOT / '.github/workflows' / workflow).read_text().split('jobs:', 1)[0]
            self.assertIn('pull_request:', triggers)
            self.assertIn('utility/d4planner/' + component + '/**', triggers)


if __name__ == '__main__':
    unittest.main(verbosity=2)
