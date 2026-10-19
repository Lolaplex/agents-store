"""Mirror of kernel/Cutover/Examples.lean and the cutover-check output
(kernel/Main.lean), plus parity with the spec's cutover event_mapping."""
import json
import unittest
from dataclasses import replace

from agents_store.more import cutover as c
from agents_store.more.cutover import (AdmitError, Authority, Baseline, CutoverEvent as E,
                                 ForecastEntry as F, Interval as I, ReflowPolicy,
                                 ReflowProposal, Task)
from agents_store.more.log import EventLog
from agents_store.more.profile import SPEC_PATH, load_profile
from agents_store.more.status import derive, drift_check

P = load_profile()
REPLICATION = Task(1, (), I(1000, 2000))
DNS = Task(2, (1,), I(2000, 3000))
SMOKE = Task(3, (2,), I(3000, 5000))
BASELINE = Baseline(1, (REPLICATION, DNS, SMOKE), ((1, 2), (2, 3)))
AUTH = Authority(("commander",))
PROPOSAL = ReflowProposal(7, 1, (F(1, I(1000, 2500)), F(2, I(2500, 3500)), F(3, I(3500, 5500))),
                          "replication late")
LOG = [E(9, "baselinePublished", revision=1),
       E(10, "actualStarted", task=1, at=1000),
       E(11, "actualFinished", task=1, at=2500),
       E(12, "reflowProposed", proposal=PROPOSAL),
       E(13, "reflowApproved", reflow=7, approver="commander")]


def open_decisions(events, subject):
    inactive = {s for e in events for s in e.supersedes}
    return [e.id for e in events if subject in e.subjects and e.id not in inactive
            and e.type == "decision" and e.body.get("status") == "open"]


class Examples(unittest.TestCase):
    def test_validate_and_project(self):
        self.assertTrue(c.log_well_formed(BASELINE, LOG))
        st = c.validate(AUTH, BASELINE, LOG)
        self.assertEqual(st.forecast_revision, 7)
        self.assertEqual(st.statuses, [(1, "completed"), (2, "ready"), (3, "planned")])

    def test_reflow(self):
        r = c.run_reflow(AUTH, BASELINE, LOG, ReflowPolicy(True, False), 2500)
        self.assertEqual(r.conflicts, [])
        self.assertEqual(r.affected, [2, 3])
        self.assertTrue(c.schedule_invariants(BASELINE, r.forecast))
        self.assertEqual({fe.task for fe in r.forecast}, set(BASELINE.task_ids()))

    def test_duplicate_refused(self):
        with self.assertRaisesRegex(AdmitError, "duplicate_id"):
            c.admit_event(AUTH, BASELINE, LOG, E(10, "blocked", task=2, reason="x"))
        with self.assertRaisesRegex(AdmitError, "unknown_approver"):
            c.admit_event(AUTH, BASELINE, LOG, E(14, "reflowApproved", reflow=7, approver="mallory"))

    def test_corrected_approval_falls_back(self):
        log = LOG + [E(14, "corrected", old=13, replacement=12)]
        self.assertEqual(c.project(AUTH, BASELINE, log).forecast_revision, 1)

    def test_congruence(self):
        self.assertEqual(c.project(AUTH, BASELINE, LOG), c.project(AUTH, BASELINE, LOG[::-1]))

    def test_cycle_is_a_conflict(self):
        b = Baseline(1, (Task(1, (2,), I(0, 1)), Task(2, (1,), I(0, 1))), ((1, 2), (2, 1)))
        self.assertEqual(c.reflow(b, [], 0, []).conflicts, [("cycle", 1), ("cycle", 2)])


class AsMoreProfile(unittest.TestCase):
    def setUp(self):
        self.more = c.to_more_log(AUTH, BASELINE, LOG)

    def test_types_and_ids(self):
        self.assertEqual([(e.id, e.type) for e in self.more],
                         [("18", "inclusion"), ("20", "verification"), ("22", "verification"),
                          ("24", "decision"), ("26", "decision"), ("27", "supersession")])

    def test_admitted_as_is(self):
        log = EventLog()
        for e in self.more:
            log.append(replace(e, id=None, seq=None))
        self.assertEqual(len(list(log.events())), 6)

    def test_drift_clash_fixed(self):
        self.assertEqual(self.more[0].subjects, ("cutover", "task:1", "task:2", "task:3"))
        self.assertEqual(drift_check(self.more, P), [])
        self.assertEqual(open_decisions(self.more, "reflow:7"), [])
        self.assertFalse(derive(self.more, "task:1@1", P).proven_in_production)

    def test_unauthorized_approval_closes_nothing(self):
        log = LOG[:4] + [E(13, "reflowApproved", reflow=7, approver="mallory")]
        self.assertEqual(open_decisions(c.to_more_log(AUTH, BASELINE, log), "reflow:7"), ["24"])
        self.assertEqual(c.project(AUTH, BASELINE, log).forecast_revision, 1)

    def test_superseded_ids_are_more_inactive(self):
        for log in (LOG, LOG + [E(14, "corrected", old=13, replacement=12)]):
            inactive = sorted(s for e in c.to_more_log(AUTH, BASELINE, log) for s in e.supersedes)
            self.assertEqual(inactive, sorted(c.more_id(x) for x in c.superseded_ids(AUTH, log)))


class SpecParity(unittest.TestCase):
    def test_event_mapping_matches_classify(self):
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        cut = spec["layers"]["profiles"]["cutover"]
        self.assertEqual(c.kind_types(), cut["event_mapping"])
        self.assertEqual(set(c.STATUSES), set(
            cut["status"].split("(")[1].split(")")[0].replace(" ", "").split(",")))


if __name__ == "__main__":
    unittest.main()
