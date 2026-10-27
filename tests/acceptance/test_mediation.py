"""T16 — generated mediator end to end (MEGAPLAN §6.1).

A jsoncal export lands entities in `jcal:*` terms only. Two confirmed
correspondences + a generated mediator materialize `when`/`status`, so
the SAME entities appear over real CalDAV — zero plugin/adapter edits.
A CalDAV edit routes back through the correspondence to `jcal:*` and the
re-exported file carries it. That is the thesis.
"""
from __future__ import annotations

import json
import unittest

from agents_store import Change, derive, match
from agents_store.adapters import jsonfile
from agents_store.certify import certify, grant_roundtrip
from agents_store.wrappers.jsoncal import JsoncalWrapper

from tests.acceptance.test_poc import PocCase

JCAL_CORPUS = [
    {"jcal:uid": "u1", "jcal:summary": "d", "jcal:dtstart": "2026-12-01T10:00:00Z"},
]


def _edge_ids(conn, *a_froms):
    ph = ",".join("?" * len(a_froms))
    return [r[0] for r in conn.execute(
        f"SELECT id FROM correspondence WHERE a_from IN ({ph})", a_froms)]


class TestMediation(PocCase):
    """§6.1: two confirmed correspondences -> items appear in CalDAV."""

    def test_jsoncal_items_in_caldav_and_back(self):
        jw = JsoncalWrapper()
        cert = certify(self.conn, jw, JCAL_CORPUS)
        grant_roundtrip(self.conn, jw, cert)
        # 1. a foreign export file, synced in its own terms
        jpath = self.tmp / "export.json"
        jpath.write_text(json.dumps([
            {"uid": "jx-1", "summary": "mediated event",
             "dtstart": "2026-12-22T10:00:00Z"},
            {"uid": "jx-2", "summary": "mediated dual",
             "dtstart": "2026-12-22T14:00:00Z", "status": "open"},
        ]), encoding="utf-8")
        rep = jsonfile.sync(self.store, jpath, jw)
        self.assertFalse(rep.refusals, rep.refusals)
        e1 = self.conn.execute(
            "SELECT e FROM v_current WHERE a='jcal:uid' AND v='jx-1'"
        ).fetchone()[0]
        e2 = self.conn.execute(
            "SELECT e FROM v_current WHERE a='jcal:uid' AND v='jx-2'"
        ).fetchone()[0]
        # not yet visible anywhere: only jcal:* attrs exist
        self.assertNotIn("when", self._view(e1))

        # 2. propose, confirm exactly 2 correspondences, witness
        match.propose(self.conn, "jcal", "")
        ids = _edge_ids(self.conn, "jcal:dtstart", "jcal:status")
        self.assertEqual(len(ids), 2)
        match.witness(self.conn, ids)
        mid = derive.generate(self.conn, "jcal", ids)
        self.assertEqual(self.conn.execute(
            "SELECT exactness FROM mediator WHERE id=?", (mid,)
        ).fetchone()[0], "exact")
        derive.run(self.store, mid)

        # 3. mediated attrs landed, marked derived
        self.assertEqual(self._view(e1)["when"], "2026-12-22T10:00:00Z")
        self.assertEqual(derive.is_derived(self.conn, e1, "when"), mid)

        # 4. REAL CalDAV: same entity served as VEVENT (plugin untouched)
        status, _, body = self._request("GET", f"/test/calendar/{e1}.ics")
        self.assertEqual(status, 200)
        text = body.decode()
        self.assertIn("BEGIN:VEVENT", text)
        self.assertIn("DTSTART:20261222T100000Z", text)
        self.assertIn(f"UID:{e1}", text)
        # dual facet: jx-2 got when AND status -> VEVENT in calendar,
        # VTODO in tasks
        status, _, body = self._request("GET", f"/test/tasks/{e2}.ics")
        self.assertEqual(status, 200)
        self.assertIn("BEGIN:VTODO", body.decode())
        status, _, body = self._request("GET", f"/test/calendar/{e2}.ics")
        self.assertEqual(status, 200)
        self.assertIn("BEGIN:VEVENT", body.decode())

        # 5. independent witness: agents-calendar list sees it
        p = self._cli("list", "--from", "2026-12-22T00:00:00Z",
                      "--to", "2026-12-23T00:00:00Z",
                      "--calendar", "calendar")
        if p.returncode == 127 or "No module named" in (p.stderr or ""):
            self.skipTest("agents-calendar not installed (named skip)")
        self.assertEqual(p.returncode, 0, p.stderr)
        events = json.loads(p.stdout)
        mine = [ev for ev in events if str(e1) in json.dumps(ev)]
        self.assertTrue(mine, events)

        # 6. mediated write-back: independent CLI updates DTSTART,
        #    the store inverts it through the correspondence edge
        ev1 = mine[0]
        p = self._cli("update", "--href", ev1["href"],
                      "--etag", ev1["etag"],
                      "--dtstart", "2026-12-25T08:00:00Z",
                      "--dtend", "2026-12-25T09:00:00Z")
        self.assertEqual(p.returncode, 0, p.stderr)
        view = self._view(e1)
        self.assertEqual(view["jcal:dtstart"], "2026-12-25T08:00:00Z")
        self.assertEqual(view["when"], "2026-12-25T08:00:00Z")  # re-derived
        note = self.conn.execute(
            "SELECT note FROM tx WHERE note LIKE '%mediated-write%'"
        ).fetchone()
        self.assertIn("mediated-write via mediator", note[0])
        # 7. the re-exported file carries the CalDAV edit
        jsonfile.sync(self.store, jpath, jw)
        data = {it["uid"]: it for it in
                json.loads(jpath.read_text(encoding="utf-8"))}
        self.assertEqual(data["jx-1"]["dtstart"], "2026-12-25T08:00:00Z")

    def test_non_roundtrippable_write_refused(self):
        jw = JsoncalWrapper()
        cert = certify(self.conn, jw, JCAL_CORPUS)
        grant_roundtrip(self.conn, jw, cert)
        e = self.store.transact([
            Change(e=None, a="jcal:uid", v="u9"),
            Change(e=None, a="jcal:summary", v="x"),
        ], wrapper="jcal").entity
        # an unwitnessed refines edge -> mediator 'contained', derivation
        # lands, but write-back must refuse
        self.conn.execute(
            "INSERT INTO correspondence (a_from, a_to, kind)"
            " VALUES ('jcal:summary', 'title', 'refines')")
        cid = self.conn.execute("SELECT MAX(id) FROM correspondence"
                                ).fetchone()[0]
        mid = derive.generate(self.conn, "jcal", [cid])
        self.assertEqual(self.conn.execute(
            "SELECT exactness FROM mediator WHERE id=?", (mid,)
        ).fetchone()[0], "contained")
        derive.run(self.store, mid)
        self.assertEqual(self._view(e)["title"], "x")  # derived value lands
        res = self.store.transact(
            [Change(e=e, a="title", v="hijack")], wrapper="ical")
        self.assertTrue(any(r.reason == "derived_attr"
                            for r in res.refusals), res.refusals)
        self.assertEqual(self._view(e)["title"], "x")  # unchanged
        # and the refusal is on record
        rows = self.conn.execute(
            "SELECT reason FROM refusal WHERE reason='derived_attr'"
        ).fetchall()
        self.assertTrue(rows)


if __name__ == "__main__":
    unittest.main()
