"""#110 structural Graph actual must NOT magically satisfy real #108 Maxroll parity."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
REPO=HERE.parents[1]
FIXTURE=REPO/"utility"/"d4-maxroll-parity"/"rogue-3.2.1.73552-fixture.json"
GATE=REPO/"utility"/"d4-maxroll-parity"/"gate.py"
sys.path.insert(0,str(HERE))
import demo_graph
import graph


class RealParityCannotPass(unittest.TestCase):
    def test_internal_unknown_graph_actual_and_missing_independent_golden_block(self):
        o=graph.read_json(HERE/"fixtures"/"synthetic-alpha.json")
        f=graph.read_json(HERE/"fixtures"/"synthetic-three-families.json")
        actual=demo_graph.build(o,f)
        self.assertEqual(actual["realCharacterComputed"],0)
        with tempfile.TemporaryDirectory() as d:
            actual_file=Path(d)/"actual.json"
            report_file=Path(d)/"parity-report.json"
            actual_file.write_text(json.dumps(actual))
            run=subprocess.run([
                sys.executable,str(GATE),"--fixture",str(FIXTURE),
                "--actual",str(actual_file),"--report",str(report_file)
            ],capture_output=True,text=True)
            self.assertEqual(run.returncode,2,run.stdout+run.stderr)
            report=json.loads(report_file.read_text())
            self.assertEqual(report["status"],"BLOCKED")
            self.assertNotEqual(report.get("status"),"PASS")

    def test_missing_approved_golden_is_independent_of_synthetic_graph(self):
        with tempfile.TemporaryDirectory() as d:
            report=Path(d)/"not-pass.json"
            run=subprocess.run([sys.executable,str(GATE),"--fixture",str(FIXTURE),
                "--report",str(report)],capture_output=True,text=True)
            self.assertEqual(run.returncode,2,run.stdout+run.stderr)
            self.assertEqual(json.loads(report.read_text())["status"],"BLOCKED")
