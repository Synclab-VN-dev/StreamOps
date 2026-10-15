import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from check import validate  # noqa: E402

EXAMPLE = json.loads((ROOT / 'examples-synthetic.json').read_text(encoding='utf-8'))

class TestCaptureContract(unittest.TestCase):
    def test_synthetic_is_candidate_only(self):
        self.assertEqual(validate(EXAMPLE)['status'], 'PASS_CANDIDATE_ONLY')
        self.assertEqual(validate(EXAMPLE)['totalVisibleMetrics'], 1)
        self.assertEqual(validate(EXAMPLE)['maxrollParity'], 'NOT_TESTED')
    def test_synthetic_is_not_golden(self):
        self.assertEqual(validate(EXAMPLE, golden=True)['status'], 'FAIL')
    def test_missing_metric_is_not_full_coverage(self):
        data = copy.deepcopy(EXAMPLE)
        data['groups'][0]['metrics'] = []
        self.assertEqual(validate(data)['status'], 'FAIL')
    def test_duplicate_ids_fail(self):
        data = copy.deepcopy(EXAMPLE)
        data['groups'][0]['metrics'].append(copy.deepcopy(data['groups'][0]['metrics'][0]))
        data['groups'][0]['visibleCount'] = 2
        data['totalVisibleMetrics'] = 2
        self.assertIn('duplicate metric id', '\n'.join(validate(data)['errors']))
    def test_raw_without_runtime_origin_fails(self):
        data = copy.deepcopy(EXAMPLE)
        data['groups'][0]['metrics'][0]['rawValue'] = 123
        self.assertEqual(validate(data)['status'], 'FAIL')
    def test_non_maxroll_source_fails(self):
        data = copy.deepcopy(EXAMPLE)
        data['source'] = 'BLIZZARD'
        self.assertEqual(validate(data)['status'], 'FAIL')
    def test_no_invented_global_coverage(self):
        data = copy.deepcopy(EXAMPLE)
        data['globalGameCoverage'] = 100
        self.assertEqual(validate(data)['status'], 'FAIL')
    def test_patch_format(self):
        data = copy.deepcopy(EXAMPLE)
        data['versionEvidence']['gamePatch'] = 'fake-patch'
        self.assertEqual(validate(data)['status'], 'FAIL')
    def test_critical_fixture_fields(self):
        data = copy.deepcopy(EXAMPLE)
        data['fixture']['inputSnapshotSha256'] = 'fake'
        self.assertEqual(validate(data)['status'], 'FAIL')
    def test_valid_golden_record_does_not_require_causal_formula_evidence(self):
        data = copy.deepcopy(EXAMPLE)
        data['versionEvidence'].update(status='VERIFIED', appVersion='1.0.0', gamePatch='3.2.1', gameBuild='73552')
        data['fixture']['inputCompleteness'] = 'COMPLETE'
        data['referenceApproval'] = 'INDEPENDENTLY_REVIEWED'
        data['referenceManifestSha256'] = 'b' * 64
        data['fixtureOrigin'] = 'CAPTURED_MAXROLL_INDEPENDENTLY'
        result = validate(data, golden=True)
        self.assertEqual(result['status'], 'PASS_GOLDEN_RECORD_INTEGRITY')
        self.assertEqual(result['maxrollParity'], 'NOT_TESTED')
    def test_no_expected_from_engine(self):
        data = copy.deepcopy(EXAMPLE)
        data['versionEvidence'].update(status='VERIFIED', appVersion='1.0.0', gamePatch='3.2.1', gameBuild='73552')
        data['fixture']['inputCompleteness'] = 'COMPLETE'
        data['referenceApproval'] = 'INDEPENDENTLY_REVIEWED'
        data['referenceManifestSha256'] = 'a' * 64
        data['fixtureOrigin'] = 'STREAMOPS_ENGINE_OUTPUT'
        self.assertEqual(validate(data, golden=True)['status'], 'FAIL')

if __name__ == '__main__': unittest.main()
