"""Kernel vocabulary from the vendored kernel-proposal.json (domain-neutral registry)."""
import unittest

from agents_store.registry import (
    KERNEL_PROPOSAL_SHA256,
    MORE_FRAMEWORK_PIN,
    kernel_artifact_types,
    kernel_proposal_sha256,
    kernel_relation_reverse_names,
    kernel_relation_types,
    kernel_violation_ids,
)


class KernelRegistry(unittest.TestCase):
    def test_more_framework_pin_recorded(self):
        self.assertEqual(MORE_FRAMEWORK_PIN, "bb37b5d8d859415202e0f07c67238696f2e86605")

    def test_kernel_proposal_byte_identity(self):
        self.assertEqual(kernel_proposal_sha256(), KERNEL_PROPOSAL_SHA256)

    def test_regulation_requirement_artifact_type(self):
        self.assertIn("regulation_requirement", kernel_artifact_types())

    def test_maps_to_relation_and_mapped_from_reverse(self):
        self.assertIn("maps_to", kernel_relation_types())
        self.assertIn("mapped_from", kernel_relation_reverse_names())

    def test_compliance_violation_ids_reserved(self):
        ids = kernel_violation_ids()
        for vid in (
            "duty_unmapped",
            "matrix_hand_edited",
            "maps_to_target_mismatch",
            "maps_to_compliance_purpose_invalid",
            "preserves_missing",
        ):
            self.assertIn(vid, ids)


if __name__ == "__main__":
    unittest.main()
