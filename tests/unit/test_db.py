"""Schema/bootstrap contract tests. The store itself is T01; this file owns only bootstrap."""
import sqlite3
import unittest

from agents_store import connect


class TestBootstrap(unittest.TestCase):
    def setUp(self):
        self.conn = connect()

    def test_connect_is_idempotent(self):
        conn = connect()
        conn.execute("SELECT 1")
        conn.close()

    def test_tables_exist(self):
        names = {
            r[0]
            for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        for expected in (
            "entity", "attr", "tx", "datom", "v_current", "lineage", "kind",
            "certificate", "wrapper", "grant_", "correspondence", "capability",
            "mediator", "provenance", "refusal",
        ):
            self.assertIn(expected, names)

    def test_core_attrs_seeded(self):
        attrs = {r[0] for r in self.conn.execute("SELECT name FROM attr")}
        self.assertTrue({"title", "body", "when", "end", "status", "md:path"} <= attrs)

    def test_core_kinds_seeded(self):
        kinds = {r[0] for r in self.conn.execute("SELECT name FROM kind")}
        self.assertTrue({"event", "task", "note"} <= kinds)

    def test_foreign_keys_enforced(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO datom (e, a, v, tx, added) VALUES ('noent','title','x',1,1)"
            )

    def test_datom_is_append_only(self):
        cur = self.conn.execute(
            "INSERT INTO tx (op, agent) VALUES ('assert','test') RETURNING id"
        )
        tx = cur.fetchone()[0]
        self.conn.execute("INSERT INTO entity (id, created_tx) VALUES ('e1', ?)", (tx,))
        self.conn.execute(
            "INSERT INTO datom (e,a,v,tx,added) VALUES ('e1','title','x',?,1)", (tx,)
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE datom SET v = 'y' WHERE e = 'e1'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM datom WHERE e = 'e1'")


if __name__ == "__main__":
    unittest.main()
