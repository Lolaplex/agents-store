"""v0 audit ledger holes: append-only history, code_hash, attr registry, provenance, retire, severs."""
import sqlite3
import unittest

from agents_store import AttrSpec, Change, PutResult, connect
from agents_store.certify import certify, grant_roundtrip, register_wrapper
from agents_store.code_hash import code_hash_for_wrapper
from agents_store.grant import grant, is_writable
from agents_store.lineage import correct, evolve
from agents_store.mediator import mediate, wrapper_capability
from agents_store.registry import Registry, RegistryError
from agents_store.store import Store
from agents_store.wrappers.markdown import MarkdownWrapper
from dataclasses import dataclass


_HISTORY = ("tx", "lineage", "certificate", "grant_", "refusal", "provenance")


class TestHistoryAppendOnly(unittest.TestCase):
    def setUp(self):
        self.conn = connect()

    def test_certificate_update_aborts(self):
        cid = certify(self.conn, MarkdownWrapper(), [{"body": "b"}])
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE certificate SET result='pass' WHERE id=?", (cid,))

    def test_all_history_tables_reject_update_and_delete(self):
        for table in _HISTORY:
            conn = connect()
            conn.execute("INSERT INTO tx (op, wrapper) VALUES ('assert', 'store')")
            if table == "grant_":
                cert = certify(conn, MarkdownWrapper(), [{"body": "b"}])
                grant_roundtrip(conn, MarkdownWrapper(), cert)
            elif table == "refusal":
                conn.execute("INSERT INTO refusal (wrapper, reason) VALUES ('t', 'probe')")
            elif table == "lineage":
                store = Store(conn)
                e = store.transact([Change(e=None, a="body", v="b")], wrapper="store").entity
                conn.execute(
                    "INSERT INTO lineage (child, parent, kind, tx, reason) "
                    "VALUES (?, ?, 'wasDerivedFrom', 1, 't')",
                    (e, e),
                )
            elif table == "certificate":
                certify(conn, MarkdownWrapper(), [{"body": "b"}])
            elif table == "provenance":
                store = Store(conn)
                e = store.transact([Change(e=None, a="body", v="b")], wrapper="store").entity
                reg = Registry()
                reg.register_capability(wrapper_capability(MarkdownWrapper(), "markdown"))
                mediate(conn, reg, e, "markdown")
            with self.assertRaises(sqlite3.IntegrityError, msg=f"update {table}"):
                if table == "tx":
                    conn.execute("UPDATE tx SET note = 'tamper' WHERE id = 1")
                elif table == "lineage":
                    conn.execute("UPDATE lineage SET reason = 'tamper'")
                elif table == "certificate":
                    conn.execute("UPDATE certificate SET result = 'fail'")
                elif table == "grant_":
                    conn.execute("UPDATE grant_ SET attr = 'tamper'")
                elif table == "refusal":
                    conn.execute("UPDATE refusal SET reason = 'tamper'")
                else:
                    conn.execute("UPDATE provenance SET out_ref = 'tamper'")
            with self.assertRaises(sqlite3.IntegrityError, msg=f"delete {table}"):
                conn.execute(f"DELETE FROM {table}")


class TestCertificateCodeHash(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.w = MarkdownWrapper()

    def test_grant_rejects_stale_code_hash(self):
        certify(self.conn, self.w, [{"body": "b"}])
        bad = self.conn.execute(
            "INSERT INTO certificate (tier, subject, ref, result, code_hash) "
            "VALUES ('witness', 'wrapper:md', 't', 'pass', ?)",
            ("0" * 64,),
        ).lastrowid
        with self.assertRaises(ValueError):
            grant(self.conn, "md", "body", bad)


@dataclass
class OtherType:
    id: str = "md"
    namespace: str = "md"

    def attrs(self):
        return [AttrSpec("body", "json", doc="conflict")]

    def get(self, e, view):
        return ""

    def put(self, rep, e, view):
        return PutResult()


class TestAttrRegistryLoud(unittest.TestCase):
    def test_conflicting_attr_spec_raises(self):
        conn = connect()
        register_wrapper(conn, MarkdownWrapper())
        with self.assertRaises(RegistryError):
            register_wrapper(conn, OtherType())


class TestProvenanceTxAndRetire(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.store = Store(self.conn)

    def test_mediator_provenance_carries_tx(self):
        reg = Registry()
        reg.register_capability(wrapper_capability(MarkdownWrapper(), "markdown"))
        e = self.store.transact([Change(e=None, a="body", v="b")], wrapper="store").entity
        art = mediate(self.conn, reg, e, "markdown")
        tx = self.conn.execute(
            "SELECT tx FROM provenance WHERE mediator_id = ?", (art.mediator_id,)
        ).fetchone()[0]
        self.assertIsNotNone(tx)

    def test_retire_op_on_retract_batch(self):
        e = self.store.transact(
            [Change(e=None, a="title", v="t"), Change(e=None, a="ical:client-uid", v="u")],
            wrapper="store",
        ).entity
        self.store.transact(
            [Change(e=e, a="title", v="t", added=False),
             Change(e=e, a="ical:client-uid", v="u", added=False)],
            wrapper="store",
            op="retire",
            note="item.ics",
        )
        view = self.store.view(e)
        self.assertNotIn("title", view)
        self.assertNotIn("ical:client-uid", view)
        op = self.conn.execute(
            "SELECT op FROM tx ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        self.assertEqual(op, "retire")


class TestSeversVsEvolve(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.store = Store(self.conn)

    def test_correct_uses_severs_evolve_uses_wasRevisionOf(self):
        old = self.store.transact([Change(e=None, a="body", v="v1")], wrapper="store").entity
        new = self.store.transact([Change(e=None, a="body", v="v2")], wrapper="store").entity
        correct(self.store, new, old, reason="fix")
        kind_c = self.conn.execute(
            "SELECT kind FROM lineage WHERE child = ? AND parent = ?", (new, old)
        ).fetchone()[0]
        self.assertEqual(kind_c, "severs")
        e = self.store.transact([Change(e=None, a="body", v="b")], wrapper="store").entity
        evolve(
            self.store, e, [Change(e=e, a="body", v="c")],
            reason="rev", record_edge=True,
        )
        kind_e = self.conn.execute(
            "SELECT kind FROM lineage WHERE child = ? AND parent = ?", (e, e)
        ).fetchone()[0]
        self.assertEqual(kind_e, "wasRevisionOf")


class TestCodeHashRecorded(unittest.TestCase):
    def test_cert_stores_live_hash(self):
        conn = connect()
        w = MarkdownWrapper()
        cert = certify(conn, w, [{"body": "b"}])
        row = conn.execute(
            "SELECT code_hash FROM certificate WHERE id = ?", (cert,)
        ).fetchone()
        self.assertEqual(row[0], code_hash_for_wrapper(w))


if __name__ == "__main__":
    unittest.main()
