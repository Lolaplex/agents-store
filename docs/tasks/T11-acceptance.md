---
id: T11
status: open
depends: [T05, T06, T07, T08]
owns: [tests/acceptance/test_poc.py, docs/acceptance-matrix.md]
accepts: [A1, A2, A3, A4, A5, A6, A7, A8, A9, A10, A11]
---

# T11 — POC acceptance harness (A1–A11)

## Goal

One end-to-end test module mapping each acceptance criterion to executed
checks, plus `docs/acceptance-matrix.md` tracking status.

## Coverage

- A1 create canonical record → visible through md/html/ical (same id in all).
- A2 edit through one lawful path → canonical + other projections update.
- A3 markdown round-trip incl. rename-keeps-id.
- A4 CalDAV item UID ↔ entity id; event/task visibility.
- A5 independent witness: agents-calendar client reads the CalDAV surface;
  Thunderbird manual checklist documented in the matrix (agent cannot drive
  TB — mark `manual`).
- A6 html pane renders same identity.
- A7 history append-only (API + direct SQL attempt).
- A8 malformed payloads refused (ics/md/html), no partial writes.
- A9 note+status→task same id; split→new id + lineage edge.
- A10 unsupported/lossy write refused with reason + refusal row.
- A11 no secrets in logs/fixtures/serialized records (scan test).

Each check names its A-id in the test name (`test_A9_note_becomes_task`).

## Contract changes proposed

(none)
