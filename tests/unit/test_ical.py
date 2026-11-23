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
    {"title": "zoned", "when": "2026-12-20T08:00:00Z", "end": "2026-12-20T09:00:00Z",
     "ical:tz": "TZID=Europe/Berlin"},
    {"title": "all day", "when": "2026-12-24T00:00:00Z", "end": "2026-12-25T00:00:00Z",
     "ical:tz": "date"},
    {"title": "floating", "when": "2026-07-01T12:00:00Z", "ical:tz": "floating"},
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

    def test_tzid_wall_time_becomes_utc_instant(self):
        rep = W.get("E1", {"when": "2026-10-12T10:00:00Z"})
        local = rep.replace("DTSTART:20261012T100000Z", "DTSTART;TZID=Europe/Berlin:20261012T100000")
        res = W.put(local, "E1", None)
        self.assertEqual(res.refusals, ())
        got = {c.a: c.v for c in res.changes}
        self.assertEqual(got["when"], "2026-10-12T08:00:00Z")
        self.assertEqual(got["ical:tz"], "TZID=Europe/Berlin")

    def test_tzid_rendered_back_with_vtimezone(self):
        vtz = ["BEGIN:VTIMEZONE", "TZID:Europe/Berlin", "BEGIN:STANDARD",
               "DTSTART:19701025T030000", "TZOFFSETFROM:+0200", "TZOFFSETTO:+0100",
               "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU", "END:STANDARD", "END:VTIMEZONE"]
        rep = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "\r\n".join(vtz) +
               "\r\nBEGIN:VEVENT\r\nUID:E1\r\nSUMMARY:x\r\n"
               "DTSTART;TZID=Europe/Berlin:20261220T090000\r\n"
               "DTEND;TZID=Europe/Berlin:20261220T100000\r\n"
               "END:VEVENT\r\nEND:VCALENDAR\r\n")
        res = W.put(rep, "E1", None)
        self.assertEqual(res.refusals, ())
        view = {c.a: c.v for c in res.changes}
        self.assertEqual(view["when"], "2026-12-20T08:00:00Z")
        self.assertEqual(view["end"], "2026-12-20T09:00:00Z")
        self.assertEqual(view["ical:vtimezone"], vtz)
        out = W.get("E1", view)
        self.assertIn("DTSTART;TZID=Europe/Berlin:20261220T090000", out)
        self.assertIn("DTEND;TZID=Europe/Berlin:20261220T100000", out)
        self.assertIn("BEGIN:VTIMEZONE", out)
        self.assertEqual(W.put(out, "E1", view).changes, ())

    def test_floating_resolved_in_store_zone(self):
        import os
        from unittest import mock
        rep = W.get("E1", {"when": "2026-10-12T10:00:00Z"}).replace(
            "DTSTART:20261012T100000Z", "DTSTART:20261012T100000")
        with mock.patch.dict(os.environ, {"AGENTS_STORE_TIMEZONE": "America/New_York"}):
            res = W.put(rep, "E1", None)
            got = {c.a: c.v for c in res.changes}
            self.assertEqual(got["when"], "2026-10-12T14:00:00Z")
            self.assertEqual(got["ical:tz"], "floating")
            self.assertIn("DTSTART:20261012T100000\r\n", W.get("E1", got))

    def test_all_day_date(self):
        rep = W.get("E1", {"when": "2026-10-12T10:00:00Z"}).replace(
            "DTSTART:20261012T100000Z", "DTSTART;VALUE=DATE:20261224")
        res = W.put(rep, "E1", None)
        got = {c.a: c.v for c in res.changes}
        self.assertEqual(got["when"], "2026-12-24T00:00:00Z")
        self.assertEqual(got["ical:tz"], "date")
        self.assertIn("DTSTART;VALUE=DATE:20261224", W.get("E1", got))

    def test_back_to_utc_retracts_form(self):
        view = {"when": "2026-10-12T08:00:00Z", "ical:tz": "TZID=Europe/Berlin"}
        utc = W.get("E1", {"when": "2026-10-12T08:00:00Z"})
        res = W.put(utc, "E1", view)
        self.assertEqual([(c.a, c.added) for c in res.changes], [("ical:tz", False)])

    def test_tzid_on_utc_value_is_utc(self):
        rep = W.get("E1", {"when": "2026-10-12T10:00:00Z"}).replace(
            "DTSTART:20261012T100000Z", "DTSTART;TZID=UTC:20261012T100000Z")
        res = W.put(rep, "E1", {"when": "2026-10-12T10:00:00Z"})
        self.assertEqual((res.refusals, res.changes), ((), ()))

    def test_second_fallback_hour_rendered_as_utc(self):
        # 2026-10-25 02:30 happens twice in Berlin; 01:30Z is the second pass.
        view = {"when": "2026-10-25T01:30:00Z", "ical:tz": "TZID=Europe/Berlin"}
        out = W.get("E1", view)
        self.assertIn("DTSTART:20261025T013000Z", out)
        self.assertEqual(W.put(out, "E1", view).changes[0].a, "ical:tz")

    def test_unknown_tzid_refused(self):
        rep = W.get("E1", {"when": "2026-10-12T10:00:00Z"})
        local = rep.replace("DTSTART:20261012T100000Z", "DTSTART;TZID=Mars/Olympus:20261012T100000")
        res = W.put(local, "E1", None)
        self.assertEqual(res.refusals[0].reason, "tz_unsupported")
        self.assertEqual(res.changes, ())

    def test_nonexistent_wall_time_refused(self):
        rep = W.get("E1", {"when": "2026-10-12T10:00:00Z"})
        gap = rep.replace("DTSTART:20261012T100000Z", "DTSTART;TZID=Europe/Berlin:20260329T023000")
        res = W.put(gap, "E1", None)
        self.assertEqual(res.refusals[0].reason, "tz_unsupported")

    def test_mixed_date_and_datetime_refused(self):
        rep = W.get("E1", {"when": "2026-10-12T10:00:00Z", "end": "2026-10-12T11:00:00Z"})
        rep = rep.replace("DTSTART:20261012T100000Z", "DTSTART;VALUE=DATE:20261012")
        res = W.put(rep, "E1", None)
        self.assertEqual(res.refusals[0].reason, "tz_unsupported")

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
