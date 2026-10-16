"""#109 source-to-candidate DSL audit, fail-closed negative gates."""
from __future__ import annotations
import copy
import importlib.util
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import registry as reg
import audit_agent as agent


class CandidateAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog,cls.fingerprint=reg.read_pinned_catalog()
        cls.policy=reg.load(reg.POLICY)
        cls.candidates=reg.load(HERE/"candidates.json")
        cls.research=reg.load(HERE/"research"/"fire-dr-f7-2.json")

    def test_50_metric_source_queue_and_zero_promotion(self):
        a=agent.audit(self.catalog,self.fingerprint,self.policy,self.candidates,self.research)
        self.assertEqual(a["status"],"PASS_SOURCE_CANDIDATE_AUDIT_ONLY")
        self.assertEqual(a["g1CandidateDsl"],1)
        self.assertEqual(a["g2VerifiedBindings"],0)
        self.assertEqual(a["g3CompleteFormulas"],0)
        self.assertEqual(a["g4VisibleMetricIds"],50)
        self.assertEqual(a["activeRules"],0)
        self.assertEqual(a["approvedGoldens"],0)
        self.assertEqual(len(a["reviewQueue"]),50)
        self.assertEqual(a["sourceDisplayReplay"]["checked"],5)
        self.assertEqual(a["maxrollParity"],"BLOCKED_NOT_RUN")
        self.assertEqual(a["auditSha256"],
                         reg.sha256({k:v for k,v in a.items() if k!="auditSha256"}))
        self.assertEqual(a,agent.audit(self.catalog,self.fingerprint,self.policy,
                                       self.candidates,self.research))

    def test_exact_source_numeric_ast_is_required(self):
        for factor, value in [("num", 0.85), ("den", 14)]:
            b=copy.deepcopy(self.candidates)
            expr=b[0]["dsl"]["mechanics"][0]["actions"][0]["value"]
            if factor=="num":
                expr["args"][0]["args"][0]["value"]=value
            else:
                expr["args"][1]["args"][1]["args"][0]["value"]=value
            with self.subTest(factor=factor), self.assertRaisesRegex(reg.RegistryError,
                                                                     "FIRE_SOURCE_AST_MISMATCH"):
                agent.audit(self.catalog,self.fingerprint,self.policy,b,self.research)

    def test_changed_formula_binding_fails(self):
        b=copy.deepcopy(self.candidates)
        b[0]["dsl"]["mechanics"][0]["actions"][0]["value"]["args"][0]["args"][1]["path"]="resistance.all.total"
        with self.assertRaisesRegex(reg.RegistryError,"FIRE_SOURCE_AST_MISMATCH"):
            agent.audit(self.catalog,self.fingerprint,self.policy,b,self.research)

    def test_no_green_when_helper_or_cap_unverified_is_promoted(self):
        for key in ("exactRawHelperVerified","explicitCapVerified",
                    "sourceInputsKnownFully","approvedGolden"):
            b=copy.deepcopy(self.research)
            b[key]=True
            with self.subTest(key=key),self.assertRaises(AssertionError):
                agent.audit(self.catalog,self.fingerprint,self.policy,self.candidates,b)

    def test_missing_candidate_is_blocked_not_false_pass(self):
        with self.assertRaisesRegex(reg.RegistryError,"FIRE_BOUNDED_ONLY_SOURCE_CANDIDATE"):
            agent.audit(self.catalog,self.fingerprint,self.policy,[],self.research)

    def test_dsl_verified_promotion_is_blocked(self):
        b=copy.deepcopy(self.candidates)
        b[0]["dsl"]["verification"]["status"]="verified"
        with self.assertRaises(reg.RegistryError):
            agent.audit(self.catalog,self.fingerprint,self.policy,b,self.research)

    def test_unknown_binding_warning_is_mandatory(self):
        b=copy.deepcopy(self.candidates)
        b[0]["dsl"]["verification"]["knownLimitations"]=[]
        with self.assertRaisesRegex(reg.RegistryError,"MISSING_UNKNOWN_BINDING_WARNING"):
            agent.audit(self.catalog,self.fingerprint,self.policy,b,self.research)
