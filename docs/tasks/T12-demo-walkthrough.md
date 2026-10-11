---
id: T12
status: done
depends: [T07, T11]
owns: [examples/demo.py, docs/walkthrough.md]
accepts: [A1, A2]
---

# T12 — Demo + walkthrough

## Goal

`examples/demo.py` — the "you can just do things" script:

1. open store, register wrappers/capabilities, grant certified attrs;
2. create one entity {title, body, status, when};
3. render markdown file into `scratch/notes/`, print html pane, start nothing
   (Radicale run is `examples/radicale.config` + documented command);
4. flip `status` through the markdown file path (edit file, re-sync);
5. print: entity id, kinds, history length, all three representations —
   same id everywhere.

`docs/walkthrough.md` — run-by-run transcript format (pinned commit,
commands, expected output), Thunderbird checklist steps for A5 manual.

## Tests

- demo.py runs clean on a fresh store (subprocess test in tests/acceptance).
- second run is idempotent (same entity, no dup datoms beyond deltas).

## Contract changes proposed

(none)

