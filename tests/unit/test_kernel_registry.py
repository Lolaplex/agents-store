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
    verify_replay_contract_manifest,
)


class KernelRegistry(unittest.TestCase):
    def test_more_framework_pin_recorded(self):
        self.assertEqual(MORE_FRAMEWORK_PIN, "504c85f2854a66da9d4cb165f3559cd13c855ec2")

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
            "refines_meaning_missing",
            "refines_pair_not_in_profile",
            "refines_level_invalid",
        ):
            self.assertIn(vid, ids)

    def test_replay_contract_manifest(self):
        self.assertEqual(verify_replay_contract_manifest(), [])

if __name__ == "__main__":
    unittest.main()
