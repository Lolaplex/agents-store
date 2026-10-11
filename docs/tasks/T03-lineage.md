---
id: T03
status: done
agent: devin-local
claimed: 2026-10-11
done: 2026-10-11
depends: [T01]
owns: [src/agents_store/lineage.py, tests/unit/test_lineage.py]
accepts: [A9]
---

# T03 — Lineage ops: evolve, split, merge, correct

## Goal

Explicit identity-change operations writing `lineage` + `tx` rows
(PROV vocabulary). In-place edit is a revision (T01 covers it); this card is
for true identity events.

## API (`lineage.py`)

- `split(store, e, into, *, reason) -> list[str]` — mint `into` child ids;
  copy or reference attrs per `into` spec (each entry: attr list to carry);
  `lineage` rows `wasDerivedFrom` child→e.
- `merge(store, es, *, reason) -> str` — mint survivor; attrs = union
  (conflicting cardinality-one values → all retained as `many`-style history
  unless caller picks one via `choose`); `wasDerivedFrom` survivor→each source.
- `correct(store, e, supersedes, *, reason)` — `wasRevisionOf` edge; the
  superseded entity is not deleted, `view` gains a `superseded_by` note via
  queries (document how callers detect it).
- `evolve(store, e, changes, *, reason)` — revision tx with `op='evolve'` and
  optional `wasRevisionOf` self-edge for provenance.

All ops are single `transact` calls (atomic), op tagged on tx row.

## Tests

- A9 split: note → split → new id exists, lineage edge present, parent intact.
- merge: two entities → survivor has lineage to both; sources unchanged.
- correct: edge recorded; superseded entity still readable.
- history: lineage rows appear under the op tx.

## Contract changes proposed

(none)
