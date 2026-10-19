import tempfile
import unittest
from pathlib import Path

from tests.more.helpers import CI, FAB, Event, decision, verification
from agents_store.more.checks import EVENT_MUTATED
from agents_store.more.log import EventLog, Refused


class AppendOnly(unittest.TestCase):
    def setUp(self):
        self.log = EventLog()

    def tearDown(self):
        self.log.close()

    def test_append_assigns_minted_id_seq_and_chain(self):
        a = self.log.append(verification("RULE-1", "RULE-1@1"))
        b = self.log.append(decision("RULE-1", "RULE-1@1", status="open"))
        self.assertEqual(len(a.id), 26)
        self.assertNotEqual(a.id, b.id)
        self.assertEqual((a.seq, b.seq), (1, 2))
        self.assertEqual(a.prev, "")
        self.assertEqual(b.prev, a.digest)
        self.assertEqual(self.log.verify(), [])

    def test_round_trip(self):
        a = self.log.append(verification("RULE-1", "RULE-1@1"))
        got = self.log.get(a.id)
        self.assertEqual(got, a)
        self.assertEqual([e.id for e in self.log.events("RULE-1")], [a.id])
        self.assertEqual(list(self.log.events("OTHER")), [])

    def test_no_update_no_delete(self):
        self.log.append(verification("RULE-1", "RULE-1@1"))
        with self.assertRaisesRegex(Exception, "append-only"):
            self.log.conn.execute("UPDATE event SET actor = 'x'")
        with self.assertRaisesRegex(Exception, "append-only"):
            self.log.conn.execute("DELETE FROM event")
        with self.assertRaisesRegex(Exception, "append-only"):
            self.log.conn.execute("DELETE FROM event_subject")

    def test_refusal_is_recorded_and_raised(self):
        with self.assertRaises(Refused) as cm:
            self.log.append(Event("status", FAB, ("UC-1",), ("UC-1@1",), body={"to": "Geschlossen"}))
        self.assertEqual([v.id for v in cm.exception.violations], ["status_hand_set"])
        self.assertEqual(self.log.refusals()[0][0], "status_hand_set")
        self.assertEqual(list(self.log.events()), [])

    def test_caller_body_is_not_shared(self):
        body = {"status": "open"}
        e = Event("decision", FAB, ("DEC-1",), ("UC-1@1",), body=body)
        body["status"] = "decided"
        self.assertEqual(e.body["status"], "open")

    def test_persists_to_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "events.db"
            log = EventLog(p)
            a = log.append(verification("RULE-1", "RULE-1@1"))
            log.close()
            log = EventLog(p)
            self.assertEqual(log.get(a.id), a)
            self.assertEqual(log.verify(), [])
            log.close()


class Tamper(unittest.TestCase):
    """Edits made below the triggers (raw access to the file) are caught by
    the hash chain as event_mutated."""

    def setUp(self):
        self.log = EventLog()
        self.a = self.log.append(verification("RULE-1", "RULE-1@1", result="fail"))
        self.b = self.log.append(verification("RULE-1", "RULE-1@1"))
        self.log.conn.execute("DROP TRIGGER event_no_update")
        self.log.conn.execute("DROP TRIGGER event_no_delete")

    def tearDown(self):
        self.log.close()

    def test_changed_content(self):
        row = self.log.conn.execute("SELECT envelope FROM event WHERE seq = 1").fetchone()[0]
        self.log.conn.execute("UPDATE event SET envelope = ? WHERE seq = 1",
                              (row.replace('"fail"', '"pass"'),))
        ids = [v.id for v in self.log.verify()]
        self.assertIn(EVENT_MUTATED, ids)

    def test_removed_event(self):
        self.log.conn.execute("DELETE FROM event WHERE seq = 1")
        vs = self.log.verify()
        self.assertEqual([v.id for v in vs], [EVENT_MUTATED])
        self.assertIn("chain broken", vs[0].detail)


if __name__ == "__main__":
    unittest.main()
