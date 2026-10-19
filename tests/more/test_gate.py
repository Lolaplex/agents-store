"""The witness is code that actually ran: these tests spawn real
subprocesses and feed their results through a gate into the log."""
import sys
import unittest

from tests.more.helpers import CI, acceptance, inclusion
from agents_store.more.gate import Gate, run_witness
from agents_store.more.log import EventLog
from agents_store.more.status import derive

R = "RULE-UStVA_Kz84_85"
V1 = f"{R}@1"

VALIDATOR = (
    "import sys\n"
    "rec = dict(a.split('=') for a in sys.argv[1:])\n"
    "sys.exit(0 if ('Kz84' in rec) == ('Kz85' in rec) else 1)\n"
)


class GateDigestsWitness(unittest.TestCase):
    def setUp(self):
        self.log = EventLog()
        self.gate = Gate("ci-validator", "validator", CI)

    def tearDown(self):
        self.log.close()

    def test_passing_witness_becomes_passing_verification(self):
        w = run_witness([sys.executable, "-c", VALIDATOR, "Kz84=100", "Kz85=19.00"])
        self.assertEqual(w.exit_code, 0)
        e = self.log.append(self.gate.digest(w, subject=R, pinned_against=V1, check="pairing"))
        self.assertEqual(e.body["result"], "pass")
        self.assertEqual(e.body["witness"]["exit_code"], 0)
        self.assertEqual(len(e.body["witness"]["stdout_sha256"]), 64)
        self.assertTrue(derive(self.log, V1).verified)

    def test_failing_witness_becomes_failing_verification(self):
        w = run_witness([sys.executable, "-c", VALIDATOR, "Kz84=100"])
        self.assertEqual(w.exit_code, 1)
        e = self.log.append(self.gate.digest(w, subject=R, pinned_against=V1, check="pairing"))
        self.assertEqual(e.body["result"], "fail")
        self.assertFalse(derive(self.log, V1).verified)

    def test_chain_to_done_with_real_witnesses(self):
        ok = run_witness([sys.executable, "-c", VALIDATOR, "Kz84=0", "Kz85=0.00"])
        t = self.log.append(self.gate.digest(ok, subject=R, pinned_against=V1))
        self.log.append(acceptance(R, V1, [t.id]))
        self.log.append(inclusion(R, V1, "REL-2026.09"))
        smoke = run_witness([sys.executable, "-c", "pass"])
        self.log.append(Gate("prod-smoke", "smoke", CI).digest(
            smoke, subject=R, pinned_against="REL-2026.09", stage="production"))
        d = derive(self.log, V1)
        self.assertTrue(d.done)
        self.assertEqual(d.state, "proven_in_production")


if __name__ == "__main__":
    unittest.main()
