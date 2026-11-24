"""Frontier W03: migration ordering, atomic ingest/transact, scrub echo,
hlc invariants, sync filters.

Each test pins one acceptance-oracle item: real pre-v6/pre-v2 databases
open cleanly, a mid-ingest crash rolls back whole, remote scrubs dedupe
without echo, the hlc resists drift/garbage, case variants of
never-sync prefixes are blocked on both directions.
"""
import re
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from agents_store import Change, connect
from agents_store.grant import grant
from agents_store.hlc import Hlc, MAX_DRIFT_MS, is_hlc, normalize_node_id
from agents_store.ingest import ingest, ops_since
from agents_store.scrub import scrub_datoms, scrub_entity
from agents_store.store import Store

from tests.unit.test_distributed import _CODE_HASH, _IMPL, make_node

_HLC = re.compile(r"^\d{13}\.\d{5}\.[A-Za-z0-9_-]+$")


def _v1_ddl():
    """A genuine v1 store: 6-col tx without 'retire'/'scrub', datom
    without ord, attr without syncable, certificate without code_hash."""
    return """
        CREATE TABLE entity (id TEXT PRIMARY KEY,
          created_tx INTEGER NOT NULL REFERENCES tx(id));
        CREATE TABLE attr (name TEXT PRIMARY KEY, value_type TEXT NOT NULL,
                           cardinality TEXT NOT NULL, doc TEXT NOT NULL DEFAULT '');
        CREATE TABLE tx (id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
          agent TEXT, wrapper TEXT,
          op TEXT NOT NULL CHECK (op IN ('assert','evolve','split','merge','correct')),
          note TEXT);
        CREATE TABLE datom (e TEXT NOT NULL REFERENCES entity(id),
          a TEXT NOT NULL REFERENCES attr(name), v TEXT NOT NULL,
          tx INTEGER NOT NULL REFERENCES tx(id), added INTEGER NOT NULL,
          PRIMARY KEY (e,a,v,tx));
        CREATE TABLE lineage (child TEXT NOT NULL REFERENCES entity(id),
          parent TEXT NOT NULL REFERENCES entity(id),
          kind TEXT NOT NULL, tx INTEGER NOT NULL REFERENCES tx(id),
          reason TEXT, PRIMARY KEY (child,parent,kind,tx));
        CREATE TABLE kind (name TEXT PRIMARY KEY, required TEXT NOT NULL,
          optional TEXT NOT NULL DEFAULT '[]', derivations TEXT NOT NULL DEFAULT '[]');
        CREATE TABLE certificate (id INTEGER PRIMARY KEY AUTOINCREMENT,
          tier TEXT NOT NULL, subject TEXT NOT NULL, ref TEXT NOT NULL,
          corpus TEXT, result TEXT NOT NULL,
          ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
        CREATE TABLE wrapper (id TEXT PRIMARY KEY, namespace TEXT NOT NULL,
          impl_ref TEXT NOT NULL, doc TEXT NOT NULL DEFAULT '');
        CREATE TABLE grant_ (wrapper TEXT NOT NULL, attr TEXT NOT NULL,
          certificate_id INTEGER NOT NULL, PRIMARY KEY (wrapper,attr,certificate_id));
        CREATE TABLE correspondence (id INTEGER PRIMARY KEY AUTOINCREMENT,
          a_from TEXT NOT NULL, a_to TEXT NOT NULL, kind TEXT NOT NULL,
          lens_ref TEXT, status TEXT NOT NULL DEFAULT 'proposed',
          certificate_id INTEGER);
        CREATE TABLE capability (id TEXT PRIMARY KEY, in_kind TEXT NOT NULL,
          out_kind TEXT NOT NULL, mode TEXT NOT NULL, impl_ref TEXT NOT NULL,
          certificate_id INTEGER);
        CREATE TABLE mediator (id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL, target TEXT NOT NULL, path TEXT NOT NULL,
          exactness TEXT NOT NULL, certificate_id INTEGER);
        CREATE TABLE provenance (out_ref TEXT NOT NULL, in_refs TEXT NOT NULL,
          mediator_id INTEGER, tx INTEGER);
        CREATE TABLE refusal (id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
          wrapper TEXT NOT NULL, entity TEXT, attr TEXT, reason TEXT NOT NULL,
          payload TEXT);
        CREATE VIEW v_current AS
        SELECT d.e, d.a, d.v, MAX(d.tx) AS tx FROM datom d
        WHERE d.added = 1 AND NOT EXISTS (
          SELECT 1 FROM datom r WHERE r.e=d.e AND r.a=d.a AND r.v=d.v
            AND r.added=0 AND r.tx>d.tx) GROUP BY d.e,d.a,d.v;
        INSERT INTO attr (name,value_type,cardinality) VALUES ('title','text','one');
    """


class TestRealOldDbs(unittest.TestCase):
    def _old_db(self, ddl_extra="", version=5):
        path = Path(tempfile.mkdtemp()) / "old.db"
        raw = sqlite3.connect(str(path))
        raw.executescript(_v1_ddl() + ddl_extra + f"\nPRAGMA user_version = {version};")
        raw.close()
        return path

    def test_pre_v6_db_with_repeated_eav_history_opens(self):
        # entity 'e1' carries assert/retract/assert of the same (e,a,v)
        # across three txs: every backfilled ord collides on '' before
        # backfill, so creating ux_datom_eav_ord first would IntegrityError.
        path = self._old_db("""
            INSERT INTO tx (op,agent) VALUES ('assert','a'),('assert','a'),('assert','a');
            INSERT INTO entity VALUES ('e1',1);
            INSERT INTO datom (e,a,v,tx,added) VALUES
              ('e1','title','v1',1,1),
              ('e1','title','v1',2,0),
              ('e1','title','v1',3,1),
              ('e1','title','v2',3,1);
            PRAGMA user_version = 5;
        """, version=5)
        # v5->v7 shape: simulate the version markers a v5 db really has
        raw = sqlite3.connect(str(path))
        raw.execute("PRAGMA user_version = 5")
        raw.close()
        conn = connect(str(path))  # must not raise IntegrityError
        self.assertEqual(Store(conn).view("e1"), {"title": "v2"})
        self.assertEqual(
            conn.execute("PRAGMA user_version").fetchone()[0], 7)
        # ord backfilled per tx; view resolves by max ord
        ords = [r[0] for r in conn.execute(
            "SELECT ord FROM datom WHERE e='e1' ORDER BY tx")]
        self.assertTrue(all(re.match(r"^\d{12}$", o) for o in ords))

    def test_pre_v2_db_opens_without_operational_error(self):
        # v1-era tx has 6 cols; the fixed pipeline must not crash rebuilding
        # it into the 'retire' CHECK even after origin cols were pre-added.
        path = self._old_db("""
            INSERT INTO tx (op,agent) VALUES ('assert','a');
            INSERT INTO entity VALUES ('e1',1);
            INSERT INTO datom (e,a,v,tx,added) VALUES ('e1','title','legacy',1,1);
            PRAGMA user_version = 1;
        """, version=1)
        conn = connect(str(path))  # must not raise OperationalError
        self.assertEqual(Store(conn).view("e1"), {"title": "legacy"})
        self.assertEqual(
            conn.execute("PRAGMA user_version").fetchone()[0], 7)
        tx_cols = {r[1] for r in conn.execute("PRAGMA table_info(tx)")}
        self.assertTrue({"hlc", "origin_actor", "origin_seq"} <= tx_cols)
        self.assertIn("'scrub'", conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='tx'").fetchone()[0])
        self.assertIn("'retire'", conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='tx'").fetchone()[0])

    def test_migrated_db_has_syncable_check_and_eao_index(self):
        path = self._old_db("""
            INSERT INTO tx (op,agent) VALUES ('assert','a');
            PRAGMA user_version = 6;
        """, version=6)
        conn = connect(str(path))
        attr_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='attr'").fetchone()[0]
        self.assertIn("CHECK (syncable IN (0,1))", attr_sql)
        idx = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index'"
            " AND name='idx_datom_eao'").fetchone()
        self.assertIsNotNone(idx)


class TestAtomicIngest(unittest.TestCase):
    def setUp(self):
        self.ca, self.sa = make_node("nodeA")
        self.cb, self.sb = make_node("nodeB")

    def test_mid_ingest_crash_rolls_back_replay_applies_all(self):
        datoms = [("e1", "title", "a", True), ("e2", "body", "boom", True)]
        # fail on the second datom's entity insert path via datom trigger
        self.cb.execute(
            "CREATE TRIGGER boom BEFORE INSERT ON datom WHEN NEW.v = 'boom'"
            " BEGIN SELECT RAISE(FAIL, 'simulated crash'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            ingest(self.cb, "nodeA", 1, "0000000000050.00000.nodeA", datoms)
        self.cb.execute("DROP TRIGGER boom")
        # nothing survived: no tx row means replay is not deduped away
        self.assertIsNone(self.cb.execute(
            "SELECT id FROM tx WHERE origin_actor='nodeA' AND origin_seq=1"
        ).fetchone())
        r = ingest(self.cb, "nodeA", 1, "0000000000050.00000.nodeA", datoms)
        self.assertEqual(r.applied, 2)
        self.assertEqual(Store(self.cb).view("e1"), {"title": "a"})
        self.assertEqual(Store(self.cb).view("e2"), {"body": "boom"})

    def test_bad_hlc_and_bad_op_refused(self):
        r = ingest(self.cb, "nodeA", 1, "zzzz", [("e1", "title", "x", True)])
        self.assertGreaterEqual(r.refused, 1)
        r = ingest(self.cb, "nodeA", 2, "0000000000050.00000.nodeA",
                   [("e1", "title", "x", True)], op="detonate")
        self.assertGreaterEqual(r.refused, 1)
        self.assertIsNone(self.cb.execute(
            "SELECT id FROM tx WHERE origin_actor='nodeA'").fetchone())


class TestScrubEcho(unittest.TestCase):
    def setUp(self):
        self.ca, self.sa = make_node("nodeA")
        self.cb, self.sb = make_node("nodeB")

    def test_remote_scrub_no_echo_and_blocks_resurrection(self):
        e = self.sb.transact([Change(e=None, a="title", v="gone")], wrapper="test").entity
        cutoff = "0000000000100.00000.nodeB"
        r = ingest(self.ca, "nodeB", 7, cutoff, [], op="scrub", note=e)
        self.assertFalse(self.sa.exists(e))
        self.assertEqual(
            self.ca.execute("SELECT hlc FROM scrubbed WHERE e=?", (e,)).fetchone()[0],
            cutoff)
        # origined tx row: dedupes redelivery AND is invisible to origin_only
        row = self.ca.execute(
            "SELECT origin_actor, origin_seq FROM tx WHERE id=?", (r.tx,)).fetchone()
        self.assertEqual(row, ("nodeB", 7))
        self.assertEqual(
            [op for op in ops_since(self.ca, 0, origin_only=True)
             if op["op"] == "scrub"], [])
        # redelivery dedupes, does not re-delete
        r2 = ingest(self.ca, "nodeB", 7, cutoff, [], op="scrub", note=e)
        self.assertEqual(r2.tx, r.tx)
        self.assertEqual(r2.applied, 0)
        # late-arriving datom with ord <= cutoff is dropped
        r3 = ingest(self.ca, "nodeB", 8, "0000000000050.00000.nodeB",
                    [(e, "title", "zombie", True)])
        self.assertEqual(r3.applied, 0)
        self.assertFalse(self.sa.exists(e))
        # a NEWER ord resurrects nothing either once e is re-created? no:
        # ord > cutoff datoms land again only if they postdate the scrub
        r4 = ingest(self.ca, "nodeB", 9, "0000000000200.00000.nodeB",
                    [(e, "title", "after", True)])
        self.assertEqual(r4.applied, 1)

    def test_remote_scrub_uses_max_cutoff(self):
        e = self.sb.transact([Change(e=None, a="title", v="x")], wrapper="test").entity
        ingest(self.ca, "nodeB", 7, "0000000000100.00000.nodeB", [], op="scrub", note=e)
        ingest(self.ca, "nodeB", 8, "0000000000080.00000.nodeB", [], op="scrub", note=e)
        # lower second scrub must not lower the tombstone (min() bug)
        self.assertEqual(
            self.ca.execute("SELECT hlc FROM scrubbed WHERE e=?", (e,)).fetchone()[0],
            "0000000000100.00000.nodeB")

    def test_scrub_op_requires_target(self):
        r = ingest(self.ca, "nodeB", 1, "0000000000100.00000.nodeB",
                   [], op="scrub", note="  ")
        self.assertGreaterEqual(r.refused, 1)

    def test_local_scrub_mints_ord_and_propagates(self):
        e = self.sa.transact([Change(e=None, a="title", v="x")], wrapper="test").entity
        r = scrub_entity(self.ca, e)  # no ord_key: must auto-mint
        tomb = self.ca.execute("SELECT hlc FROM scrubbed WHERE e=?", (e,)).fetchone()[0]
        self.assertTrue(_HLC.match(tomb))
        envelopes = [op for op in ops_since(self.ca, 0) if op["op"] == "scrub"]
        self.assertEqual(len(envelopes), 1)
        self.assertEqual(envelopes[0]["note"], e)
        # peer replays the propagated tombstone
        ingest(self.cb, "nodeA", envelopes[0]["origin_seq"], envelopes[0]["hlc"],
               [], op="scrub", note=envelopes[0]["note"])
        self.assertTrue(self.cb.execute(
            "SELECT 1 FROM scrubbed WHERE e=?", (e,)).fetchone())

    def test_scrub_redacts_provenance_and_refusal_payload(self):
        e = self.sa.transact([Change(e=None, a="title", v="x")], wrapper="test").entity
        self.ca.execute(
            "INSERT INTO refusal (wrapper, entity, attr, reason, payload)"
            " VALUES ('t', ?, 'title', 'no_grant', 'pii-here')", (e,))
        self.ca.execute(
            "INSERT INTO provenance (out_ref, in_refs, tx) VALUES (?, '[]', 1)",
            ('{"a": "title", "e": "%s"}' % e,))
        scrub_entity(self.ca, e)
        self.assertIsNone(self.ca.execute(
            "SELECT payload FROM refusal WHERE entity=?", (e,)).fetchone()[0])
        self.assertEqual(self.ca.execute(
            "SELECT COUNT(*) FROM provenance").fetchone()[0], 0)

    def test_repeat_scrub_stricter_cutoff_emits_new_tombstone(self):
        e = self.sa.transact([Change(e=None, a="title", v="x")], wrapper="test").entity
        scrub_entity(self.ca, e, ord_key="0000000000100.00000.nodeA")
        r2 = scrub_entity(self.ca, e, ord_key="0000000000200.00000.nodeA")
        self.assertEqual(
            self.ca.execute("SELECT hlc FROM scrubbed WHERE e=?", (e,)).fetchone()[0],
            "0000000000200.00000.nodeA")
        envs = [op for op in ops_since(self.ca, 0) if op["op"] == "scrub"]
        self.assertEqual(len(envs), 2)  # the stricter cutoff must reach peers
        self.assertEqual(envs[-1]["hlc"], "0000000000200.00000.nodeA")
        # and a weaker re-scrub emits nothing new and cannot re-lower it
        r3 = scrub_entity(self.ca, e, ord_key="0000000000050.00000.nodeA")
        self.assertEqual(r3.tx, envs[0]["tx"])
        envs2 = [op for op in ops_since(self.ca, 0) if op["op"] == "scrub"]
        self.assertEqual(len(envs2), 2)
        self.assertEqual(
            self.ca.execute("SELECT hlc FROM scrubbed WHERE e=?", (e,)).fetchone()[0],
            "0000000000200.00000.nodeA")

    def test_scrub_datoms_emits_event_and_peer_replays(self):
        e = self.sa.transact(
            [Change(e=None, a="title", v="leak"), Change(e=None, a="body", v="keep")],
            wrapper="test").entity
        n = scrub_datoms(self.ca, a="title", v="leak")
        self.assertEqual(n, 1)
        envs = [op for op in ops_since(self.ca, 0) if op["op"] == "scrub"]
        self.assertEqual(len(envs), 1)
        # the event names the attr and a sha256[:12] of the value — the
        # plaintext value must never persist in append-only tx.note
        import hashlib
        want = f"attr-hash:title:{hashlib.sha256('leak'.encode()).hexdigest()[:12]}"
        self.assertEqual(envs[0]["note"], want)
        self.assertNotIn("leak", envs[0]["note"])
        # peer holds the same leak datom; the event deletes it there too
        ingest(self.cb, "nodeA", 40, "0000000000050.00000.nodeA",
               [(e, "title", "leak", True), (e, "body", "keep", True)])
        self.assertEqual(self.sb.view(e), {"title": "leak", "body": "keep"})
        r = ingest(self.cb, "nodeA", envs[0]["origin_seq"], envs[0]["hlc"],
                   [], op="scrub", note=envs[0]["note"])
        self.assertEqual(r.applied, 1)
        self.assertEqual(self.sb.view(e), {"body": "keep"})
        # redelivery dedupes; the entity itself was never tombstoned
        r2 = ingest(self.cb, "nodeA", envs[0]["origin_seq"], envs[0]["hlc"],
                    [], op="scrub", note=envs[0]["note"])
        self.assertEqual(r2.tx, r.tx)
        self.assertIsNone(self.cb.execute(
            "SELECT 1 FROM scrubbed WHERE e=?", (e,)).fetchone())


class TestHlcInvariants(unittest.TestCase):
    def test_did_key_node_id_accepted(self):
        h = Hlc("did:key:z6MkpTHR8VNsBxYAAKWut2AaddF6v3Y5nR7VW2CjjJJfQJ3L")
        self.assertTrue(is_hlc(h.tick()))
        self.assertTrue(h.node.startswith("k_"))
        self.assertEqual(normalize_node_id("nodeA"), "nodeA")
        self.assertEqual(normalize_node_id("did:key:abc"), normalize_node_id("did:key:abc"))

    def test_observe_clamps_extreme_future(self):
        h = Hlc("n")
        far = "9999000000000.00000.nodeZ"  # year 2286
        h.observe(far)
        ticked = h.tick()
        ms = int(ticked.split(".")[0])
        self.assertLess(ms, 9999000000000)
        self.assertLessEqual(ms, int(time.time() * 1000) + MAX_DRIFT_MS + 50)

    def test_observe_accepts_within_drift(self):
        h = Hlc("n")
        soon = int(time.time() * 1000) + 30_000
        remote = f"{soon:013d}.00000.nodeZ"
        h.observe(remote)
        self.assertGreater(h.tick(), remote)

    def test_counter_overflow_advances_ms(self):
        h = Hlc("n")
        h._ms = int(time.time() * 1000) + 10_000
        h._counter = 99_999
        t = h.tick()
        ms, ctr, _ = t.split(".", 2)
        self.assertEqual(int(ms), h._ms)
        self.assertEqual(ctr, "00000")

    def test_current_rows_bound_matches_v_current_out_of_order(self):
        conn, _ = make_node("nodeB")
        s = Store(conn)
        # remote ops arrive out of order: retract(ord20), assert(ord10), assert(ord30)
        t1 = ingest(conn, "nodeA", 1, "0000000000020.00000.nodeA",
                    [("e1", "status", "open", False)]).tx
        t2 = ingest(conn, "nodeA", 2, "0000000000010.00000.nodeA",
                    [("e1", "status", "open", True)]).tx
        t3 = ingest(conn, "nodeA", 3, "0000000000030.00000.nodeA",
                    [("e1", "status", "open", True)]).tx
        # as-of bound must resolve by ord argmax, not tx order:
        # at t2 the only write seen is the ord-20 retract + ord-10 assert,
        # whose ord-max is the retract -> empty, even though the assert
        # has the later local tx.
        self.assertEqual(s.view("e1", tx=t2), {})
        self.assertEqual(s.view("e1", tx=t3), {"status": "open"})
        # bound at the newest tx converges identically with v_current
        self.assertEqual(s.view("e1", tx=t3), s.view("e1"))


class TestSyncFilters(unittest.TestCase):
    def setUp(self):
        self.ca, self.sa = make_node("nodeA")
        self.cb, self.sb = make_node("nodeB")

    def test_case_variant_never_sync_blocked_inbound(self):
        self.cb.execute(
            "INSERT INTO attr (name, value_type, cardinality)"
            " VALUES ('LOCAL:secret', 'text', 'one')")
        r = ingest(self.cb, "nodeA", 1, "0000000000050.00000.nodeA",
                   [("e1", "LOCAL:secret", "x", True)])
        self.assertGreaterEqual(r.refused, 1)
        self.assertIsNone(self.cb.execute(
            "SELECT 1 FROM datom WHERE a='LOCAL:secret'").fetchone())

    def test_case_variant_never_sync_blocked_outbound(self):
        self.ca.execute(
            "INSERT INTO attr (name, value_type, cardinality)"
            " VALUES ('LOCAL:secret', 'text', 'one')")
        self.sa.transact(
            [Change(e=None, a="LOCAL:secret", v="x")], wrapper="store")
        for op in ops_since(self.ca, 0):
            for d in op["datoms"]:
                self.assertNotEqual(d["a"], "LOCAL:secret")

    def test_pure_non_syncable_tx_emits_no_envelope(self):
        self.ca.execute(
            "INSERT INTO attr (name, value_type, cardinality, syncable)"
            " VALUES ('host:pin', 'text', 'one', 0)")
        self.sa.transact([Change(e=None, a="host:pin", v="p")], wrapper="store")
        self.assertEqual(ops_since(self.ca, 0), [])

    def test_bare_string_local_origins_raises(self):
        with self.assertRaises(TypeError):
            ops_since(self.ca, 0, local_origins="proj:")


class TestTransactHardening(unittest.TestCase):
    def setUp(self):
        self.conn, self.store = make_node("nodeA")

    def test_card_one_multi_change_same_tx_last_wins(self):
        r = self.store.transact(
            [Change(e=None, a="title", v="first"),
             Change(e=None, a="title", v="second")],
            wrapper="test")
        self.assertEqual(self.store.view(r.entity)["title"], "second")
        # exactly one assert datom: no same-ord pair on (e,a)
        self.assertEqual(
            [d.v for d in self.store.history(r.entity) if d.added], ["second"])

    def test_same_eav_retract_and_assert_one_tx(self):
        e = self.store.transact([Change(e=None, a="title", v="x")], wrapper="test").entity
        r = self.store.transact(
            [Change(e=e, a="title", v="x", added=False),
             Change(e=e, a="title", v="x")],
            wrapper="test")
        self.assertEqual(self.store.view(e)["title"], "x")

    def test_duplicate_mint_changes_do_not_crash(self):
        # duplicate e=None changes previously escaped dedupe and crashed
        # on ux_datom_eav_ord (assert + auto-retract share one ord)
        r = self.store.transact(
            [Change(e=None, a="title", v="x"),
             Change(e=None, a="title", v="y"),
             Change(e=None, a="title", v="x", added=False),
             Change(e=None, a="body", v="b")],
            wrapper="test")
        self.assertEqual(self.store.view(r.entity), {"body": "b"})

    def test_transact_rolls_back_on_mid_batch_error(self):
        e = self.store.transact([Change(e=None, a="title", v="a")], wrapper="test").entity
        txs = self.conn.execute("SELECT COUNT(*) FROM tx").fetchone()[0]
        self.conn.execute(
            "CREATE TRIGGER boom BEFORE INSERT ON datom WHEN NEW.v = 'boomv'"
            " BEGIN SELECT RAISE(FAIL, 'simulated crash'); END")
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                self.store.transact(
                    [Change(e=e, a="body", v="ok"),
                     Change(e=e, a="title", v="boomv")],
                    wrapper="test")
        finally:
            self.conn.execute("DROP TRIGGER boom")
        # rolled back whole: no tx row, no datom, state untouched
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM tx").fetchone()[0], txs)
        self.assertEqual(self.store.view(e), {"title": "a"})

    def test_bad_value_encoded_is_refusal_not_crash(self):
        self.conn.execute(
            "INSERT INTO attr (name, value_type, cardinality)"
            " VALUES ('n:int', 'int', 'one')")
        e = self.store.transact([Change(e=None, a="title", v="a")], wrapper="test").entity
        self.store._specs = None
        r = self.store.transact(
            [Change(e=e, a="n:int", v="not-an-int")], wrapper="store")
        self.assertEqual(r.refusals[0].reason, "bad_value")
        self.assertEqual(self.store.view(e), {"title": "a"})

    def test_entity_remint_of_scrubbed_id_rejected(self):
        e = self.store.transact([Change(e=None, a="title", v="x")], wrapper="test").entity
        scrub_entity(self.conn, e)
        with self.assertRaises(ValueError):
            self.store.transact([Change(e=None, a="title", v="y")],
                                wrapper="test", entity=e)

    def test_specs_refresh_sees_late_attr(self):
        self.store._spec("title")  # warm the cache
        self.conn.execute(
            "INSERT INTO attr (name, value_type, cardinality)"
            " VALUES ('late:attr', 'text', 'one')")
        self.assertIsNotNone(self.store._spec("late:attr"))


if __name__ == "__main__":
    unittest.main()
