"""world_model_projection in the vendored kernel-proposal.json (mirror of
Cypoe/more-framework@504c85f2854a66da9d4cb165f3559cd13c855ec2, companion/python/more_kernel/world_model.py and
More/WorldModel.lean). The Python world model is not vendored here; lolaplex-board
ports it."""
import json
import unittest

from agents_store.more.profile import SPEC_PATH

OPEN_ITEM_REASONS = (
    "decision_open",
    "dor_violation",
    "claim_unmet",
    "compliance_gap",
    "challenge_open",
    "gap_signal_open",
)
COMPLIANCE_GAP_FIELD = "compliance"
COMPLIANCE_GAP_REF = {
    "regulation": "string",
    "duty": "string",
    "duty_version": "string",
    "event_type": "event type id from core_primitives.event.types",
}
COMPLIANCE_GAP_TEXT = (
    "compliance matrix projection: any row with gap at the subject's hierarchy "
    "level (More/Compliance.lean matrix, More/WorldModel.lean complianceOpenItems)"
)


class WorldModelProjection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        doc = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        cls.wmp = doc["projections"]["lolaplex-board"]["board_only_config"][
            "world_model_projection"
        ]

    def test_open_item_reasons_order(self):
        self.assertEqual(list(OPEN_ITEM_REASONS), self.wmp["open_item_reasons"])

    def test_compliance_gap_spec_fields(self):
        self.assertEqual(COMPLIANCE_GAP_FIELD, self.wmp["compliance_gap_field"])
        self.assertEqual(COMPLIANCE_GAP_REF, self.wmp["compliance_gap_ref"])
        self.assertEqual(COMPLIANCE_GAP_TEXT, self.wmp["compliance_gap"])


if __name__ == "__main__":
    unittest.main()
