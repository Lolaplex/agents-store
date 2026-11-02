"""Unit tests for scripts/run_acceptance_ci classification."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = ROOT / "scripts" / "run_acceptance_ci.py"
_spec = importlib.util.spec_from_file_location("run_acceptance_ci", _SCRIPT)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
classify = _mod.classify_expected_failure_run


def _result(
    *,
    failures=None,
    errors=None,
    skipped=None,
    tests_run: int = 1,
    successful: bool = True,
) -> mock.Mock:
    r = mock.Mock(spec=unittest.TestResult)
    r.failures = failures or []
    r.errors = errors or []
    r.skipped = skipped or []
    r.testsRun = tests_run
    r.wasSuccessful = mock.Mock(return_value=successful)
    return r


class ClassifyExpectedFailureRun(unittest.TestCase):
    def test_failure_is_expected(self) -> None:
        self.assertEqual(
            classify(_result(failures=[("t", "traceback")])),
            "expected_failure",
        )

    def test_error_fails_ci_not_expected(self) -> None:
        self.assertEqual(
            classify(_result(errors=[("t", "ImportError")])),
            "error",
        )

    def test_error_beats_failure(self) -> None:
        self.assertEqual(
            classify(
                _result(
                    failures=[("t", "f")],
                    errors=[("t", "e")],
                )
            ),
            "error",
        )

    def test_skip_warns(self) -> None:
        self.assertEqual(
            classify(_result(skipped=[("t", "reason")], successful=True)),
            "skip",
        )

    def test_unexpected_pass(self) -> None:
        self.assertEqual(classify(_result()), "unexpected_pass")

    def test_nothing_ran(self) -> None:
        self.assertEqual(
            classify(_result(tests_run=0, successful=True)),
            "nothing_ran",
        )


if __name__ == "__main__":
    unittest.main()
