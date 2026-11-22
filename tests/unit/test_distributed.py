"""Distributed semantics: ord-keyed v_current, remote ingest, scrub.

Simulates the agents-sync distributor verbatim: pull ops_since(cursor) on
the source, ingest() into the destination with the sender's node id.
Delivery may drop, duplicate, reorder — convergence is the assertion.
"""
import unittest

from agents_store import Change, connect
from agents_store.code_hash import code_hash_for_impl_ref
from agents_store.grant import grant
from agents_store.ingest import (
    ResyncRequired, cursor, ingest, ops_since)
from agents_store.scrub import scrub_datoms, scrub_entity
from agents_store.store import Store

_IMPL = "agents_store.wrappers.markdown.MarkdownWrapper"
_CODE_HASH = code_hash_for_impl_ref(_IMPL)
_ATTRS = ["title", "body", "status", "md:path"]


def make_node(node_id):
    conn = connect()
    conn.execute(
        "INSERT INTO wrapper (id, namespace, impl_ref) VALUES ('test', 'test', ?)",
        (_IMPL,),
    )
    cert = conn.execute(
        "INSERT INTO certificate (tier, subject, ref, result, code_hash)"
        " VALUES ('witness', 'wrapper:test', 't', 'pass', ?)",
        (_CODE_HASH,),
    ).lastrowid
    for a in _ATTRS:
        grant(conn, "test", a, cert)
    return conn, Store(conn, node_id)


def tail(src_conn, since=0):
    """The distributor's pull: ops with wire-ready datoms."""
    return since, ops_since(src_conn, since)


def deliver(src_conn, dst_conn, src_node, since=0, dst_clock=None):
    """Ship every op after `since`; returns the new cursor."""
    for op in ops_since(src_conn, since):
        actor = op["origin_actor"] or src_node
        ingest(
            dst_conn, actor, op["origin_seq"], op["hlc"],
            [(d["e"], d["a"], d["v"], d["added"]) for d in op["datoms"]],
            op=op["op"], note=op["note"],
        )
        if dst_clock is not None and op["hlc"]:
            dst_clock.observe(op["hlc"])
    return cursor(src_conn)


class TestIngest(unittest.TestCase):
    def setUp(self):
        self.ca, self.sa = make_node("nodeA")
        self.cb, self.sb = make_node("nodeB")

    def test_convergence_basic(self):
        e = self.sa.transact(
            [Change(e=None, a="title", v="x"), Change(e=None, a="body", v="b")],
            wrapper="test",
        ).entity
        deliver(self.ca, self.cb, "nodeA")
        self.assertEqual(Store(self.cb).view(e), {"title": "x", "body": "b"})

    def test_card_one_conflict_remote_later_wins(self):
        e = self.sa.transact([Change(e=None, a="title", v="old")], wrapper="test").entity
        c = deliver(self.ca, self.cb, "nodeA")
        # concurrent writes; B merges A's op key so its tick is strictly later
        self.sa.transact([Change(e=e, a="title", v="fromA")], wrapper="test")
        hlc_a = ops_since(self.ca, c)[-1]["hlc"]
        self.sb._clock.observe(hlc_a)
        self.sb.transact([Change(e=e, a="title", v="fromB")], wrapper="test")
        deliver(self.ca, self.cb, "nodeA")
        deliver(self.cb, self.ca, "nodeB")
        self.assertEqual(self.sa.view(e)["title"], "fromB")
        self.assertEqual(Store(self.cb).view(e)["title"], "fromB")

    def test_card_one_stale_remote_does_not_overwrite(self):
        e = self.sb.transact([Change(e=None, a="title", v="new")], wrapper="test").entity
        deliver(self.cb, self.ca, "nodeB")
        # A's stale write (earlier hlc) arrives after B's newer value
        ingest(self.ca, "nodeA", 1, "0000000000010.00001.nodeA",
               [(e, "title", "stale", True)])
        self.assertEqual(self.sa.view(e)["title"], "new")

    def test_out_of_order_retract_before_assert(self):
        # remote retract (ord 20) lands before the assert (ord 10) it kills
        ingest(self.cb, "nodeA", 2, "0000000000020.00000.nodeA",
               [("e1", "status", "open", False)])
        ingest(self.cb, "nodeA", 1, "0000000000010.00000.nodeA",
               [("e1", "status", "open", True)])
        self.assertEqual(Store(self.cb).view("e1"), {})
        # a later assert (ord 30) still wins over the retract
        ingest(self.cb, "nodeA", 3, "0000000000030.00000.nodeA",
               [("e1", "status", "open", True)])
        self.assertEqual(Store(self.cb).view("e1"), {"status": "open"})

    def test_redelivery_is_idempotent(self):
        e = self.sa.transact([Change(e=None, a="title", v="x")], wrapper="test").entity
        op = ops_since(self.ca, 0)[0]
        d = [(x["e"], x["a"], x["v"], x["added"]) for x in op["datoms"]]
        r1 = ingest(self.cb, "nodeA", op["origin_seq"], op["hlc"], d)
        r2 = ingest(self.cb, "nodeA", op["origin_seq"], op["hlc"], d)
        self.assertEqual(r1.tx, r2.tx)
        self.assertEqual((r2.applied, r2.dupes), (0, len(d)))
        self.assertEqual(Store(self.cb).view(e)["title"], "x")

    def test_card_many_union(self):
        e = self.sa.transact([Change(e=None, a="title", v="doc")], wrapper="test").entity
        deliver(self.ca, self.cb, "nodeA")
        self.sa.transact([Change(e=e, a="md:path", v="p/one.md")], wrapper="test")
        self.sb.transact([Change(e=e, a="md:path", v="p/two.md")], wrapper="test")
        deliver(self.ca, self.cb, "nodeA")
        deliver(self.cb, self.ca, "nodeB")
        for conn in (self.ca, self.cb):
            self.assertEqual(
                set(Store(conn).view(e)["md:path"]), {"p/one.md", "p/two.md"})

    def test_echo_dedupes_at_datom_level(self):
        # hub re-delivers A's own op back to A: no duplicate datom rows
        e = self.sa.transact([Change(e=None, a="title", v="x")], wrapper="test").entity
        op = ops_since(self.ca, 0)[0]
        d = [(x["e"], x["a"], x["v"], x["added"]) for x in op["datoms"]]
        r = ingest(self.ca, "nodeA", op["origin_seq"], op["hlc"], d)
        before = self.ca.execute("SELECT COUNT(*) FROM datom WHERE e = ?", (e,)).fetchone()[0]
        self.assertEqual(r.applied, 0)
        self.assertEqual(before, 1)

    def test_unknown_attr_refused_loudly(self):
        r = ingest(self.cb, "nodeA", 9, "0000000000099.00000.nodeA",
                   [("e1", "nosuchattr", "v", True)])
        self.assertEqual(r.refused, 1)
        reasons = [x[0] for x in self.cb.execute(
            "SELECT reason FROM refusal WHERE wrapper = 'sync'")]
        self.assertIn("unknown_attr", reasons)


class TestScrub(unittest.TestCase):
    def setUp(self):
        self.conn, self.store = make_node("nodeA")

    def test_scrub_entity_removes_history_and_audits(self):
        e = self.store.transact(
            [Change(e=None, a="title", v="secret"), Change(e=None, a="body", v="x")],
            wrapper="test",
        ).entity
        r = scrub_entity(self.conn, e, reason="gdpr")
        self.assertGreaterEqual(r.datoms_removed, 2)
        self.assertFalse(self.store.exists(e))
        self.assertEqual(self.store.history(e), [])
        rows = self.conn.execute(
            "SELECT reason FROM refusal WHERE wrapper = 'scrub' AND entity = ?",
            (e,)).fetchall()
        self.assertEqual(rows, [("gdpr",)])
        # triggers restored: deleting a real row must raise
        e2 = self.store.transact([Change(e=None, a="title", v="z")], wrapper="test").entity
        with self.assertRaises(Exception):
            self.conn.execute("DELETE FROM datom WHERE e = ?", (e2,))

    def test_scrub_datoms_by_attr(self):
        e = self.store.transact(
            [Change(e=None, a="title", v="leak"), Change(e=None, a="body", v="keep")],
            wrapper="test",
        ).entity
        n = scrub_datoms(self.conn, a="title", v="leak")
        self.assertEqual(n, 1)
        self.assertEqual(self.store.view(e), {"body": "keep"})


class TestMigrationV6(unittest.TestCase):
    def test_backfill_and_view_after_v5(self):
        # minimal pre-v6 shape: tx/datom/attr without ord/origin columns
        conn = connect()
        conn.execute("PRAGMA user_version = 5")
        e = "legacyent"
        conn.execute(
            "INSERT INTO tx (op, agent, wrapper) VALUES ('assert', 'a', 'test')")
        tx = conn.execute("SELECT MAX(id) FROM tx").fetchone()[0]
        conn.execute("INSERT INTO entity (id, created_tx) VALUES (?, ?)", (e, tx))
        # ord='' simulates a pre-v6 row awaiting the migration backfill
        conn.execute(
            "INSERT INTO datom (e, a, v, tx, added, ord) VALUES (?, 'title', 'old', ?, 1, '')",
            (e, tx))
        from agents_store.db import _migrate_v6
        _migrate_v6(conn)
        ord_key = conn.execute("SELECT ord FROM datom WHERE e = ?", (e,)).fetchone()[0]
        self.assertEqual(ord_key, f"{tx:012d}")
        self.assertEqual(Store(conn).view(e), {"title": "old"})
        # a synced write beats the backfilled local one
        ingest(conn, "nodeB", 1, "0000000000099.00000.nodeB",
               [(e, "title", "synced", True)])
        self.assertEqual(Store(conn).view(e), {"title": "synced"})


class TestFrontierRules(unittest.TestCase):
    def setUp(self):
        self.ca, self.sa = make_node("nodeA")
        self.cb, self.sb = make_node("nodeB")

    def test_boot_seeded_clock_orders_after_restart(self):
        r = self.sa.transact([Change(e=None, a="title", v="x")], wrapper="test")
        hlc1 = ops_since(self.ca, 0)[-1]["hlc"]
        # a fresh Store on the same conn resumes the clock, never rewinds it
        s2 = Store(self.ca, "nodeA")
        r2 = s2.transact([Change(e=r.entity, a="title", v="y")], wrapper="test")
        hlc2 = ops_since(self.ca, cursor(self.ca) - 1)[-1]["hlc"]
        self.assertGreater(hlc2, hlc1)

    def test_ingest_observes_remote_hlc(self):
        self.sa.transact([Change(e=None, a="title", v="a")], wrapper="test")
        far = "9999000000000.00000.nodeZ"
        ingest(self.ca, "nodeZ", 1, far,
               [("e1", "title", "z", True)], clock=self.sa._clock)
        self.sa.transact([Change(e=None, a="title", v="b")], wrapper="test")
        new_hlc = ops_since(self.ca, cursor(self.ca) - 1)[-1]["hlc"]
        self.assertGreater(new_hlc, far)

    def test_card_one_same_ord_canonicalizes_to_max(self):
        r = ingest(self.cb, "nodeA", 1, "0000000000050.00000.nodeA",
                   [("e1", "title", "alpha", True),
                    ("e1", "title", "omega", True)])
        self.assertEqual(r.refused, 1)
        self.assertEqual(Store(self.cb).view("e1"), {"title": "omega"})
        ref = self.cb.execute(
            "SELECT reason FROM refusal WHERE reason = 'card_one_same_ord'"
        ).fetchall()
        self.assertEqual(len(ref), 1)

    def test_same_eav_retract_wins(self):
        r = ingest(self.cb, "nodeA", 1, "0000000000050.00000.nodeA",
                   [("e1", "title", "x", True), ("e1", "title", "x", False)])
        self.assertEqual(Store(self.cb).view("e1"), {})

    def test_scrub_tombstone_blocks_resurrection(self):
        e = self.sa.transact([Change(e=None, a="title", v="s")], wrapper="test").entity
        res = scrub_entity(self.ca, e, ord_key="0000000000100.00000.nodeA")
        self.assertGreater(res.tx, 0)
        self.assertEqual(
            self.ca.execute("SELECT hlc FROM scrubbed WHERE e = ?", (e,)).fetchone()[0],
            "0000000000100.00000.nodeA")
        # stale datom for e (ord below tombstone) must be dropped
        r = ingest(self.ca, "nodeB", 7, "0000000000050.00000.nodeB",
                   [(e, "title", "zombie", True)])
        self.assertEqual(r.applied, 0)
        self.assertFalse(self.sa.exists(e))

    def test_remote_scrub_op_replays_locally(self):
        e = self.sb.transact([Change(e=None, a="title", v="gone")], wrapper="test").entity
        r = ingest(self.cb, "nodeA", 5, "0000000000100.00000.nodeA",
                   [], op="scrub", note=e)
        self.assertFalse(Store(self.cb).exists(e))
        self.assertTrue(self.cb.execute(
            "SELECT 1 FROM scrubbed WHERE e = ?", (e,)).fetchone())

    def test_never_sync_prefixes_blocked_both_directions(self):
        conn = self.cb
        conn.execute(
            "INSERT INTO attr (name, value_type, cardinality) VALUES ('local:pin','text','one')")
        r = ingest(conn, "nodeA", 1, "0000000000050.00000.nodeA",
                   [("e1", "local:pin", "x", True)])
        self.assertEqual(r.refused, 1)
        # and outbound: ops_since never carries it
        e = self.sa.transact([Change(e=None, a="title", v="t")], wrapper="test").entity
        self.ca.execute(
            "INSERT INTO attr (name, value_type, cardinality) VALUES ('local:x','text','one')")
        self.sa.transact([Change(e=e, a="local:x", v="1")], wrapper="store")
        # 'store' wrapper is INTERNAL — writes bypass grant checks? verify via raw
        for op in ops_since(self.ca, 0):
            for d in op["datoms"]:
                self.assertNotEqual(d["a"], "local:x")

    def test_origin_only_tail(self):
        self.sa.transact([Change(e=None, a="title", v="a")], wrapper="test")
        ingest(self.ca, "nodeZ", 1, "0000000000050.00000.nodeZ",
               [("eZ", "title", "z", True)])
        own = ops_since(self.ca, 0, origin_only=True)
        self.assertTrue(all(op["origin_actor"] is None for op in own))
        full = ops_since(self.ca, 0)
        self.assertGreater(len(full), len(own))

    def test_self_echo_no_phantom_tx(self):
        self.sa.transact([Change(e=None, a="title", v="a")], wrapper="test")
        before = self.ca.execute("SELECT COUNT(*) FROM tx").fetchone()[0]
        r = ingest(self.ca, "nodeA", 1, "0000000000050.00000.nodeA",
                   [("e1", "title", "a", True)], local_node_id="nodeA")
        after = self.ca.execute("SELECT COUNT(*) FROM tx").fetchone()[0]
        self.assertEqual(before, after)
        self.assertEqual(r.dupes, 1)

    def test_floor_tx_resync(self):
        self.ca.execute(
            "INSERT INTO meta (key, value) VALUES ('floor_tx', '10')")
        with self.assertRaises(ResyncRequired):
            ops_since(self.ca, 5)
        self.assertEqual(ops_since(self.ca, 10), [])


class TestRealPrev6Db(unittest.TestCase):
    def test_open_and_migrate(self):
        """A real pre-v6 store.db on disk must open without crashing —
        regression for schema.sql index creation running before ALTERs."""
        import sqlite3, tempfile
        from pathlib import Path
        path = Path(tempfile.mkdtemp()) / "old.db"
        raw = sqlite3.connect(str(path))
        raw.executescript("""
            CREATE TABLE entity (id TEXT PRIMARY KEY, created_tx INTEGER NOT NULL);
            CREATE TABLE attr (name TEXT PRIMARY KEY, value_type TEXT NOT NULL,
                               cardinality TEXT NOT NULL, doc TEXT NOT NULL DEFAULT '');
            CREATE TABLE tx (id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
              agent TEXT, wrapper TEXT,
              op TEXT NOT NULL CHECK (op IN ('assert','evolve','split','merge','correct','retire')),
              note TEXT);
            CREATE TABLE datom (e TEXT NOT NULL, a TEXT NOT NULL, v TEXT NOT NULL,
              tx INTEGER NOT NULL, added INTEGER NOT NULL, PRIMARY KEY (e,a,v,tx));
            CREATE TRIGGER datom_no_update BEFORE UPDATE ON datom
            BEGIN SELECT RAISE(ABORT, 'datom is append-only'); END;
            CREATE TRIGGER datom_no_delete BEFORE DELETE ON datom
            BEGIN SELECT RAISE(ABORT, 'datom is append-only'); END;
            CREATE VIEW v_current AS
            SELECT d.e, d.a, d.v, MAX(d.tx) AS tx FROM datom d
            WHERE d.added = 1 AND NOT EXISTS (
              SELECT 1 FROM datom r WHERE r.e=d.e AND r.a=d.a AND r.v=d.v
                AND r.added=0 AND r.tx>d.tx) GROUP BY d.e,d.a,d.v;
            CREATE TABLE lineage (child TEXT NOT NULL, parent TEXT NOT NULL,
              kind TEXT NOT NULL, tx INTEGER NOT NULL, reason TEXT,
              PRIMARY KEY (child,parent,kind,tx));
            CREATE TABLE kind (name TEXT PRIMARY KEY, required TEXT NOT NULL,
              optional TEXT NOT NULL DEFAULT '[]', derivations TEXT NOT NULL DEFAULT '[]');
            CREATE TABLE certificate (id INTEGER PRIMARY KEY AUTOINCREMENT,
              tier TEXT NOT NULL, subject TEXT NOT NULL, ref TEXT NOT NULL,
              corpus TEXT, result TEXT NOT NULL, code_hash TEXT NOT NULL DEFAULT '',
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
            INSERT INTO attr (name,value_type,cardinality) VALUES ('title','text','one');
            INSERT INTO tx (op,agent) VALUES ('assert','a');
            INSERT INTO entity VALUES ('e1',1);
            INSERT INTO datom (e,a,v,tx,added) VALUES ('e1','title','legacy',1,1);
            PRAGMA user_version = 5;
        """)
        raw.close()
        conn = connect(str(path))  # must not raise 'no such column: ord'
        self.assertEqual(Store(conn).view("e1"), {"title": "legacy"})
        ingest(conn, "nodeB", 1, "0000000000099.00000.nodeB",
               [("e1", "title", "synced", True)])
        self.assertEqual(Store(conn).view("e1"), {"title": "synced"})
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertGreaterEqual(ver, 7)


if __name__ == "__main__":
    unittest.main()
