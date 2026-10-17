---
id: 0013
task: T14+T15
tree: <commit sha — this file>
date: 2026-10-17
---

# T14+T15 evidence — Match + generated mediator (read direction)

## What landed

`match.py`: `propose` generates `correspondence` rows structurally —
local-name equality + same spec → `equal`; prefix relation → `refines`;
the declared `ALIAS` table carries cross-vocabulary claims
(`jcal:dtstart`↔`when` etc). Confirmation = the selection passed to
`witness()`; a pass cert raises `proposed → witnessed`.

`derive.py`: `generate` writes the `mediator` row (`exact` iff all edges
equal+witnessed, else `contained`); `run` materializes derived datoms on
every entity carrying a source attr, `provenance` rows naming
inputs + deriving tx. `transact` hook (`store.py`) auto re-derives on
any tx touching a source attr — a jcal adapter write is a normal tx.

Laws enforced: derived values never clobber non-derived current values —
`mediator-conflict` refusal rows; derivation runs under internal
authority `wrapper='store'`; `is_derived` = live provenance check
(asserted datom still in `v_current`).

Caught by tests: conflict check initially allowed native-value clobbering
(`None not in (None, m.id)` polarity bug).

## Evidence

```
.venv\Scripts\python -m unittest discover -s tests
Ran 187 tests — OK
```
