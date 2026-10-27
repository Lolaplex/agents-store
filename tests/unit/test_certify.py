"""certify: lens-law checking -> certificate rows -> grants (default-deny stays)."""
import json
import unittest
from dataclasses import dataclass

from agents_store import AttrSpec, Change, PutResult, Refusal, connect
from agents_store.certify import apply, certify, check_lens, grant_roundtrip
from agents_store.grant import is_writable
from agents_store.store import Store


@dataclass
class Lossless:
    """JSON round-trip wrapper: get renders declared attrs as json; put diffs."""
    id: str = "ll"
    namespace: str = "ll"

    def attrs(self):
        return [AttrSpec("ll:x", "text"), AttrSpec("ll:y", "text")]

    def get(self, e, view):
        return json.dumps({a: view.get(a) for a in ("ll:x", "ll:y")}, sort_keys=True)

    def put(self, rep, e, view):
        target = json.loads(rep)
        changes = []
        for a in ("ll:x", "ll:y"):
            cur = None if view is None else view.get(a)
            if target.get(a) != cur:
                changes.append(Change(e=e, a=a, v=target.get(a)))
        return PutResult(changes=tuple(changes))


@dataclass
class SpuriousPut(Lossless):
    """Violates GetPut: always proposes a change."""
    id: str = "sp"

    def put(self, rep, e, view):
        r = super().put(rep, e, view)
        return PutResult(changes=r.changes + (Change(e=e, a="ll:x", v="__spurious__"),))


@dataclass
class DropsAttr(Lossless):
    """Violates PutGet: never proposes ll:y."""
    id: str = "dp"

    def put(self, rep, e, view):
        target = json.loads(rep)
        changes = []
        a = "ll:x"
        cur = None if view is None else view.get(a)
        if target.get(a) != cur:
            changes.append(Change(e=e, a=a, v=target.get(a)))
        return PutResult(changes=tuple(changes))


CORPUS = [
    {"ll:x": "a", "ll:y": "1"},
    {"ll:x": "b", "ll:y": "2"},
    {"ll:x": "c"},
]


class TestCheckLens(unittest.TestCase):
    def test_lossless_passes(self):
        r = check_lens(Lossless(), CORPUS)
        self.assertTrue(r.passed, r.failures)
        self.assertEqual(set(r.attrs_checked), {"ll:x", "ll:y"})

    def test_getput_violation_named(self):
        r = check_lens(SpuriousPut(), CORPUS)
        self.assertFalse(r.passed)
        self.assertTrue(any("GetPut" in f for f in r.failures))

    def test_putget_violation_named(self):
        r = check_lens(DropsAttr(), CORPUS)
        self.assertFalse(r.passed)
        self.assertTrue(any("PutGet[ll:y]" in f for f in r.failures))


class TestApply(unittest.TestCase):
    def test_set_and_remove(self):
        v = apply({"a": 1}, [Change(e="e", a="a", v=2), Change(e="e", a="b", v=3)])
        self.assertEqual(v, {"a": 2, "b": 3})
        v2 = apply(v, [Change(e="e", a="b", v=3, added=False)])
        self.assertEqual(v2, {"a": 2})


class TestCertifyAndGrant(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.store = Store(self.conn)

    def test_pass_writes_cert_and_grants(self):
        w = Lossless()
        cert = certify(self.conn, w, CORPUS)
        row = self.conn.execute(
            "SELECT subject, result FROM certificate WHERE id = ?", (cert,)
        ).fetchone()
        self.assertEqual(row, ("wrapper:ll", "pass"))
        granted = grant_roundtrip(self.conn, w, cert)
        self.assertEqual(set(granted), {"ll:x", "ll:y"})
        self.assertTrue(is_writable(self.conn, "ll", "ll:x"))

    def test_fail_cert_no_grants(self):
        w = SpuriousPut()
        cert = certify(self.conn, w, CORPUS)
        row = self.conn.execute("SELECT result FROM certificate WHERE id = ?", (cert,)).fetchone()
        self.assertEqual(row[0], "fail")
        self.assertFalse(is_writable(self.conn, "sp", "ll:x"))

    def test_certified_wrapper_can_write(self):
        w = Lossless()
        cert = certify(self.conn, w, CORPUS)
        grant_roundtrip(self.conn, w, cert)
        rep = w.get("e", {"ll:x": "hello", "ll:y": "y"})
        res = w.put(rep, None, None)
        r = self.store.transact(res.changes, wrapper="ll")
        self.assertEqual(r.refusals, ())
        self.assertEqual(self.store.view(r.entity)["ll:x"], "hello")

    def test_uncertified_wrapper_refused(self):
        # attrs registered but no certificate: refusal is no_grant, not unknown_attr
        from agents_store.certify import register_wrapper
        w = Lossless()
        register_wrapper(self.conn, w)
        res = w.put(w.get("e", {"ll:x": "x"}), None, None)
        r = self.store.transact(res.changes, wrapper="ll")
        self.assertEqual(r.refusals[0].reason, "no_grant")

    def test_attrs_registered(self):
        certify(self.conn, Lossless(), CORPUS)
        names = {r[0] for r in self.conn.execute("SELECT name FROM attr")}
        self.assertIn("ll:x", names)
        self.assertIn("ll", {r[0] for r in self.conn.execute("SELECT id FROM wrapper")})


if __name__ == "__main__":
    unittest.main()
