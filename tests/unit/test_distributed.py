"""Distributed semantics: ord-keyed v_current, remote ingest, scrub.

Simulates the agents-sync distributor verbatim: pull ops_since(cursor) on
the source, ingest() into the destination with the sender's node id.
Delivery may drop, duplicate, reorder — convergence is the assertion.
"""
import unittest

from agents_store import Change, connect
from agents_store.code_hash import code_hash_for_impl_ref
from agents_store.grant import grant
from agents_store.ingest import cursor, ingest, ops_since
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


if __name__ == "__main__":
    unittest.main()
