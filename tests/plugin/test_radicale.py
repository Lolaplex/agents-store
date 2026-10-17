"""T07: Radicale plugin over the agents-store layer.

In-process WSGI: PUT/GET/DELETE real HTTP requests against
radicale.Application with storage type radicale_agents_store.
Refusals must land in `refusal` AND surface as HTTP errors.
"""
from __future__ import annotations

import io
import os
import shutil
import tempfile
import unittest

import radicale
import radicale.config

import agents_store
from radicale_agents_store import Collection, Storage

VEVENT = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//test//EN\r
BEGIN:VEVENT\r
UID:client-uid-1\r
SUMMARY:Test Event\r
DTSTART:20261201T100000Z\r
DTEND:20261201T110000Z\r
END:VEVENT\r
END:VCALENDAR\r
"""

VTODO = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//test//EN\r
BEGIN:VTODO\r
UID:client-uid-2\r
SUMMARY:Test Task\r
STATUS:NEEDS-ACTION\r
END:VTODO\r
END:VCALENDAR\r
"""

VTODO_DONE = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//test//EN\r
BEGIN:VTODO\r
UID:{uid}\r
SUMMARY:Test Task\r
STATUS:COMPLETED\r
END:VTODO\r
END:VCALENDAR\r
"""

BAD_TZ = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//test//EN\r
BEGIN:VEVENT\r
UID:client-uid-3\r
SUMMARY:TZ Event\r
DTSTART;TZID=Europe/Berlin:20261201T100000\r
END:VEVENT\r
END:VCALENDAR\r
"""


def _request(app, method, path, data=None, headers=None):
    status_box, headers_box = {}, {}

    def start_response(status, hdrs, exc_info=None):
        status_box["s"] = status
        headers_box["h"] = dict(hdrs)
        return lambda b: None

    body = (data or "").encode()
    environ = {
        "REQUEST_METHOD": method,
        "HTTP_AUTHORIZATION": "Basic dGVzdDp4",  # test:x
        "PATH_INFO": path,
        "SCRIPT_NAME": "",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "80",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.errors": io.StringIO(),
        "wsgi.input": io.BytesIO(body),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }
    if data is not None:
        environ["CONTENT_TYPE"] = "text/calendar; charset=utf-8"
        environ["CONTENT_LENGTH"] = str(len(body))
    for k, v in (headers or {}).items():
        environ["HTTP_" + k.upper().replace("-", "_")] = v
    out = b"".join(app(environ, start_response))
    return status_box["s"], headers_box["h"], out


class PluginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="agents-store-test-")
        self.db = os.path.join(self.tmp, "store.sqlite")
        os.environ["AGENTS_STORE_DB"] = self.db
        conf = radicale.config.load()
        conf.update({
            "storage": {"type": "radicale_agents_store",
                        "filesystem_folder": self.tmp},
            "auth": {"type": "none"},
            "rights": {"type": "owner_only"},
        }, "test")
        self.app = radicale.Application(conf)
        self.conn = agents_store.connect(self.db)

    def tearDown(self):
        self.conn.close()
        os.environ.pop("AGENTS_STORE_DB", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- topology ------------------------------------------------------

    def test_discover_root_and_collections(self):
        storage = self.app._storage
        root = list(storage.discover("/"))
        self.assertEqual(len(root), 1)
        self.assertIsInstance(root[0], Collection)
        # principals are dynamic -> root enumerates no children
        kids = list(storage.discover("/", depth="1"))
        self.assertEqual([c.path for c in kids], [""])
        # a principal exposes exactly the two membership views
        kids = list(storage.discover("/test/", depth="1"))
        self.assertEqual(sorted(c.path for c in kids),
                         ["test", "test/calendar", "test/tasks"])
        # arbitrary item path under a principal discovers nothing
        self.assertEqual(list(storage.discover("/test/bogus/x.ics")), [])

    def test_create_collection_refused(self):
        storage = self.app._storage
        # nested collections are refused: membership is a view
        with self.assertRaises(ValueError):
            storage.create_collection("/test/bogus/")
        # tagged collection creation outside the views is refused
        with self.assertRaises(ValueError):
            storage.create_collection("/bogus/", props={"tag": "VCALENDAR"})
        # tagless single-segment = principal container (Radicale auto-creates)
        coll, _, _ = storage.create_collection("/test/")
        self.assertEqual(coll.path, "test")
        coll, _, _ = storage.create_collection("/test/calendar/")
        self.assertEqual(coll.path, "test/calendar")

    # ---- PUT / GET -----------------------------------------------------

    def test_put_get_vevent(self):
        status, headers, _ = _request(
            self.app, "PUT", "/test/calendar/x.ics", VEVENT,
            {"If-None-Match": "*"})
        self.assertTrue(status.startswith("201"), status)
        self.assertIn("ETag", headers)
        # entity minted; client uid stored as data, NOT the id
        rows = self.conn.execute(
            "SELECT e, v FROM v_current WHERE a = 'ical:client-uid'").fetchall()
        self.assertEqual(len(rows), 1)
        e, uid = rows[0]
        self.assertEqual(uid, "client-uid-1")
        self.assertEqual(len(e), 26)  # ULID
        view = self._view(e)
        self.assertEqual(view["title"], "Test Event")
        self.assertEqual(view["when"], "2026-12-01T10:00:00Z")
        # GET returns the item at the client's href with UID = entity id
        status, _, body = _request(self.app, "GET", "/test/calendar/x.ics")
        self.assertTrue(status.startswith("200"), status)
        text = body.decode()
        self.assertIn(f"UID:{e}", text)
        self.assertIn("SUMMARY:Test Event", text)

    def test_put_todo_then_complete(self):
        status, headers, _ = _request(
            self.app, "PUT", "/test/tasks/t.ics", VTODO,
            {"If-None-Match": "*"})
        self.assertTrue(status.startswith("201"), status)
        e = self.conn.execute(
            "SELECT e FROM v_current WHERE a = 'ical:href' AND v = 't.ics'"
        ).fetchone()[0]
        self.assertEqual(self._view(e)["status"], "open")
        # complete it: client echoes our emitted UID (the entity id)
        status, _, _ = _request(
            self.app, "PUT", "/test/tasks/t.ics",
            VTODO_DONE.format(uid=e),
            {"If-Match": headers["ETag"]})
        self.assertTrue(status.startswith("204"), status)
        self.assertEqual(self._view(e)["status"], "done")
        # task entity also carries no `when` -> absent from calendar view
        self.assertNotIn("when", self._view(e))

    def test_etag_precondition(self):
        status, headers, _ = _request(
            self.app, "PUT", "/test/calendar/x.ics", VEVENT,
            {"If-None-Match": "*"})
        self.assertTrue(status.startswith("201"), status)
        e = self.conn.execute(
            "SELECT e FROM v_current WHERE a = 'ical:href' AND v = 'x.ics'"
        ).fetchone()[0]
        update = VEVENT.replace("client-uid-1", e).replace(
            "Test Event", "Other")
        # stale etag -> 412
        status, _, _ = _request(
            self.app, "PUT", "/test/calendar/x.ics", update,
            {"If-Match": '"deadbeef"'})
        self.assertTrue(status.startswith("412"), status)
        # correct etag -> 204
        status, _, _ = _request(
            self.app, "PUT", "/test/calendar/x.ics", update,
            {"If-Match": headers["ETag"]})
        self.assertTrue(status.startswith("204"), status)

    # ---- refusals ------------------------------------------------------

    def test_tz_refusal_http_and_table(self):
        status, _, _ = _request(
            self.app, "PUT", "/test/calendar/z.ics", BAD_TZ,
            {"If-None-Match": "*"})
        self.assertTrue(status.startswith("400"), status)
        rows = self.conn.execute(
            "SELECT reason FROM refusal WHERE wrapper = 'ical'").fetchall()
        self.assertIn(("tz-unsupported",), rows)

    def test_put_to_unknown_collection_conflicts(self):
        status, _, _ = _request(
            self.app, "PUT", "/bogus/x.ics", VEVENT,
            {"If-None-Match": "*"})
        self.assertTrue(status.startswith(("400", "403", "404", "409")),
                        status)

    # ---- DELETE --------------------------------------------------------

    def test_delete_retracts_keeps_history(self):
        _request(self.app, "PUT", "/test/calendar/x.ics", VEVENT,
                 {"If-None-Match": "*"})
        e = self.conn.execute(
            "SELECT e FROM v_current WHERE a = 'ical:href' AND v = 'x.ics'"
        ).fetchone()[0]
        status, _, _ = _request(self.app, "DELETE", "/test/calendar/x.ics")
        self.assertTrue(status.startswith(("200", "204")), status)
        # gone from the projection
        status, _, _ = _request(self.app, "GET", "/test/calendar/x.ics")
        self.assertTrue(status.startswith("404"), status)
        # but history retains every datom
        n = self.conn.execute(
            "SELECT COUNT(*) FROM datom WHERE e = ?", (e,)).fetchone()[0]
        self.assertGreaterEqual(n, 4)  # asserted + retracted mapped attrs
        view = self._view(e)
        for a in ("title", "when", "end"):
            self.assertNotIn(a, view)
        # the href + client uid are provenance, not facet data: kept, so
        # a later PUT to the same href rebinds this entity.
        self.assertEqual(view["ical:href"], "x.ics")
        self.assertEqual(view["ical:client-uid"], "client-uid-1")
        row = self.conn.execute(
            "SELECT op, note FROM tx WHERE id = (SELECT MAX(id) FROM tx)"
        ).fetchone()
        self.assertEqual(row[0], "retire")
        self.assertEqual(row[1], "x.ics")

    # ---- per-surface projection law (BetterBird) -----------------------

    def _put_dual_facet_task(self):
        """A task WITH a date -> member of both `tasks` and `calendar`."""
        todo = VTODO.replace(
            "STATUS:NEEDS-ACTION",
            "DTSTART:20261205T090000Z\r\nSTATUS:NEEDS-ACTION")
        status, _, _ = _request(
            self.app, "PUT", "/test/tasks/t.ics", todo,
            {"If-None-Match": "*"})
        self.assertTrue(status.startswith("201"), status)
        return self.conn.execute(
            "SELECT e FROM v_current WHERE a = 'ical:href' AND v = 't.ics'"
        ).fetchone()[0]

    def test_task_with_when_plots_in_calendar_as_vevent(self):
        e = self._put_dual_facet_task()
        # tasks view: VTODO, status round-trips
        status, _, body = _request(self.app, "GET", "/test/tasks/t.ics")
        self.assertTrue(status.startswith("200"), status)
        text = body.decode()
        self.assertIn("BEGIN:VTODO", text)
        self.assertIn("STATUS:NEEDS-ACTION", text)
        self.assertIn(f"UID:{e}", text)
        # calendar view: same entity rendered VEVENT — plotted, no STATUS
        status, _, body = _request(self.app, "GET", "/test/calendar/t.ics")
        self.assertTrue(status.startswith("200"), status)
        text = body.decode()
        self.assertIn("BEGIN:VEVENT", text)
        self.assertIn("DTSTART:20261205T090000Z", text)
        self.assertNotIn("VTODO", text)
        self.assertNotIn("STATUS", text)
        self.assertIn(f"UID:{e}", text)  # same canonical id both surfaces

    def test_calendar_put_preserves_task_facet(self):
        e = self._put_dual_facet_task()
        # client rewrites it AS VEVENT through the calendar surface
        ev = VEVENT.replace("client-uid-1", e).replace("Test Event",
                                                     "Renamed")
        _, headers, _ = _request(self.app, "GET", "/test/calendar/t.ics")
        status, _, _ = _request(
            self.app, "PUT", "/test/calendar/t.ics", ev,
            {"If-Match": headers["ETag"]})
        self.assertTrue(status.startswith("204"), status)
        view = self._view(e)
        self.assertEqual(view["title"], "Renamed")   # lawful part landed
        self.assertEqual(view["status"], "open")     # task facet intact
        # the out-of-projection change was refused visibly, not dropped
        rows = self.conn.execute(
            "SELECT reason FROM refusal WHERE wrapper = 'ical' "
            "AND entity = ?", (e,)).fetchall()
        self.assertIn(("out-of-projection",), rows)
        # tasks/ still renders the task
        status, _, body = _request(self.app, "GET", "/test/tasks/t.ics")
        self.assertIn("BEGIN:VTODO", body.decode())

    def test_calendar_delete_keeps_task_facet(self):
        e = self._put_dual_facet_task()
        status, _, _ = _request(self.app, "DELETE", "/test/calendar/t.ics")
        self.assertTrue(status.startswith(("200", "204")), status)
        view = self._view(e)
        # the event facet is retracted (when = calendar write-set)...
        self.assertNotIn("when", view)
        # ...the task facet survives
        self.assertEqual(view["status"], "open")
        # gone from the calendar projection, still served by tasks/
        status, _, _ = _request(self.app, "GET", "/test/calendar/t.ics")
        self.assertTrue(status.startswith("404"), status)
        status, _, body = _request(self.app, "GET", "/test/tasks/t.ics")
        self.assertTrue(status.startswith("200"), status)
        self.assertIn("BEGIN:VTODO", body.decode())

    def test_component_set_metadata(self):
        storage = self.app._storage
        cal = next(iter(storage.discover("/test/calendar/")))
        tsk = next(iter(storage.discover("/test/tasks/")))
        self.assertEqual(
            cal.get_meta("C:supported-calendar-component-set"), "VEVENT")
        self.assertEqual(
            tsk.get_meta("C:supported-calendar-component-set"), "VTODO")

    # ---- sync token ----------------------------------------------------

    def test_sync_default_token(self):
        _request(self.app, "PUT", "/test/calendar/x.ics", VEVENT,
                 {"If-None-Match": "*"})
        storage = self.app._storage
        coll = next(iter(storage.discover("/test/calendar/")))
        token, hrefs = coll.sync()
        self.assertIn("http://radicale.org/ns/sync/", token)
        self.assertIn("x.ics", list(hrefs))
        with self.assertRaises(ValueError):
            coll.sync("stale-token")

    # ---- direct API (no WSGI) ------------------------------------------

    def test_upload_mints_entity_preserves_extras(self):
        storage = self.app._storage
        coll = next(iter(storage.discover("/test/calendar/")))
        from radicale.item import Item
        ics = VEVENT.replace("SUMMARY:Test Event",
                             "SUMMARY:With Extra\r\nX-POC:kept")
        item = Item(collection_path="test/calendar", href="e.ics", text=ics)
        item.prepare()
        uploaded, old = coll.upload("e.ics", item)
        self.assertIsNone(old)
        self.assertEqual(uploaded.href, "e.ics")
        e = self.conn.execute(
            "SELECT e FROM v_current WHERE a = 'ical:href'").fetchone()[0]
        view = self._view(e)
        self.assertEqual(view["ical:extra"], ["X-POC:kept"])
        # rendered back out losslessly
        self.assertIn("X-POC:kept", uploaded.serialize())

    def test_move_repaths_href(self):
        storage = self.app._storage
        coll = next(iter(storage.discover("/test/calendar/")))
        from radicale.item import Item
        item = Item(collection_path="test/calendar", href="a.ics", text=VEVENT)
        item.prepare()
        coll.upload("a.ics", item)
        storage.move(item, coll, "b.ics")
        view_row = self.conn.execute(
            "SELECT v FROM v_current WHERE a = 'ical:href'").fetchone()
        self.assertEqual(view_row[0], "b.ics")
        self.assertIsNotNone(coll._item("b.ics"))
        self.assertIsNone(coll._item("a.ics"))

    def _view(self, e):
        return {a: self._decode(a, v) for a, v in self.conn.execute(
            "SELECT a, v FROM v_current WHERE e = ?", (e,))}

    @staticmethod
    def _decode(a, v):
        import json
        if a == "ical:extra":
            return json.loads(v)
        return v


if __name__ == "__main__":
    unittest.main()
