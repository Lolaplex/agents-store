---
id: 0012
task: T13
tree: <commit sha — this file>
date: 2026-10-17
---

# T13 evidence — jsoncal wrapper + jsonfile adapter

## What landed

`wrappers/jsoncal.py` + `adapters/jsonfile.py`: a second calendar source
in **its own terms** (`jcal:*` namespace only — no core attrs; alignment
is T14/T15's job, that is the demo's point).

- `jcal:uid` (provenance), `jcal:summary`, `jcal:dtstart`, `jcal:dtend`,
  `jcal:status`, `jcal:extra` (lossless keys), `jcal:path` (`file#uid`).
- Refusals: `parse-fail` (bad JSON / non-object / non-array file),
  `tz-unsupported` (non-Z instants).
- Design fix found by the lens laws: `uid-mismatch` refusal removed —
  `jcal:uid` is a declared attr so PutGet requires it writable; a uid
  change is a revision. uid→entity alignment is the adapter's `_by_uid`
  resolution (jcal:uid datum, then `uid == entity id` for re-exports).
- Adapter: per-item failures are refusals, others land; item removed →
  `jcal:path` retracted, entity survives; file re-exported canonical
  (sorted keys, sorted by uid) → converges on second sync.

## Evidence

```
.venv\Scripts\python -m unittest tests.unit.test_jsoncal tests.unit.test_jsonfile
Ran 18 tests — OK
```
