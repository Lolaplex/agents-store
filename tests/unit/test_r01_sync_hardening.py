"""R01 remediation regression tests (agents-store#35 review findings):

- scrub_datoms must never persist the plaintext value it removes;
- remote attr-level scrubs may only purge syncable attrs;
- far-future remote HLCs refuse with clock_skew before any write;
- ops_since pages past non-syncable txs instead of starving the pull;
- ingest dedupe runs inside BEGIN IMMEDIATE (no ux_tx_origin race);
- P2 hardening: ord_key validation, normalized local_node_id, strict
  _encode bool/int, calendar-valid instant, unknown_attr refusal.
"""
import hashlib
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agents_store import Change, connect
from agents_store.hlc import MAX_DRIFT_MS, normalize_node_id
from agents_store.ingest import ingest, ops_since
from agents_store.scrub import scrub_datoms, scrub_entity
from agents_store.store import Store, _valid_text

from tests.unit.test_distributed import make_node

_SECRET = "SUPERSECRET_VALUE"


def _hlc(ms, node="nodeZ"):
    return f"{ms:013d}.00000.{node}"


class TestScrubSecretNeverPersists(unittest.TestCase):
    def setUp(self):
        self.conn, self.store = make_node("nodeA")
        self.conn.execute(
            "INSERT INTO attr (name, value_type, cardinality)"
            " VALUES ('secret:tok', 'text', 'one')")
        self.store._specs = None
        self.e = self.store.transact(
            [Change(e=None, a="secret:tok", v=_SECRET),
             Change(e=None, a="title", v="keep")],
            wrapper="store").entity

    def test_plaintext_value_absent_everywhere(self):
        n = scrub_datoms(self.conn, a="secret:tok", v=_SECRET)
        self.assertEqual(n, 1)
        for (note,) in self.conn.execute(
                "SELECT note FROM tx WHERE note IS NOT NULL"):
            self.assertNotIn(_SECRET, note)
        for (payload,) in self.conn.execute(
                "SELECT payload FROM refusal WHERE payload IS NOT NULL"):
            self.assertNotIn(_SECRET, payload)
        for op in ops_since(self.conn, 0):
            self.assertNotIn(_SECRET, str(op["note"]))
            for d in op["datoms"]:
                self.assertNotIn(_SECRET, str(d["v"]))

    def test_secret_attr_scrub_envelope_not_shipped(self):
        # a scrub event naming a never-sync attr must not cross the wire
        scrub_datoms(self.conn, a="secret:tok", v=_SECRET)
        self.assertEqual(
            [op for op in ops_since(self.conn, 0)
             if "secret" in str(op["note"])], [])

    def test_attr_hash_envelope_replays_value_scoped(self):
        # the wire form carries attr + sha256[:12] of the value: a peer
        # deletes exactly the scrubbed value, nothing else
        cb, sb = make_node("nodeB")
        cb.execute(
            "INSERT INTO attr (name, value_type, cardinality)"
            " VALUES ('leakme', 'text', 'many')")
        sb._specs = None
        e = sb.transact(
            [Change(e=None, a="leakme", v=_SECRET)], wrapper="store").entity
        sb.transact([Change(e=e, a="leakme", v="harmless")], wrapper="store")
        note = f"attr-hash:leakme:{hashlib.sha256(_SECRET.encode()).hexdigest()[:12]}"
        r = ingest(cb, "nodeA", 1, _hlc(int(time.time() * 1000), "nodeA"),
                   [], op="scrub", note=note)
        self.assertEqual(r.applied, 1)
        remaining = {r[0] for r in cb.execute(
            "SELECT v FROM v_current WHERE e = ? AND a = 'leakme'", (e,))}
        self.assertEqual(remaining, {"harmless"})


class TestRemoteAttrScrubGate(unittest.TestCase):
    def setUp(self):
        self.conn, self.store = make_node("nodeA")
        self.conn.execute(
            "INSERT INTO attr (name, value_type, cardinality)"
            " VALUES ('local:foo', 'text', 'one')")
        self.store._specs = None
        self.e = self.store.transact(
            [Change(e=None, a="local:foo", v="pin"),
             Change(e=None, a="title", v="t")],
            wrapper="store").entity
        self._wall = _hlc(int(time.time() * 1000), "nodeB")

    def _datoms(self, a):
        return self.conn.execute(
            "SELECT COUNT(*) FROM datom WHERE e = ? AND a = ?",
            (self.e, a)).fetchone()[0]

    def test_never_sync_attr_scrub_refused(self):
        r = ingest(self.conn, "nodeB", 1, self._wall, [],
                   op="scrub", note="attr:local:foo")
        self.assertEqual(r.refused, 1)
        reasons = {r[0] for r in self.conn.execute(
            "SELECT reason FROM refusal WHERE wrapper = 'sync'")}
        self.assertIn("scrub_forbidden_attr", reasons)
        self.assertEqual(self._datoms("local:foo"), 1)

    def test_empty_attr_scrub_refused(self):
        r = ingest(self.conn, "nodeB", 2, self._wall, [],
                   op="scrub", note="attr:")
        self.assertEqual(r.refused, 1)
        self.assertEqual(self._datoms("local:foo"), 1)
        self.assertEqual(self._datoms("title"), 1)

    def test_unknown_attr_scrub_refused(self):
        r = ingest(self.conn, "nodeB", 3, self._wall, [],
                   op="scrub", note="attr:nosuchattr")
        self.assertEqual(r.refused, 1)

    def test_syncable_attr_scrub_replays(self):
        r = ingest(self.conn, "nodeB", 4, self._wall, [],
                   op="scrub", note="attr:title")
        self.assertEqual(r.applied, 1)
        self.assertEqual(self._datoms("title"), 0)
        self.assertEqual(self._datoms("local:foo"), 1)


class TestClockSkewRefusal(unittest.TestCase):
    def setUp(self):
        self.conn, self.store = make_node("nodeA")

    def test_far_future_hlc_refused(self):
        e = self.store.transact(
            [Change(e=None, a="title", v="mine")], wrapper="test").entity
        wall = int(time.time() * 1000)
        far = _hlc(wall + 10_000_000)
        txs = self.conn.execute("SELECT COUNT(*) FROM tx").fetchone()[0]
        r = ingest(self.conn, "nodeZ", 1, far,
                   [(e, "title", "hijack", True)])
        self.assertEqual((r.applied, r.dupes), (0, 0))
        self.assertEqual(r.refused, 1)
        self.assertIn("clock_skew", {x[0] for x in self.conn.execute(
            "SELECT reason FROM refusal WHERE wrapper = 'sync'")})
        # nothing was written: no tx, no datom, v_current untouched
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM tx").fetchone()[0], txs)
        self.assertEqual(self.store.view(e)["title"], "mine")
        self.assertIsNone(self.conn.execute(
            "SELECT 1 FROM tx WHERE hlc = ?", (far,)).fetchone())
        # the clock was never poisoned: the next tick stays at wall time
        tick = self.store._tick()
        self.assertLessEqual(
            int(tick.split(".")[0]),
            int(time.time() * 1000) + MAX_DRIFT_MS)

    def test_within_drift_still_admitted(self):
        wall = int(time.time() * 1000)
        r = ingest(self.conn, "nodeZ", 2, _hlc(wall + MAX_DRIFT_MS - 1_000),
                   [("e1", "title", "ok", True)])
        self.assertEqual(r.applied, 1)


class TestOpsSinceStarvation(unittest.TestCase):
    def test_pages_past_local_only_txs(self):
        conn, store = make_node("nodeA")
        conn.execute(
            "INSERT INTO attr (name, value_type, cardinality)"
            " VALUES ('local:pin', 'text', 'one')")
        store._specs = None
        e = store.transact(
            [Change(e=None, a="local:pin", v="seed")], wrapper="store").entity
        conn.execute("BEGIN IMMEDIATE")
        for i in range(1200):
            tx = conn.execute(
                "INSERT INTO tx (op, hlc) VALUES ('assert', '')").lastrowid
            conn.execute(
                "INSERT INTO datom (e, a, v, tx, added, ord)"
                " VALUES (?, 'local:pin', ?, ?, 1, '')",
                (e, f"v{i}", tx))
        conn.execute("COMMIT")
        store.transact([Change(e=e, a="title", v="real")], wrapper="test")
        ops = ops_since(conn, 0, limit=100)
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["datoms"][0]["a"], "title")
        self.assertEqual(ops[0]["datoms"][0]["v"], "real")


class TestIngestDedupeInsideLock(unittest.TestCase):
    def test_concurrent_same_origin_no_integrity_error(self):
        path = Path(tempfile.mkdtemp()) / "race.db"
        c1 = connect(path, check_same_thread=False)
        c2 = connect(path, check_same_thread=False)
        rounds = 30
        barrier = threading.Barrier(2)
        errs = []

        def worker(conn):
            try:
                for i in range(1, rounds + 1):
                    barrier.wait(timeout=10)
                    ingest(conn, "nodeZ", i, _hlc(50_000 + i),
                           [(f"e{i}", "title", "x", True)])
            except Exception as ex:  # noqa: BLE001 — collected for assertion
                errs.append(ex)

        threads = [threading.Thread(target=worker, args=(c,))
                   for c in (c1, c2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errs, [])
        self.assertEqual(
            c1.execute("SELECT COUNT(*) FROM tx").fetchone()[0], rounds)


class TestP2Hardening(unittest.TestCase):
    def setUp(self):
        self.conn, self.store = make_node("nodeA")

    def test_scrub_entity_validates_ord_key(self):
        e = self.store.transact(
            [Change(e=None, a="title", v="x")], wrapper="test").entity
        with self.assertRaises(ValueError):
            scrub_entity(self.conn, e, ord_key="not-an-hlc")
        self.assertTrue(self.store.exists(e))

    def test_local_node_id_normalized(self):
        s = Store(self.conn, "did:key:z6MkTest")
        self.assertEqual(s.local_node_id,
                         normalize_node_id("did:key:z6MkTest"))
        self.assertTrue(s.local_node_id.startswith("k_"))

    def test_bool_encode_rejects_garbage(self):
        self.conn.execute(
            "INSERT INTO attr (name, value_type, cardinality)"
            " VALUES ('flag', 'bool', 'one')")
        self.store._specs = None
        e = self.store.transact(
            [Change(e=None, a="flag", v=True)], wrapper="store").entity
        r = self.store.transact(
            [Change(e=e, a="flag", v="garbage")], wrapper="store")
        self.assertEqual(r.refusals[0].reason, "bad_value")
        r = self.store.transact(
            [Change(e=e, a="flag", v=1)], wrapper="store")
        self.assertEqual(r.refusals[0].reason, "bad_value")
        self.assertEqual(self.store.view(e)["flag"], True)

    def test_int_encode_rejects_bool(self):
        self.conn.execute(
            "INSERT INTO attr (name, value_type, cardinality)"
            " VALUES ('n', 'int', 'one')")
        self.store._specs = None
        e = self.store.transact(
            [Change(e=None, a="n", v=7)], wrapper="store").entity
        r = self.store.transact(
            [Change(e=e, a="n", v=True)], wrapper="store")
        self.assertEqual(r.refusals[0].reason, "bad_value")
        self.assertEqual(self.store.view(e)["n"], 7)

    def test_instant_requires_calendar_valid_date(self):
        self.assertFalse(_valid_text("instant", "2026-99-99junk"))
        self.assertFalse(_valid_text("instant", "2026-02-30"))
        self.assertFalse(_valid_text("instant", "2026-01-01junk"))
        self.assertTrue(_valid_text("instant", "2026-01-01"))
        self.assertTrue(_valid_text("instant", "2026-01-01T10:00:00Z"))

    def test_unknown_attr_non_json_refuses_not_typeerror(self):
        e = self.store.transact(
            [Change(e=None, a="title", v="x")], wrapper="test").entity
        r = self.store.transact(
            [Change(e=e, a="nosuchattr", v={1, 2})], wrapper="test")
        self.assertEqual(r.refusals[0].reason, "unknown_attr")


if __name__ == "__main__":
    unittest.main()
