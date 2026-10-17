---
id: T15
status: open
depends: [T14]
owns: [src/agents_store/derive.py, src/agents_store/store.py, tests/unit/test_derive.py]
accepts: []
---

# T15 — generated mediator: materialize derived attrs

## Goal

Given `witnessed` correspondences, generate a `mediator` row and
*materialize* derived datoms: an entity carrying `jcal:dtstart` gains a
real `when` datom. Every existing projection (calendar membership =
`when` present, kinds, pane, folder export) picks it up with zero
adapter changes — that is the thesis. (MEGAPLAN §6.1)

Naming: this is attribute-level mediation; `mediator.py` composes
capabilities for render paths — same `mediator`/`provenance` tables,
different granularity. Do not merge the modules.

## API (`src/agents_store/derive.py`)

- `generate(conn, source_ns: str, corr_ids: list[int]) -> int` —
  inserts `mediator(source=source_ns, target='core',
  path=json(corr_ids), exactness)`; `exact` iff every corr is
  `kind='equal'` AND `status='witnessed'`; any `refines`/`derivable` or
  non-witnessed edge → `contained`. Refuses (ValueError) on empty path.
- `run(store, mediator_id) -> report` — for every entity carrying any
  `a_from` of the path: compute derived `(a_to, value)` per edge and
  assert via `store.transact(changes, wrapper='store',
  note=f'mediator:{id} derive')` — internal authority, plus one
  `provenance` row per derived datom:
  `out_ref=json({"e":e,"a":a_to})`, `in_refs=json([{"e":e,"a":a_from}])`,
  `mediator_id`, `tx` = the deriving tx.
  - Conflict: `a_to` has a current value NOT derived from this mediator
    → skip that attr, record `refusal` row `mediator-conflict`
    (visible anomaly, not silent clobber). A current value derived by
    this mediator → normal revision.
- `rederive(store, entities: set[str])` — after any tx that touched a
  mediated source attr: retract derived datoms whose inputs changed
  (retract old `when`, assert new) in one follow-up tx; also retract
  derived datoms whose source attr was retracted.
- `is_derived(conn, e, a) -> bool` — live provenance: an `out_ref`
  matches AND its asserted datom is still current.

## Store hook (`store.py`, owns-listed)

End of `transact` (after apply, before return): collect changed
`(e, a)`; if any `a` is a source attr of a registered mediator on those
entities → call `derive.rederive` (guard flag `_deriving` to prevent
recursion; internal-authority txs also trigger — a jcal adapter write is
a normal tx and must re-derive). The derived tx is a separate tx id
(append-only: no tx nesting).

Derived-attr write law (rule 5, "derived values are never written back"):
assertions by the mediator itself run under `wrapper='store'`; external
writes to a derived attr are T16 (here, they still apply — T16 adds the
inversion/refusal).

## Tests

- generate on 2 witnessed equal edges → mediator row `exact`;
  one `proposed` edge → `contained`.
- entity with `jcal:dtstart` → after `run`, `view` has `when`; kind
  `event` gained; `provenance` row names the input datom + tx.
- edit `jcal:dtstart` (new tx) → derived `when` auto-updates; old value
  retracted in the follow-up tx; history shows both txs.
- retract `jcal:dtstart` → derived `when` retracted.
- entity with native `when` + `jcal:dtstart` → `mediator-conflict`
  refusal row, native value untouched.
- `is_derived` true for mediated attr, false for native attr.

## Contract changes proposed

(none — `mediator`/`provenance`/`refusal` tables already exist)
