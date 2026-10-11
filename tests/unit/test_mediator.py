"""mediator: path search, composition, mediator+provenance rows."""
import json
import unittest

from agents_store import Change, Registry, connect
from agents_store.capabilities.entity_html import EntityHtml
from agents_store.capabilities.markdown_html import MarkdownHtml
from agents_store.mediator import find_path, mediate, wrapper_capability
from agents_store.store import Store
from agents_store.wrappers.ical import ICalWrapper
from agents_store.wrappers.markdown import MarkdownWrapper


def reg_full():
    reg = Registry()
    reg.register_capability(wrapper_capability(MarkdownWrapper(), "markdown"))
    reg.register_capability(wrapper_capability(ICalWrapper(), "ical"))
    reg.register_capability(MarkdownHtml())
    reg.register_capability(EntityHtml())
    return reg


class TestFindPath(unittest.TestCase):
    def test_direct_and_two_hop(self):
        reg = reg_full()
        self.assertEqual(find_path(reg, "entity", "html").steps, ("entity-html",))
        self.assertEqual(find_path(reg, "entity", "markdown").steps, ("md-get",))
        self.assertEqual(find_path(reg, "entity", "ical").steps, ("ical-get",))

    def test_no_path(self):
        reg = Registry()
        reg.register_capability(MarkdownHtml())
        self.assertIsNone(find_path(reg, "entity", "html"))


class TestMediate(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.store = Store(self.conn)
        self.reg = reg_full()

    def make(self, attrs):
        return self.store.transact(
            [Change(e=None, a=a, v=v) for a, v in attrs.items()], wrapper="store"
        ).entity

    def test_html_via_markdown_path(self):
        reg = Registry()
        reg.register_capability(wrapper_capability(MarkdownWrapper(), "markdown"))
        reg.register_capability(MarkdownHtml())
        e = self.make({"title": "T", "body": "# Hi\n\nbody"})
        art = mediate(self.conn, reg, e, "html")
        self.assertIsNotNone(art)
        self.assertEqual(art.path.steps, ("md-get", "md-html"))
        self.assertEqual(art.exactness, "contained")  # a render step makes it lossy
        self.assertIn("<h1>Hi</h1>", art.value)

    def test_exact_when_all_lens(self):
        e = self.make({"title": "T", "body": "b"})
        art = mediate(self.conn, self.reg, e, "markdown")
        self.assertEqual(art.exactness, "exact")
        self.assertIn("title: T", art.value)

    def test_mediator_and_provenance_rows(self):
        e = self.make({"body": "b"})
        art = mediate(self.conn, self.reg, e, "html")
        row = self.conn.execute(
            "SELECT source, target, exactness FROM mediator WHERE id = ?", (art.mediator_id,)
        ).fetchone()
        self.assertEqual(row, ("entity", "html", "contained"))
        prov = self.conn.execute(
            "SELECT in_refs FROM provenance WHERE mediator_id = ?", (art.mediator_id,)
        ).fetchone()
        self.assertEqual(json.loads(prov[0]), [e, "entity"])

    def test_no_path_returns_none(self):
        reg = Registry()
        e = self.make({"body": "b"})
        self.assertIsNone(mediate(self.conn, reg, e, "html"))

    def test_derived_end_marked_in_card(self):
        e = self.make({"when": "2026-10-12T10:00:00Z"})
        art = mediate(self.conn, self.reg, e, "html")
        self.assertIn("plus_1h", art.value)  # end derived via rule name


if __name__ == "__main__":
    unittest.main()
