# 0004 certify (T04)

- commit: <this commit>
- task: T04
- claim: check_lens runs GetPut/PutGet over caller corpus; certify registers
  wrapper+attrs and writes certificate rows; grant_roundtrip grants declared
  attrs on pass; uncertified writes hit no-grant.
- evidence: `.venv\Scripts\python -m unittest discover -s tests` → 63 tests OK.
  Covers: lossless pass, named GetPut/PutGet violations (spurious change,
  dropped attr), cert rows pass/fail, certified write lands, uncertified refuses.
- limits: per-attr granularity is "all-or-nothing" at grant time (grants every
  declared attr once laws pass); corpus is caller-supplied, no generator yet.
