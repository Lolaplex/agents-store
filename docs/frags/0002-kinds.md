# 0002 kinds (T02)

- commit: <this commit>
- task: T02
- claim: structural multiplicative kind membership; graded gaps report with
  declared derivations (derivable gaps don't block membership, marked derived).
- evidence: `.venv\Scripts\python -m unittest discover -s tests` → 54 tests OK.
  Covers: note+status → {note,task} same id (A9 half); when-only → event with
  `end` derivable via plus_1h; empty entity → no kinds; unknown kind raises.
- limits: derivation rules are named strings, not evaluated (no value synthesis
  yet); fit is boolean per kind, no partial-score ranking.
