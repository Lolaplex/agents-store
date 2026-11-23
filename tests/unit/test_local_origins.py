"""ops_since(origin_only=True, local_origins=...) echo filter + thread-shared connect."""
import threading
import unittest

from agents_store import connect
from agents_store.ingest import ingest, ops_since

from tests.unit.test_distributed import make_node


def _actors(conn, **kw):
    return [op["origin_actor"] for op in ops_since(conn, 0, origin_only=True, **kw)]


class TestLocalOrigins(unittest.TestCase):
    def setUp(self):
        self.conn, self.store = make_node("nodeA")
        ingest(self.conn, "proj:s1@hostA", 1, "", [("e1", "title", "a", True)])
        ingest(self.conn, "remote-node", 1, "", [("e2", "title", "b", True)])
        ingest(self.conn, "pr%j:x", 1, "", [("e3", "title", "c", True)])
        ingest(self.conn, "prXj:y", 1, "", [("e4", "title", "d", True)])
        ingest(self.conn, "it's:z", 1, "", [("e5", "title", "e", True)])

    def test_default_excludes_all_ingested(self):
        self.assertEqual(_actors(self.conn), [])

    def test_prefix_marks_ingest_as_local(self):
        self.assertEqual(_actors(self.conn, local_origins=("proj:",)),
                         ["proj:s1@hostA"])

    def test_foreign_origin_never_local(self):
        got = _actors(self.conn, local_origins=("proj:", "bind:"))
        self.assertNotIn("remote-node", got)

    def test_like_wildcards_are_literal(self):
        # `%` / `_` must not act as LIKE wildcards
        self.assertEqual(_actors(self.conn, local_origins=("pr%j:",)), ["pr%j:x"])
        self.assertEqual(_actors(self.conn, local_origins=("pr_j:",)), [])

    def test_quote_in_prefix_is_safe(self):
        self.assertEqual(_actors(self.conn, local_origins=("it's",)), ["it's:z"])

    def test_empty_prefix_ignored(self):
        self.assertEqual(_actors(self.conn, local_origins=("",)), [])

    def test_origin_only_false_ignores_local_origins(self):
        all_ops = ops_since(self.conn, 0, local_origins=("proj:",))
        self.assertEqual(len(all_ops), 5)


class TestThreadSharedConnect(unittest.TestCase):
    def test_default_conn_rejects_other_thread(self):
        conn = connect()
        err = []

        def run():
            try:
                conn.execute("SELECT 1").fetchone()
            except Exception as exc:  # noqa: BLE001
                err.append(exc)

        t = threading.Thread(target=run)
        t.start()
        t.join()
        self.assertTrue(err)

    def test_shared_conn_usable_from_other_thread(self):
        conn = connect(check_same_thread=False)
        out = []
        t = threading.Thread(target=lambda: out.append(
            conn.execute("SELECT 1").fetchone()[0]))
        t.start()
        t.join()
        self.assertEqual(out, [1])


if __name__ == "__main__":
    unittest.main()
