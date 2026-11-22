---
task: T18
status: claimed
agent: devin-w2
date: 2026-11-22
depends: [T17]
owns:
  - src/agents_store/hlc.py
  - src/agents_store/ingest.py
  - src/agents_store/scrub.py
  - src/agents_store/db.py
  - src/agents_store/store.py
  - tests/unit/test_distributed.py
accepts: []
---

# T18 — distributed ordering (ord) + op ingest + scrub

Board: agents-store#2, agents-sync#10, agents-relay#40 (W2 wave of
klanker#140). `store.db` is the universal per-workspace op log; the sync
distributor transports datoms verbatim and every node converges without
ingest-time resolution.

## Problem this solves

`v_current` orders by local `tx` — arrival order. Two distributed hazards:

1. **cardinality-one lost update**: a remote assert carries no retractions
   for values its writer never saw, so two values stay visible forever.
2. **out-of-order delivery**: a transported retraction arriving before the
   assert it retracts would lose to the later-arriving assert under
   tx-ordering.

Fix: every datom carries `ord` — a globally comparable hybrid-logical-clock
key — and `v_current` picks argmax-per-(e,a[,v]) by `ord`, not arrival.

## Contract changes proposed (orchestrator applies)

`schema.sql` + `_migrate_v6`:

- `datom.ord TEXT NOT NULL DEFAULT ''`; backfill `ord = printf('%012d', tx)`.
- `UNIQUE INDEX ux_datom_eav_ord ON datom(e, a, v, ord)` — redelivery of
  the same datom is a no-op, dedupe at the fact level.
- `tx.origin_actor TEXT`, `tx.origin_seq INTEGER`, `tx.origin_hlc TEXT`;
  partial `UNIQUE INDEX ux_tx_origin ON tx(origin_actor, origin_seq)
  WHERE origin_actor IS NOT NULL` — op-level ingest idempotency.
- `v_current` rewritten:
  - cardinality `many`: per-(e,a,v) argmax-ord row visible iff added=1.
  - cardinality `one`: per-(e,a) argmax-ord row visible iff added=1.
  - Columns stay `(e, a, v, tx)`: tx = the winning datom's local tx.
- `PRAGMA user_version = 6`.

## Deliverables

- `hlc.py`: per-node hybrid clock. `ord = f"{ms:013d}.{counter:05d}.{node}"`
  — sorts after every 12-digit legacy backfill key and totally orders.
- `store.transact`: mints hlc per tx (`Store(conn, node_id)`); every
  datom written gets `ord` = the tx hlc.
- `ingest.ingest(conn, actor, seq, hlc, datoms, op='assert', note=None)`:
  idempotent by `(origin_actor, origin_seq)`; creates unseen entities;
  `INSERT OR IGNORE` per datom (ord dedupe). Returns tx + counts.
- `ingest.ops_since(conn, tx_id)`: local log tail for the distributor.
- `scrub.scrub_entity(conn, e)`: privileged hard delete (drop datom
  triggers → delete datoms+entity+lineage → recreate triggers), refusal
  audit row `reason='scrub'` recorded first.
- Tests: 2-node convergence under drop/dup/reorder, card-one cross-node
  conflict, out-of-order retract/assert, redelivery dedupe, scrub,
  migration on a v5 database.

## Out of scope

Wire format + peer cursors live in agents-sync (distributor). Grant
re-checking at ingest: bypassed by design (origin checked grants; fleet
nodes share trust). Documented in ingest docstring.
