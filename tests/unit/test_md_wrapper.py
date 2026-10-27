"""Markdown wrapper: get/put lens, refusal cases, certify round-trip."""
import unittest

from agents_store import AttrSpec, connect
from agents_store.certify import check_lens
from agents_store.wrappers.markdown import MarkdownWrapper

W = MarkdownWrapper()

CORPUS = [
    {"title": "t1", "body": "body one"},
    {"title": "t2", "body": "multi\nline body", "status": "open",
     "when": "2026-10-12T10:00:00Z", "end": "2026-10-12T11:00:00Z"},
    {"body": "b", "md:extra": {"custom": "v", "other": "w"}},
    {"title": "only title"},
]


class TestGetPut(unittest.TestCase):
    def test_get_includes_id_and_attrs(self):
        r = W.get("E1", {"title": "t", "status": "open", "body": "b"})
        self.assertIn("id: E1", r)
        self.assertIn("title: t", r)
        self.assertIn("status: open", r)
        self.assertTrue(r.endswith("b\n"))

    def test_put_roundtrip_attrs(self):
        view = {"title": "t", "status": "open", "body": "hello"}
        res = W.put(W.get("E1", view), "E1", view)
        self.assertEqual(res.changes, ())
        self.assertEqual(res.refusals, ())

    def test_put_proposes_diff(self):
        view = {"title": "old", "body": "b"}
        rep = W.get("E1", {"title": "new", "body": "b"})
        res = W.put(rep, "E1", view)
        self.assertEqual([(c.a, c.v) for c in res.changes], [("title", "new")])

    def test_put_no_id_new_entity(self):
        res = W.put("just body text", None, None)
        self.assertTrue(all(c.e is None for c in res.changes))
        self.assertEqual(res.changes[0].a, "body")

    def test_put_retracts_removed_attr(self):
        view = {"title": "t", "status": "open", "body": "b"}
        rep = W.get("E1", {"title": "t", "body": "b"})
        res = W.put(rep, "E1", view)
        kinds = [(c.a, c.added) for c in res.changes]
        self.assertIn(("status", False), kinds)

    def test_id_mismatch_refused(self):
        rep = W.get("E1", {"body": "b"})
        res = W.put(rep, "OTHER", {"body": "b"})
        self.assertEqual(res.refusals[0].reason, "id_mismatch")
        self.assertEqual(res.changes, ())

    def test_parse_fail_unterminated(self):
        res = W.put("---\nid: E1\ntitle: no end", "E1", None)
        self.assertEqual(res.refusals[0].reason, "parse_fail")

    def test_parse_fail_bad_line(self):
        res = W.put("---\nid: E1\nnot a kv\n---\nbody", "E1", None)
        self.assertEqual(res.refusals[0].reason, "parse_fail")

    def test_extra_keys_lossless(self):
        view = {"title": "t", "md:extra": {"custom": "v"}, "body": "b"}
        rep = W.get("E1", view)
        self.assertIn("custom: v", rep)
        res = W.put(rep, "E1", view)
        self.assertEqual(res.changes, ())

    def test_lens_laws_pass(self):
        r = check_lens(W, CORPUS)
        self.assertTrue(r.passed, r.failures)

    def test_peek_id(self):
        self.assertEqual(W.peek_id(W.get("E9", {"body": "b"})), "E9")
        self.assertIsNone(W.peek_id("plain text"))


if __name__ == "__main__":
    unittest.main()
