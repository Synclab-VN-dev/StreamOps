"""Failure-path regression using the real CI executor, logs and artifact manifest."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[5]
CONTRACT = 'utility/d4planner/d4planner-rulekit/catalog-export/ci.test.py'
SENTINEL = 'synthetic-private-config-never-upload'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ci = load('privacy_ci_engine', ROOT / '.github/workflows/ci.py')


class ArtifactPrivacy(unittest.TestCase):
    def exercise(self, stage):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'ci-results'
            source = {'head': 'test', 'tree': 'a' * 64, 'dirty': False}
            spec = ci.metadata((ROOT / CONTRACT).read_text(), CONTRACT)
            job = dict(next(j for j in spec['jobs'] if j['id'] == 'export'),
                       key='d4planner-catalog-export--export', component=spec['id'],
                       contract=CONTRACT, contractSha256=spec['sha256'], operation='test')
            original = ci.Context
            observed = []

            class Context(original):
                def prepare_checkout(self):
                    pass

                def tool(self, *args):
                    pass

                def close(self):
                    # Verify component-level finally cleanup before the engine's
                    # own fallback cleanup could mask a leaked temporary file.
                    self_test.assertFalse(list(self.temp.glob('catalog-private-*')))
                    return super().close()

                def shell(self, *args, **kwargs):
                    if stage == 'setup_failure':
                        raise RuntimeError('SYNTHETIC_SETUP_FAILURE')

                def run(self, args, **kwargs):
                    if args[0] != 'node':
                        return super().run(args, **kwargs)
                    filename = Path(args[2])
                    observed.append(filename)
                    if stage == 'invalid_config':
                        # Actual Node validator and sanitized CLI failure, no network.
                        return super().run(args, **kwargs)
                    self_test.assertFalse(filename.is_relative_to(self.output))
                    self_test.assertEqual(filename.stat().st_mode & 0o777, 0o600)
                    if stage == 'job_failure':
                        raise RuntimeError('SYNTHETIC_JOB_FAILURE')
                    target = Path(args[3])
                    target.mkdir()
                    (target / 'catalog.json.age').write_bytes(b'synthetic-ciphertext')
                    (target / 'report.json').write_text('{"status":"PASS"}')

            self_test = self
            config = {'unapproved': SENTINEL} if stage == 'invalid_config' else {'snapshot': SENTINEL}
            env = {'GITHUB_ACTIONS': 'false', 'CI_BOUND_SECRET_1': 'synthetic-identity',
                   'CI_TRUSTED_EXECUTION': '1', 'AGE_IDENTITY_SECRET': 'synthetic-identity',
                   'CI_VARIABLES_JSON': json.dumps({'D4PLANNER_CATALOG_EXPORT_CONFIG': json.dumps(config)}),
                   'RUNNER_TEMP': temporary}
            with patch.dict(os.environ, env), patch.object(ci, 'snapshot', return_value=source), patch.object(ci, 'Context', Context):
                result = ci.execute(ROOT, {'source': source, 'planId': 'synthetic', 'operation': 'test'}, job, output)
            self.assertEqual(result['status'], 'PASS' if stage == 'success' else 'FAIL')
            # main.yml uploads the entire output directory on failure too.
            upload_manifest = [p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()]
            self.assertFalse(any('catalog-config' in p for p in upload_manifest), upload_manifest)
            for file in output.rglob('*'):
                if file.is_file():
                    self.assertNotIn(SENTINEL.encode(), file.read_bytes())
                    self.assertNotIn(b'synthetic-identity', file.read_bytes())
            self.assertEqual(set(result['artifactManifest']),
                             {'catalog.json.age', 'report.json'} if stage == 'success' else set())
            self.assertTrue(all(not p.exists() for p in observed))

    def test_invalid_config(self):
        self.exercise('invalid_config')

    def test_setup_failure(self):
        self.exercise('setup_failure')

    def test_job_failure(self):
        self.exercise('job_failure')

    def test_success_uploads_only_ciphertext_and_report(self):
        self.exercise('success')


if __name__ == '__main__':
    unittest.main()
