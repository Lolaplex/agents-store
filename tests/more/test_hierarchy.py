import unittest

from agents_store.more.hierarchy import Node, lint, lint_profile
from agents_store.more.profile import load_profile

P = load_profile()


def ids(findings):
    return [f.id for f in findings]


def tree(**extra):
    """BEL §7.3 example domain: cut-over shown as a use case with an open DEC."""
    nodes = [
        Node("FG-COP", "Fachgebiet", None, {"Fachgebiet": "Cut-over planning: UC-COP-011 shows the stock; UC-COP-012 plans the steps."}),
        Node("UC-COP-011", "Anwendungsfall", "FG-COP", {"Anwendungsfall": "The planner wants to see the cut-over stock on the board."}),
        Node("AC-COP-011-1", "AC", "UC-COP-011", {"AC": "Every open item of the stock is listed with its owner."}),
        Node("DEC-COP-001", "DEC", "UC-COP-011", {"DEC": "Open: which system holds the stock."}),
    ]
    nodes += extra.get("more", [])
    return nodes


class Profile(unittest.TestCase):
    def test_every_level_declares_one_question(self):
        self.assertEqual(lint_profile(P), [])


class OneQuestion(unittest.TestCase):
    def test_clean_tree(self):
        self.assertEqual(lint(tree(), P), [])

    def test_answers_none(self):
        for text in (None, "", "  TBD ", "…", "n/a"):
            sections = {} if text is None else {"AC": text}
            f = lint(tree(more=[Node("AC-X", "AC", "UC-COP-011", sections)]), P)
            self.assertEqual(ids(f), ["node_answers_none"], text)
            self.assertIn("When is the requirement fulfilled", f[0].detail)

    def test_answers_multiple_by_section(self):
        uc = Node("UC-X", "Anwendungsfall", "FG-COP", {
            "Anwendungsfall": "The clerk wants to export the UStVA.",
            "AC": "Kz84 and Kz85 are both present or both absent.",
        })
        self.assertEqual(ids(lint(tree(more=[uc]), P)), ["node_answers_multiple"])

    def test_answers_multiple_by_heading_alias(self):
        uc = Node("UC-X", "Anwendungsfall", "FG-COP", {"Anwendungsfall":
            "The clerk wants to export the UStVA.\n\n## Akzeptanzkriterien\n- both or neither"})
        f = lint(tree(more=[uc]), P)
        self.assertEqual(ids(f), ["node_answers_multiple"])
        self.assertIn("AC section", f[0].detail)

    def test_answers_multiple_by_question_text(self):
        uc = Node("UC-X", "Anwendungsfall", "FG-COP", {"Anwendungsfall":
            "The clerk wants to export the UStVA.\nWarum ist es so gelöst?\nBecause ERiC needs it."})
        f = lint(tree(more=[uc]), P)
        self.assertEqual(ids(f), ["node_answers_multiple"])
        self.assertIn("DEC section", f[0].detail)

    def test_own_level_heading_is_fine(self):
        dec = Node("DEC-X", "DEC", "UC-COP-011", {"DEC": "## Decision\nThe CRM already has it; no build."})
        self.assertEqual(lint(tree(more=[dec]), P), [])

    def test_placeholder_sections_for_other_levels_are_ignored(self):
        uc = Node("UC-X", "Anwendungsfall", "FG-COP", {"Anwendungsfall": "Export.", "AC": "TBD"})
        self.assertEqual(lint(tree(more=[uc]), P), [])


class Structure(unittest.TestCase):
    def test_unknown_level(self):
        self.assertEqual(ids(lint([Node("X-1", "Epic", None, {"Epic": "x"})], P)), ["level_unknown"])

    def test_wrong_parent_level(self):
        ac = Node("AC-X", "AC", "FG-COP", {"AC": "listed"})
        self.assertEqual(ids(lint(tree(more=[ac]), P)), ["hierarchy_parent_invalid"])

    def test_missing_parent(self):
        uc = Node("UC-X", "Anwendungsfall", None, {"Anwendungsfall": "x"})
        self.assertEqual(ids(lint(tree(more=[uc]), P)), ["hierarchy_parent_invalid"])

    def test_root_with_parent(self):
        fg = Node("FG-2", "Fachgebiet", "FG-COP", {"Fachgebiet": "x"})
        self.assertEqual(ids(lint(tree(more=[fg]), P)), ["hierarchy_parent_invalid"])


if __name__ == "__main__":
    unittest.main()
