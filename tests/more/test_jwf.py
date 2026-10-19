"""Mirror of kernel/More/JwfExamples.lean: work item WI-7@1 walks the JWF
board from Neu to Geschlossen. Every state is derived from the log."""
import unittest

from agents_store.more.checks import ACCEPTANCE_AS_STATUS, STATUS_HAND_SET, VERIFICATION_UNPINNED
from agents_store.more.events import Event
from agents_store.more.hierarchy import Node
from agents_store.more.jwf import ACCEPTANCE_TOPIC, GUARDS, REACHES, chain, gate_held, jwf_state
from agents_store.more.log import EventLog, Refused
from agents_store.more.profile import load_profile
from agents_store.more.ready import (DOR_AC_UNCLEAR, DOR_DECISION_OPEN, DOR_SPEC_NOT_POINTED,
                               dor_violations, ready)
from agents_store.more.relations import Pointer
from agents_store.more.status import derive, drift_check

WI, SPEC, CODE = "WI-7@1", "SPEC-3@2", "CODE-9@5"
PO, QA, RM = "did:example:po", "did:example:qa", "did:example:rm"
ACTOR = "did:example:fabian"
JWF = load_profile().with_settings(
    roles={PO: ["PO/Fachbereich"], QA: ["Test/Abnahme"], RM: ["Release/Team"]})

NODES = [
    Node("WI-7", "Anwendungsfall", "FG-1", {"Anwendungsfall": "Submit the monthly report."}),
    Node("AC-7", "AC", "WI-7", {"AC": "Accepted when the office confirms receipt."}),
    Node("UI-7", "UI", "WI-7", {"UI": "Form with period and amount."}),
]
SPEC_PTR = Pointer("P-S", WI, SPEC, "refines")
IMPL_PTR = Pointer("P-I", WI, CODE, "implements", (("verification", "value_range"),))
BOTH = [SPEC_PTR, IMPL_PTR]


def dec(subject, pins, status="decided", by=None, **body):
    b = {"status": status, **body}
    if by:
        b["decided_by"] = by
    return Event("decision", ACTOR, (subject,), pins, body=b)


def ver(subject, pins, stage, method, result, gate, witness):
    return Event("verification", ACTOR, (subject,), pins,
                 body={"stage": stage, "method": method, "result": result,
                       "gate": gate, "witness": witness})


def accept(by, ids, outcome="accepted", topic=ACCEPTANCE_TOPIC):
    return dec("WI-7", (WI,), by=by, kind="acceptance", outcome=outcome,
               tests=[ids[9], ids[11]], topic=topic)


def base(ids):
    return [
        (1, lambda: dec("WI-7", (WI,), status="open")),
        (2, lambda: Event("supersession", ACTOR, ("WI-7",), (WI,), supersedes=(ids[1],))),
        (3, lambda: dec("WI-7", (WI,), by=PO, topic="selection")),
        (4, lambda: ver("WI-7", (WI,), "review", "goal_understood", "pass", "QG1", "r-4")),
        (5, lambda: ver("WI-7", (WI,), "review", "acceptance_criteria_sufficient", "pass", "QG1", "r-5")),
        (6, lambda: ver("WI-7", (WI,), "review", "essential_risks_known", "pass", "QG1", "r-6")),
        (7, lambda: ver("CODE-9", (CODE,), "test", "unit", "pass", "ci", "run-7")),
        (8, lambda: ver("WI-7", (WI, CODE), "test", "integration", "fail", "ci", "run-8")),
        (9, lambda: ver("WI-7", (WI, CODE), "test", "integration", "pass", "ci", "run-9")),
        (10, lambda: ver("WI-7", (WI,), "test", "uat", "fail", "uat", "u-10")),
        (11, lambda: ver("WI-7", (WI,), "test", "uat", "pass", "uat", "u-11")),
        (13, lambda: accept(QA, ids)),
        (14, lambda: Event("inclusion", ACTOR, ("WI-7",), (WI,), body={"into": "R-7"})),
        (15, lambda: ver("WI-7", ("R-7",), "production", "smoke", "pass", "mon", "w-15")),
    ]


def build(n, extra=None, profile=JWF):
    log = EventLog(profile=profile)
    ids = {}
    for k, make in base(ids)[:n]:
        ids[k] = log.append(make()).id
    for e in (extra(ids) if extra else []):
        log.append(e)
    return log


def state(n, g=BOTH, nodes=NODES, extra=None, profile=JWF):
    return jwf_state(build(n, extra, profile), g, nodes, WI, profile)


class Walk(unittest.TestCase):
    def test_board_walk(self):
        expect = ["Neu", "In technischer Beschreibung", "In technischer Beschreibung",
                  "In technischer Beschreibung", "In technischer Beschreibung",
                  "In technischer Beschreibung", "Fertig für Entwicklung", "In Entwicklung",
                  "In technischer QS", "In Abnahme", "Im fachlichen Test", "In Abnahme",
                  "Abgenommen", "Produktion", "Geschlossen"]
        self.assertEqual([state(n) for n in range(15)], expect)

    def test_early_states(self):
        self.assertEqual(state(1, [], []), "Ausgewählt")
        self.assertEqual(state(1, [], NODES[:2]), "In fachlicher Beschreibung")
        self.assertEqual(state(1, [SPEC_PTR]), "In technischer Beschreibung")
        self.assertEqual(dor_violations(build(1), [], [], WI, JWF),
                         [DOR_DECISION_OPEN, DOR_AC_UNCLEAR, DOR_SPEC_NOT_POINTED])
        self.assertEqual(state(3, [SPEC_PTR]), "In technischer Beschreibung")
        self.assertTrue(ready(build(3), [SPEC_PTR], NODES, WI, JWF))
        self.assertEqual(state(6, [SPEC_PTR]), "Fertig für Einplanung")

    def test_never_test_abgeschlossen(self):
        for n in range(15):
            self.assertNotEqual(state(n), "Test abgeschlossen")

    def test_geschlossen_iff_all_conditions(self):
        log = build(14)
        self.assertTrue(all(chain(log, BOTH, NODES, WI, JWF)))
        self.assertTrue(gate_held(log, BOTH, NODES, WI, "QG3", JWF))


class Acceptance(unittest.TestCase):
    def test_po_accepts_by_default(self):
        self.assertEqual(state(11, extra=lambda i: [accept(PO, i)]), "Abgenommen")

    def test_narrowed_profile_keeps_in_abnahme(self):
        qa_only = JWF.with_settings(acceptor_roles=["Test/Abnahme"])
        self.assertEqual(state(11, extra=lambda i: [accept(PO, i)], profile=qa_only), "In Abnahme")

    def test_release_team_is_no_acceptor(self):
        self.assertEqual(state(11, extra=lambda i: [accept(RM, i)]), "In Abnahme")

    def test_other_topic_is_not_the_acceptance_decision(self):
        self.assertEqual(state(11, extra=lambda i: [accept(QA, i, topic="selection")]), "In Abnahme")

    def test_later_rejection_withdraws(self):
        self.assertEqual(state(12, extra=lambda i: [accept(QA, i, outcome="rejected")]), "In Abnahme")


class Production(unittest.TestCase):
    def test_failing_production_evidence_stays_produktion(self):
        extra = lambda i: [ver("WI-7", ("R-7",), "production", "smoke", "fail", "mon", "w-15")]
        self.assertEqual(state(13, extra=extra), "Produktion")


class Drift(unittest.TestCase):
    def test_unpinned_verification_blocks_every_gate(self):
        extra = lambda i: [ver("WI-7", ("main",), "test", "unit", "pass", "ci", "run-17")]
        self.assertEqual(state(14, extra=extra), "In technischer Beschreibung")

    def test_unpinned_review_is_drift(self):
        log = build(3, lambda i: [ver("WI-7", ("main",), "review", "goal_understood", "pass", "QG1", "r-18")])
        self.assertEqual([v.id for v in drift_check(log)], [VERIFICATION_UNPINNED])


class LatestPerCheck(unittest.TestCase):
    UNIT = staticmethod(lambda: ver("WI-7", (WI, CODE), "test", "unit", "pass", "ci", "run-30"))

    def test_later_pass_on_other_check_does_not_hide_fail(self):
        self.assertFalse(derive(build(8, lambda i: [self.UNIT()]), WI, JWF).verified)

    def test_later_pass_on_same_check_replaces_fail(self):
        again = ver("WI-7", (WI, CODE), "test", "integration", "pass", "ci", "run-9")
        self.assertTrue(derive(build(8, lambda i: [self.UNIT(), again]), WI, JWF).verified)


class StatusWrites(unittest.TestCase):
    def test_hand_set_state_is_refused(self):
        log = build(14)
        for value, vid in (("Geschlossen", STATUS_HAND_SET), ("Abgenommen", ACCEPTANCE_AS_STATUS)):
            with self.assertRaises(Refused) as cm:
                log.append(Event("status", ACTOR, ("WI-7",), (WI,), body={"to": value}))
            self.assertEqual([v.id for v in cm.exception.violations], [vid])


class SpecParity(unittest.TestCase):
    def test_gates_match_spec(self):
        gates = JWF.status_model.gates
        for q, guards in GUARDS.items():
            self.assertEqual([g[1] for g in guards], gates[q]["guards"], q)
            self.assertEqual(REACHES[q], gates[q]["reaches"], q)
            self.assertIn(REACHES[q], JWF.status_model.states)

    def test_acceptance_matches_spec(self):
        acc = JWF.status_model.acceptance
        self.assertEqual(acc["topic"], ACCEPTANCE_TOPIC)
        self.assertEqual(acc["reaches"], "Abgenommen")
        self.assertEqual(load_profile().setting("acceptor_roles"), acc["default_acceptor_roles"])

    def test_default_profile_has_no_roles(self):
        self.assertEqual(load_profile().roles(PO), ())


if __name__ == "__main__":
    unittest.main()
