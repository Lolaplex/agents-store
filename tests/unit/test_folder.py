"""Folder adapter: sync between a directory and the canonical store."""
import tempfile
import unittest
from pathlib import Path

from agents_store import Change, connect
from agents_store.adapters.folder import sync
from agents_store.certify import certify, grant_roundtrip
from agents_store.store import Store
from agents_store.wrappers.markdown import MarkdownWrapper

# corpus excludes md:path (adapter-owned; put never sees it in text)
CORPUS = [
    {"title": "t1", "body": "b1"},
    {"title": "t2", "status": "open", "body": "b2"},
    {"body": "b", "md:extra": {"k": "v"}},
    {"when": "2026-10-12T10:00:00Z", "end": "2026-10-12T11:00:00Z", "body": "b3"},
]


class FolderCase(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.store = Store(self.conn)
        self.w = MarkdownWrapper()
        cert = certify(self.conn, self.w, CORPUS)
        grant_roundtrip(self.conn, self.w, cert)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        (self.root / name).write_text(text, encoding="utf-8")


class TestSync(FolderCase):
    def test_new_file_mints_and_rewrites(self):
        self.write("note.md", "---\ntitle: hello\n---\nfirst body")
        rep = sync(self.store, self.root, self.w)
        self.assertEqual(rep.created, 1)
        text = (self.root / "note.md").read_text()
        self.assertIn("id: ", text)
        eid = [l for l in text.splitlines() if l.startswith("id: ")][0][4:]
        self.assertTrue(self.store.exists(eid))
        self.assertEqual(self.store.view(eid)["body"], "first body")

    def test_second_sync_converges(self):
        self.write("note.md", "---\ntitle: hello\n---\nbody")
        sync(self.store, self.root, self.w)
        before = self.conn.execute("SELECT COUNT(*) FROM entity").fetchone()[0]
        rep2 = sync(self.store, self.root, self.w)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM entity").fetchone()[0], before)
        self.assertEqual(rep2.created, 0)

    def test_edit_propagates(self):
        self.write("n.md", "---\ntitle: v1\n---\nb")
        sync(self.store, self.root, self.w)
        self.write("n.md", (self.root / "n.md").read_text().replace("title: v1", "title: v2"))
        sync(self.store, self.root, self.w)
        e = self.conn.execute("SELECT e FROM v_current WHERE a='title'").fetchone()[0]
        self.assertEqual(self.store.view(e)["title"], "v2")

    def test_unknown_entity_refused(self):
        self.write("ghost.md", "---\nid: NOPE\ntitle: x\n---\nb")
        rep = sync(self.store, self.root, self.w)
        self.assertIn("unknown-entity", {r.reason for r in rep.refusals})
        self.assertIn("title: x", (self.root / "ghost.md").read_text())  # untouched

    def test_rename_keeps_id(self):
        self.write("a.md", "---\ntitle: t\n---\nb")
        sync(self.store, self.root, self.w)
        eid = [r[0] for r in self.conn.execute("SELECT e FROM v_current WHERE a='md:path'")][0]
        (self.root / "a.md").rename(self.root / "renamed.md")
        sync(self.store, self.root, self.w)
        paths = {r[0] for r in self.conn.execute(
            "SELECT v FROM v_current WHERE e=? AND a='md:path'", (eid,))}
        self.assertEqual(paths, {"renamed.md"})

    def test_delete_retracts_path_not_entity(self):
        self.write("a.md", "---\ntitle: t\n---\nb")
        sync(self.store, self.root, self.w)
        eid = [r[0] for r in self.conn.execute("SELECT e FROM v_current WHERE a='md:path'")][0]
        (self.root / "a.md").unlink()
        sync(self.store, self.root, self.w)
        self.assertTrue(self.store.exists(eid))
        self.assertNotIn("md:path", self.store.view(eid))
        self.assertFalse((self.root / "a.md").exists())  # not resurrected
        # nor rewritten under a new name
        self.assertEqual(list(self.root.glob("*.md")), [])

    def test_store_entity_written_back(self):
        eid = self.store.transact(
            [Change(e=None, a="title", v="From Store"), Change(e=None, a="body", v="sb")],
            wrapper="store").entity
        rep = sync(self.store, self.root, self.w)
        self.assertGreaterEqual(rep.files_written, 1)
        name = self.conn.execute(
            "SELECT v FROM v_current WHERE e=? AND a='md:path'", (eid,)).fetchone()[0]
        self.assertTrue((self.root / name).exists())
        self.assertIn(f"id: {eid}", (self.root / name).read_text())

    def test_path_collision_refused(self):
        other = self.store.transact(
            [Change(e=None, a="body", v="x"), Change(e=None, a="md:path", v="taken.md")],
            wrapper="store").entity
        self.write("taken.md", "---\ntitle: squatter\n---\nb")
        rep = sync(self.store, self.root, self.w)
        self.assertIn("path-collision", {r.reason for r in rep.refusals})
        self.assertFalse((self.root / "taken.md").read_text().startswith("---\nid:"))

    def test_id_edit_refused(self):
        self.write("a.md", "---\ntitle: t\n---\nb")
        sync(self.store, self.root, self.w)
        text = (self.root / "a.md").read_text()
        forged = text.replace("id: ", "id: FORGED", 1)
        self.write("a.md", forged)
        rep = sync(self.store, self.root, self.w)
        self.assertIn("unknown-entity", {r.reason for r in rep.refusals})


if __name__ == "__main__":
    unittest.main()
