"""T12: demo.py runs clean twice; second run reuses the entity."""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TestDemo(unittest.TestCase):
    def _run(self):
        p = subprocess.run(
            [sys.executable, "examples/demo.py"],
            cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def test_demo_runs_clean_and_idempotent(self):
        out1 = self._run()
        out2 = self._run()
        e1 = re.search(r"entity   : (\S+)", out1).group(1)
        e2 = re.search(r"entity   : (\S+)", out2).group(1)
        self.assertEqual(e1, e2)  # same identity across runs
        h1 = int(re.search(r"history  : (\d+) datoms", out1).group(1))
        h2 = int(re.search(r"history  : (\d+) datoms", out2).group(1))
        self.assertGreater(h2, h1)  # deltas append, nothing duplicated
        self.assertIn("STATUS:", out2)  # status flips back on second run


if __name__ == "__main__":
    unittest.main()
