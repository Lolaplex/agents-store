# MORe kernel in agents-store

The Python MORe v4 companion from [Cypoe/more-framework](https://github.com/Cypoe/more-framework) lives under `src/agents_store/more/`. Spec data is vendored as `kernel-proposal.json` beside the package; profile knobs are in `profiles/default.json`.

## Vendoring pin

Companion modules and `kernel-proposal.json` match
[Cypoe/more-framework](https://github.com/Cypoe/more-framework) at merge
**`3681d271`** on `master` (PR #5 *kernel-impl*; branch tip **`e32e5c3`**).
Upstream layout at that revision:

| agents-store | more-framework @ `e32e5c3` |
|---|---|
| `src/agents_store/more/*.py` | `companion/python/more_kernel/*.py` |
| `src/agents_store/more/kernel-proposal.json` | `lean-model/kernel-proposal.json` |
| `tests/more/` | `companion/python/tests/` (+ store integration tests) |

Porting contract and Lean reference:
`Cypoe/more-framework@e32e5c3:kernel/More/PORTING.md` (do not restate kernel
semantics here). Normative prose:
`Cypoe/more-framework@e32e5c3:lean-model/more-lean-model.md`.

JWF board **state spellings** in profile JSON and tests remain the German
labels from the neutralised workflow deck (e.g. `In Abnahme`, `Abgenommen`,
`Geschlossen`); English names appear in module docstrings and this README.

## Loaded here

- Event log, checks, derived status, gates, JWF board state, relations, readiness, hierarchy lint, compliance projection, cut-over profile
- Companion unit tests in `tests/more/` (**114** at `e9f470868be05a5031217382bd0aa48583d09737`)

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

## Queryable subjects and pins (schema v3)

The envelope stays the source of truth; these datoms are a queryable
projection of it, written in the same tx as the event entity.

| Envelope field | Datom | Type | Value |
| --- | --- | --- | --- |
| `subjects`, subject is a store entity | `more:subject` | ref, many | the entity id |
| `subjects`, any other subject | `more:subject_ptr` | text, many | the subject string, verbatim |
| `pinned_against` | `more:pinned_against` | text, many | each pin, verbatim |

**Subjects.** A subject resolves to a ref only when its string is an existing
store entity id (exact match, at append time). Every other subject (a board
artifact id such as `UC-1`, an external locator) is kept as a pointer target
id in `more:subject_ptr`. No stub entity is minted for it. PORTING.md types
`Event.subjects` as artifact ids, and the kernel model says that each artifact
exists once, at one leading place. An artifact held in another system is
pointed to, never copied in, and a pointer carries no content of its target.
A stub entity would be a second, content-free copy with its own store id, so
the pointer form is the faithful one.

**Pins.** `Event.pinnedAgainst` is `Pin.ref` (subject@version), `Pin.baseline`
or a commit. A ref cannot carry the version, so the pin stays text, in the
same `target@version` shape as `more:pin` (`entity@tx`).

**Queries.** `Store.find(a, v)` / `Store.find(a, prefix=…)` returns the entities
with a current value (via the `(a, v)` index), in creation order.
`agents_store.more.query` builds on it:

- `events_about(store, subject)`: ref or pointer subject;
- `events_pinned_against(store, "UC-1@3")`: exact pin (also a commit or baseline);
- `events_pinned_to(store, "UC-1")`: any version of `UC-1` (`UC-1@…`), not `UC-10`.

These return raw event ids; liveness (supersession, overrule) is still folded
by `status.py` / `decisions.py`.

**Migration.** `db.connect()` runs `_migrate_v3` once (`PRAGMA user_version`
2 → 3). It sets `more:subject` to `ref`, adds the two attrs, lists them as
optional on the `more-event` and `decision` kinds, and backfills every
materialized event from its envelope. A text `more:subject` that is not an
entity is retracted and re-asserted as `more:subject_ptr`, missing
`more:pinned_against` datoms are asserted, and all of this goes in one internal
`evolve` tx with the note `more:migrate queryable-refs (v3)`. Nothing is
deleted; the old datoms stay in `history()`. The backfill writes only the
difference, so a re-run is a no-op.
`more.migrate.migrate_queryable_refs(conn)` can be called again later: when
a pointer target has since become a store entity, it turns that pointer into
a ref.

**Later: SAIDs.** Not implemented. A self-addressing id would be one more
additive attr on the event entity (e.g. `more:said`, text, one), plus SAID
values accepted wherever a pin or pointer target is a string today. Refs hold
device-local entity ids, while envelopes keep the portable strings. Adding a
SAID does not change the shape of `more:subject`, `more:subject_ptr` or
`more:pinned_against`.

## Still owned by the board

- Board UI projection of JWF / work-item state from store-backed logs
- CLI/MCP surface for MORe append (T18)
