"""JSON file adapter: sync between an export file and the store."""
import json
import tempfile
import unittest
from pathlib import Path

from agents_store import connect
from agents_store.adapters import jsonfile
from agents_store.certify import certify, grant_roundtrip
from agents_store.store import Store
from agents_store.wrappers.jsoncal import JsoncalWrapper

CORPUS = [
    {"jcal:uid": "u1", "jcal:summary": "d", "jcal:dtstart": "2026-12-01T10:00:00Z"},
    {"jcal:uid": "u2", "jcal:summary": "s", "jcal:status": "confirmed",
     "jcal:extra": {"category": ["x"]}},
]


class JsonfileCase(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.store = Store(self.conn)
        self.w = JsoncalWrapper()
        cert = certify(self.conn, self.w, CORPUS)
        grant_roundtrip(self.conn, self.w, cert)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "export.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, items):
        self.path.write_text(json.dumps(items), encoding="utf-8")

    def entities(self):
        return {r[0] for r in self.conn.execute(
            "SELECT DISTINCT e FROM v_current WHERE a LIKE 'jcal:%'")}


class TestIngest(JsonfileCase):
    def test_items_mint_entities(self):
        self.write([
            {"uid": "abc-1", "summary": "dentist",
             "dtstart": "2026-12-01T10:00:00Z"},
            {"uid": "abc-2", "summary": "standup", "status": "confirmed"},
        ])
        rep = jsonfile.sync(self.store, self.path)
        self.assertFalse(rep.refusals, rep.refusals)
        self.assertEqual(rep.created, 2)
        self.assertEqual(len(self.entities()), 2)
        e = self.conn.execute(
            "SELECT e FROM v_current WHERE a='jcal:uid' AND v='abc-1'"
        ).fetchone()[0]
        view = self.store.view(e)
        self.assertEqual(view["jcal:summary"], "dentist")
        self.assertEqual(view["jcal:dtstart"], "2026-12-01T10:00:00Z")
        self.assertIn(f"export.json#abc-1", view["jcal:path"])

    def test_edit_same_uid_updates_same_entity(self):
        self.write([{"uid": "abc-1", "summary": "dentist"}])
        jsonfile.sync(self.store, self.path)
        e = self.conn.execute(
            "SELECT e FROM v_current WHERE a='jcal:uid' AND v='abc-1'"
        ).fetchone()[0]
        self.write([{"uid": "abc-1", "summary": "dentist (moved)",
                     "dtstart": "2026-12-02T10:00:00Z"}])
        rep = jsonfile.sync(self.store, self.path)
        self.assertEqual(rep.created, 0)
        view = self.store.view(e)
        self.assertEqual(view["jcal:summary"], "dentist (moved)")
        self.assertEqual(view["jcal:dtstart"], "2026-12-02T10:00:00Z")

    def test_removed_item_retracts_path_keeps_entity(self):
        self.write([{"uid": "a", "summary": "x"}, {"uid": "b", "summary": "y"}])
        jsonfile.sync(self.store, self.path)
        e_b = self.conn.execute(
            "SELECT e FROM v_current WHERE a='jcal:uid' AND v='b'").fetchone()[0]
        self.write([{"uid": "a", "summary": "x"}])
        jsonfile.sync(self.store, self.path)
        view = self.store.view(e_b)
        self.assertEqual(view["jcal:summary"], "y")      # entity survives
        self.assertNotIn("jcal:path", view)               # but left the file
        n = self.conn.execute(
            "SELECT COUNT(*) FROM datom WHERE e=? AND a='jcal:path'",
            (e_b,)).fetchone()[0]
        self.assertEqual(n, 2)                            # assert + retract

    def test_malformed_item_refused_others_land(self):
        self.write([{"uid": "ok", "summary": "x"},
                    "not-an-object",
                    {"uid": "ok2", "summary": "y"}])
        rep = jsonfile.sync(self.store, self.path)
        self.assertEqual(rep.created, 2)
        self.assertTrue(any(r.reason == "parse-fail" for r in rep.refusals))
        rows = self.conn.execute(
            "SELECT reason FROM refusal WHERE wrapper='jcal'").fetchall()
        self.assertIn(("parse-fail",), rows)

    def test_garbage_file_refused(self):
        self.path.write_text("{not json", encoding="utf-8")
        rep = jsonfile.sync(self.store, self.path)
        self.assertEqual(rep.created, 0)
        self.assertTrue(any(r.reason == "parse-fail" for r in rep.refusals))

    def test_no_uid_mints_then_stable(self):
        self.write([{"summary": "no id here"}])
        rep = jsonfile.sync(self.store, self.path)
        self.assertEqual(rep.created, 1)
        # second sync: the re-exported item carries uid=<entity id>
        rep2 = jsonfile.sync(self.store, self.path)
        self.assertEqual(rep2.created, 0)
        self.assertEqual(len(self.entities()), 1)


class TestWriteBack(JsonfileCase):
    def test_file_rewritten_canonical(self):
        self.write([{"uid": "b", "summary": "y", "weird": True},
                    {"uid": "a", "summary": "x"}])
        jsonfile.sync(self.store, self.path)
        data = json.loads(self.path.read_text())
        self.assertEqual([it["uid"] for it in data], ["a", "b"])  # sorted
        self.assertEqual(data[1]["weird"], True)                  # extra kept

    def test_roundtrip_converges(self):
        self.write([{"uid": "a", "summary": "x",
                     "dtstart": "2026-12-01T10:00:00Z"}])
        jsonfile.sync(self.store, self.path)
        first = self.path.read_text()
        rep = jsonfile.sync(self.store, self.path)
        self.assertFalse(rep.written)   # stable: no rewrite needed
        self.assertEqual(self.path.read_text(), first)


if __name__ == "__main__":
    unittest.main()
