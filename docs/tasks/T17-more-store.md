---
id: T17
status: done
depends: []
owns:
  - src/agents_store/more/log.py
  - src/agents_store/more/store_bridge.py
  - src/agents_store/more/schema.sql
  - src/agents_store/db.py
  - tests/more/test_store_integration.py
  - tests/more/test_decisions_store.py
  - src/agents_store/more/decisions.py
  - docs/more/README.md
  - docs/frags/0015-more-store.md
accepts: []
agent: cloud-agent/more-store-integration
date: 2026-10-19
---

# T17 — MORe event log in the entity store

## Goal

Persist the MORe append-only event log in the same SQLite file as the
agents-store entity store. Every admitted event is also an entity with the
same ULID; refused events land only in `more_refusal`. One `BEGIN IMMEDIATE`
transaction covers event row, entity row, datoms, and supersession lineage.

## Design

- MORe tables live in `src/agents_store/more/schema.sql`, applied by
  `db.connect()` and standalone `EventLog(:memory:)` alike.
- Store `refusal` and MORe `more_refusal` are separate tables (no
  `CREATE TABLE IF NOT EXISTS` clash).
- Version pin on each admitted event entity: `more:pin` = `{entity_id}@{tx}`.
- Supersession / overrule events add `wasRevisionOf` lineage from the new
  event entity to each id in `supersedes`.
- Materialization uses internal `store` wrapper authority (same as lineage ops);
  `tx.op` stays `assert` — no new MORe-specific ops.

## Acceptance

- [x] Admitted event → event row + entity, same id
- [x] Refused → exactly one `more_refusal`, no event/entity/datom
- [x] Forced mid-write failure rolls back both sides
- [x] `verify()` clean; raw UPDATE blocked by trigger and caught by `verify()`
- [x] Superseded decision inactive in folds, readable via `store.history`
- [x] Store refusals and MORe refusals independent
- [x] `decision` kind (ADR): title, body, more:topic, more:pin; helper `latest_live_decision`
- [x] All MORe tests green (114 at land)
- [x] Evidence frag `docs/frags/0015-more-store.md`

## Contract changes proposed

Applied in this branch (orchestrator merge):

- **`seed.sql`**: attrs `more:type`, `more:actor`, `more:at`, `more:subject`,
  `more:pin`, `more:body`, `more:topic`; kinds `more-event` and `decision`
  (ADR: `title`, `body`, `more:topic`, `more:pin`).
- **`db.connect`**: executes MORe `schema.sql` after store bootstrap so new
  store files carry both schemas.
- **MORe `schema.sql`**: table `refusal` renamed to `more_refusal`.

## Evidence

See `docs/frags/0015-more-store.md`.

## commit

e9f4708 (T17 merge on `main`; inventory refresh in docs consistency pass)
