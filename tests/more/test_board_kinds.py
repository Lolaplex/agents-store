"""Board hierarchy kinds and the implements relation in the vendored
kernel-proposal.json (mirror of Cypoe/more-framework@c56f457,
kernel/More/BoardProjection.lean boardKindLevel / boardRelType)."""
import json
import unittest

from agents_store.more.profile import SPEC_PATH, load_profile

KINDS = {
    "domain": "Fachgebiet",
    "use_case": "Anwendungsfall",
    "business_process": "BP",
    "conceptual_model": "CM",
    "ui_spec": "UI",
    "api_spec": "API",
    "acceptance_criterion": "AC",
}


class BoardKinds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        doc = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        cls.cfg = doc["projections"]["lolaplex-board"]["board_only_config"]
        cls.rel_types = doc["layers"]["relations"]["types"]
        cls.p = load_profile()

    def test_hierarchy_kinds(self):
        hier = {k: v.split(" ", 1)[1] for k, v in self.cfg["kind_map"].items()
                if v.startswith("hierarchy_node ")}
        self.assertEqual(hier, KINDS)
        for kind, level in KINDS.items():
            self.assertIn(level, self.p.levels)
            self.assertEqual(self.cfg["kind_map_hierarchy"][kind]["level"], level)
            self.assertTrue(self.cfg["kind_map_hierarchy"][kind]["level_source"])

    def test_jwf_node_levels_covered(self):
        self.assertTrue({"BP", "CM", "AC", "UI", "API"} <= set(KINDS.values()))

    def test_relation_map_is_flat_and_typed(self):
        for board_rel, kernel in self.cfg["relation_map"].items():
            self.assertIsInstance(kernel, str)
            if kernel != "board-only":
                self.assertIn(kernel, self.rel_types)
        self.assertEqual(self.cfg["relation_map"]["implements"], "implements")
        src = self.cfg["relation_map_sources"]["implements"]
        self.assertEqual(src["source"], "BEL §7.2, ELSTER §6")
        self.assertTrue(src["preserves_required"])


if __name__ == "__main__":
    unittest.main()
