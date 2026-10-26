# agents-store — architecture

One identity, many lawful projections. This file is the module map; the plan
is `docs/MEGAPLAN.md`; the work breakdown is `docs/tasks/`.

## Layers (dependency flows downward only)

```
adapters/   I/O shells: folders, servers, files. The only place open()/listen() happens.
wrappers/   Pure lenses: EntityView <-> representation text. No I/O, no clock, no RNG.
core        Store, datoms, lineage, kinds, grants, registry, mediator, pane.
more/       MORe v4 companion (event log, checks, JWF); T17 bridges admitted events
            into the entity store (see docs/more/README.md). Tests in tests/more/.
schema.sql  Contract DDL. Changes here are contract changes (docs/tasks/README.md).
```

A **Wrapper** (`contracts.Wrapper`) is a pure lens over text: `get(e, view) -> str`,
`put(rep, e, view) -> PutResult{changes, refusals}`. Put never writes; it
*proposes* `Change`s. The store decides whether each proposed attr is writable
(rule: a `grant_` row backed by a passing `certificate`), and logs every
rejected proposal in `refusal`. Adapters (folder watcher, Radicale plugin) do
the I/O and call wrapper + store — protocol code never lives in wrappers.

A **Capability** is one interpretation step `in_kind -> out_kind`
(e.g. `markdown -> html`), flagged `render` or `lens`. A **pane** is a path
search over the capability graph for a given entity + target. Composition of
wrappers/capabilities through declared `correspondence` edges produces a
**mediator** row, stamped `exact` or `contained` (declared loss).

## Tables → vocabulary map

| table | role | literature |
|---|---|---|
| entity, datom, tx, v_current | minted ID + append-only fact log + current view | Datomic; event sourcing |
| attr | nominal attribute vocab (namespace prefix = owning wrapper) | koru proto |
| kind | structural membership: required/optional/derivations | prototype theory |
| lineage | split/merge/correct/evolve edges | W3C PROV |
| wrapper, grant_, certificate | who maps what; who may write which attr, backed by evidence | mediators; default-deny |
| correspondence | typed alignment edges: equal / refines / derivable | model management `Match` |
| capability | registered interpretation steps | mediators; plugin codecs |
| mediator | composed glue path + exactness + cert | query rewriting using views |
| provenance | which sources/maps produced a derived value | provenance semirings; PROV |
| refusal | every denied write, with reason | — |

## Identity

- Entity IDs are minted (`ids.mint()`), never reused, never derived from
  content/path/order. `md:path` is a *projection* datum: renaming a file
  changes an attr value, not an identity.
- **Prior art for hash-identity at hard boundaries:** PlayStation NID linkage —
  binaries resolve imports by truncated-SHA1 name hashes, never pointers; a
  compat layer (PS5-Anywhere, Wine) is literally a `correspondence` table
  hash→impl, and unresolved NIDs refuse loudly at bind time. Pointer = memoized
  resolution of a name, per-process, invalidatable. Same shape as our
  projection vs. identity split.

## Kinds are multiplicative and graded

An entity is in *every* kind whose `required` attrs it has (note + `status`
→ also task; + `when` → also event). `derivations` fill gaps for display only
(e.g. event with no `end` shows as +1h) and are marked derived — never written
back. Graded fit ("like the kind") is for ranking/suggestion; writes need the
attrs present or a declared derivation allowed to supply them.

## Write path (default-deny)

```
adapter receives bytes
 → wrapper.put() proposes Changes  (pure; no store access)
 → store.transact(changes, wrapper_id)
     for each change: grant_ exists for (wrapper, attr) with passing cert?
       yes → datom row (+ cardinality check for 'one')
       no  → refusal row, change dropped, caller told
```

Split/merge/correct are `tx` ops (`lineage` rows mint children, sever links).
History queries walk `datom` by entity/tx; `v_current` is always derivable.

## Extension points

1. `Registry` (`registry.py`): in-process registration, or entry-point groups
   `agents_store.wrappers` / `agents_store.capabilities` in an external package.
2. New attrs: wrapper seeds its `ns:*` attrs in `attrs()`; core vocabulary in
   `seed.sql` only (contract change).
3. New kind: `kind` row (JSON required/optional/derivations).
4. GPL boundary: Radicale plugin lives in `plugins/radicale_agents_store/`,
   licensed GPLv3, depends on this MIT core — never the reverse.

## What this is NOT (POC scope)

- No new storage substrate, no custom DB engine, no GPU. Python 3.11 stdlib +
  sqlite3 only, until A1–A11 pass.
- No silent cross-format sync engine; all cross-view movement is mediator rows
  backed by certificates.
- No identity from path/order/content anywhere in core.
