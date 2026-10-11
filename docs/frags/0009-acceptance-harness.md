---
id: 0009
task: T11
tree: <commit sha — this file>
date: 2026-10-11
---

# T11 evidence — acceptance harness

## What landed

- `tests/acceptance/test_poc.py`: 12 checks, one per A-criterion
  (T11 numbering). Live environment per class: real `radicale.Application`
  served by wsgiref on an ephemeral port; canonical store + markdown folder
  + pane all on the same db.
- A5 witness is `agents-calendar` (sibling repo, editable install) run as a
  subprocess over real HTTP: `calendars` (principal→home-set discovery),
  `add`, `list` (calendar-query REPORT), `update` + `delete` (If-Match
  etags). Not a mock — the true socket path.
- `docs/acceptance-matrix.md`: status table + documented POC limits.

## Evidence

```
.venv\Scripts\python -m unittest discover -s tests
Ran 143 tests in 11.209s
OK
```

## Fixes the harness forced (this is what it's for)

- `storage.py`: per-thread sqlite connections — Radicale serves on worker
  threads; the single shared conn raised ProgrammingError on real HTTP
  (in-process WSGI tests never saw it).
- `folder.py`: write-back gate was `body`-only — CalDAV-created events
  never materialized as notes. Now any md-mapped attr triggers a file.
- Radicale auto-creates the user principal → `create_collection` tolerates
  tagless single-segment names, still refuses tagged/nested.
