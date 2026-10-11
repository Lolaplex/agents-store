---
id: 0010
task: T12
tree: <commit sha — this file>
date: 2026-10-11
---

# T12 evidence — demo + walkthrough

## What landed

- `examples/demo.py`: creates/reuses one entity via an anchor md file
  (idempotent), syncs the folder projection, flips `status` by editing
  the FILE (write enters through md wrapper -> canonical tx), prints
  id + kinds (`event note task`) + md + ical + html pane + datom count.
- `examples/radicale.config`: localhost, `auth type=none`,
  `storage type=radicale_agents_store`, `AGENTS_STORE_DB` env for db path.
- `docs/walkthrough.md`: full transcript — setup, tests, demo, CalDAV
  server, agents-calendar commands, Thunderbird manual checklist.
- `tests/acceptance/test_demo.py`: demo subprocess x2, asserts same
  entity id and growing history.

## Evidence

```
.venv\Scripts\python examples\demo.py   (run 1)
entity   : 01M4N430A680A3GMF4B58CV2BF
kinds    : ['event', 'note', 'task']
status   : open -> done (via file edit)
history  : 7 datoms

.venv\Scripts\python examples\demo.py   (run 2)
entity   : 01M4N430A680A3GMF4B58CV2BF   <- same id
status   : done -> open (via file edit)
history  : 9 datoms                      <- deltas only
```

All 12 task cards landed; 144 tests green.
