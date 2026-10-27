"""jcal wrapper: get/put lens, refusals, certify round-trip."""
import unittest

from agents_store.certify import check_lens
from agents_store.wrappers.jsoncal import JsoncalWrapper

W = JsoncalWrapper()

# jcal:uid present in every view: a stored entity that ever synced has it;
# views without it would emit uid=<e> and propose an assertion (not an
# error — the fallback for entities minted elsewhere).
CORPUS = [
    {"jcal:uid": "u1", "jcal:summary": "dentist",
     "jcal:dtstart": "2026-12-01T10:00:00Z"},
    {"jcal:uid": "u2", "jcal:summary": "standup",
     "jcal:dtstart": "2026-12-02T09:00:00Z",
     "jcal:dtend": "2026-12-02T09:30:00Z", "jcal:status": "confirmed"},
    {"jcal:uid": "u3", "jcal:extra": {"category": ["health"], "priority": 3}},
]


class TestGet(unittest.TestCase):
    def test_item_shape(self):
        r = W.get("E1", {"jcal:uid": "u1", "jcal:summary": "dentist",
                         "jcal:dtstart": "2026-12-01T10:00:00Z"})
        import json
        item = json.loads(r)
        self.assertEqual(item["uid"], "u1")
        self.assertEqual(item["summary"], "dentist")
        self.assertEqual(item["dtstart"], "2026-12-01T10:00:00Z")
        self.assertNotIn("dtend", item)

    def test_uid_falls_back_to_entity_id(self):
        import json
        item = json.loads(W.get("E2", {"jcal:summary": "x"}))
        self.assertEqual(item["uid"], "E2")

    def test_extra_keys_preserved(self):
        import json
        item = json.loads(W.get("E1", {"jcal:uid": "u9",
                                       "jcal:extra": {"category": ["h"], "priority": 3}}))
        self.assertEqual(item["category"], ["h"])
        self.assertEqual(item["priority"], 3)


class TestPut(unittest.TestCase):
    def test_roundtrip(self):
        v = {"jcal:uid": "u1", "jcal:summary": "d",
             "jcal:dtstart": "2026-12-01T10:00:00Z"}
        res = W.put(W.get("E1", v), "E1", v)
        self.assertEqual(res.changes, ())
        self.assertEqual(res.refusals, ())

    def test_new_item_changes(self):
        res = W.put('{"uid": "u1", "summary": "d", "status": "confirmed"}',
                    None, {})
        attrs = {c.a for c in res.changes}
        self.assertEqual(
            attrs, {"jcal:uid", "jcal:summary", "jcal:status"})

    def test_uid_change_is_a_revision(self):
        # uid is provenance, not identity: changing it is an ordinary
        # attr change; the adapter's _by_uid resolution prevents squashing
        v = {"jcal:uid": "u1"}
        res = W.put('{"uid": "other", "summary": "x"}', "E1", v)
        self.assertEqual(res.refusals, ())
        uid_change = [c for c in res.changes if c.a == "jcal:uid"]
        self.assertEqual(len(uid_change), 1)
        self.assertEqual(uid_change[0].v, "other")

    def test_tz_refusal(self):
        res = W.put('{"uid": "u1", "dtstart": "2026-12-01T10:00:00+01:00"}',
                    "E1", {"jcal:uid": "u1"})
        self.assertEqual(res.refusals[0].reason, "tz_unsupported")

    def test_parse_fail(self):
        res = W.put('{"uid": 1', "E1", {})
        self.assertEqual(res.refusals[0].reason, "parse_fail")
        res = W.put('[1,2]', "E1", {})
        self.assertEqual(res.refusals[0].reason, "parse_fail")

    def test_retract_on_absent_key(self):
        v = {"jcal:uid": "u1", "jcal:summary": "d", "jcal:status": "confirmed"}
        res = W.put('{"uid": "u1", "summary": "d"}', "E1", v)
        retracts = [(c.a, c.added) for c in res.changes if not c.added]
        self.assertEqual(retracts, [("jcal:status", False)])


class TestLens(unittest.TestCase):
    def test_certify_corpus(self):
        rep = check_lens(W, CORPUS)
        self.assertTrue(rep.passed, rep.failures)


if __name__ == "__main__":
    unittest.main()
