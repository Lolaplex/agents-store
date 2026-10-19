"""Derived status over the ELSTER rule UStVA_Kz84_85_Gemeinsam (§7.3)."""
import unittest

from tests.more.helpers import CI, FAB, Event, acceptance, decision, inclusion, verification
from agents_store.more.log import EventLog
from agents_store.more.profile import load_profile
from agents_store.more.status import derive, drift_check

R = "RULE-UStVA_Kz84_85"
V1 = f"{R}@1"
V2 = f"{R}@2"
REL = "REL-2026.09"


def vids(vs):
    return [v.id for v in vs]


class Chain(unittest.TestCase):
    def setUp(self):
        self.log = EventLog()
        self.a = self.log.append

    def tearDown(self):
        self.log.close()

    def d(self, ref=V1, **kw):
        return derive(self.log, ref, **kw)

    def full_chain(self):
        t = self.a(verification(R, V1))
        self.a(acceptance(R, V1, [t.id]))
        self.a(inclusion(R, V1, REL))
        p = self.a(verification(R, REL, stage="production"))
        return t, p

    def test_empty_log_reaches_nothing(self):
        d = self.d()
        self.assertIsNone(d.state)
        self.assertFalse(d.done)

    def test_full_chain_in_order(self):
        self.full_chain()
        d = self.d()
        self.assertEqual((d.verified, d.accepted, d.released, d.proven_in_production),
                         (True, True, True, True))
        self.assertTrue(d.done)
        self.assertEqual(d.state, "proven_in_production")
        self.assertEqual(d.violations, ())
        self.assertEqual(drift_check(self.log), [])

    def test_states_step_by_step(self):
        t = self.a(verification(R, V1))
        self.assertEqual(self.d().state, "verified")
        self.a(acceptance(R, V1, [t.id]))
        self.assertEqual(self.d().state, "accepted")
        self.assertFalse(self.d().done)
        self.a(inclusion(R, V1, REL))
        self.assertEqual(self.d().state, "released")
        self.assertTrue(self.d().done)

    def test_verification_on_another_version_counts_for_nothing(self):
        t = self.a(verification(R, V2))
        self.a(acceptance(R, V1, [t.id]))
        self.a(inclusion(R, V1, REL))
        d = self.d()
        self.assertFalse(d.verified)
        self.assertFalse(d.done)
        self.assertTrue(self.d(V2).verified)

    def test_unpinned_verification_is_unmeasured(self):
        self.a(verification(R, None))
        self.a(verification(R, R))
        d = self.d()
        self.assertFalse(d.verified)
        self.assertEqual(vids(d.violations), ["verification_unpinned", "verification_unpinned"])
        self.assertEqual(vids(drift_check(self.log)), ["verification_unpinned", "verification_unpinned"])

    def test_verification_without_gate_or_witness_is_not_gate_accepted(self):
        self.a(verification(R, V1, gate=None))
        self.a(verification(R, V1, witness=False))
        d = self.d()
        self.assertFalse(d.verified)
        self.assertTrue(any("not gate-accepted" in r for r in d.reasons))

    def test_latest_failing_check_blocks(self):
        self.a(verification(R, V1))
        self.a(verification(R, V1, result="fail"))
        self.assertFalse(self.d().verified)
        self.a(verification(R, V1))
        self.assertTrue(self.d().verified)

    def test_inclusion_without_acceptance_is_not_done(self):
        self.a(verification(R, V1))
        self.a(inclusion(R, V1, REL))
        d = self.d()
        self.assertTrue(d.verified)
        self.assertFalse(d.done)
        self.assertTrue(any("not accepted" in r for r in d.reasons))

    def test_done_without_acceptance_when_profile_says_so(self):
        p = load_profile()
        p = type(p)(**{**p.__dict__, "settings": {**p.settings, "done_requires_acceptance": False}})
        self.a(verification(R, V1))
        self.a(inclusion(R, V1, REL))
        self.assertTrue(derive(self.log, V1, p).done)

    def test_acceptance_must_link_passing_tests_of_that_version(self):
        other = self.a(verification(R, V2))
        self.a(verification(R, V1))
        self.a(acceptance(R, V1, [other.id]))
        self.assertFalse(self.d().accepted)
        self.a(acceptance(R, V1, []))
        self.assertFalse(self.d().accepted)

    def test_rejection_after_acceptance_wins(self):
        t = self.a(verification(R, V1))
        self.a(acceptance(R, V1, [t.id]))
        self.a(acceptance(R, V1, [t.id], outcome="rejected"))
        self.assertFalse(self.d().accepted)

    def test_production_evidence_before_release(self):
        t = self.a(verification(R, V1))
        self.a(acceptance(R, V1, [t.id]))
        early = self.a(verification(R, REL, stage="production"))
        self.a(inclusion(R, V1, REL))
        d = self.d()
        self.assertTrue(d.released)
        self.assertFalse(d.proven_in_production)
        self.assertEqual(vids(d.violations), ["production_evidence_before_release"])
        self.assertEqual(d.violations[0].event_id, early.id)
        self.assertEqual(vids(drift_check(self.log)), ["production_evidence_before_release"])
        self.a(verification(R, REL, stage="production"))
        self.assertTrue(self.d().proven_in_production)

    def test_production_evidence_needs_released(self):
        self.a(verification(R, V1))
        self.a(inclusion(R, V1, REL))
        self.a(verification(R, REL, stage="production"))
        d = self.d()
        self.assertFalse(d.proven_in_production)
        self.assertEqual(d.violations, ())

    def test_overrule_withdraws_a_verification(self):
        t, p = self.full_chain()
        self.a(Event("overrule", FAB, (R,), (V1,), supersedes=(t.id,),
                     reason="ran against the wrong fixture", signals=("belief:fixture-wrong",)))
        d = self.d()
        self.assertFalse(d.verified)
        self.assertFalse(d.done)
        self.assertFalse(d.proven_in_production)
        self.assertIsNotNone(self.log.get(t.id))

    def test_open_decision_is_reported_and_closed_by_supersession(self):
        o = self.a(decision(R, V1, status="open", question="Berichtigung: keep explicit 0.00?"))
        self.assertEqual(self.d().open_decisions, (o.id,))
        self.a(Event("decision", FAB, (R,), (V1,), supersedes=(o.id,),
                     body={"status": "decided", "decided_by": FAB, "outcome": "keep 0.00"}))
        self.a(Event("supersession", FAB, (R,), (V1,), supersedes=(o.id,), body={"kind": "evolve"}))
        self.assertEqual(self.d().open_decisions, ())

    def test_no_status_is_ever_stored(self):
        self.full_chain()
        for (env,) in self.log.conn.execute("SELECT envelope FROM event"):
            for word in ('"released"', '"done"', '"proven_in_production"', '"accepted":'):
                self.assertNotIn(word, env)

    def test_derive_needs_a_version(self):
        with self.assertRaises(ValueError):
            derive(self.log, R)


if __name__ == "__main__":
    unittest.main()
