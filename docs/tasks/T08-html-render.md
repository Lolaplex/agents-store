---
id: T08
status: open
depends: [T05]
owns: [src/agents_store/capabilities/__init__.py, src/agents_store/capabilities/markdown_html.py, src/agents_store/capabilities/entity_html.py, tests/unit/test_capabilities.py]
accepts: [A6]
---

# T08 — HTML render capabilities (the first pane content)

## Goal

Two `Capability` impls, `mode='render'`:

- `markdown -> html` — minimal stdlib markdown (headers, lists, bold/italic,
  links, fenced code). Document the subset; anything outside renders as
  escaped text, never raw HTML passthrough (XSS boundary).
- `entity -> html` — generic entity card: title, kind badges, attr table,
  derived values marked `(derived)`, lineage links if present.

## Tests

- entity → html: card contains id, kinds, attrs; derived `end` marked.
- markdown → html: subset renders; `<script>` in source is escaped.
- capabilities register in `Registry` without collision.

## Contract changes proposed

(none)
