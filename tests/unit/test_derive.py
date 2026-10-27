"""derive: generated mediators materialize derived attrs + provenance."""
import json
import unittest

from agents_store import Change, connect, derive, match
from agents_store.certify import certify, grant_roundtrip
from agents_store.store import Store
from agents_store.wrappers.jsoncal import JsoncalWrapper

CORPUS = [
    {"jcal:uid": "u1", "jcal:summary": "d", "jcal:dtstart": "2026-12-01T10:00:00Z"},
]


def _setup(witnessed=("jcal:dtstart", "jcal:summary")):
    conn = connect()
    store = Store(conn)
    cert = certify(conn, JsoncalWrapper(), CORPUS)
    grant_roundtrip(conn, JsoncalWrapper(), cert)
    match.propose(conn, "jcal", "")
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM correspondence WHERE a_from IN "
        f"({','.join('?' * len(witnessed))})", witnessed)]
    match.witness(conn, ids)
    return conn, store


class TestGenerate(unittest.TestCase):
    def test_exact_when_all_witnessed_equal(self):
        conn, _ = _setup()
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM correspondence WHERE status='witnessed'")]
        mid = derive.generate(conn, "jcal", ids)
        self.assertEqual(conn.execute(
            "SELECT exactness FROM mediator WHERE id = ?", (mid,)
        ).fetchone()[0], "exact")

    def test_contained_when_unwitnessed(self):
        conn, _ = _setup()
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM correspondence")]  # some still 'proposed'
        mid = derive.generate(conn, "jcal", ids)
        self.assertEqual(conn.execute(
            "SELECT exactness FROM mediator WHERE id = ?", (mid,)
        ).fetchone()[0], "contained")

    def test_empty_path_refused(self):
        conn, _ = _setup()
        with self.assertRaises(ValueError):
            derive.generate(conn, "jcal", [])


class TestMaterialize(unittest.TestCase):
    def test_derived_attrs_land_with_provenance(self):
        conn, store = _setup()
        e = store.transact([
            Change(e=None, a="jcal:uid", v="u1"),
            Change(e=None, a="jcal:dtstart", v="2026-12-01T10:00:00Z"),
        ], wrapper="jcal").entity
        mid = derive.generate(conn, "jcal", [r[0] for r in conn.execute(
            "SELECT id FROM correspondence WHERE status='witnessed'")])
        rep = derive.run(store, mid)
        self.assertEqual(rep["derived"], 1)   # only dtstart->when
        view = store.view(e)
        self.assertEqual(view["when"], "2026-12-01T10:00:00Z")
        self.assertEqual(derive.is_derived(conn, e, "when"), mid)
        prov = conn.execute(
            "SELECT out_ref, in_refs, mediator_id FROM provenance").fetchone()
        self.assertEqual(json.loads(prov[0]), {"e": e, "a": "when"})
        self.assertEqual(json.loads(prov[1]), [{"e": e, "a": "jcal:dtstart"}])
        self.assertEqual(prov[2], mid)
        # kinds: the entity is structurally an event now — every existing
        # projection picks it up for free
        kinds = {r[0] for r in conn.execute(
            "SELECT name FROM kind").fetchall()}
        self.assertIn("when", view)  # membership is the attr itself

    def test_source_edit_auto_rederives(self):
        conn, store = _setup()
        e = store.transact([
            Change(e=None, a="jcal:uid", v="u1"),
            Change(e=None, a="jcal:dtstart", v="2026-12-01T10:00:00Z"),
        ], wrapper="jcal").entity
        mid = derive.generate(conn, "jcal", [r[0] for r in conn.execute(
            "SELECT id FROM correspondence WHERE status='witnessed'")])
        derive.run(store, mid)
        # a normal tx on the source attr (adapter-shaped) -> derived moves
        store.transact([Change(e=e, a="jcal:dtstart",
                               v="2026-12-03T10:00:00Z")], wrapper="jcal")
        self.assertEqual(store.view(e)["when"], "2026-12-03T10:00:00Z")
        txs = conn.execute(
            "SELECT note FROM tx WHERE note LIKE 'mediator%'").fetchall()
        self.assertTrue(txs)
        # history keeps everything: old derived value retracted, not lost
        hist = [d for d in store.history(e) if d.a == "when"]
        self.assertEqual(len(hist), 3)  # assert, retract, assert

    def test_source_retract_removes_derived(self):
        conn, store = _setup()
        e = store.transact([
            Change(e=None, a="jcal:uid", v="u1"),
            Change(e=None, a="jcal:dtstart", v="2026-12-01T10:00:00Z"),
        ], wrapper="jcal").entity
        mid = derive.generate(conn, "jcal", [r[0] for r in conn.execute(
            "SELECT id FROM correspondence WHERE status='witnessed'")])
        derive.run(store, mid)
        store.transact([Change(e=e, a="jcal:dtstart",
                               v="2026-12-01T10:00:00Z", added=False)],
                       wrapper="jcal")
        self.assertNotIn("when", store.view(e))
        self.assertIsNone(derive.is_derived(conn, e, "when"))

    def test_native_value_conflict_refused(self):
        conn, store = _setup()
        # native `when` (internal write) + jcal source -> mediator must
        # not clobber the native value
        e = store.transact([
            Change(e=None, a="when", v="2026-01-01T00:00:00Z"),
            Change(e=None, a="jcal:dtstart", v="2026-12-01T10:00:00Z"),
        ], wrapper="store").entity
        mid = derive.generate(conn, "jcal", [r[0] for r in conn.execute(
            "SELECT id FROM correspondence WHERE status='witnessed'")])
        rep = derive.run(store, mid)
        self.assertEqual(rep["conflicts"], 1)
        self.assertEqual(store.view(e)["when"], "2026-01-01T00:00:00Z")
        rows = conn.execute(
            "SELECT reason FROM refusal WHERE reason='mediator_conflict'"
        ).fetchall()
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
