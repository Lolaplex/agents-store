"""MORe provider kernel violation registry (refines §16)."""
import unittest

from agents_store.domains.more import factory as more_factory
from agents_store.domains.more_violations import more_violation_registry
from agents_store.registry import MORE_FRAMEWORK_PIN, MORE_FRAMEWORK_REPLAY_REPO


class MoreViolationRegistry(unittest.TestCase):
    def test_registry_ids_and_provenance(self) -> None:
        reg = more_violation_registry()
        self.assertEqual({v.id for v in reg}, {
            "refines_meaning_missing",
            "refines_pair_not_in_profile",
            "refines_level_invalid",
        })
        pin = f"{MORE_FRAMEWORK_REPLAY_REPO}@{MORE_FRAMEWORK_PIN}"
        for v in reg:
            self.assertEqual(v.domain, "more")
            self.assertEqual(v.severity, "refusal")
            self.assertEqual(v.provenance_ref, pin)
            self.assertTrue(v.fires_when)

    def test_more_domain_exposes_registry(self) -> None:
        d = more_factory()
        self.assertEqual(list(d.violation_registry()), list(more_violation_registry()))
        for vid in ("refines_meaning_missing", "refines_pair_not_in_profile", "refines_level_invalid"):
            self.assertIn(vid, d.refusal_ids())


if __name__ == "__main__":
    unittest.main()
