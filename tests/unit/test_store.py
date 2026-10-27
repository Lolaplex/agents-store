"""Store.transact / view / history / refusals — grant enforcement (default-deny)."""
import unittest

from agents_store import Change, connect
from agents_store.code_hash import code_hash_for_impl_ref
from agents_store.grant import grant, is_writable
from agents_store.store import Store, TxResult

_IMPL = "agents_store.wrappers.markdown.MarkdownWrapper"
_CODE_HASH = code_hash_for_impl_ref(_IMPL)


def _cert(conn, subject="wrapper:test", result="pass"):
    return conn.execute(
        "INSERT INTO certificate (tier, subject, ref, result, code_hash) "
        "VALUES ('witness', ?, 't', ?, ?)",
        (subject, result, _CODE_HASH),
    ).lastrowid


def _wrapper(conn, wid="test"):
    conn.execute(
        "INSERT INTO wrapper (id, namespace, impl_ref) VALUES (?, 'test', ?)",
        (wid, _IMPL),
    )


def grant_attrs(conn, wid, attrs):
    _wrapper(conn, wid)
    cert = _cert(conn, f"wrapper:{wid}")
    for a in attrs:
        grant(conn, wid, a, cert)


class TestTransact(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.store = Store(self.conn)

    def test_create_entity_one_tx(self):
        grant_attrs(self.conn, "test", ["title", "body"])
        r = self.store.transact(
            [Change(e=None, a="title", v="x"), Change(e=None, a="body", v="b")],
            wrapper="test",
        )
        self.assertIsNotNone(r.entity)
        self.assertTrue(self.store.exists(r.entity))
        self.assertEqual(self.store.view(r.entity), {"title": "x", "body": "b"})
        self.assertEqual(len({d.tx for d in self.store.history(r.entity)}), 1)

    def test_cardinality_one_retracts_prior(self):
        grant_attrs(self.conn, "test", ["title"])
        e = self.store.transact([Change(e=None, a="title", v="a")], wrapper="test").entity
        self.store.transact([Change(e=e, a="title", v="b")], wrapper="test")
        self.assertEqual(self.store.view(e)["title"], "b")
        kinds = [(d.v, d.added) for d in self.store.history(e)]
        self.assertIn(("a", True), kinds)
        self.assertIn(("a", False), kinds)
        self.assertIn(("b", True), kinds)

    def test_no_op_reassert_skipped(self):
        grant_attrs(self.conn, "test", ["title"])
        e = self.store.transact([Change(e=None, a="title", v="a")], wrapper="test").entity
        r = self.store.transact([Change(e=e, a="title", v="a")], wrapper="test")
        self.assertEqual(r.applied, ())
        self.assertEqual(len(self.store.history(e)), 1)

    def test_default_deny(self):
        # 'title' NOT granted for wrapper 'test'
        _wrapper(self.conn)
        e = self.store.transact(
            [Change(e=None, a="title", v="x")], wrapper="store"
        ).entity  # store is internal authority
        r = self.store.transact([Change(e=e, a="title", v="y")], wrapper="test")
        self.assertEqual(len(r.refusals), 1)
        self.assertEqual(r.refusals[0].reason, "no-grant")
        self.assertEqual(self.store.view(e)["title"], "x")  # unchanged
        row = self.conn.execute("SELECT reason FROM refusal").fetchone()
        self.assertEqual(row[0], "no-grant")

    def test_grant_then_write(self):
        _wrapper(self.conn)
        e = self.store.transact([Change(e=None, a="title", v="x")], wrapper="store").entity
        cert = _cert(self.conn)
        grant(self.conn, "test", "title", cert)
        self.assertTrue(is_writable(self.conn, "test", "title"))
        r = self.store.transact([Change(e=e, a="title", v="y")], wrapper="test")
        self.assertEqual(r.refusals, ())
        self.assertEqual(self.store.view(e)["title"], "y")

    def test_unknown_attr_refused_not_fk_crash(self):
        _wrapper(self.conn)
        e = self.store.transact([Change(e=None, a="title", v="x")], wrapper="store").entity
        r = self.store.transact([Change(e=e, a="bogus:attr", v="v")], wrapper="test")
        self.assertEqual(r.refusals[0].reason, "unknown-attr")

    def test_unknown_entity_refused(self):
        _wrapper(self.conn)
        r = self.store.transact([Change(e="noentity", a="title", v="x")], wrapper="test")
        self.assertEqual(r.refusals[0].reason, "unknown-entity")

    def test_internal_wrapper_bypasses_grants(self):
        # 'store' needs no grant_ rows — substrate authority for identity ops
        r = self.store.transact([Change(e=None, a="title", v="x")], wrapper="store")
        self.assertEqual(r.refusals, ())

    def test_retraction(self):
        grant_attrs(self.conn, "test", ["status"])
        e = self.store.transact([Change(e=None, a="status", v="open")], wrapper="test").entity
        r = self.store.transact([Change(e=e, a="status", v="open", added=False)], wrapper="test")
        self.assertEqual(self.store.view(e).get("status"), None)
        self.assertEqual(r.applied[-1].added, False)

    def test_view_asof_tx(self):
        grant_attrs(self.conn, "test", ["title"])
        e = self.store.transact([Change(e=None, a="title", v="a")], wrapper="test").entity
        tx1 = self.conn.execute("SELECT MAX(tx) FROM datom").fetchone()[0]
        self.store.transact([Change(e=e, a="title", v="b")], wrapper="test")
        self.assertEqual(self.store.view(e, tx=tx1)["title"], "a")
        self.assertEqual(self.store.view(e)["title"], "b")

    def test_many_cardinality(self):
        grant_attrs(self.conn, "test", ["md:path"])
        e = self.store.transact(
            [Change(e=None, a="md:path", v="a.md"), Change(e=None, a="md:path", v="b.md")],
            wrapper="test",
        ).entity
        self.assertEqual(set(self.store.view(e)["md:path"]), {"a.md", "b.md"})

    def test_refusals_query_filters_entity(self):
        _wrapper(self.conn)
        e = self.store.transact([Change(e=None, a="title", v="x")], wrapper="store").entity
        self.store.transact([Change(e=e, a="status", v="open")], wrapper="test")
        self.assertEqual(len(self.store.refusals(e)), 1)
        self.assertEqual(len(self.store.refusals()), 1)


class TestGrantAPI(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        _wrapper(self.conn)

    def test_grant_requires_pass_cert(self):
        fail_cert = self.conn.execute(
            "INSERT INTO certificate (tier, subject, ref, result, code_hash) "
            "VALUES ('witness','x','t','fail', ?)",
            (_CODE_HASH,),
        ).lastrowid
        with self.assertRaises(ValueError):
            grant(self.conn, "test", "title", fail_cert)

    def test_grant_unknown_cert_raises(self):
        with self.assertRaises(ValueError):
            grant(self.conn, "test", "title", 9999)

    def test_not_writable_without_grant(self):
        self.assertFalse(is_writable(self.conn, "test", "title"))

    def test_writable_after_grant(self):
        cert = _cert(self.conn)
        grant(self.conn, "test", "title", cert)
        self.assertTrue(is_writable(self.conn, "test", "title"))
        self.assertFalse(is_writable(self.conn, "test", "status"))


class TestTransactPreassignedEntity(unittest.TestCase):
    """entity= / tx_changes= (used by the MORe store bridge)."""

    def setUp(self):
        self.conn = connect()
        self.store = Store(self.conn)

    def test_entity_param_uses_given_id(self):
        r = self.store.transact([Change(None, "title", "x")], wrapper="store", entity="EID-1")
        self.assertEqual(r.entity, "EID-1")
        self.assertEqual(self.store.view("EID-1")["title"], "x")
        row = self.conn.execute("SELECT created_tx FROM entity WHERE id = 'EID-1'").fetchone()
        self.assertEqual(row[0], r.tx)

    def test_entity_param_refuses_existing_id(self):
        self.store.transact([Change(None, "title", "x")], wrapper="store", entity="EID-1")
        txs = self.conn.execute("SELECT COUNT(*) FROM tx").fetchone()[0]
        with self.assertRaises(ValueError):
            self.store.transact([Change(None, "title", "y")], wrapper="store", entity="EID-1")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM tx").fetchone()[0], txs)

    def test_tx_changes_see_own_tx_and_land_in_it(self):
        r = self.store.transact(
            [Change(None, "title", "x")], wrapper="store", entity="EID-2",
            tx_changes=lambda tx, e: [Change(None, "more:pin", f"{e}@{tx}")])
        self.assertEqual(self.store.view("EID-2")["more:pin"], (f"EID-2@{r.tx}",))
        self.assertEqual({d.tx for d in self.store.history("EID-2")}, {r.tx})

    def test_tx_changes_internal_only(self):
        with self.assertRaises(ValueError):
            self.store.transact([], wrapper="test", tx_changes=lambda tx, e: [])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM tx").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
