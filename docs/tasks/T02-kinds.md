---
id: T02
status: open
depends: [T01]
owns: [src/agents_store/kinds.py, tests/unit/test_kinds.py]
accepts: [A9]
---

# T02 — Kind membership (multiplicative, graded)

## Goal

`kinds.of(conn, e) -> set[str]`: every kind whose `required` attrs the entity
has. `kinds.gaps(conn, e, kind) -> GapsReport`: missing required attrs, which
declared `derivations` could fill them, and which optional attrs exist.
Derivations are display-only — the report marks values as `derived=True`;
nothing writes them.

## Semantics

- Membership is structural over attr names, never on type identity.
- A kind is just a `kind` table row (JSON `required`/`optional`/`derivations`).
- Graded fit = report of "how much is there"; it must expose the full
  required/missing/derivable breakdown, not a bare bool.

## Tests

- entity with `body` → `{note}`; add `status` (granted) → `{note, task}`,
  same id (half of A9).
- entity with `when` only → `event`; `gaps` reports `end` derivable via
  `plus_1h`, marked derived.
- empty entity → no kinds.

## Contract changes proposed

(none)
