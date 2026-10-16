"""Source-only bounded numeric replay negative checks; not real Graph parity."""
import copy
import importlib.util
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parents[1]/"research"
spec=importlib.util.spec_from_file_location("source_fire_check",HERE/"check_fire_dr.py")
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class FireResearchGateTests(unittest.TestCase):
    def setUp(self):
        import json
        self.doc=json.loads((HERE/"fire-dr-f7-2.json").read_text())

    def test_five_controlled_display_points_are_consistent(self):
        r=m.compare(self.doc)
        self.assertEqual(r["sourceMatch"],5)
        self.assertEqual(r["status"],"PASS_BOUNDED_RESEARCH_REPLAY_ONLY")
        self.assertFalse(r["approvedGolden"])
        self.assertFalse(r["promotableToActiveRule"])

    def test_source_display_mismatch_blocks(self):
        b=copy.deepcopy(self.doc)
        b["vectors"][2]["maxrollDisplayPercent"]="71.9"
        with self.assertRaisesRegex(AssertionError,"F7.2_DISPLAY_MISMATCH"):
            m.compare(b)

    def test_raw_helper_or_cap_promotion_blocks(self):
        for key in ("exactRawHelperVerified","explicitCapVerified",
                    "sourceInputsKnownFully","approvedGolden"):
            b=copy.deepcopy(self.doc)
            b[key]=True
            with self.subTest(key=key),self.assertRaises(AssertionError):
                m.compare(b)

    def test_wrong_level_patch_or_tolerance_blocks(self):
        for key,value in [("patch","3.2.3.73883"),("displayTolerancePercentagePoints","2")]:
            b=copy.deepcopy(self.doc)
            b[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):
                m.compare(b)
        b=copy.deepcopy(self.doc)
        b["vectors"][0]["level"]=60
        with self.assertRaises(AssertionError):
            m.compare(b)

    def test_not_fully_independent_goldens(self):
        result=m.compare(self.doc)
        self.assertEqual(result["graphParity"],"BLOCKED_NOT_RUN")
        self.assertFalse(result["verifiedExactRawHelper"])
        self.assertFalse(result["verifiedExplicitCap"])
