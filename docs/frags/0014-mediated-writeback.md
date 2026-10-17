---
id: 0014
task: T16
tree: <commit sha — this file>
date: 2026-10-17
---

# T16 evidence — mediated write-back, §6.1 closed end to end

## What landed

`store.transact` pre-pass: a Change on a *derived* attr
(`derive.derived_edge` finds the live mediator via provenance) is
rewritten to `(e, a_from, v)` under internal authority when the edge is
`equal`+`witnessed`; the follow-up tx is noted
`mediated-write via mediator N` and re-derivation refreshes the derived
value. Any weaker edge (`refines`, unwitnessed, `contained` mediator)
refuses `derived-attr`; rest of batch still applies.

`adapters/jsonfile.py` last-render tracking (`jcal:rev`): ingest skips
items identical to the last exported render — fixes silent reversion
of store-side edits by a stale file. `folder.py` shares the pre-fix
semantics (file always wins); flagged in BACKLOG, not patched here.

## The demo the megaplan asked for

`tests/acceptance/test_mediation.py`:

1. `export.json` (2 items, `jcal:*` terms only) → `jsonfile.sync`.
2. `match.propose` → confirm exactly `jcal:dtstart→when`,
   `jcal:status→status` → `match.witness` → `derive.generate` (`exact`)
   + `run`.
3. **Zero plugin/adapter edits:** the same entities now GET as VEVENT
   in `/test/calendar/` and VTODO in `/test/tasks/` — membership views
   picked up the derived attrs structurally.
4. agents-calendar subprocess `list` finds the event (real HTTP,
   independent witness).
5. agents-calendar `update --etag` moves DTSTART → store inverts the
   `when` write to `jcal:dtstart`, `when` re-derives; `jsonfile.sync`
   re-export carries the new value into `export.json`.
6. A `refines`/`contained` mediator's derived `title` refuses a write
   with `derived-attr` (recorded refusal row), value untouched.

## Bugs the harness caught

- `is_derived` used `json_extract(p.out_ref, ...)` unguarded —
  T09 capability mediators write `out_ref` as a *string*, so the first
  capability mediation broke every subsequent `transact`
  (`malformed JSON`). Fixed with a `CASE WHEN json_valid` guard.
- agents-calendar `update` requires DTEND (`emit_vevent` always emits
  one); test event carries `end` via a native attr write.

## Evidence

```
.venv\Scripts\python -m unittest discover -s tests
Ran 189 tests — OK
```
