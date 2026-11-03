"""MORe provider kernel violation registry (relation projection ids)."""
import unittest

from agents_store.domains.more import factory as more_factory
from agents_store.domains.more_violations import (
    RELATION_VIOLATION_IDS,
    more_violation_registry,
)
from agents_store.registry import MORE_FRAMEWORK_PIN, MORE_FRAMEWORK_REPLAY_REPO


class MoreViolationRegistry(unittest.TestCase):
    def test_registry_covers_relation_check_ids(self) -> None:
        reg = more_violation_registry()
        self.assertEqual({v.id for v in reg}, RELATION_VIOLATION_IDS)
        self.assertEqual(len(reg), 9)

    def test_registry_provenance_and_fires_when(self) -> None:
        pin = f"@{MORE_FRAMEWORK_PIN}"
        for v in more_violation_registry():
            self.assertEqual(v.domain, "more")
            self.assertEqual(v.severity, "refusal")
            self.assertIn(MORE_FRAMEWORK_REPLAY_REPO, v.provenance_ref)
            self.assertIn(pin, v.provenance_ref)
            self.assertIn(":", v.provenance_ref)
            self.assertTrue(v.fires_when)
        refines = {
            e.id: e.provenance_ref
            for e in more_violation_registry()
            if e.id.startswith("refines_")
        }
        self.assertTrue(
            all(p.endswith("#section-16") for p in refines.values()),
            refines,
        )

    def test_more_domain_exposes_registry(self) -> None:
        d = more_factory()
        self.assertEqual(list(d.violation_registry()), list(more_violation_registry()))

    def test_refusal_ids_are_write_path_only(self) -> None:
        d = more_factory()
        self.assertEqual(tuple(d.refusal_ids()), ("payload_invalid", "append_refused"))
        for vid in RELATION_VIOLATION_IDS:
            self.assertNotIn(vid, d.refusal_ids())


if __name__ == "__main__":
    unittest.main()
