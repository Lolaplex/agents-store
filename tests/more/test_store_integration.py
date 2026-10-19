"""MORe event log co-located with the agents-store entity store."""
import sqlite3
import unittest
from unittest.mock import patch

from agents_store import connect
from agents_store.contracts import Refusal
from agents_store.more.events import Event
from agents_store.more.log import EventLog, Refused
from agents_store.more.status import derive
from agents_store.store import Store
from tests.more.helpers import FAB, decision, verification


class StoreBackedLog(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.store = Store(self.conn)
        self.log = EventLog(conn=self.conn)

    def tearDown(self):
        self.log.close()
        self.conn.close()

    def test_admitted_event_is_entity_with_same_id(self):
        ev = self.log.append(verification("RULE-1", "RULE-1@1"))
        self.assertTrue(self.store.exists(ev.id))
        view = self.store.view(ev.id)
        self.assertEqual(view["more:type"], "verification")
        self.assertEqual(view["more:actor"], ev.actor)
        self.assertIn("RULE-1", view["more:subject"])
        pin = view["more:pin"]
        self.assertEqual(len(pin), 1)
        self.assertRegex(pin[0], rf"^{ev.id}@\d+$")
        row = self.conn.execute("SELECT id FROM event WHERE id = ?", (ev.id,)).fetchone()
        self.assertIsNotNone(row)

    def test_refused_writes_only_more_refusal(self):
        before = self.conn.execute("SELECT COUNT(*) FROM entity").fetchone()[0]
        with self.assertRaises(Refused):
            self.log.append(Event("status", FAB, ("UC-1",), ("UC-1@1",), body={"to": "Geschlossen"}))
        after = self.conn.execute("SELECT COUNT(*) FROM entity").fetchone()[0]
        self.assertEqual(before, after)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM datom").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM event").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM more_refusal").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM refusal").fetchone()[0], 0)

    def test_mid_write_failure_rolls_back(self):
        with patch("agents_store.more.log.materialize_lineage", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.log.append(verification("RULE-1", "RULE-1@1"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM event").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM entity").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM datom").fetchone()[0], 0)

    def test_verify_clean_and_update_caught(self):
        self.log.append(verification("RULE-1", "RULE-1@1", result="fail"))
        self.log.append(verification("RULE-1", "RULE-1@1"))
        self.assertEqual(self.log.verify(), [])
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            self.log.conn.execute("UPDATE event SET actor = 'tampered'")
        self.log.conn.execute("DROP TRIGGER event_no_update")
        row = self.log.conn.execute("SELECT envelope FROM event WHERE seq = 1").fetchone()[0]
        self.log.conn.execute(
            "UPDATE event SET envelope = ? WHERE seq = 1",
            (row.replace('"fail"', '"pass"'),))
        self.assertTrue(self.log.verify())

    def test_supersession_inactive_in_fold_but_readable_in_history(self):
        open_d = self.log.append(decision("DEC-1", "DEC-1@1", status="open"))
        self.log.append(decision("DEC-1", "DEC-1@1", status="decided"))
        sup = self.log.append(Event(
            "supersession", FAB, ("DEC-1",), ("DEC-1@1",),
            supersedes=(open_d.id,), reason="supersede open draft"))
        d = derive(self.log, "DEC-1@1")
        self.assertNotIn(open_d.id, d.open_decisions)
        self.assertTrue(self.store.history(open_d.id))
        edge = self.conn.execute(
            "SELECT kind FROM lineage WHERE child = ? AND parent = ?",
            (sup.id, open_d.id),
        ).fetchone()
        self.assertEqual(edge[0], "wasRevisionOf")

    def test_store_refusal_independent_of_more_refusal(self):
        self.store.record_refusal(Refusal(wrapper="t", reason="probe"))
        with self.assertRaises(Refused):
            self.log.append(Event("status", FAB, ("UC-1",), ("UC-1@1",), body={"to": "x"}))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM refusal").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM more_refusal").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
