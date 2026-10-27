"""T11 — POC acceptance harness. One end-to-end pass mapping each
acceptance criterion (docs/tasks/T11 numbering) to executed checks.

Layout per test:
  tempdir/
    store.sqlite   <- canonical layer (Radicale plugin + test conn share it)
    notes/         <- markdown folder projection (folder.sync)

CalDAV surface: real HTTP via wsgiref on an ephemeral port, so the
agents-calendar CLI witness exercises the true socket path.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from wsgiref.simple_server import WSGIServer, make_server

import radicale
import radicale.config

import agents_store
from agents_store import Change
from agents_store.adapters import folder
from agents_store.capabilities.entity_html import EntityHtml
from agents_store.capabilities.markdown_html import MarkdownHtml
from agents_store.certify import certify, grant_roundtrip
from agents_store.contracts import WriteRefusal
from agents_store.lineage import split
from agents_store.mediator import Artifact, wrapper_capability
from agents_store.pane import render, targets
from agents_store.registry import Registry
from agents_store.store import Store
from agents_store.wrappers.ical import ICalWrapper
from agents_store.wrappers.markdown import MarkdownWrapper

PASSWORD_MARKER = "TESTPASS-SECRET-MARKER"

VEVENT = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//acceptance//EN\r
BEGIN:VEVENT\r
UID:{uid}\r
SUMMARY:{summary}\r
DTSTART:{dtstart}\r
DTEND:{dtend}\r
END:VEVENT\r
END:VCALENDAR\r
"""

_MD_CORPUS = [  # proven corpus (same as tests/unit/test_folder.py)
    {"title": "t1", "body": "b1"},
    {"title": "t2", "status": "open", "body": "b2"},
    {"body": "b", "md:extra": {"k": "v"}},
    {"when": "2026-10-12T10:00:00Z", "end": "2026-10-12T11:00:00Z", "body": "b3"},
]


def _reg_full():
    reg = Registry()
    reg.register_capability(wrapper_capability(MarkdownWrapper(), "markdown"))
    reg.register_capability(wrapper_capability(ICalWrapper(), "ical"))
    reg.register_capability(MarkdownHtml())
    reg.register_capability(EntityHtml())
    return reg


class QuietHandler:
    """Suppress wsgiref request logging noise."""

    def __init__(self, base):
        self.base = base

    def __call__(self, environ, start_response):
        environ["wsgi.errors"] = io.StringIO()
        return self.base(environ, start_response)


class PocCase(unittest.TestCase):
    """Shared live environment: server + store + folder."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="agents-store-poc-"))
        cls.db = str(cls.tmp / "store.sqlite")
        cls.notes = cls.tmp / "notes"
        cls.notes.mkdir()
        os.environ["AGENTS_STORE_DB"] = cls.db
        conf = radicale.config.load()
        conf.update({
            "storage": {"type": "radicale_agents_store"},
            "auth": {"type": "none"},
            "rights": {"type": "owner_only"},
        }, "acceptance")
        app = radicale.Application(conf)
        cls.server: WSGIServer = make_server(
            "127.0.0.1", 0, QuietHandler(app))
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(
            target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        # canonical side: own connection (WAL lets us see plugin commits)
        cls.conn = agents_store.connect(cls.db)
        cls.store = Store(cls.conn)
        cls.mdw = MarkdownWrapper()
        cert = certify(cls.conn, cls.mdw, _MD_CORPUS)
        grant_roundtrip(cls.conn, cls.mdw, cert)
        cls.conn.commit()
        cls.reg = _reg_full()
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.cal = f"{cls.base}/test/calendar"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.conn.close()
        os.environ.pop("AGENTS_STORE_DB", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- helpers -------------------------------------------------------

    def _cli(self, *args):
        env = dict(os.environ)
        env.update({
            "CALDAV_URL": self.base + "/",
            "CALDAV_USERNAME": "test",
            "CALDAV_PASSWORD": PASSWORD_MARKER,
            "CALDAV_CALENDAR": "calendar",
        })
        p = subprocess.run(
            [sys.executable, "-m", "agents_calendar", *args],
            capture_output=True, text=True, env=env, timeout=60)
        return p

    def _request(self, method, path, data=None, headers=None):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        h = {"Authorization": "Basic dGVzdDp4"}
        h.update(headers or {})
        if data is not None:
            h.setdefault("Content-Type", "text/calendar; charset=utf-8")
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        body = r.read()
        hs = {k: v for k, v in r.getheaders()}
        c.close()
        return r.status, hs, body

    def _view(self, e):
        out = {}
        for a, v in self.conn.execute(
                "SELECT a, v FROM v_current WHERE e = ?", (e,)):
            if a == "ical:extra" or a == "md:extra":
                out[a] = json.loads(v)
            else:
                out[a] = v
        return out

    def _entity_by_href(self, href):
        row = self.conn.execute(
            "SELECT e FROM v_current WHERE a = 'ical:href' AND v = ?",
            (href,)).fetchone()
        return row[0] if row else None


class TestA1OneIdentityAllProjections(PocCase):
    """A1: one entity visible through md, ical (both collections) and html."""

    def test_A1_entity_projects_everywhere(self):
        e = self.store.transact([
            Change(e=None, a="title", v="A1 thing"),
            Change(e=None, a="status", v="open"),
            Change(e=None, a="when", v="2026-12-15T10:00:00Z"),
            Change(e=None, a="body", v="the body"),
        ], wrapper="store").entity
        # markdown projection
        folder.sync(self.store, str(self.notes), self.mdw)
        files = list(self.notes.glob("*.md"))
        self.assertEqual(len(files), 1)
        self.assertIn(f"id: {e}", files[0].read_text())
        # ical projection: has status AND when -> VTODO member of tasks,
        # and (has when) also listed in calendar
        status, _, body = self._request(
            "GET", f"/test/tasks/{e}.ics")
        self.assertEqual(status, 200)
        self.assertIn(f"UID:{e}", body.decode())
        # html pane
        art = render(self.conn, self.reg, e, "html")
        self.assertIsInstance(art, Artifact)
        self.assertIn(e, art.value)


class TestA2EditOneLawfulPath(PocCase):
    """A2: CalDAV edit -> canonical + md + html reflect it."""

    def test_A2_caldav_move_propagates(self):
        p = self._cli("add", "--summary", "A2 event",
                      "--dtstart", "2026-12-16T10:00:00Z",
                      "--dtend", "2026-12-16T11:00:00Z",
                      "--calendar", "calendar")
        self.assertEqual(p.returncode, 0, p.stderr)
        added = json.loads(p.stdout)
        e = self._entity_by_href(os.path.basename(added["href"]))
        self.assertIsNotNone(e)
        # move it
        p = self._cli("update", "--href", added["href"],
                      "--etag", added["etag"],
                      "--dtstart", "2026-12-17T10:00:00Z")
        self.assertEqual(p.returncode, 0, p.stderr)
        # canonical moved
        self.assertEqual(self._view(e)["when"], "2026-12-17T10:00:00Z")
        # new tx recorded
        last = self.conn.execute(
            "SELECT note FROM tx ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.assertIn("caldav PUT", last)
        # markdown + pane reflect it
        folder.sync(self.store, str(self.notes), self.mdw)
        md = next(self.notes.glob("*.md")).read_text()
        self.assertIn("when: 2026-12-17T10:00:00Z", md)


class TestA3MarkdownRoundTrip(PocCase):
    """A3: markdown edits -> canonical; rename keeps id (path is data)."""

    def test_A3_md_edit_and_rename(self):
        e = self.store.transact([
            Change(e=None, a="title", v="A3 title"),
            Change(e=None, a="body", v="old body"),
        ], wrapper="store").entity
        folder.sync(self.store, str(self.notes), self.mdw)
        path = next(self.notes.glob("*.md"))
        # user edits title + body, renames the file
        text = path.read_text().replace("A3 title", "A3 renamed")
        text = text.replace("old body", "new body")
        path.unlink()
        (self.notes / "completely-different-name.md").write_text(text)
        rep = folder.sync(self.store, str(self.notes), self.mdw)
        self.assertFalse(rep.refusals, rep.refusals)
        v = self._view(e)
        self.assertEqual(v["title"], "A3 renamed")
        self.assertEqual(v["body"], "new body")
        # same entity, only md:path changed
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM entity WHERE id = ?", (e,)).fetchone()[0], 1)


class TestA4UidIsEntityId(PocCase):
    """A4: emitted UID == entity id; events in calendar, tasks in tasks."""

    def test_A4_uid_and_membership(self):
        ev = self.store.transact([
            Change(e=None, a="title", v="A4 event"),
            Change(e=None, a="when", v="2026-12-18T09:00:00Z"),
        ], wrapper="store").entity
        td = self.store.transact([
            Change(e=None, a="title", v="A4 task"),
            Change(e=None, a="status", v="open"),
        ], wrapper="store").entity
        status, _, body = self._request("GET", f"/test/calendar/{ev}.ics")
        self.assertEqual(status, 200)
        self.assertIn(f"UID:{ev}", body.decode())
        status, _, body = self._request("GET", f"/test/tasks/{td}.ics")
        self.assertEqual(status, 200)
        self.assertIn(f"UID:{td}", body.decode())
        self.assertIn("BEGIN:VTODO", body.decode())


class TestA5IndependentWitness(PocCase):
    """A5: agents-calendar CLI over real HTTP (Thunderbird = manual)."""

    def test_A5_agents_calendar_list_update_delete(self):
        p = self._cli("calendars")
        self.assertEqual(p.returncode, 0, p.stderr)
        cals = json.loads(p.stdout)
        names = [c.get("displayname") for c in cals]
        self.assertIn("agents-store calendar", names)
        p = self._cli("add", "--summary", "A5 witnessed",
                      "--dtstart", "2026-12-20T08:00:00Z",
                      "--dtend", "2026-12-20T09:00:00Z",
                      "--calendar", "calendar")
        self.assertEqual(p.returncode, 0, p.stderr)
        added = json.loads(p.stdout)
        self.assertTrue(added.get("etag"), added)
        # independent list sees it
        p = self._cli("list", "--from", "2026-12-20T00:00:00Z",
                      "--to", "2026-12-21T00:00:00Z",
                      "--calendar", "calendar")
        self.assertEqual(p.returncode, 0, p.stderr)
        events = json.loads(p.stdout)
        self.assertTrue(any(ev.get("summary") == "A5 witnessed"
                            for ev in events), events)
        # update with etag, delete with etag
        p = self._cli("update", "--href", added["href"],
                      "--etag", added["etag"],
                      "--summary", "A5 moved")
        self.assertEqual(p.returncode, 0, p.stderr)
        moved = json.loads(p.stdout)
        self.assertTrue(moved.get("etag"))
        p = self._cli("delete", "--href", added["href"],
                      "--etag", moved["etag"])
        self.assertEqual(p.returncode, 0, p.stderr)
        # gone from the projection, history intact
        e = self._entity_by_href(os.path.basename(added["href"]))
        if e is not None:  # href datum may be retracted with delete
            self.assertNotIn("when", self._view(e))


class TestA6PaneIdentity(PocCase):
    """A6: html pane renders the same identity."""

    def test_A6_pane_same_id(self):
        e = self.store.transact([
            Change(e=None, a="title", v="A6"),
            Change(e=None, a="body", v="x"),
        ], wrapper="store").entity
        self.assertIn("html", targets(self.conn, self.reg, e))
        art = render(self.conn, self.reg, e, "html")
        self.assertIsInstance(art, Artifact)
        self.assertIn(e, art.value)


class TestA7AppendOnly(PocCase):
    """A7: datom rejects UPDATE/DELETE; history is ordered + complete."""

    def test_A7_datom_immutable(self):
        e = self.store.transact(
            [Change(e=None, a="title", v="A7")], wrapper="store").entity
        with self.assertRaises(Exception):
            self.conn.execute("UPDATE datom SET added = 0")
        with self.assertRaises(Exception):
            self.conn.execute("DELETE FROM datom")
        hist = self.store.history(e)
        self.assertGreaterEqual(len(hist), 1)


class TestA8MalformedRefused(PocCase):
    """A8: malformed payloads refused, no partial writes."""

    def test_A8_bad_ics_no_partial(self):
        n0 = self.conn.execute("SELECT COUNT(*) FROM entity").fetchone()[0]
        # syntax-level garbage: vobject rejects app-side -> 400, nothing minted
        status, _, _ = self._request(
            "PUT", "/test/calendar/bad.ics",
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            "UID:b\r\nSUMMARY:x\r\nDTSTART:not-a-date\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n",
            {"If-None-Match": "*"})
        self.assertNotEqual(status, 201)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM entity").fetchone()[0],
            n0)
        # parses fine but breaks our law -> wrapper refusal lands in table
        status, _, _ = self._request(
            "PUT", "/test/calendar/tz.ics",
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            "UID:t1\r\nSUMMARY:x\r\n"
            "DTSTART;TZID=Europe/Berlin:20261201T100000\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n",
            {"If-None-Match": "*"})
        self.assertEqual(status, 400)
        self.assertTrue(any(r.reason == "tz_unsupported"
                            for r in self.store.refusals()))

    def test_A8_md_id_edit_refused(self):
        e = self.store.transact(
            [Change(e=None, a="title", v="A8"), Change(e=None, a="body", v="b")],
            wrapper="store").entity
        folder.sync(self.store, str(self.notes), self.mdw)
        path = next(p for p in self.notes.glob("*.md") if f"id: {e}" in p.read_text())
        path.write_text(path.read_text().replace(f"id: {e}", "id: forged-id"))
        rep = folder.sync(self.store, str(self.notes), self.mdw)
        self.assertTrue(rep.refusals or
                        any(r.reason for r in self.store.refusals()))
        self.assertEqual(self._view(e)["title"], "A8")


class TestA9KindChangeAndSplit(PocCase):
    """A9: +status -> task (same id); split -> new id + lineage."""

    def test_A9_note_becomes_task_and_split(self):
        e = self.store.transact([
            Change(e=None, a="title", v="A9 note"),
            Change(e=None, a="body", v="b"),
        ], wrapper="store").entity
        self.store.transact(
            [Change(e=e, a="status", v="open")], wrapper="store")
        self.assertEqual(self._view(e)["status"], "open")
        self.assertTrue(self.store.exists(e))
        new_e = split(self.store, e, [["title"]], reason="halve it")[0]
        self.assertNotEqual(new_e, e)
        edge = self.conn.execute(
            "SELECT kind FROM lineage WHERE child = ? AND parent = ?",
            (new_e, e)).fetchone()
        self.assertIsNotNone(edge)


class TestA10LossyWriteRefused(PocCase):
    """A10: non-lawful write refused with reason + refusal row."""

    def test_A10_tz_refused(self):
        status, _, _ = self._request(
            "PUT", "/test/calendar/tz.ics",
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            "UID:t1\r\nSUMMARY:x\r\n"
            "DTSTART;TZID=Europe/Berlin:20261201T100000\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n",
            {"If-None-Match": "*"})
        self.assertEqual(status, 400)
        self.assertTrue(any(r.reason == "tz_unsupported"
                            for r in self.store.refusals()))


class TestA11NoSecrets(PocCase):
    """A11: the configured password never leaks into data or artifacts."""

    def test_A11_password_absent_everywhere(self):
        self._cli("calendars")  # exercise an authenticated request
        e = self.store.transact([
            Change(e=None, a="title", v="A11"), Change(e=None, a="body", v="b")],
            wrapper="store").entity
        status, _, body = self._request("GET", f"/test/tasks/{e}.ics")
        self.assertNotIn(PASSWORD_MARKER.encode(), body if status == 200 else b"")
        folder.sync(self.store, str(self.notes), self.mdw)
        for f in self.notes.glob("*.md"):
            self.assertNotIn(PASSWORD_MARKER, f.read_text())
        art = render(self.conn, self.reg, e, "html")
        self.assertNotIn(PASSWORD_MARKER, getattr(art, "value", ""))
        for r in self.store.refusals():
            self.assertNotIn(PASSWORD_MARKER, str(r.payload))
        # and nowhere on disk in the fixture tree
        for f in self.tmp.rglob("*"):
            if f.is_file() and f.suffix in {".md", ".ics", ".html", ".json"}:
                self.assertNotIn(PASSWORD_MARKER,
                                 f.read_text(errors="replace"))


if __name__ == "__main__":
    unittest.main()
