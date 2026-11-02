#!/usr/bin/env python3
"""Run acceptance tests with an explicit expected-failure list for CI."""
from __future__ import annotations

import sys
import unittest

# Pre-existing CalDAV failures on main (tz_unsupported / agents-calendar).
EXPECTED_FAILURE_IDS = (
    "tests.acceptance.test_poc.TestA2EditOneLawfulPath.test_A2_caldav_move_propagates",
    "tests.acceptance.test_poc.TestA5IndependentWitness.test_A5_agents_calendar_list_update_delete",
    "tests.acceptance.test_mediation.TestMediation.test_jsoncal_items_in_caldav_and_back",
)
EXPECTED_FAILURE_METHODS = frozenset(t.rsplit(".", 1)[-1] for t in EXPECTED_FAILURE_IDS)


def _filter_suite(suite: unittest.TestSuite, exclude_methods: frozenset[str]) -> unittest.TestSuite:
    out = unittest.TestSuite()
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            sub = _filter_suite(test, exclude_methods)
            if sub.countTestCases():
                out.addTest(sub)
        elif test.id().rsplit(".", 1)[-1] not in exclude_methods:
            out.addTest(test)
    return out


def main() -> int:
    loader = unittest.TestLoader()
    suite = loader.discover("tests/acceptance", pattern="test_*.py", top_level_dir=".")
    suite = _filter_suite(suite, EXPECTED_FAILURE_METHODS)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        return 1

    for test_id in EXPECTED_FAILURE_IDS:
        case = loader.loadTestsFromName(test_id)
        sub = runner.run(case)
        if sub.failures or sub.errors:
            continue
        if sub.skipped:
            continue
        if sub.testsRun and sub.wasSuccessful():
            print(
                f"::warning title=expected acceptance failure now passes::{test_id} passed; "
                "remove from EXPECTED_FAILURE_IDS in scripts/run_acceptance_ci.py",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
