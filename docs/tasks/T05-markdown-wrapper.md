---
id: T05
status: open
depends: [T04]
owns: [src/agents_store/wrappers/__init__.py, src/agents_store/wrappers/markdown.py, src/agents_store/adapters/__init__.py, src/agents_store/adapters/folder.py, tests/unit/test_md_wrapper.py, tests/unit/test_folder.py]
accepts: [A3]
---

# T05 — Markdown wrapper + folder adapter

## Goal

Entities with `body` ↔ markdown files: `get` renders frontmatter + body;
`put` parses frontmatter back into `Change`s (title, body, extra `md:*` attrs).
This is the Obsidian surface.

## Format (contract for this wrapper)

```markdown
---
id: 01JXYZ…            # minted entity id — the anchor, NOT the path
title: …
status: open           # any declared attrs pass through frontmatter
---
body text…
```

- `id` in frontmatter is the identity. A file with no `id` is a *new* entity
  (put proposes `e=None` changes). A file whose `id` doesn't exist is a
  refusal (`unknown-entity`).
- Path is `md:path` (cardinality many): many paths → one entity is legal;
  one path → many entities is refused (`path-collision`).

## Files

- `wrappers/markdown.py` — `Wrapper` impl (`id='md'`, `namespace='md'`),
  `attrs()` includes `md:path` (seeded). Frontmatter: minimal YAML-subset
  parser (std only; `key: value` lines, no nesting — document limits).
- `adapters/folder.py` — `sync(store, reg, root)`:
  scan `*.md`, group by `id`, call `put` per file, `transact` results, write
  rendered files for entities lacking the path. All I/O lives here.

## Tests

- get/put round-trip on frontmatter+body corpus (certify-compatible).
- unknown-id file → refusal, nothing written.
- two files same path, different id → path-collision refusal.
- rename file (same id, new path) → `md:path` updated, entity id unchanged.
- folder sync: edit file → store updated; new entity → file written at
  `<title-slug>.md` with frontmatter id.

## Contract changes proposed

(none)
