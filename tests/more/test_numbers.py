"""Canonical numbers in MORe events (numbers.py, C4: integers with a declared
scale, no binary floats)."""
import os
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import patch

from agents_store import connect
from agents_store.more import said as S
from agents_store.more.log import EventLog
from agents_store.more.migrate import migrate_said, number_report, planned_said_changes
from agents_store.more.numbers import (MAX_SAFE_INTEGER, NUMBER_FLOAT, NUMBER_NONFINITE,
                                       NUMBER_OUT_OF_RANGE, number_issues, scaled, unscaled)
from agents_store.more.store_bridge import StoreWriteRefused, assert_canonical_numbers
from agents_store.store import Store
from tests.more.helpers import verification


def ev(**body):
    return verification("UC-1", "UC-1@1", body=body)


class Issues(unittest.TestCase):
    def test_reasons(self):
        cases = [
            (0.8, NUMBER_FLOAT), (1e-07, NUMBER_FLOAT), (-0.0, NUMBER_FLOAT), (1.0, NUMBER_FLOAT),
            (0.1 + 0.2, NUMBER_FLOAT),
            (float("nan"), NUMBER_NONFINITE), (float("inf"), NUMBER_NONFINITE),
            (float("-inf"), NUMBER_NONFINITE),
            (2**53, NUMBER_OUT_OF_RANGE), (-(2**53), NUMBER_OUT_OF_RANGE), (2**64, NUMBER_OUT_OF_RANGE),
        ]
        for v, reason in cases:
            with self.subTest(v=v):
                self.assertEqual([i.reason for i in number_issues({"x": v})], [reason])

    def test_canonical_values_pass(self):
        for v in (0, 1, -1, MAX_SAFE_INTEGER, -MAX_SAFE_INTEGER, True, False, None, "0.8",
                  {"value": 80, "scale": 2}, [1, 2, {"a": [3]}]):
            with self.subTest(v=v):
                self.assertEqual(number_issues({"x": v}), [])

    def test_paths(self):
        issues = number_issues({"a": [1, {"b": 0.5}], "c": {"d": float("nan")}})
        self.assertEqual([(i.path, i.reason) for i in issues],
                         [("$.a[1].b", NUMBER_FLOAT), ("$.c.d", NUMBER_NONFINITE)])


class Scaled(unittest.TestCase):
    def test_ruling_example(self):
        self.assertEqual(scaled("0.8"), {"value": 8, "scale": 1})
        self.assertEqual(scaled("0.80"), {"value": 80, "scale": 2})   # declared scale is kept
        self.assertEqual(scaled(Decimal("-12.345")), {"value": -12345, "scale": 3})
        self.assertEqual(scaled(42), {"value": 42, "scale": 0})
        self.assertEqual(unscaled({"value": 80, "scale": 2}), Decimal("0.80"))

    def test_refuses_float_and_nonfinite(self):
        with self.assertRaises(TypeError):
            scaled(0.8)
        with self.assertRaises(ValueError):
            scaled("NaN")
        with self.assertRaises(ValueError):
            scaled(str(2**53))


class Serialization(unittest.TestCase):
    def test_dumps_refuses_nan(self):
        for v in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                S.dumps({"x": v})

    def test_canonical_refuses_nan(self):
        e = ev(x=float("nan"))
        with self.assertRaises(ValueError):
            e.canonical()
        self.assertIn(b"NaN", e.canonical(allow_nan=True))


class AppendGuard(unittest.TestCase):
    def setUp(self):
        self.log = EventLog()
        self.addCleanup(self.log.close)

    def test_refused_with_typed_reason(self):
        for v, reason in ((0.8, NUMBER_FLOAT), (float("nan"), NUMBER_NONFINITE),
                          (float("-inf"), NUMBER_NONFINITE), (2**53, NUMBER_OUT_OF_RANGE)):
            with self.subTest(v=v):
                with self.assertRaises(StoreWriteRefused) as cm:
                    self.log.append(ev(amount=v))
                (r,) = cm.exception.refusals
                self.assertEqual((r.reason, r.a, r.payload), (reason, "body", "$.body.amount"))
        self.assertEqual(list(self.log.events()), [])
        self.assertEqual([v for v, _ in self.log.refusals()],
                         [NUMBER_FLOAT, NUMBER_NONFINITE, NUMBER_NONFINITE, NUMBER_OUT_OF_RANGE])

    def test_scaled_integer_admitted(self):
        out = self.log.append(ev(amount=scaled("0.80")))
        self.assertTrue(S.is_said(out.said))
        self.assertEqual(self.log.get(out.id).body["amount"], {"value": 80, "scale": 2})
        self.assertEqual(self.log.verify(), [])

    def test_guard_runs_before_any_write_store_backed(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(os.unlink, path)
        conn = connect(path)
        self.addCleanup(conn.close)
        log = EventLog(conn=conn)
        n = conn.execute("SELECT COUNT(*) FROM datom").fetchone()[0]
        with self.assertRaises(StoreWriteRefused):
            log.append(ev(amount=0.8))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM datom").fetchone()[0], n)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM event").fetchone()[0], 0)

    def test_assert_canonical_numbers_direct(self):
        assert_canonical_numbers(ev(amount=1))
        with self.assertRaises(StoreWriteRefused):
            assert_canonical_numbers(ev(rows=[1, 2.5]))


class LegacyEvents(unittest.TestCase):
    """Events stored before the guard are reported, never rewritten."""

    def _legacy_db(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(os.unlink, path)
        conn = connect(path)
        self.addCleanup(conn.close)
        log = EventLog(conn=conn)
        ok = log.append(ev(amount=1))
        with patch("agents_store.more.log.assert_canonical_numbers"):
            bad = log.append(ev(amount=0.8))
        return conn, log, ok, bad

    def test_number_report(self):
        conn, _, ok, bad = self._legacy_db()
        rep = number_report(conn)
        self.assertEqual([(eid, i.path, i.reason) for eid, i in rep],
                         [(bad.id, "$.body.amount", NUMBER_FLOAT)])

    def test_migrate_said_reports_and_does_not_rewrite(self):
        conn, log, ok, bad = self._legacy_db()
        store = Store(conn)
        envelopes = conn.execute("SELECT id, envelope, digest FROM event ORDER BY seq").fetchall()
        report = []
        self.assertEqual(planned_said_changes(store, report), [])
        self.assertEqual([(eid, i.reason) for eid, i in report], [(bad.id, NUMBER_FLOAT)])
        report = []
        self.assertIsNone(migrate_said(conn, report))
        self.assertEqual([(eid, i.reason) for eid, i in report], [(bad.id, NUMBER_FLOAT)])
        self.assertEqual(conn.execute("SELECT id, envelope, digest FROM event ORDER BY seq").fetchall(),
                         envelopes)
        self.assertEqual(store.view(bad.id)["more:said"], bad.said)   # existing SAID left as is
        self.assertEqual(log.verify(), [])

    def test_nan_legacy_event_reads_without_said(self):
        log = EventLog()
        self.addCleanup(log.close)
        # write the legacy row directly, as the pre-guard code did (it wrote NaN)
        e = ev(amount=float("nan"))
        payload = e.canonical(allow_nan=True).decode()
        from agents_store.more.log import _digest
        digest = _digest("", "01JBQ7Z8X0000000000000000N", payload.encode())
        log.conn.execute(
            "INSERT INTO event (id, type, actor, at, envelope, prev, digest) VALUES (?,?,?,?,?,?,?)",
            ("01JBQ7Z8X0000000000000000N", e.type, e.actor, e.at, payload, "", digest))
        (got,) = list(log.events())
        self.assertIsNone(got.said)
        self.assertEqual(log.verify(), [])
        self.assertEqual([i.reason for _, i in number_report(log.conn)], [NUMBER_NONFINITE])


if __name__ == "__main__":
    unittest.main()
