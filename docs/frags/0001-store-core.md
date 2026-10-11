# 0001 store-core (T01)

- commit: c819d08
- task: T01
- claim: minted IDs (ULID, monotonic same-ms), transact with grant enforcement,
  append-only datoms, cardinality-one auto-retract, as-of views, refusals recorded.
- evidence: `.venv\Scripts\python -m unittest discover -s tests -v` → 36 tests, OK.
  Covers: 10k unique sortable ids; one-entity-one-tx create; no-grant/unknown-attr/
  unknown-entity refusals (row + returned); internal 'store' authority bypass;
  retraction; view-as-of-tx; many-cardinality.
- limits: no lineage ops (T03), no kind membership (T02), no wrapper certs (T04).
  TxResult is store.py-local, not promoted to contracts.py.
