"""pane: targets gating + render."""
import unittest

from agents_store import Change, WriteRefusal, connect
from agents_store.capabilities.entity_html import EntityHtml
from agents_store.capabilities.markdown_html import MarkdownHtml
from agents_store.mediator import Artifact, wrapper_capability
from agents_store.pane import entities_viewable, render, targets
from agents_store.registry import Registry
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


class TestPane(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.store = Store(self.conn)
        self.reg = reg_full()

    def make(self, attrs):
        return self.store.transact(
            [Change(e=None, a=a, v=v) for a, v in attrs.items()], wrapper="store"
        ).entity

    def test_full_entity_all_targets(self):
        e = self.make({"title": "T", "body": "b", "status": "open",
                       "when": "2026-10-12T10:00:00Z"})
        t = targets(self.conn, self.reg, e)
        self.assertTrue({"html", "markdown", "ical"} <= t)

    def test_title_only_no_targets(self):
        e = self.make({"title": "T"})
        self.assertEqual(targets(self.conn, self.reg, e), set())
        r = render(self.conn, self.reg, e, "html")
        self.assertIsInstance(r, WriteRefusal)
        self.assertEqual(r.reason, "no_capability_path")

    def test_note_has_markdown_and_html_not_ical(self):
        e = self.make({"body": "b"})
        t = targets(self.conn, self.reg, e)
        self.assertIn("markdown", t)
        self.assertIn("html", t)
        self.assertNotIn("ical", t)

    def test_event_has_ical(self):
        e = self.make({"when": "2026-10-12T10:00:00Z"})
        self.assertIn("ical", targets(self.conn, self.reg, e))

    def test_render_same_id_all_reprs(self):
        e = self.make({"title": "T", "body": "b", "status": "open",
                       "when": "2026-10-12T10:00:00Z"})
        for target in ("markdown", "ical", "html"):
            art = render(self.conn, self.reg, e, target)
            self.assertIsInstance(art, Artifact)
            self.assertIn(e, art.value if isinstance(art.value, str) else str(art.value))

    def test_derived_end_not_in_ical(self):
        # derived 'end' is display-only, never written into a repr
        e = self.make({"when": "2026-10-12T10:00:00Z"})
        art = render(self.conn, self.reg, e, "ical")
        self.assertNotIn("DTEND", art.value)
        self.assertNotIn("DUE", art.value)
        art2 = render(self.conn, self.reg, e, "html")
        self.assertIn("plus_1h", art2.value)

    def test_entities_viewable(self):
        e1 = self.make({"body": "b"})
        e2 = self.make({"when": "2026-10-12T10:00:00Z"})
        e3 = self.make({"title": "t"})
        md_view = entities_viewable(self.conn, self.reg, "markdown")
        self.assertIn(e1, md_view)
        self.assertNotIn(e2, md_view)
        self.assertNotIn(e3, md_view)


if __name__ == "__main__":
    unittest.main()
