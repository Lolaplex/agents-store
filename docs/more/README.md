# MORe kernel in agents-store

The Python MORe v4 companion from [Cypoe/more-framework](https://github.com/Cypoe/more-framework) lives under `src/agents_store/more/`. Spec data is vendored as `kernel-proposal.json` beside the package; profile knobs are in `profiles/default.json`.

Porting contract and Lean reference: **`kernel/More/PORTING.md`** in more-framework (do not restate kernel semantics here).

## Loaded here

- Event log, checks, derived status, gates, JWF board state, relations, readiness, hierarchy lint, compliance projection, cut-over profile
- Companion unit tests in `tests/more/`

## Store integration (T17)

`db.connect()` applies both the entity-store schema and `more/schema.sql` in one
file. `EventLog(conn=store_conn)` detects the `entity` table and, on each
admitted append, mints one ULID used as both `event.id` and `entity.id`, writes
`more:*` datoms under an internal `assert` tx, and records `wasRevisionOf`
edges for supersession/overrule events. Refused envelopes go to `more_refusal`
only (store `refusal` is for wrapper grant denials).

**Decision artifacts (ADRs):** admitted `decision` events with `title`, `body`,
and `topic` in the envelope are projected onto the store `decision` kind
(`title`, `body`, `more:topic`, plus `more:pin` = `{entity_id}@{tx}`).
`latest_live_decision(log, store, subject_ref=…, topic=…, at_tx=…)` returns the
latest non-superseded decision using the same inactive-event fold as
`status.py`; superseded records stay readable via `store.history()`.

Standalone `EventLog(:memory:)` or a MORe-only sqlite file still works for the
companion tests — no entity materialization without the store schema.

## Still owned by the board

- Board UI projection of JWF / work-item state from store-backed logs
- CLI/MCP surface for MORe append (T18)
