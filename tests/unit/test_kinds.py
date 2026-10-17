"""kinds.of / kinds.gaps — multiplicative, structural membership."""
import unittest

from agents_store import Change, connect, kinds
from agents_store.code_hash import code_hash_for_impl_ref
from agents_store.grant import grant
from agents_store.store import Store

_IMPL = "agents_store.wrappers.markdown.MarkdownWrapper"


def grant_attrs(conn, wid, attrs):
    conn.execute(
        "INSERT INTO wrapper (id, namespace, impl_ref) VALUES (?, 't', ?)", (wid, _IMPL)
    )
    cert = conn.execute(
        "INSERT INTO certificate (tier, subject, ref, result, code_hash) "
        "VALUES ('witness', 'w', 'r', 'pass', ?)",
        (code_hash_for_impl_ref(_IMPL),),
    ).lastrowid
    for a in attrs:
        grant(conn, wid, a, cert)


def make_entity(store, attrs):
    changes = [Change(e=None, a=a, v=v) for a, v in attrs.items()]
    return store.transact(changes, wrapper="test").entity


class TestKinds(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.store = Store(self.conn)
        grant_attrs(self.conn, "test", ["title", "body", "status", "when", "end"])

    def test_note_membership(self):
        e = make_entity(self.store, {"body": "b"})
        self.assertEqual(kinds.of(self.conn, e), {"note"})

    def test_note_becomes_task_same_id(self):
        # A9 half one: adding status to a note makes it task-like, no mint.
        e = make_entity(self.store, {"body": "b"})
        self.store.transact([Change(e=e, a="status", v="open")], wrapper="test")
        self.assertEqual(kinds.of(self.conn, e), {"note", "task"})

    def test_multiplicative_event_and_task(self):
        e = make_entity(self.store, {"body": "b", "status": "open", "when": "2026-10-12T10:00:00Z"})
        self.assertEqual(kinds.of(self.conn, e), {"note", "task", "event"})

    def test_empty_entity_no_kinds(self):
        tx = self.conn.execute("INSERT INTO tx (op, wrapper) VALUES ('assert', 't')").lastrowid
        self.conn.execute("INSERT INTO entity (id, created_tx) VALUES ('empty1', ?)", (tx,))
        self.assertEqual(kinds.of(self.conn, "empty1"), set())

    def test_gaps_derivable_end(self):
        e = make_entity(self.store, {"when": "2026-10-12T10:00:00Z"})
        g = kinds.gaps(self.conn, e, "event")
        self.assertTrue(g.member)
        self.assertIn("end", g.derivable)
        self.assertEqual(g.missing, ())

    def test_gaps_missing_not_derivable(self):
        e = make_entity(self.store, {"body": "b"})
        g = kinds.gaps(self.conn, e, "task")
        self.assertFalse(g.member)
        self.assertIn("status", g.missing)

    def test_gaps_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            kinds.gaps(self.conn, "x", "nosuch")


if __name__ == "__main__":
    unittest.main()
