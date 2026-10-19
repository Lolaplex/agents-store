"""Mirror of the slice-1/2 demo in kernel/More/Examples.lean: REQ-1@2,
purpose-indexed equivalence and the compliance matrix."""
import json
import unittest

from agents_store.more.compliance import (DUTY_UNMAPPED, MATRIX_HAND_EDITED, ROW, Duty, Mapping,
                                    Subject, compliance_violations, matrix)
from agents_store.more.events import Event
from agents_store.more.log import EventLog
from agents_store.more.profile import SPEC_PATH, load_profile
from agents_store.more.relations import Pointer, equivalent, relation_check
from agents_store.more.status import derive

P = load_profile()
R1, R2, XSD3, TC1 = "REQ-1@1", "REQ-1@2", "XSD-1@3", "TC-1@1"
FAB, PO = "did:example:fabian", "did:example:po"
FIELD = ("value_range", "optionality", "cardinality", "dependency")


def ver(pins, stage, method, gate, witness):
    return Event("verification", FAB, ("REQ-1",), pins,
                 body={"stage": stage, "method": method, "result": "pass",
                       "gate": gate, "witness": witness})


def demo_log():
    log = EventLog()
    a = log.append
    a(ver((R1,), "test", "unit", "ci", "run-1"))
    a(ver(("main",), "test", "unit", "ci", "run-2"))
    a(ver(("R-2026.10",), "production", "smoke", "mon", "w-0"))
    t = a(ver((R2,), "test", "unit", "ci", "run-4"))
    a(Event("decision", FAB, ("REQ-1",), (R2,),
            body={"status": "decided", "decided_by": PO, "kind": "acceptance",
                  "outcome": "accepted", "tests": [t.id]}))
    inc = a(Event("inclusion", FAB, ("REQ-1",), (R2,), body={"into": "R-2026.10"}))
    a(ver(("R-2026.10",), "production", "smoke", "mon", "w-7"))
    return log, inc


REPR = Pointer("P-1", R2, XSD3, "represented_by", tuple(("verification", q) for q in FIELD))
VERIF = Pointer("P-2", R2, TC1, "verifies", (("verification", "value_range"),))
FLOAT = Pointer("P-3", R2, "XSD-1", "references")
GRAPH = [REPR, VERIF, FLOAT]


class Demo(unittest.TestCase):
    def test_chain(self):
        log, _ = demo_log()
        d = derive(log, R2, P)
        self.assertEqual((d.verified, d.accepted, d.released, d.proven_in_production),
                         (True, True, True, True))


class Equivalence(unittest.TestCase):
    def test_purpose_indexed(self):
        self.assertTrue(equivalent(GRAPH, "verification", R2, XSD3, P))
        self.assertFalse(equivalent(GRAPH, "acceptance", R2, XSD3, P))
        self.assertFalse(equivalent(GRAPH, "operations", R2, XSD3, P))

    def test_symmetric_and_transitive(self):
        nxt = Pointer("P-9", XSD3, "XSD-2@1", "derives_from", tuple(("verification", q) for q in FIELD))
        self.assertTrue(equivalent(GRAPH + [nxt], "verification", "XSD-2@1", R2, P))

    def test_only_representation_edges_count(self):
        self.assertFalse(equivalent(GRAPH, "verification", R2, TC1, P))
        self.assertTrue(equivalent([], "verification", R2, R2, P))

    def test_relation_check_with_evidence(self):
        log, _ = demo_log()
        log.append(Event("verification", "did:example:ci", ("REQ-1",), (R2, XSD3),
                         body={"stage": "test", "method": "derivation", "result": "pass",
                               "gate": "xsd-gen", "witness": "h-8"}))
        self.assertEqual(relation_check(log, GRAPH, P), [("P-2", "claim_unmet"), ("P-3", "pointer_unpinned")])


DUTIES = [Duty("DORA", "DORA-9", "2022"), Duty("NIS2", "NIS2-21", "2022"), Duty("ISO 27001", "ISO-A8", "2022")]
MAPS = [Mapping("DORA-9", "2022", "Anwendungsfall", "inclusion"), Mapping("NIS2-21", "2022", "AC", "decision")]
SUBJECTS = [Subject(R2, "Anwendungsfall")]


class Compliance(unittest.TestCase):
    def test_matrix_as_in_lean(self):
        log, inc = demo_log()
        rows = matrix(DUTIES, MAPS, SUBJECTS, log)
        self.assertEqual([(r.duty, r.satisfying, r.gap) for r in rows],
                         [("DORA-9", ((R2, inc.id),), False), ("NIS2-21", (), True)])

    def test_violations(self):
        log, _ = demo_log()
        stored = matrix(DUTIES, MAPS, SUBJECTS, log)
        self.assertEqual([v.id for v in compliance_violations(DUTIES, MAPS, SUBJECTS, log, stored)],
                         [DUTY_UNMAPPED])
        self.assertEqual([v.id for v in compliance_violations(DUTIES, MAPS, SUBJECTS, log, [])],
                         [DUTY_UNMAPPED, MATRIX_HAND_EDITED])

    def test_row_and_violations_match_spec(self):
        cm = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["generated_projections"]["compliance_matrix"]
        self.assertEqual(list(ROW), cm["row"])
        self.assertEqual(sorted(cm["violations"]), sorted([DUTY_UNMAPPED, MATRIX_HAND_EDITED]))


if __name__ == "__main__":
    unittest.main()
