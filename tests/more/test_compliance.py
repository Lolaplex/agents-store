"""Mirror of kernel/More/Examples.lean slice 2: relations, equivalence, compliance matrix."""
import json
import unittest

from agents_store.more.compliance import (
    COMPLIANCE_PURPOSE,
    DUTY_UNMAPPED,
    MAPS_TO_COMPLIANCE_PURPOSE_INVALID,
    MAPS_TO_REL_REVERSE,
    MAPS_TO_TARGET_MISMATCH,
    MATRIX_HAND_EDITED,
    PRESERVES_MISSING,
    ROW,
    Duty,
    Mapping,
    RegulationRequirement,
    Subject,
    compliance_maps,
    compliance_matrix_from_inputs,
    compliance_violations_from_inputs,
    duty_unmapped_detail,
    mapping_of,
)
from agents_store.more.events import Event
from agents_store.more.log import EventLog
from agents_store.more.profile import SPEC_PATH, load_profile
from agents_store.more.relations import (
    REL_TYPE_REVERSE,
    Pointer,
    equivalent,
    relation_check,
    relation_violations,
)
from agents_store.more.status import _events, derive

P = load_profile()
R1, R2, XSD3, TC1 = "REQ-1@1", "REQ-1@2", "XSD-1@3", "TC-1@1"
FAB, PO = "did:example:fabian", "did:example:po"
FIELD = ("value_range", "optionality", "cardinality", "dependency")


def ver(pins, stage, method, gate, witness):
    return Event(
        "verification",
        FAB,
        ("REQ-1",),
        pins,
        body={"stage": stage, "method": method, "result": "pass", "gate": gate, "witness": witness},
    )


def demo_log():
    log = EventLog()
    a = log.append
    a(ver((R1,), "test", "unit", "ci", "run-1"))
    a(ver(("main",), "test", "unit", "ci", "run-2"))
    a(ver(("R-2026.10",), "production", "smoke", "mon", "w-0"))
    t = a(ver((R2,), "test", "unit", "ci", "run-4"))
    a(
        Event(
            "decision",
            FAB,
            ("REQ-1",),
            (R2,),
            body={
                "status": "decided",
                "decided_by": PO,
                "kind": "acceptance",
                "outcome": "accepted",
                "tests": [t.id],
            },
        )
    )
    inc = a(Event("inclusion", FAB, ("REQ-1",), (R2,), body={"into": "R-2026.10"}))
    a(ver(("R-2026.10",), "production", "smoke", "mon", "w-7"))
    return log, inc


def rel_log():
    log, _ = demo_log()
    log.append(
        Event(
            "verification",
            "did:example:ci",
            ("REQ-1",),
            (R2, XSD3),
            body={
                "stage": "test",
                "method": "derivation",
                "result": "pass",
                "gate": "xsd-gen",
                "witness": "h-8",
            },
        )
    )
    return log


REPR = Pointer("P-1", R2, XSD3, "derives_into", tuple(("verification", q) for q in FIELD))
VERIF = Pointer("P-2", R2, TC1, "verifies", (("verification", "value_range"),))
FLOAT = Pointer("P-3", R2, "XSD-1", "references")
GRAPH = [REPR, VERIF, FLOAT]

DEMO_REQS = (
    RegulationRequirement("DORA-9@2022", "DORA", "DORA-9", "2022"),
    RegulationRequirement("NIS2-21@2022", "NIS2", "NIS2-21", "2022"),
    RegulationRequirement("ISO-A8@2022", "ISO 27001", "ISO-A8", "2022"),
)

DEMO_PTRS = (
    Pointer(
        "CM-DORA",
        "DORA-9@2022",
        "DORA@2022",
        "maps_to",
        preserves=(("compliance", "Anwendungsfall"), ("compliance", "inclusion")),
    ),
    Pointer(
        "CM-NIS2",
        "NIS2-21@2022",
        "NIS2@2022",
        "maps_to",
        preserves=(("compliance", "AC"), ("compliance", "decision")),
    ),
)

SUBJECTS = [Subject(R2, "Anwendungsfall")]


class Demo(unittest.TestCase):
    def test_chain(self):
        log, _ = demo_log()
        d = derive(log, R2, P)
        self.assertEqual(
            (d.verified, d.accepted, d.released, d.proven_in_production),
            (True, True, True, True),
        )


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
        log = rel_log()
        self.assertEqual(
            relation_check(log, GRAPH, P),
            [("P-2", "claim_unmet"), ("P-3", "pointer_unpinned")],
        )


class ComplianceFromRequirements(unittest.TestCase):
    def test_matrix_matches_lean_examples(self):
        log = rel_log()
        inc_id = next(e.id for e in _events(log) if e.type == "inclusion")
        rows = compliance_matrix_from_inputs(DEMO_REQS, DEMO_PTRS, SUBJECTS, log)
        self.assertEqual(
            [(r.duty, r.satisfying, r.gap) for r in rows],
            [("DORA-9", ((R2, inc_id),), False), ("NIS2-21", (), True)],
        )

    def test_author_view_violations(self):
        log = rel_log()
        projected = compliance_matrix_from_inputs(DEMO_REQS, DEMO_PTRS, SUBJECTS, log)
        viols = compliance_violations_from_inputs(DEMO_REQS, DEMO_PTRS, SUBJECTS, log, projected)
        self.assertEqual([v.id for v in viols], [DUTY_UNMAPPED])
        self.assertEqual(viols[0].detail, duty_unmapped_detail(Duty("ISO 27001", "ISO-A8", "2022")))

    def test_matrix_hand_edited_refusal(self):
        log = rel_log()
        viols = compliance_violations_from_inputs(DEMO_REQS, DEMO_PTRS, SUBJECTS, log, [])
        self.assertEqual([v.id for v in viols], [DUTY_UNMAPPED, MATRIX_HAND_EDITED])


class MapsToRelationViolations(unittest.TestCase):
    def setUp(self) -> None:
        self.req = RegulationRequirement("DORA-9@2022", "DORA", "DORA-9", "2022")
        self.reqs = [self.req]
        self.ok_preserves = (("compliance", "Anwendungsfall"), ("compliance", "inclusion"))

    def test_target_mismatch_wrong_corpus(self):
        ptr = Pointer("CM-BAD", "DORA-9@2022", R2, "maps_to", preserves=self.ok_preserves)
        self.assertIn(MAPS_TO_TARGET_MISMATCH, relation_violations([], ptr, P, regulation_requirements=self.reqs))

    def test_target_mismatch_floating_target(self):
        ptr = Pointer("CM-FLT", "DORA-9@2022", "DORA", "maps_to", preserves=self.ok_preserves)
        self.assertIn(MAPS_TO_TARGET_MISMATCH, relation_violations([], ptr, P, regulation_requirements=self.reqs))

    def test_compliance_purpose_wrong(self):
        ptr = Pointer(
            "CM-OP",
            "DORA-9@2022",
            "DORA@2022",
            "maps_to",
            preserves=(("operations", "Anwendungsfall"), ("operations", "inclusion")),
        )
        self.assertIn(
            MAPS_TO_COMPLIANCE_PURPOSE_INVALID,
            relation_violations([], ptr, P, regulation_requirements=self.reqs),
        )
        self.assertEqual(compliance_maps(self.reqs, [ptr], P.levels), [])

    def test_compliance_purpose_mixed_refuses_mapping(self):
        ptr = Pointer(
            "CM-T1",
            "DORA-9@2022",
            "DORA@2022",
            "maps_to",
            preserves=(
                ("operations", "Anwendungsfall"),
                ("compliance", "Anwendungsfall"),
                ("compliance", "inclusion"),
            ),
        )
        self.assertIsNone(mapping_of(self.reqs, ptr, P.levels))
        self.assertIn(
            MAPS_TO_COMPLIANCE_PURPOSE_INVALID,
            relation_violations([], ptr, P, regulation_requirements=self.reqs),
        )

    def test_preserves_missing_empty(self):
        ptr = Pointer("CM-EMP", "DORA-9@2022", "DORA@2022", "maps_to", preserves=())
        viols = relation_violations([], ptr, P, regulation_requirements=self.reqs)
        self.assertIn(PRESERVES_MISSING, viols)
        self.assertNotIn(MAPS_TO_COMPLIANCE_PURPOSE_INVALID, viols)

    def test_preserves_missing_ambiguous_levels(self):
        ptr = Pointer(
            "CM-2L",
            "DORA-9@2022",
            "DORA@2022",
            "maps_to",
            preserves=(("compliance", "Anwendungsfall"), ("compliance", "AC"), ("compliance", "inclusion")),
        )
        self.assertIn(PRESERVES_MISSING, relation_violations([], ptr, P, regulation_requirements=self.reqs))
        self.assertIsNone(mapping_of(self.reqs, ptr, P.levels))

    def test_preserves_missing_only_level(self):
        ptr = Pointer(
            "CM-L",
            "DORA-9@2022",
            "DORA@2022",
            "maps_to",
            preserves=(("compliance", "Anwendungsfall"),),
        )
        self.assertIn(PRESERVES_MISSING, relation_violations([], ptr, P, regulation_requirements=self.reqs))

    def test_mapped_from_reverse_reading(self):
        self.assertEqual(REL_TYPE_REVERSE["maps_to"], MAPS_TO_REL_REVERSE)
        rel = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["layers"]["relations"]["types"]["maps_to"]
        self.assertEqual(rel["reverse"], "mapped_from")


class ComplianceSpec(unittest.TestCase):
    def test_row_and_violations_match_spec(self):
        cm = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["generated_projections"]["compliance_matrix"]
        self.assertEqual(list(ROW), cm["row"])
        self.assertEqual(
            sorted(cm["violations"]),
            sorted(
                [
                    DUTY_UNMAPPED,
                    MATRIX_HAND_EDITED,
                    MAPS_TO_TARGET_MISMATCH,
                    MAPS_TO_COMPLIANCE_PURPOSE_INVALID,
                    PRESERVES_MISSING,
                ]
            ),
        )

    def test_compliance_purpose_registered(self):
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        entry = spec["purpose_register"]["profiles"]["compliance_matrix"]["entries"][0]
        self.assertEqual(entry["key"], COMPLIANCE_PURPOSE)


if __name__ == "__main__":
    unittest.main()
