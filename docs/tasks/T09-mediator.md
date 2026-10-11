---
id: T09
status: done
agent: devin-local
claimed: 2026-10-11
done: 2026-10-11
depends: [T04]
owns: [src/agents_store/mediator.py, tests/unit/test_mediator.py]
accepts: [A11]
---

# T09 — mediator: composed glue with provenance

## Goal

`mediator.py` — the layer that produces a derived artifact by composing
registered wrappers/capabilities/correspondences:

- `find_path(reg, in_kind, out_kind) -> CapabilityPath|None` — BFS over the
  capability graph (in/out_kind strings are the edge labels).
- `mediate(conn, reg, e, out_kind) -> Artifact` — pick the entity's source
  representation (via kind→wrapper mapping, declared in this card), run the
  path, write a `mediator` row (`path` = capability ids, `exactness`), a
  `provenance` row (`in_refs` = entity+source kind, `mediator_id`, `tx`), and
  return the artifact.
- exactness: `exact` if every step is `lens` or a render declared lossless;
  else `contained`, and the artifact carries a `declared_loss` note.

## Tests

- path search finds `entity→html` direct and `entity→markdown→html` 2-hop.
- mediator row + provenance row written per call; re-call with unchanged
  source reuses/recomputes deterministically (document which).
- lossy step in path → `contained` + loss note.

## Contract changes proposed

`Artifact` type (value + out_kind + declared_loss + provenance refs) —
implement locally; propose promotion to contracts.py.
