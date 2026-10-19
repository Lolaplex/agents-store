import unittest

from tests.more.helpers import CI, FAB, Event, acceptance, decision, verification
from agents_store.more.checks import check_event
from agents_store.more.profile import load_profile

P = load_profile()


def ids(e):
    return [v.id for v in check_event(e, P)]


class StatusIsNeverWritten(unittest.TestCase):
    def test_status_event_type(self):
        self.assertEqual(ids(Event("set_status", FAB, ("UC-1",), ("UC-1@1",), body={"to": "Done"})),
                         ["status_hand_set"])

    def test_jwf_state_written_into_body(self):
        e = Event("inclusion", CI, ("UC-1",), ("UC-1@1",), body={"into": "REL-1", "status": "Geschlossen"})
        self.assertEqual(ids(e), ["status_hand_set"])

    def test_nested_status_key(self):
        e = verification("UC-1", "UC-1@1", body={"meta": {"jira_status": "Produktion"}})
        self.assertEqual(ids(e), ["status_hand_set"])

    def test_decision_own_status_is_allowed(self):
        self.assertEqual(ids(decision("DEC-1", "UC-1@1", status="open")), [])
        self.assertEqual(ids(decision("DEC-1", "UC-1@1")), [])


class AcceptanceIsADecision(unittest.TestCase):
    def test_acceptance_written_as_status(self):
        e = Event("transition", FAB, ("UC-1",), ("UC-1@1",), body={"to": "Abgenommen"})
        self.assertEqual(ids(e), ["acceptance_as_status"])

    def test_acceptance_in_body_status(self):
        e = Event("inclusion", CI, ("UC-1",), ("UC-1@1",), body={"into": "REL-1", "state": "accepted"})
        self.assertEqual(ids(e), ["acceptance_as_status"])

    def test_acceptance_as_verification_result(self):
        self.assertEqual(ids(verification("UC-1", "UC-1@1", result="accepted")), ["acceptance_as_status"])

    def test_acceptance_as_decision_is_fine(self):
        self.assertEqual(ids(acceptance("UC-1", "UC-1@1", ["X"])), [])

    def test_acceptance_needs_outcome(self):
        self.assertEqual(ids(decision("UC-1", "UC-1@1", kind="acceptance")), ["envelope_invalid"])


class EnvelopeRules(unittest.TestCase):
    def test_unknown_type(self):
        self.assertEqual(ids(Event("comment", FAB, ("UC-1",), ("UC-1@1",))), ["event_type_unknown"])

    def test_unpinned_verification_is_not_refused(self):
        # recorded as an unmeasured claim; reported by drift_check instead
        self.assertEqual(ids(verification("UC-1", None)), [])
        self.assertEqual(ids(verification("UC-1", "UC-1")), [])

    def test_inclusion_must_pin_versions(self):
        self.assertEqual(ids(Event("inclusion", CI, ("UC-1",), ("UC-1",), body={"into": "REL-1"})),
                         ["event_unpinned"])
        self.assertEqual(ids(Event("inclusion", CI, ("UC-1",), (), body={"into": "REL-1"})),
                         ["event_unpinned"])

    def test_supersession_unlinked(self):
        e = Event("supersession", FAB, ("UC-1",), ("UC-1@1",), body={"kind": "evolve"})
        self.assertEqual(ids(e), ["supersession_unlinked"])

    def test_overrule_rules(self):
        e = Event("overrule", FAB, ("UC-1",), ("UC-1@1",), supersedes=("EV1",), signals=("acknowledged-none",))
        self.assertEqual(sorted(ids(e)), ["overrule_unreasoned", "overrule_without_signal"])
        ok = Event("overrule", FAB, ("UC-1",), ("UC-1@1",), supersedes=("EV1",),
                   reason="test was run on the wrong fixture", signals=("belief:fixture-wrong",))
        self.assertEqual(ids(ok), [])

    def test_move_cannot_change_content(self):
        body = {"custody_from": "koru-libs", "custody_to": "koru",
                "content_hash_before": "aa", "content_hash_after": "bb"}
        self.assertEqual(ids(Event("move", FAB, ("ART-1",), ("ART-1@3",), body=body)), ["move_changes_content"])
        body["content_hash_after"] = "aa"
        self.assertEqual(ids(Event("move", FAB, ("ART-1",), ("ART-1@3",), body=body)), [])


if __name__ == "__main__":
    unittest.main()
