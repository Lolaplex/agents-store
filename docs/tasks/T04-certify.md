---
id: T04
status: open
depends: [T01]
owns: [src/agents_store/certify.py, tests/unit/test_certify.py]
accepts: [A10]
---

# T04 — certify: lens-law runner → certificates → grants

## Goal

Turn a registered wrapper into a *writable* one by evidence. `certify.py`:

- `check_lens(w, corpus) -> report` — for each seeded entity view in `corpus`:
  - **GetPut:** `put(get(v), e, v)` yields no changes.
  - **PutGet:** take a representation `r`, `put` it, apply the changes to the
    view, `get` again → `r` over the attrs `w` may write (i.e. attrs in
    `w.attrs()` that are declared round-trippable by the wrapper).
- `certify(conn, w, corpus, *, tier='witness') -> Certificate` — on all-pass,
  insert a `certificate` row (`subject='wrapper:<id>'`, `corpus='seed=…,n=…'`)
  and return it. Any failure → `result='fail'` row, no grants.
- `grant_roundtrip(conn, cert)` — insert `grant_` rows for the attrs the
  wrapper proved round-trippable.

Corpus: `corpus` is a caller-supplied deterministic generator
(`seed`, `n`). certify never invents views itself.

## Tests

- toy lossless wrapper → cert pass, grants created, later writes allowed.
- lossy wrapper (drops an attr on put) → cert fail, refusal on write path.
- GetPut violation (put always rewrites) → cert fail with named law.
- grant_ requires cert id (FK enforced).

## Contract changes proposed

`PutGet` needs a small `apply(view, changes)` helper — implement in
`certify.py` for now; flag if it should promote to contracts.
