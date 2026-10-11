---
id: T10
status: open
depends: [T09]
owns: [src/agents_store/pane.py, tests/unit/test_pane.py]
accepts: [A6, A11]
---

# T10 — pane: "load registered capabilities to interpret a thing"

## Goal

The user-facing view concept: `pane.render(conn, reg, e, target) -> Artifact`.

- `target` is an out_kind (`'html'`, `'ical'`, `'markdown'`, …).
- Implementation = `mediator.mediate`; pane adds the *query side*: list
  available targets for an entity (reachable out_kinds), list entities
  viewable under a target (kinds→required attrs).
- No I/O. Serving the artifact (HTTP, file, CLI print) is an adapter's job —
  write the smallest `examples/` hook only if T12 needs it.

## Tests

- entity with body+status+when: targets include html, markdown, ical;
  rendered html equals T08 output; ical equals T06 output — same id in all.
- entity with only `title` → no targets, empty list (not an error).
- derived `end` appears in html marked derived; not emitted to ical unless
  present as real attr.

## Contract changes proposed

(none)
