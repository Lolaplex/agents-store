"""iCal wrapper: get/put lens, refusals, certify round-trip."""
import unittest

from agents_store.certify import check_lens
from agents_store.wrappers.ical import ICalWrapper

W = ICalWrapper()

CORPUS = [
    {"title": "meet", "when": "2026-10-12T10:00:00Z", "end": "2026-10-12T11:00:00Z"},
    {"title": "task t", "status": "open", "when": "2026-10-13T09:00:00Z"},
    {"status": "done"},
    {"title": "commas, semis; and\nnewline", "when": "2026-10-14T00:00:00Z",
     "ical:extra": ["LOCATION:HQ", "X-CUSTOM:42"]},
]


class TestGet(unittest.TestCase):
    def test_event(self):
        r = W.get("E1", {"title": "m", "when": "2026-10-12T10:00:00Z"})
        self.assertIn("BEGIN:VEVENT", r)
        self.assertIn("UID:E1", r)
        self.assertIn("DTSTART:20261012T100000Z", r)
        self.assertIn("SUMMARY:m", r)

    def test_todo_when_status_present(self):
        r = W.get("E1", {"status": "done", "when": "2026-10-12T10:00:00Z"})
        self.assertIn("BEGIN:VTODO", r)
        self.assertIn("STATUS:COMPLETED", r)

    def test_end_maps_due_for_todo(self):
        r = W.get("E1", {"status": "open", "end": "2026-10-15T00:00:00Z"})
        self.assertIn("DUE:20261015T000000Z", r)

    def test_extra_lines_preserved(self):
        r = W.get("E1", {"when": "2026-10-12T10:00:00Z", "ical:extra": ["X-FOO:bar"]})
        self.assertIn("X-FOO:bar", r)


class TestPut(unittest.TestCase):
    def test_roundtrip_event(self):
        v = {"title": "m", "when": "2026-10-12T10:00:00Z", "end": "2026-10-12T11:00:00Z"}
        res = W.put(W.get("E1", v), "E1", v)
        self.assertEqual(res.changes, ())
        self.assertEqual(res.refusals, ())

    def test_todo_completed_maps_done(self):
        rep = W.get("E1", {"status": "open"})
        res = W.put(rep.replace("NEEDS-ACTION", "COMPLETED"), "E1", {"status": "open"})
        self.assertEqual([(c.a, c.v) for c in res.changes], [("status", "done")])

    def test_tz_unsupported_refused(self):
        rep = W.get("E1", {"when": "2026-10-12T10:00:00Z"})
        local = rep.replace("DTSTART:20261012T100000Z", "DTSTART;TZID=Europe/Berlin:20261012T100000")
        res = W.put(local, "E1", None)
        self.assertEqual(res.refusals[0].reason, "tz_unsupported")
        self.assertEqual(res.changes, ())

    def test_status_map_refused(self):
        rep = W.get("E1", {"status": "open"})
        res = W.put(rep.replace("NEEDS-ACTION", "IN-PROCESS"), "E1", None)
        self.assertEqual(res.refusals[0].reason, "status_map")

    def test_parse_fail_garbage(self):
        res = W.put("not an ics at all", "E1", None)
        self.assertEqual(res.refusals[0].reason, "parse_fail")

    def test_uid_mismatch_refused(self):
        res = W.put(W.get("E1", {"when": "2026-10-12T10:00:00Z"}), "E2", None)
        self.assertEqual(res.refusals[0].reason, "uid_mismatch")

    def test_unmapped_props_to_extra(self):
        rep = W.get("E1", {"when": "2026-10-12T10:00:00Z"})
        with_rrule = rep.replace("END:VEVENT", "RRULE:FREQ=DAILY\nEND:VEVENT")
        res = W.put(with_rrule, "E1", {"when": "2026-10-12T10:00:00Z"})
        extra = [c for c in res.changes if c.a == "ical:extra"]
        self.assertTrue(extra and "RRULE:FREQ=DAILY" in extra[0].v)

    def test_lens_laws_pass(self):
        r = check_lens(W, CORPUS)
        self.assertTrue(r.passed, r.failures)


if __name__ == "__main__":
    unittest.main()
