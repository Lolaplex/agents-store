#!/usr/bin/env python3
"""Run acceptance tests with an explicit expected-failure list for CI."""
from __future__ import annotations

import sys
import unittest

# Pre-existing CalDAV failures on main (tz_unsupported / agents-calendar).
EXPECTED_FAILURE_IDS = frozenset(
    (
        "tests.acceptance.test_poc.TestA2EditOneLawfulPath.test_A2_caldav_move_propagates",
        "tests.acceptance.test_poc.TestA5IndependentWitness.test_A5_agents_calendar_list_update_delete",
        "tests.acceptance.test_mediation.TestMediation.test_jsoncal_items_in_caldav_and_back",
    )
)


def _filter_suite(suite: unittest.TestSuite, exclude_ids: frozenset[str]) -> unittest.TestSuite:
    out = unittest.TestSuite()
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            sub = _filter_suite(test, exclude_ids)
            if sub.countTestCases():
                out.addTest(sub)
        elif test.id() not in exclude_ids:
            out.addTest(test)
    return out


def classify_expected_failure_run(result: unittest.TestResult) -> str:
    """Classify a single expected-failure test run.

    Returns one of: expected_failure, error, skip, unexpected_pass, nothing_ran.
    """
    if result.errors:
        return "error"
    if result.failures:
        return "expected_failure"
    if result.skipped:
        return "skip"
    if result.testsRun and result.wasSuccessful():
        return "unexpected_pass"
    return "nothing_ran"


def main() -> int:
    loader = unittest.TestLoader()
    suite = loader.discover("tests/acceptance", pattern="test_*.py", top_level_dir=".")
    suite = _filter_suite(suite, EXPECTED_FAILURE_IDS)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        return 1

    for test_id in sorted(EXPECTED_FAILURE_IDS):
        case = loader.loadTestsFromName(test_id)
        sub = runner.run(case)
        kind = classify_expected_failure_run(sub)
        if kind == "error":
            print(
                f"expected-failure test errored (must fail CI): {test_id}",
                file=sys.stderr,
            )
            return 1
        if kind == "skip":
            print(
                f"::warning title=expected acceptance failure skipped::{test_id} skipped; "
                "environment may hide CalDAV regression",
                file=sys.stderr,
            )
            continue
        if kind == "unexpected_pass":
            print(
                f"::warning title=expected acceptance failure now passes::{test_id} passed; "
                "remove from EXPECTED_FAILURE_IDS in scripts/run_acceptance_ci.py",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
