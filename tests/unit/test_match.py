"""match: correspondence proposals + witness certification."""
import unittest

from agents_store import Change, connect
from agents_store import match
from agents_store.certify import certify, grant_roundtrip
from agents_store.store import Store
from agents_store.wrappers.jsoncal import JsoncalWrapper
from agents_store.wrappers.markdown import MarkdownWrapper

JCAL_CORPUS = [
    {"jcal:uid": "u1", "jcal:summary": "d", "jcal:dtstart": "2026-12-01T10:00:00Z"},
]
MD_CORPUS = [{"title": "t", "body": "b"}]


def _setup():
    conn = connect()
    store = Store(conn)
    for w, corpus in ((JsoncalWrapper(), JCAL_CORPUS),
                      (MarkdownWrapper(), MD_CORPUS)):
        cert = certify(conn, w, corpus)
        grant_roundtrip(conn, w, cert)
    return conn, store


class TestPropose(unittest.TestCase):
    def test_alias_edges(self):
        conn, _ = _setup()
        ids = match.propose(conn, "jcal", "")
        edges = conn.execute(
            "SELECT a_from, a_to, kind, status FROM correspondence "
            "WHERE kind = 'equal' ORDER BY a_from").fetchall()
        self.assertEqual(
            edges,
            [("jcal:dtend", "end", "equal", "proposed"),
             ("jcal:dtstart", "when", "equal", "proposed"),
             ("jcal:status", "status", "equal", "proposed"),
             ("jcal:summary", "title", "equal", "proposed")])
        self.assertEqual(len(ids), 4)

    def test_same_name_equal(self):
        # jcal vs md share 'jcal:extra'/'md:extra' local name 'extra',
        # both json/one -> structural equal edge without any alias
        conn, _ = _setup()
        match.propose(conn, "jcal", "md")
        rows = conn.execute(
            "SELECT a_from, a_to, kind FROM correspondence").fetchall()
        self.assertIn(("jcal:extra", "md:extra", "equal"), rows)

    def test_idempotent(self):
        conn, _ = _setup()
        n1 = len(match.propose(conn, "jcal", ""))
        n2 = len(match.propose(conn, "jcal", ""))
        self.assertGreater(n1, 0)
        self.assertEqual(n2, 0)


class TestWitness(unittest.TestCase):
    def test_equal_edge_witnessed(self):
        conn, store = _setup()
        store.transact([Change(e=None, a="jcal:uid", v="u1"),
                        Change(e=None, a="jcal:dtstart",
                               v="2026-12-01T10:00:00Z")],
                       wrapper="jcal")
        ids = match.propose(conn, "jcal", "")
        want = [r[0] for r in conn.execute(
            "SELECT id FROM correspondence WHERE a_from='jcal:dtstart'")]
        cert = match.witness(conn, want)
        self.assertIsNotNone(cert)
        row = conn.execute(
            "SELECT status, certificate_id FROM correspondence WHERE id = ?",
            (want[0],)).fetchone()
        self.assertEqual(row[0], "witnessed")
        cert_row = conn.execute(
            "SELECT tier, subject, result FROM certificate WHERE id = ?",
            (row[1],)).fetchone()
        self.assertEqual(cert_row, ("witness", f"corr:{want[0]}", "pass"))
        # unselected proposals stay proposed
        others = conn.execute(
            "SELECT COUNT(*) FROM correspondence WHERE status = 'proposed'"
        ).fetchone()[0]
        self.assertEqual(others, 3)

    def test_bad_corpus_fails(self):
        conn, store = _setup()
        # a non-Z instant cannot lawfully equal-map to `when`
        store.transact([Change(e=None, a="jcal:uid", v="u1")], wrapper="jcal")
        store.conn.execute(
            "INSERT INTO datom (e, a, v, tx, added) "
            "SELECT id, 'jcal:dtstart', '2026-12-01T10:00:00+01:00', "
            "(SELECT MAX(id) FROM tx), 1 FROM entity")
        ids = match.propose(conn, "jcal", "")
        want = [r[0] for r in conn.execute(
            "SELECT id FROM correspondence WHERE a_from='jcal:dtstart'")]
        match.witness(conn, want)
        row = conn.execute(
            "SELECT status FROM correspondence WHERE id = ?",
            (want[0],)).fetchone()
        self.assertEqual(row[0], "proposed")
        fail = conn.execute(
            "SELECT result FROM certificate WHERE subject = ?",
            (f"corr:{want[0]}",)).fetchone()
        self.assertEqual(fail[0], "fail")

    def test_non_equal_not_witnessed(self):
        conn, _ = _setup()
        # hand-plant a refines edge
        conn.execute(
            "INSERT INTO correspondence (a_from, a_to, kind) "
            "VALUES ('jcal:dtstart', 'when', 'refines')")
        cid = conn.execute("SELECT MAX(id) FROM correspondence").fetchone()[0]
        match.witness(conn, [cid])
        self.assertEqual(conn.execute(
            "SELECT status FROM correspondence WHERE id = ?",
            (cid,)).fetchone()[0], "proposed")


if __name__ == "__main__":
    unittest.main()
