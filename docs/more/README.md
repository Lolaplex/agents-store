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

**Board kinds (partial re-vendor).** `projections.lolaplex-board.board_only_config`
`kind_map`, `kind_map_hierarchy`, `relation_map` and `relation_map_sources`
match `Cypoe/more-framework@c56f457` (merge of PR #7, head `db55d43`): the hierarchy
kinds `domain`, `use_case`, `business_process`, `conceptual_model`, `ui_spec`,
`api_spec`, `acceptance_criterion` and the `implements` relation (BEL §7.2,
ELSTER §6). The author calculus (`registerNode`) and the board projection
(`More/BoardProjection.lean`) are not vendored here; the board ports them.
Store entity kinds in `seed.sql` are unrelated and unchanged.

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

## Event SAIDs (schema v4)

**Name vs. content.** The event's *name* (event id = entity id, a minted
ULID) stays the reference target for lineage edges, `more:pin` (`eid@tx`),
supersession and overrule. The *SAID* is a separate content digest, written
as `more:said` (text, cardinality one) in the event's own tx. That datom is
the name → SAID binding. A correction or supersession is a new event with a
new name and a new SAID; nothing is rewritten.

**Scheme** (`agents_store.more.said`, KERI/CESR as in keripy `Saider`):

- digest: BLAKE3-256 (the `blake3` package is a runtime dependency; no SHA2
  fallback);
- encoding: CESR qb64, code `E` (`Blake3_256`). That is base64url of one zero
  lead byte followed by the 32 raw bytes, with the first char replaced by `E`,
  44 chars in total (`E[A-P][A-Za-z0-9_-]{42}`);
- digesting: the `d` field holds the KERI placeholder `'#' * 44`, and the
  result replaces it;
- hashed body (the SAD): `d`, `i` (= the event name), then the envelope fields
  in `events._ENVELOPE` order (`type`, `actor`, `at`, `pinned_against`,
  `subjects`, `reason`, `supersedes`, `signals`, `provenance`, `body`).
  Because `i` is hashed, the same content under another name has another
  SAID, so a SAID cannot be rebound to a different name. The log's
  `seq`/`prev`/`digest` are not hashed; the sha256 chain column stays as it
  is.

**Canonical serialization: KERI fixed field order, not JCS.** The SAD is
serialized the way keripy does it: compact JSON
(`json.dumps(sad, separators=(",", ":"), ensure_ascii=False)`, UTF-8) in the
SAD's own field order, and the top-level order above is fixed. Nested objects
(`body`, …) have no schema-fixed order, so their keys are sorted (code-point
order, as with `sort_keys=True`). The reasons: keripy's
`Saider.saidify`/`verify` reproduce our SAIDs unchanged, which JCS's
lexicographic top-level order and ES6 number formatting would not. It also
matches KERI/ACDC practice, where the field order is part of the schema.
`allow_nan=False` is set in `said.dumps` and in `Event.canonical`, so NaN and
±Infinity never reach a digest.

**Numbers: integers with a declared scale (C4, ruled 2026-10-27).** A number
in an event is a JSON integer with |n| ≤ 2^53 − 1 (the I-JSON safe range,
RFC 7493 §2.2). A non-integer quantity is an object `{"value": <int>,
"scale": <int>}` that means value × 10^−scale. For example, 0.80 is
`{"value": 80, "scale": 2}` and 0.8 is `{"value": 8, "scale": 1}`, so the
declared scale is kept. `numbers.scaled("0.80")` builds it from the decimal
text and `numbers.unscaled` reads it back. Binary floats are not allowed, and
neither are decimal strings or floats under JCS (both were rejected). The
reason is that Python writes a float as its shortest repr (`1e-07`,
`0.30000000000000004`, `-0.0`) and NaN as the non-JSON token `NaN`, and other
implementations write the same value differently, so the SAID would differ.

- **Append guard.** Before anything is hashed or written, `EventLog.append`
  calls `store_bridge.assert_canonical_numbers`. It raises `StoreWriteRefused`
  with one `Refusal` per bad number. `reason` is one of `number_float`,
  `number_nonfinite` and `number_out_of_range`, `a` is the envelope field and
  `payload` is the JSON path (e.g. `$.body.amount`). The refusal is also
  recorded in `more_refusal`. `bool` is a JSON literal and passes.
- **Events stored before the guard** are never rewritten (the log is
  append-only). `migrate.number_report(conn)` lists them. `migrate_said(conn,
  report=[])` skips them, so they get no new `more:said`, leaves an existing
  SAID as it is, and adds them to `report`. The fix is a new event that
  supersedes the old one and carries the number as `{value, scale}`.
  `EventLog.verify` re-reads such envelopes with `allow_nan=True`, so they do
  not show as `event_mutated`. A read of a stored NaN event gives `said=None`.

Tests: `tests/more/test_numbers.py`.

**Test vectors** (`tests/more/test_said.py`, unchanged by the number guard):

- BLAKE3 reference digests for `""` and `"abc"`;
- keripy `test_diger`: `Diger(ser=b"abc…789")` gives
  `ELC5L3iBVD77d_MYbYGGCUQgqQBju1o4x1Ud-z2sL-ux`;
- keripy `test_saider`: the JSON-Schema SAD with label `$id` gives
  `EMRvS7lGxc1eDleXBkvSHkFs8vUrslRcla6UXOJdcczw`. Both vectors are from
  WebOfTrust/keripy `tests/core/test_coring.py` at `a6866a3`;
- one event SAD, with its exact serialized bytes and SAID, cross-checked with
  keripy 1.3.6 (`Saider.saidify` gives the same qb64 and `Saider.verify` holds).

**Pins and pointers.** `more:pin` stays `eid@tx`. `pinned_against` values and
pointer targets may also be `X@<SAID>`. They are stored verbatim and found by
`events_pinned_against` / `events_pinned_to`. `more.query.resolve(store, ref)`
classifies a ref as `said`, `pin`, `floating` or `external` and verifies an
`X@<SAID>` against X's `more:said` (`ok` is True/False, or None when X is
not a store entity). `events_by_said(store, said)` returns the event name
bound to a SAID.

**Migration.** `_migrate_v4` (`PRAGMA user_version` 3 → 4) adds `more:said`
and lists it as optional on the `more-event` and `decision` kinds. It then
asserts the SAID, recomputed from each stored envelope and event name, on
every event entity that has none, in one internal `evolve` tx with the note
`more:migrate said (v4)`. A re-run writes nothing. A stored `more:said` that
differs from the recomputed one is not overwritten: `migrate_said` raises
`SaidMismatch` and rolls back.

**Identity layer.** This is not the PHI_IDENTITY identity layer (ROADMAP §5).
A MORe SAID identifies *content*, bound to a minted name. A KERI identifier
(AID) and its key event log identify a *controller*. Event SAIDs are not
signed and establish no key state.

## Still owned by the board

- Board UI projection of JWF / work-item state from store-backed logs
- CLI/MCP surface for MORe append (T18)

## Domain violation ids (open registrar)

MORe kernel violation ids live in `kernel-proposal.json` and the companion
checks. Domain-specific ids (for example a template engine's
`prose_string_missing`) are **not** added to more-framework. They register in
the store's open registrar: entry-point group `agents_store.violation_ids`,
type `DomainViolationId` (`contracts.py`), collision rules in `registry.py`.
A domain id that matches a kernel id is refused. The owning domain registers
its ids; this package does not ship first-party domain ids in that group.
