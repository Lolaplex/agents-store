"""MORe event log co-located with the agents-store entity store."""
import sqlite3
import unittest
from unittest.mock import patch

from agents_store import connect
from agents_store.contracts import Change, Refusal
from agents_store.more import store_bridge
from agents_store.more.store_bridge import StoreWriteRefused
from agents_store.more.events import Event
from agents_store.more.log import EventLog, Refused
from agents_store.more.status import derive
from agents_store.store import Store
from tests.more.helpers import FAB, adr, decision, verification


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
        # RULE-1 is not a store entity: it is kept as a pointer, not a ref
        self.assertEqual(view["more:subject_ptr"], ("RULE-1",))
        self.assertNotIn("more:subject", view)
        self.assertEqual(view["more:pinned_against"], ("RULE-1@1",))
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

    def test_writes_go_through_transact_in_one_tx(self):
        with patch.object(Store, "transact", autospec=True, side_effect=Store.transact) as spy:
            ev = self.log.append(adr("DEC-9", "DEC-9@1", "Title", "Text", "Which?"))
        self.assertEqual(spy.call_count, 1)
        kwargs = spy.call_args.kwargs
        self.assertEqual(kwargs["entity"], ev.id)
        self.assertEqual(kwargs["wrapper"], "store")
        tx = self.conn.execute(
            "SELECT id, op, agent, wrapper, note FROM tx").fetchall()
        self.assertEqual(len(tx), 1)
        tx_id, op, agent, wrapper, note = tx[0]
        self.assertEqual((op, agent, wrapper, note), ("assert", ev.actor, "store", "more:decision"))
        created = self.conn.execute(
            "SELECT created_tx FROM entity WHERE id = ?", (ev.id,)).fetchone()[0]
        self.assertEqual(created, tx_id)
        hist = self.store.history(ev.id)
        self.assertEqual({d.tx for d in hist}, {tx_id})
        attrs = {d.a for d in hist}
        self.assertEqual(attrs, {"more:type", "more:actor", "more:at", "more:body",
                                 "more:subject_ptr", "more:pinned_against", "more:pin",
                                 "title", "body", "more:topic"})
        self.assertEqual(self.store.view(ev.id)["more:pin"], (f"{ev.id}@{tx_id}",))

    def test_store_refusal_rolls_back_whole_event(self):
        real = store_bridge.event_changes
        bad = lambda ev, store=None: real(ev, store) + [Change(None, "no:such-attr", "x")]
        with patch.object(store_bridge, "event_changes", bad):
            with self.assertRaises(StoreWriteRefused):
                self.log.append(verification("RULE-1", "RULE-1@1"))
        for table in ("event", "entity", "datom", "tx", "refusal", "more_refusal"):
            self.assertEqual(
                self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)

    def test_lineage_edge_shares_event_tx(self):
        d = self.log.append(decision("DEC-1", "DEC-1@1", status="open"))
        sup = self.log.append(Event(
            "supersession", FAB, ("DEC-1",), ("DEC-1@1",),
            supersedes=(d.id,), reason="r"))
        edge_tx = self.conn.execute(
            "SELECT tx FROM lineage WHERE child = ?", (sup.id,)).fetchone()[0]
        self.assertEqual({x.tx for x in self.store.history(sup.id)}, {edge_tx})


if __name__ == "__main__":
    unittest.main()
