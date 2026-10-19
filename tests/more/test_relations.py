"""Relations and the DoR checks (mirror of the slice-2 relation example in
kernel/More/Examples.lean, plus one case per remaining dor_* id)."""
import unittest

from agents_store.more.events import Event
from agents_store.more.hierarchy import Node
from agents_store.more.log import EventLog
from agents_store.more.profile import load_profile
from agents_store.more.ready import (DOR_AC_UNCLEAR, DOR_DEPENDENCY_UNRESOLVED,
                               DOR_LINKED_DECISION_OPEN, DOR_SPEC_RESTATED, dor_violations)
from agents_store.more.relations import (CLAIM_UNMET, POINTER_SUSPECT, POINTER_UNPINNED,
                                   PRESERVES_MISSING, Pointer, claim_met, relation_check)

P = load_profile()
R2, XSD3, TC1 = "REQ-1@2", "XSD-1@3", "TC-1@1"
CI = "did:example:ci"
FIELD_RULES = tuple(("verification", q) for q in ("value_range", "optionality", "cardinality", "dependency"))

REPR = Pointer("P-1", R2, XSD3, "represented_by", FIELD_RULES)
VERIF = Pointer("P-2", R2, TC1, "verifies", (("verification", "value_range"),))
FLOAT = Pointer("P-3", R2, "XSD-1", "references")


def derivation_evidence():
    return Event("verification", CI, ("REQ-1",), (R2, XSD3),
                 body={"stage": "test", "method": "derivation", "result": "pass",
                       "gate": "xsd-gen", "witness": "h-8"})


class Relations(unittest.TestCase):
    def setUp(self):
        self.log = EventLog()
        self.log.append(derivation_evidence())

    def test_relation_check_as_in_lean(self):
        self.assertEqual(relation_check(self.log, [REPR, VERIF, FLOAT], P),
                         [("P-2", CLAIM_UNMET), ("P-3", POINTER_UNPINNED)])

    def test_evidence_must_be_pinned_to_both_ends(self):
        self.assertTrue(claim_met(self.log, REPR, P))
        one_sided = EventLog()
        one_sided.append(Event("verification", CI, ("REQ-1",), (R2,),
                               body={"stage": "test", "method": "derivation", "result": "pass",
                                     "gate": "xsd-gen", "witness": "h"}))
        self.assertFalse(claim_met(one_sided, REPR, P))

    def test_suspect_and_preserves_missing(self):
        self.log.append(Event("supersession", CI, ("XSD-1",), (XSD3,), supersedes=("x",)))
        bare = Pointer("P-4", R2, XSD3, "derives_from")
        self.assertEqual([v for _, v in relation_check(self.log, [bare], P)],
                         [POINTER_SUSPECT, PRESERVES_MISSING])


class Dor(unittest.TestCase):
    UC = "UC-1@1"
    NODES = [Node("AC-1", "AC", "UC-1", {"AC": "Accepted when the office confirms receipt."})]
    SPEC = Pointer("P-S", UC, "SPEC-1@1", "refines")

    def test_linked_decision_and_dependency(self):
        log = EventLog()
        log.append(Event("decision", CI, ("DEC-1",), ("DEC-1@1",), body={"status": "open"}))
        g = [self.SPEC, Pointer("P-D", self.UC, "DEC-1@1", "decided_in"),
             Pointer("P-X", self.UC, "DEC-1@1", "depends_on")]
        self.assertEqual(dor_violations(log, g, self.NODES, self.UC, P),
                         [DOR_LINKED_DECISION_OPEN, DOR_DEPENDENCY_UNRESOLVED])

    def test_unclear_ac_and_restated_spec(self):
        nodes = [Node("AC-1", "AC", "UC-1", {"AC": "TBD"}),
                 Node("UC-1", "Anwendungsfall", "FG-1",
                      {"Anwendungsfall": "File a return.", "AC": "Accepted on receipt."})]
        self.assertEqual(dor_violations(EventLog(), [self.SPEC], nodes, self.UC, P),
                         [DOR_AC_UNCLEAR, DOR_SPEC_RESTATED])


if __name__ == "__main__":
    unittest.main()
