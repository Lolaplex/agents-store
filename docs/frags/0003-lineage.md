# 0003 lineage ops (T03)

- commit: 4068e0ca2aa75a3039c6ef3d05ff18f64a07ca2b (audit: `severs` for correct; v0 ledger)
- task: T03
- claim: split/merge/correct/evolve as single atomic txs under 'store' authority,
  PROV lineage edges; superseded entities stay readable; merge conflicts on
  cardinality-one stay visibly unresolved (all values current) unless `choose`.
- evidence: `.venv\Scripts\python -m unittest discover -s tests` → 54 tests OK.
  Covers: A9 split (new id + wasDerivedFrom, parent intact); merge union + edges,
  sources unchanged; correct → wasRevisionOf + superseded_by; evolve same-id tx.
- limits: merge's multiple-current-values anomaly is visible but no conflicts()
  query yet; ops use package-internal store._datom/_spec by design.
