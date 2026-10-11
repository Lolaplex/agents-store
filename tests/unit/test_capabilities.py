"""Render capabilities: md-html subset + entity card."""
import unittest

from agents_store import Registry
from agents_store.capabilities.entity_html import EntityHtml, render_entity
from agents_store.capabilities.markdown_html import MarkdownHtml, render_md


class TestMarkdownHtml(unittest.TestCase):
    def test_heading_and_para(self):
        h = render_md("# Hi\n\nsome text")
        self.assertIn("<h1>Hi</h1>", h)
        self.assertIn("<p>some text</p>", h)

    def test_bold_italic_code(self):
        h = render_md("a **b** and *i* and `c`")
        self.assertIn("<strong>b</strong>", h)
        self.assertIn("<em>i</em>", h)
        self.assertIn("<code>c</code>", h)

    def test_lists(self):
        h = render_md("- one\n- two\n\n1. a\n2. b")
        self.assertIn("<ul><li>one</li><li>two</li></ul>", h)
        self.assertIn("<ol><li>a</li><li>b</li></ol>", h)

    def test_fenced_code_escaped(self):
        h = render_md("```\n<b>x</b>\n```")
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", h)

    def test_script_escaped(self):
        h = render_md("<script>alert(1)</script>")
        self.assertNotIn("<script>", h)
        self.assertIn("&lt;script&gt;", h)

    def test_javascript_link_stripped(self):
        h = render_md("[click](javascript:alert(1))")
        self.assertNotIn("javascript:", h)

    def test_safe_link_renders(self):
        h = render_md("[t](https://x.test/y)")
        self.assertIn('href="https://x.test/y"', h)


class TestEntityHtml(unittest.TestCase):
    def test_card_has_id_kinds_attrs(self):
        h = render_entity({
            "id": "E1", "view": {"title": "T", "status": "open"},
            "kinds": ["task", "note"],
        })
        self.assertIn('data-id="E1"', h)
        self.assertIn("task", h)
        self.assertIn("<td>open</td>", h)

    def test_derived_marked(self):
        h = render_entity({
            "id": "E1", "view": {"when": "2026-10-12T10:00:00Z"},
            "kinds": ["event"], "derived": {"end": "plus_1h"},
        })
        self.assertIn("derived", h)
        self.assertIn("plus_1h", h)

    def test_lineage_listed(self):
        h = render_entity({
            "id": "C", "view": {}, "lineage": [("C", "P", "wasDerivedFrom")],
        })
        self.assertIn("wasDerivedFrom", h)
        self.assertIn("P", h)


class TestRegistry(unittest.TestCase):
    def test_capabilities_register(self):
        reg = Registry()
        reg.register_capability(MarkdownHtml())
        reg.register_capability(EntityHtml())
        self.assertEqual(len(reg.capabilities), 2)


if __name__ == "__main__":
    unittest.main()
