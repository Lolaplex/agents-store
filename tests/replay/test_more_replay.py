"""Replay fixtures: store MORe provider must match the more-framework contract."""
from __future__ import annotations

import json
import unittest

from agents_store.more.replay import (
    ReplayError,
    check_mcdc_coverage,
    list_fixture_paths,
    list_invalid_paths,
    load_fixture,
    load_mcdc,
    parse_fixture_data,
    run_fixture,
    run_fixture_relations,
)
from agents_store.more.replay_store import (
    check_mcdc_coverage_store,
    run_fixture_relations_store,
    run_fixture_store,
)
from agents_store.registry import MORE_FRAMEWORK_PIN, verify_replay_contract_manifest


class MoreReplayContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        errs = verify_replay_contract_manifest()
        if errs:
            raise unittest.SkipTest("replay_contract manifest: " + "; ".join(errs))

    def test_manifest_matches_pin(self) -> None:
        self.assertEqual(MORE_FRAMEWORK_PIN, "bb37b5d8d859415202e0f07c67238696f2e86605")

    def test_mcdc_table_has_independence_pairs(self) -> None:
        errs = check_mcdc_coverage()
        self.assertEqual(errs, [], "\n".join(errs))

    def test_mcdc_table_has_independence_pairs_via_store(self) -> None:
        errs = check_mcdc_coverage_store()
        self.assertEqual(errs, [], "\n".join(errs))

    def test_mcdc_reason_order_matches_open_item_reasons(self) -> None:
        spec = load_mcdc()
        self.assertEqual(
            list(spec["reasons"].keys()),
            [
                "decision_open",
                "dor_violation",
                "claim_unmet",
                "compliance_gap",
                "challenge_open",
                "gap_signal_open",
                "maps_to_violation",
            ],
        )

    def test_fixture_count(self) -> None:
        self.assertEqual(len(list_fixture_paths()), 38)

    def test_fixture_matches_expected_open_items_via_store(self) -> None:
        for path in list_fixture_paths():
            with self.subTest(fixture=path.stem):
                data = load_fixture(path)
                actual, expected, refusals = run_fixture_store(data)
                self.assertFalse(
                    refusals,
                    f"append refused: {refusals[0].reason if refusals else ''}",
                )
                self.assertEqual(actual, expected)
                rel_actual, rel_expected, rel_ref = run_fixture_relations_store(data)
                self.assertFalse(rel_ref, "relations append refused")
                self.assertEqual(rel_actual, rel_expected)

    def test_companion_projection_matches_expected(self) -> None:
        """In-memory log projection (Lean/Python companion path) sanity-checks world_model."""
        for path in list_fixture_paths():
            with self.subTest(fixture=path.stem):
                data = load_fixture(path)
                actual, expected = run_fixture(data)
                self.assertEqual(actual, expected)

    def test_invalid_fixtures_are_rejected(self) -> None:
        paths = list_invalid_paths()
        self.assertEqual(len(paths), 3)
        for path in paths:
            with self.subTest(invalid=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                with self.assertRaises(ReplayError):
                    parse_fixture_data(data, path=str(path))


if __name__ == "__main__":
    unittest.main()
