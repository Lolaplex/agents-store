"""MORe SAIDs: KERI/CESR Blake3-256 content digests bound to the event name."""
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import blake3

from agents_store import connect
from agents_store.contracts import Change
from agents_store.db import SCHEMA_VERSION
from agents_store.grant import INTERNAL_WRAPPER
from agents_store.more import said as S
from agents_store.more import store_bridge
from agents_store.more.events import Event
from agents_store.more.log import EventLog
from agents_store.more.migrate import NOTE_SAID, SaidMismatch, migrate_said, planned_said_changes
from agents_store.more.query import (events_by_said, events_pinned_against, events_pinned_to,
                                     resolve)
from agents_store.store import Store
from tests.more.helpers import CI, FAB, verification

# Vectors from WebOfTrust/keripy tests/core/test_coring.py
# (main @ a6866a31e5b41b5d404d74554d5616ef66dba873): test_diger and test_saider.
KERIPY_DIGER_SER = b"abcdefghijklmnopqrstuvwxyz0123456789"
KERIPY_DIGER_QB64 = "ELC5L3iBVD77d_MYbYGGCUQgqQBju1o4x1Ud-z2sL-ux"
KERIPY_SAIDER_SER = (
    b'{"$id": "", "$schema": '
    b'"http://json-schema.org/draft-07/schema#", "type": "object", "properties": {"a": {"type": "string"}, '
    b'"b": {"type": "number"}, "c": {"type": "string", "format": "date-time"}}}')
KERIPY_SAIDER_SAID = "EMRvS7lGxc1eDleXBkvSHkFs8vUrslRcla6UXOJdcczw"

# Official BLAKE3 test vectors (BLAKE3-team/BLAKE3 test_vectors.json, input_len 0)
# and the 'abc' digest from the reference implementation.
BLAKE3_EMPTY = "af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262"
BLAKE3_ABC = "6437b3ac38465133ffb63b75273a8db548c558465d79db03fd359c6cd5bd9d85"

# Event SAD vector, cross-checked with keripy 1.3.6:
#   Saider.saidify(sad=event_sad(EV, NAME_A), code=MtrDex.Blake3_256, label="d")
# returns the same qb64, and Saider(qb64=...).verify(sad, prefixed=True) holds.
NAME_A = "01JBQ7Z8X0000000000000000A"
NAME_B = "01JBQ7Z8X0000000000000000B"
SAID_A = "EMueSTOaPDJXcGf7siEtOJis2cOU74Q-JsJQYokahFRJ"
SAID_B = "EOh3yHEfAGuZRw6Pd2e0NNfYKCKASenQiq0NfN_uSycr"
SER_A = (
    '{"d":"############################################","i":"01JBQ7Z8X0000000000000000A",'
    '"type":"verification","actor":"did:web:lolaplex.com:ci","at":"2026-10-27T00:00:00.000000Z",'
    '"pinned_against":["UC-1@3"],"subjects":["UC-1"],"reason":null,"supersedes":[],"signals":[],'
    '"provenance":null,"body":{"gate":"ci","method":"unittest","note":"ä ✓","result":"pass",'
    '"stage":"test","witness":{"command":["python","-m","unittest"],"exit_code":0}}}')


def _vector_event(**kw):
    body = {"result": "pass", "method": "unittest", "gate": "ci", "stage": "test",
            "witness": {"exit_code": 0, "command": ["python", "-m", "unittest"]}, "note": "ä ✓"}
    return Event("verification", CI, ("UC-1",), ("UC-1@3",),
                 at="2026-10-27T00:00:00.000000Z", body=body, **kw)


class Cesr(unittest.TestCase):
    def test_blake3_is_the_real_blake3(self):
        self.assertEqual(blake3.blake3(b"").hexdigest(), BLAKE3_EMPTY)
        self.assertEqual(blake3.blake3(b"abc").hexdigest(), BLAKE3_ABC)

    def test_keripy_diger_vector(self):
        self.assertEqual(S.digest(KERIPY_DIGER_SER), KERIPY_DIGER_QB64)

    def test_keripy_saider_vector(self):
        sad = json.loads(KERIPY_SAIDER_SER)
        said, out = S.saidify(sad, label="$id")
        self.assertEqual(said, KERIPY_SAIDER_SAID)
        self.assertEqual(out["$id"], said)
        self.assertTrue(S.verify(out, label="$id"))
        self.assertEqual(sad["$id"], "")  # input not mutated

    def test_qb64_shape(self):
        self.assertEqual(len(S.PLACEHOLDER), 44)
        q = S.qb64_blake3_256(b"\xff" * 32)
        self.assertEqual(len(q), 44)
        self.assertEqual(q[0], "E")
        self.assertTrue(S.is_said(q))
        self.assertTrue(S.is_said(KERIPY_DIGER_QB64))
        for bad in ("", "E" * 43, "F" + KERIPY_DIGER_QB64[1:], "EZ" + KERIPY_DIGER_QB64[2:],
                    KERIPY_DIGER_QB64[:-1] + "=", "01JBQ7Z8X0000000000000000A", "3"):
            self.assertFalse(S.is_said(bad), bad)
        with self.assertRaises(ValueError):
            S.qb64_blake3_256(b"\x00" * 31)


class EventSaid(unittest.TestCase):
    def test_serialization_is_fixed(self):
        self.assertEqual(S.dumps(S.event_sad(_vector_event(), NAME_A)).decode("utf-8"), SER_A)

    def test_event_vector(self):
        self.assertEqual(S.event_said(_vector_event(), NAME_A), SAID_A)

    def test_name_is_hashed(self):
        self.assertEqual(S.event_said(_vector_event(), NAME_B), SAID_B)
        self.assertNotEqual(SAID_A, SAID_B)

    def test_body_key_order_does_not_matter(self):
        ev = _vector_event()
        rev = Event(ev.type, ev.actor, ev.subjects, ev.pinned_against, at=ev.at,
                    body=dict(reversed(list(ev.body.items()))))
        self.assertEqual(S.event_said(rev, NAME_A), SAID_A)

    def test_content_change_changes_said(self):
        ev = _vector_event(reason="x")
        self.assertNotEqual(S.event_said(ev, NAME_A), SAID_A)

    def test_seq_prev_digest_excluded(self):
        ev = _vector_event().with_assigned(id=NAME_A, seq=7, prev="ab" * 32, digest="cd" * 32)
        self.assertEqual(S.event_said(ev, NAME_A), SAID_A)
        sad = S.event_sad(ev, NAME_A)
        for k in ("seq", "prev", "digest", "id", "said"):
            self.assertNotIn(k, sad)

    def test_saidified_sad_verifies(self):
        said, sad = S.saidify(S.event_sad(_vector_event(), NAME_A))
        self.assertEqual(sad["d"], said)
        self.assertTrue(S.verify(sad))
        sad["i"] = NAME_B                     # rebinding to another name breaks it
        self.assertFalse(S.verify(sad))

    def test_name_required(self):
        with self.assertRaises(ValueError):
            S.event_sad(_vector_event(), "")


class StoreBacked(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.store = Store(self.conn)
        self.log = EventLog(conn=self.conn)

    def tearDown(self):
        self.log.close()
        self.conn.close()

    def test_said_written_in_event_tx(self):
        ev = self.log.append(verification("UC-1", "UC-1@1"))
        self.assertEqual(ev.said, S.event_said(ev, ev.id))
        self.assertTrue(S.is_said(ev.said))
        hist = {d.a: d for d in self.store.history(ev.id)}
        self.assertEqual(hist["more:said"].v, ev.said)
        self.assertEqual(hist["more:said"].tx, hist["more:pin"].tx)
        self.assertEqual(self.store.view(ev.id)["more:said"], ev.said)
        self.assertEqual(self.log.get(ev.id).said, ev.said)

    def test_events_by_said(self):
        a = self.log.append(verification("UC-1", "UC-1@1"))
        b = self.log.append(verification("UC-1", "UC-1@1"))   # same content, other name
        self.assertNotEqual(a.said, b.said)
        self.assertEqual(events_by_said(self.store, a.said), [a.id])
        self.assertEqual(events_by_said(self.store, b.said), [b.id])
        self.assertEqual(events_by_said(self.store, KERIPY_DIGER_QB64), [])

    def test_supersession_is_new_name_and_said(self):
        d = self.log.append(Event("decision", FAB, ("DEC-1",), ("DEC-1@1",),
                                  body={"status": "open"}))
        sup = self.log.append(Event("supersession", FAB, ("DEC-1",), (f"{d.id}@{d.said}",),
                                    supersedes=(d.id,), reason="r"))
        self.assertNotEqual(sup.id, d.id)
        self.assertNotEqual(sup.said, d.said)
        old = [x for x in self.store.history(d.id) if x.a == "more:said"]
        self.assertEqual([(x.v, x.added) for x in old], [(d.said, True)])  # not rewritten
        # lineage still points at the name
        child, parent = self.conn.execute("SELECT child, parent FROM lineage").fetchone()
        self.assertEqual((child, parent), (sup.id, d.id))

    def test_said_pins_are_queryable_and_verified(self):
        target = self.log.append(verification("UC-1", "UC-1@1"))
        other = self.log.append(verification("UC-2", "UC-2@1"))
        pin = f"{target.id}@{target.said}"
        ev = self.log.append(verification(target.id, pin))
        self.assertEqual(self.store.view(ev.id)["more:pinned_against"], (pin,))
        self.assertEqual(events_pinned_against(self.store, pin), [ev.id])
        self.assertEqual(events_pinned_to(self.store, target.id), [ev.id])
        r = resolve(self.store, pin)
        self.assertEqual((r.target, r.version, r.kind, r.ok), (target.id, target.said, "said", True))
        bad = resolve(self.store, f"{target.id}@{other.said}")
        self.assertEqual((bad.kind, bad.ok), ("said", False))

    def test_resolve_tx_pin_and_external(self):
        ev = self.log.append(verification("UC-1", "UC-1@1"))
        tx_pin = self.store.view(ev.id)["more:pin"][0]
        self.assertEqual((resolve(self.store, tx_pin).kind, resolve(self.store, tx_pin).ok), ("pin", True))
        self.assertFalse(resolve(self.store, f"{ev.id}@999999").ok)
        self.assertEqual(resolve(self.store, "UC-1@3").kind, "external")
        self.assertIsNone(resolve(self.store, "UC-1@3").ok)
        self.assertEqual(resolve(self.store, f"UC-1@{ev.said}").kind, "said")
        self.assertIsNone(resolve(self.store, f"UC-1@{ev.said}").ok)
        self.assertEqual((resolve(self.store, ev.id).kind, resolve(self.store, ev.id).ok),
                         ("floating", True))

    def test_standalone_log_assigns_said(self):
        log = EventLog()
        self.addCleanup(log.close)
        ev = log.append(verification("UC-1", "UC-1@1"))
        self.assertEqual(ev.said, S.event_said(ev, ev.id))
        self.assertEqual(log.get(ev.id).said, ev.said)


class Migration(unittest.TestCase):
    """A v3 DB (no more:said) is backfilled from the stored envelopes."""

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(os.remove, self.path)
        conn = connect(self.path)
        conn.execute("DELETE FROM attr WHERE name = 'more:said'")
        for kind in ("more-event", "decision"):
            opt = [a for a in json.loads(conn.execute(
                "SELECT optional FROM kind WHERE name = ?", (kind,)).fetchone()[0]) if a != "more:said"]
            conn.execute("UPDATE kind SET optional = ? WHERE name = ?", (json.dumps(opt), kind))
        conn.execute("PRAGMA user_version = 3")
        log = EventLog(conn=conn)
        with patch.object(store_bridge, "said_changes", lambda *a, **k: []):
            self.events = [log.append(verification("UC-1", "UC-1@1")),
                           log.append(verification("UC-2", "UC-2@1", result="fail")),
                           log.append(Event("decision", FAB, ("DEC-1",), ("DEC-1@1",),
                                            body={"status": "open"}))]
        log.close()
        self.assertNotIn("more:said", Store(conn).view(self.events[0].id))
        conn.close()

    def _txs(self, conn):
        return conn.execute("SELECT id, op, note FROM tx ORDER BY id").fetchall()

    def test_backfill_on_connect(self):
        conn = connect(self.path)
        self.addCleanup(conn.close)
        store = Store(conn)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.assertEqual(conn.execute(
            "SELECT value_type, cardinality FROM attr WHERE name = 'more:said'").fetchone(),
            ("text", "one"))
        mig = [t for t in self._txs(conn) if t[2] == NOTE_SAID]
        self.assertEqual(len(mig), 1)
        self.assertEqual(mig[0][1], "evolve")
        for ev in self.events:
            self.assertEqual(store.view(ev.id)["more:said"], ev.said)
            self.assertEqual(events_by_said(store, ev.said), [ev.id])
        self.assertEqual({d.tx for e in self.events for d in store.history(e.id)
                          if d.a == "more:said"}, {mig[0][0]})
        self.assertEqual(EventLog(conn=conn).verify(), [])   # chain untouched

    def test_idempotent(self):
        conn = connect(self.path)
        txs = self._txs(conn)
        datoms = conn.execute("SELECT COUNT(*) FROM datom").fetchone()[0]
        self.assertEqual(planned_said_changes(Store(conn)), [])
        self.assertIsNone(migrate_said(conn))
        conn.close()
        conn = connect(self.path)
        self.addCleanup(conn.close)
        self.assertIsNone(migrate_said(conn))
        self.assertEqual(self._txs(conn), txs)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM datom").fetchone()[0], datoms)

    def test_mismatch_is_refused_not_rebound(self):
        conn = connect(self.path)
        self.addCleanup(conn.close)
        store = Store(conn)
        eid = self.events[0].id
        store.transact([Change(eid, "more:said", KERIPY_DIGER_QB64)], wrapper=INTERNAL_WRAPPER)
        before = self._txs(conn)
        with self.assertRaises(SaidMismatch):
            migrate_said(conn)
        self.assertFalse(conn.in_transaction)
        self.assertEqual(self._txs(conn), before)
        self.assertEqual(store.view(eid)["more:said"], KERIPY_DIGER_QB64)

    def test_failed_backfill_rolls_back(self):
        conn = sqlite3.connect(self.path, isolation_level=None)
        self.addCleanup(conn.close)
        before = self._txs(conn)
        with patch.object(Store, "transact", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                migrate_said(conn)
        self.assertFalse(conn.in_transaction)
        self.assertEqual(self._txs(conn), before)
        self.assertIsNone(conn.execute(
            "SELECT 1 FROM attr WHERE name = 'more:said'").fetchone())


if __name__ == "__main__":
    unittest.main()
