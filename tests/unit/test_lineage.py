"""lineage ops: split / merge / correct / evolve — A9."""
import unittest

from agents_store import Change, connect, lineage
from agents_store.store import Store


def make(store, attrs):
    return store.transact(
        [Change(e=None, a=a, v=v) for a, v in attrs.items()], wrapper="store"
    ).entity


def edges(conn, child=None, parent=None, kind=None):
    sql = "SELECT child, parent, kind FROM lineage WHERE 1=1"
    params = []
    if child:
        sql += " AND child = ?"; params.append(child)
    if parent:
        sql += " AND parent = ?"; params.append(parent)
    if kind:
        sql += " AND kind = ?"; params.append(kind)
    return conn.execute(sql, params).fetchall()


class TestSplit(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.store = Store(self.conn)

    def test_split_mints_child_with_edge(self):
        # A9: split -> new id + wasDerivedFrom edge, parent intact.
        e = make(self.store, {"title": "n", "body": "b", "status": "open"})
        children = lineage.split(self.store, e, [["title", "body"]], reason="extract task")
        self.assertEqual(len(children), 1)
        c = children[0]
        self.assertNotEqual(c, e)
        self.assertEqual(edges(self.conn, child=c, parent=e, kind="wasDerivedFrom"), [(c, e, "wasDerivedFrom")])
        self.assertEqual(self.store.view(c)["body"], "b")
        self.assertNotIn("status", self.store.view(c))
        self.assertEqual(self.store.view(e)["status"], "open")  # parent untouched

    def test_split_two_children(self):
        e = make(self.store, {"body": "b", "status": "open"})
        kids = lineage.split(self.store, e, [["body"], ["status"]], reason="halve")
        self.assertEqual(len(kids), 2)
        self.assertEqual(len(edges(self.conn, parent=e)), 2)

    def test_split_unknown_parent_raises(self):
        with self.assertRaises(ValueError):
            lineage.split(self.store, "ghost", [["body"]], reason="x")

    def test_split_op_recorded(self):
        e = make(self.store, {"body": "b"})
        lineage.split(self.store, e, [["body"]], reason="r")
        self.assertEqual(self.conn.execute("SELECT op FROM tx WHERE op='split'").fetchone()[0], "split")


class TestMerge(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.store = Store(self.conn)

    def test_merge_union_and_edges(self):
        a = make(self.store, {"title": "a", "body": "ba"})
        b = make(self.store, {"status": "open", "body": "bb"})
        s = lineage.merge(self.store, [a, b], reason="dedup")
        self.assertEqual(len(edges(self.conn, child=s)), 2)
        v = self.store.view(s)
        self.assertEqual(v["title"], "a")
        self.assertEqual(v["status"], "open")

    def test_merge_conflict_canonicalizes_to_max(self):
        # Conflicting cardinality-one values are canonicalized the same way
        # ingest does (max(v) wins, losers logged as conflict refusals) —
        # writing all values at one ord would diverge from every peer.
        a = make(self.store, {"title": "first"})
        b = make(self.store, {"title": "second"})
        s = lineage.merge(self.store, [a, b], reason="dup titles")
        hist = [d.v for d in self.store.history(s) if d.added]
        self.assertEqual(hist, ["second"])
        cur = self.conn.execute(
            "SELECT v FROM v_current WHERE e = ? AND a = 'title' ORDER BY v", (s,)
        ).fetchall()
        self.assertEqual([r[0] for r in cur], ["second"])
        self.assertEqual(self.store.view(s)["title"], "second")
        # the dropped candidate is a loud refusal, not silent resolution
        rows = self.conn.execute(
            "SELECT entity, attr, payload FROM refusal WHERE reason = 'merge_conflict'"
        ).fetchall()
        self.assertEqual(rows, [(s, "title", "first")])

    def test_merge_choose(self):
        a = make(self.store, {"title": "first"})
        b = make(self.store, {"title": "second"})
        s = lineage.merge(self.store, [a, b], reason="dup", choose={"title": "first"})
        self.assertEqual(self.store.view(s)["title"], "first")
        self.assertEqual(len(self.store.history(s)), 1)

    def test_merge_sources_unchanged(self):
        a = make(self.store, {"title": "a"})
        b = make(self.store, {"title": "b"})
        lineage.merge(self.store, [a, b], reason="x")
        self.assertEqual(self.store.view(a)["title"], "a")
        self.assertEqual(self.store.view(b)["title"], "b")


class TestCorrectEvolve(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.store = Store(self.conn)

    def test_correct_records_revision_edge(self):
        old = make(self.store, {"body": "v1"})
        new = make(self.store, {"body": "v2"})
        lineage.correct(self.store, new, old, reason="typo fix")
        self.assertEqual(edges(self.conn, child=new, parent=old), [(new, old, "severs")])
        self.assertEqual(lineage.superseded_by(self.store, old), new)
        self.assertEqual(self.store.view(old)["body"], "v1")  # superseded stays readable

    def test_evolve_same_id_revision(self):
        e = make(self.store, {"status": "open"})
        r = lineage.evolve(self.store, e, [Change(e=e, a="status", v="done")], reason="finished")
        self.assertEqual(self.store.view(e)["status"], "done")
        self.assertEqual(r.entity, None)  # no new entity
        self.assertEqual(self.conn.execute("SELECT op FROM tx WHERE id=?", (r.tx,)).fetchone()[0], "evolve")

    def test_evolve_self_edge_optional(self):
        e = make(self.store, {"status": "open"})
        lineage.evolve(self.store, e, [Change(e=e, a="status", v="done")], reason="r", record_edge=True)
        self.assertEqual(edges(self.conn, child=e, parent=e), [(e, e, "wasRevisionOf")])


if __name__ == "__main__":
    unittest.main()
