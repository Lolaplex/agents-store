"""more:subject / more:pinned_against as queryable datoms (schema v3)."""
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from agents_store import connect
from agents_store.contracts import Change
from agents_store.db import SCHEMA_VERSION
from agents_store.grant import INTERNAL_WRAPPER
from agents_store.more import store_bridge
from agents_store.more.events import Event
from agents_store.more.log import EventLog
from agents_store.more.migrate import NOTE, migrate_queryable_refs, planned_changes
from agents_store.more.query import events_about, events_pinned_against, events_pinned_to
from agents_store.store import Store
from tests.more.helpers import FAB, decision, inclusion, verification


def _attr(conn, name):
    return conn.execute(
        "SELECT value_type, cardinality FROM attr WHERE name = ?", (name,)).fetchone()


def _entity(store, title="note"):
    return store.transact([Change(None, "title", title)], wrapper=INTERNAL_WRAPPER).entity


class Vocabulary(unittest.TestCase):
    def test_fresh_db_has_v3_vocabulary(self):
        conn = connect()
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.assertGreaterEqual(SCHEMA_VERSION, 3)
        self.assertEqual(_attr(conn, "more:subject"), ("ref", "many"))
        self.assertEqual(_attr(conn, "more:subject_ptr"), ("text", "many"))
        self.assertEqual(_attr(conn, "more:pinned_against"), ("text", "many"))
        for kind in ("more-event", "decision"):
            opt = json.loads(conn.execute(
                "SELECT optional FROM kind WHERE name = ?", (kind,)).fetchone()[0])
            self.assertIn("more:subject_ptr", opt)
            self.assertIn("more:pinned_against", opt)


class Queries(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.store = Store(self.conn)
        self.log = EventLog(conn=self.conn)

    def tearDown(self):
        self.log.close()
        self.conn.close()

    def test_entity_subject_is_ref_and_external_subject_is_pointer(self):
        note = _entity(self.store)
        ev = self.log.append(Event("verification", FAB, (note, "UC-1"), (f"{note}@1", "UC-1@3"),
                                   body={"method": "review", "result": "pass", "gate": "ci",
                                         "stage": "test", "witness": {"by": FAB}}))
        view = self.store.view(ev.id)
        self.assertEqual(view["more:subject"], (note,))
        self.assertEqual(view["more:subject_ptr"], ("UC-1",))
        self.assertEqual(set(view["more:pinned_against"]), {f"{note}@1", "UC-1@3"})
        # no stub entity for the external subject
        self.assertFalse(self.store.exists("UC-1"))

    def test_find_events_by_subject_entity(self):
        note, other = _entity(self.store, "a"), _entity(self.store, "b")
        e1 = self.log.append(verification(note, f"{note}@1"))
        self.log.append(verification(other, f"{other}@1"))
        e3 = self.log.append(decision(note, f"{note}@2", status="open"))
        self.assertEqual(self.store.find("more:subject", note), [e1.id, e3.id])
        self.assertEqual(events_about(self.store, note), [e1.id, e3.id])

    def test_find_events_by_pointer_subject(self):
        e1 = self.log.append(verification("UC-1", "UC-1@1"))
        self.log.append(verification("UC-10", "UC-10@1"))
        self.assertEqual(events_about(self.store, "UC-1"), [e1.id])
        self.assertEqual(self.store.find("more:subject", "UC-1"), [])

    def test_find_events_pinned_against(self):
        e1 = self.log.append(verification("UC-1", "UC-1@1"))
        e2 = self.log.append(verification("UC-1", "UC-1@2"))
        self.log.append(verification("UC-10", "UC-10@1"))
        e4 = self.log.append(inclusion("UC-1", "UC-1@2", into="release-2026.10"))
        self.assertEqual(events_pinned_against(self.store, "UC-1@2"), [e2.id, e4.id])
        self.assertEqual(events_pinned_against(self.store, "UC-1@9"), [])
        # any version of UC-1, but not UC-10
        self.assertEqual(events_pinned_to(self.store, "UC-1"), [e1.id, e2.id, e4.id])

    def test_pinned_against_baseline_without_version(self):
        ev = self.log.append(Event("verification", FAB, ("SYS",), ("baseline-2026.10",),
                                   body={"method": "smoke", "result": "pass", "gate": "ops",
                                         "stage": "production", "witness": {"by": FAB}}))
        self.assertEqual(events_pinned_against(self.store, "baseline-2026.10"), [ev.id])
        self.assertEqual(events_pinned_to(self.store, "baseline-2026.10"), [ev.id])

    def test_store_find_unknown_attr_and_prefix(self):
        with self.assertRaises(ValueError):
            self.store.find("no:such-attr", "x")
        e1 = self.log.append(verification("UC-1", "UC-1@1"))
        self.assertEqual(self.store.find("more:pinned_against", prefix="UC-1@"), [e1.id])
        self.assertEqual(self.store.find("more:pinned_against", prefix="UC-2@"), [])


_current_changes = store_bridge.event_changes


def _legacy_changes(event, store=None):
    """What the bridge wrote before v3: every subject as text more:subject,
    pinned_against only in the envelope."""
    out = [c for c in _current_changes(event, None)
           if c.a not in ("more:subject_ptr", "more:pinned_against")]
    return out + [Change(None, "more:subject", s) for s in dict.fromkeys(event.subjects)]


class Migration(unittest.TestCase):
    """A v2 DB (text more:subject, no pinned_against datoms) is backfilled."""

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(os.remove, self.path)
        conn = connect(self.path)
        # roll the vocabulary back to v2
        conn.execute("UPDATE attr SET value_type = 'text', doc = 'MORe subject identifiers' "
                     "WHERE name = 'more:subject'")
        conn.execute("DELETE FROM attr WHERE name IN "
                     "('more:subject_ptr', 'more:pinned_against', 'more:said')")
        conn.execute("""UPDATE kind SET optional = '["more:at","more:subject","more:pin","more:body"]'
                        WHERE name = 'more-event'""")
        conn.execute("""UPDATE kind SET optional = '["more:type","more:actor","more:at","more:subject"]'
                        WHERE name = 'decision'""")
        conn.execute("PRAGMA user_version = 2")
        store = Store(conn)
        self.note = _entity(store)
        log = EventLog(conn=conn)
        with patch.object(store_bridge, "event_changes", _legacy_changes), \
                patch.object(store_bridge, "said_changes", lambda *a, **k: []):
            self.v1 = log.append(verification("UC-1", "UC-1@1")).id
            self.v2 = log.append(Event("verification", FAB, (self.note, "UC-1"),
                                       (f"{self.note}@1", "UC-1@2"),
                                       body={"method": "review", "result": "pass", "gate": "ci",
                                             "stage": "test", "witness": {"by": FAB}})).id
            self.d = log.append(decision("UC-1", "UC-1@2", status="open")).id
        log.close()
        self.assertEqual(Store(conn).view(self.v1)["more:subject"], ("UC-1",))
        self.assertIsNone(_attr(conn, "more:pinned_against"))
        conn.close()

    def _txs(self, conn):
        return conn.execute("SELECT id, op, note FROM tx ORDER BY id").fetchall()

    def test_backfill_on_connect(self):
        conn = connect(self.path)
        self.addCleanup(conn.close)
        store = Store(conn)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.assertEqual(_attr(conn, "more:subject"), ("ref", "many"))
        mig = [t for t in self._txs(conn) if t[2] == NOTE]
        self.assertEqual(len(mig), 1)
        self.assertEqual(mig[0][1], "evolve")
        v1 = store.view(self.v1)
        self.assertNotIn("more:subject", v1)
        self.assertEqual(v1["more:subject_ptr"], ("UC-1",))
        self.assertEqual(v1["more:pinned_against"], ("UC-1@1",))
        v2 = store.view(self.v2)
        self.assertEqual(v2["more:subject"], (self.note,))      # entity subject kept as ref
        self.assertEqual(v2["more:subject_ptr"], ("UC-1",))
        # queries work on the migrated DB
        self.assertEqual(events_about(store, "UC-1"), [self.v1, self.v2, self.d])
        self.assertEqual(events_about(store, self.note), [self.v2])
        self.assertEqual(events_pinned_against(store, "UC-1@2"), [self.v2, self.d])
        self.assertEqual(events_pinned_to(store, "UC-1"), [self.v1, self.v2, self.d])
        # history keeps the old text datom (retracted, not deleted)
        old = [d for d in store.history(self.v1) if d.a == "more:subject"]
        self.assertEqual([(d.v, d.added) for d in old], [("UC-1", True), ("UC-1", False)])
        # the envelope chain is untouched
        self.assertEqual(EventLog(conn=conn).verify(), [])

    def test_idempotent(self):
        conn = connect(self.path)
        txs = self._txs(conn)
        datoms = conn.execute("SELECT COUNT(*) FROM datom").fetchone()[0]
        self.assertEqual(planned_changes(Store(conn)), [])
        self.assertIsNone(migrate_queryable_refs(conn))
        conn.close()
        conn = connect(self.path)                       # second connect: no-op
        self.addCleanup(conn.close)
        self.assertIsNone(migrate_queryable_refs(conn))  # explicit re-run: no-op
        self.assertEqual(self._txs(conn), txs)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM datom").fetchone()[0], datoms)

    def test_rerun_resolves_pointer_that_became_entity(self):
        conn = connect(self.path)
        self.addCleanup(conn.close)
        store = Store(conn)
        store.transact([Change(None, "title", "UC-1 moved in")],
                       wrapper=INTERNAL_WRAPPER, entity="UC-1")
        tx = migrate_queryable_refs(conn)
        self.assertIsNotNone(tx)
        self.assertEqual(store.view(self.v1)["more:subject"], ("UC-1",))
        self.assertNotIn("more:subject_ptr", store.view(self.v1))
        self.assertEqual(events_about(store, "UC-1"), [self.v1, self.v2, self.d])
        self.assertIsNone(migrate_queryable_refs(conn))

    def test_failed_backfill_rolls_back(self):
        conn = sqlite3.connect(self.path, isolation_level=None)
        self.addCleanup(conn.close)
        before = self._txs(conn)
        with patch.object(Store, "transact", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                migrate_queryable_refs(conn)
        self.assertFalse(conn.in_transaction)
        self.assertEqual(self._txs(conn), before)
        self.assertEqual(_attr(conn, "more:subject"), ("text", "many"))


if __name__ == "__main__":
    unittest.main()
