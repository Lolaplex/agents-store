"""ADR decision artifacts and latest_live_decision resolution."""
import unittest

from agents_store import connect
from agents_store.kinds import of
from agents_store.more.decisions import latest_live_decision
from agents_store.more.events import Event
from agents_store.more.log import EventLog, Refused
from agents_store.more.status import derive
from agents_store.store import Store
from tests.more.helpers import FAB, adr, decision


class DecisionArtifact(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.store = Store(self.conn)
        self.log = EventLog(conn=self.conn)

    def tearDown(self):
        self.log.close()
        self.conn.close()

    def test_create_decision_artifact_kind(self):
        ev = self.log.append(adr(
            "ADR-1", "ADR-1@1",
            title="Use SQLite",
            body="We store events and entities in one file.",
            topic="storage",
        ))
        view = self.store.view(ev.id)
        self.assertEqual(view["title"], "Use SQLite")
        self.assertEqual(view["body"], "We store events and entities in one file.")
        self.assertEqual(view["more:topic"], "storage")
        self.assertIn("decision", of(self.conn, ev.id))

    def test_supersede_returns_new_helper_old_inactive_but_in_history(self):
        first = self.log.append(adr(
            "ADR-1", "ADR-1@1", title="v1", body="first", topic="storage",
        ))
        second = self.log.append(adr(
            "ADR-1", "ADR-1@1", title="v2", body="second", topic="storage",
        ))
        self.log.append(Event(
            "supersession", FAB, ("ADR-1",), ("ADR-1@1",),
            supersedes=(first.id,), reason="revise ADR"))
        live = latest_live_decision(self.log, self.store, subject_ref="ADR-1@1", topic="storage")
        self.assertIsNotNone(live)
        self.assertEqual(live.event.id, second.id)
        self.assertEqual(live.event.body["title"], "v2")
        d = derive(self.log, "ADR-1@1")
        self.assertNotIn(first.id, d.open_decisions)
        self.assertTrue(self.store.history(first.id))
        self.assertEqual(self.store.view(first.id)["title"], "v1")

    def test_pinned_resolution_at_older_tx(self):
        first = self.log.append(adr(
            "ADR-1", "ADR-1@1", title="v1", body="first", topic="storage",
        ))
        tx_first = self.conn.execute(
            "SELECT created_tx FROM entity WHERE id = ?", (first.id,)).fetchone()[0]
        self.log.append(adr(
            "ADR-1", "ADR-1@1", title="v2", body="second", topic="storage",
        ))
        self.log.append(Event(
            "supersession", FAB, ("ADR-1",), ("ADR-1@1",),
            supersedes=(first.id,), reason="revise ADR"))
        current = latest_live_decision(
            self.log, self.store, subject_ref="ADR-1@1", topic="storage")
        self.assertEqual(current.event.body["title"], "v2")
        older = latest_live_decision(
            self.log, self.store, subject_ref="ADR-1@1", topic="storage", at_tx=tx_first)
        self.assertEqual(older.event.id, first.id)
        self.assertEqual(older.pin, f"{first.id}@{tx_first}")
        self.assertEqual(self.store.view(first.id, tx=tx_first)["title"], "v1")

    def test_refused_invalid_decision_writes_nothing(self):
        n_ent = self.conn.execute("SELECT COUNT(*) FROM entity").fetchone()[0]
        bad = Event("decision", FAB, ("ADR-1",), ("ADR-1@1",),
                    body={"status": "decided", "title": "bad", "body": "x", "topic": "storage"})
        with self.assertRaises(Refused):
            self.log.append(bad)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM entity").fetchone()[0], n_ent)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM event").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
