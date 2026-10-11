---
id: T01
status: open
depends: []
owns: [src/agents_store/ids.py, src/agents_store/store.py, src/agents_store/grant.py, tests/unit/test_ids.py, tests/unit/test_store.py]
accepts: [A7]
---

# T01 — Store core: minted IDs, transact, read

## Goal

The canonical write/read path. Every other task depends on this API.

## Files

- `src/agents_store/ids.py` — `mint() -> str`. Time-sortable, collision-safe,
  stdlib only (e.g. ULID shape: 48-bit ms + 80-bit random, Crockford b32).
  Never derived from content.
- `src/agents_store/store.py` — `Store(conn)`:
  - `transact(changes, *, wrapper, agent=None, op='assert', note=None) -> TxResult`
    Enforce grants: for each `Change`, `(wrapper, a)` writable iff a `grant_`
    row exists whose certificate `result='pass'`. Writable → datom rows
    (+retract old value when attr cardinality is `one`, and the value differs).
    Not writable → `refusal` row, dropped, reported in `TxResult.refusals`.
    One `tx` row per call; `entity` rows auto-created for `e=None` changes
    (mint one id per put-batch, `created_tx` = this tx).
  - `view(e, *, tx=None) -> dict[str, value|tuple]` — current attrs from
    `v_current` (or as-of `tx`).
  - `history(e) -> list[Datom]` — all datoms for `e`, tx-ordered.
  - `refusals(e=None) -> list[Refusal]`.
- `src/agents_store/grant.py` — `grant(conn, wrapper_id, attr_name, cert_id)`,
  `is_writable(conn, wrapper_id, attr_name) -> bool`.

`TxResult` is a new contract type — add it via contract-change note OR define
it in `store.py` and document that it stays internal until promoted.

## Tests (tests/unit)

- mint: 10k ids unique, sortable by creation order.
- transact: assert title+body on e=None → new entity, one tx, view round-trips.
- cardinality: second `title` assert retracts the first (`v_current` has one row;
  `history` shows both datoms).
- default-deny: change on attr with no grant → refusal row + reported, datom
  unchanged. Refusal row has reason `no-grant`.
- grant: after `grant()` + passing cert, same write succeeds.
- append-only: A7 — direct UPDATE/DELETE on datom raises (already in
  test_db.py; keep, extend if the store offers no mutation path — assert that).

## Out of scope

Lineage ops (T03), kinds (T02), certify (T04). `status`/`evolve` semantics are
T03; T01 only records `op` on the tx row.

## Contract changes proposed

(none)
