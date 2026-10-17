---
id: 0011
task: T07
tree: <commit sha — this file>
date: 2026-10-17
---

# Surface law — per-collection component projection (BetterBird fix)

## Problem (manual witness report)

BetterBird showed both `calendar` and `tasks` as plain calendars, and
dual-facet entities (task with `when`) were not plotted: the rendered
component ignored which collection served it (`status` present → VTODO
everywhere), and Radicale defaulted `supported-calendar-component-set`
to VEVENT+VTODO+VJOURNAL for both.

## What landed

- `wrappers/ical.get(..., component=None)`: callers may pin VEVENT|VTODO;
  default keeps structural choice (status → VTODO).
- Plugin constants `COMPONENT`/`WRITE_SETS` per collection
  (`calendar` → VEVENT / `{title,when,end,ical:extra}`;
   `tasks` → VTODO / write-set + `status`).
- `upload`: changes outside the surface write-set are stripped **and**
  recorded as `refusal` rows (`reason='out-of-projection'`) — not silently
  dropped, not whole-PUT rejected.
- `delete`: retracts only the surface write-set; `ical:href` /
  `ical:client-uid` stay as provenance so a later PUT to the same href
  rebinds the same entity. Deleting a task's VEVENT no longer kills the
  task facet (previously status was silently retracted — real bug).
- `get_meta`: advertises `C:supported-calendar-component-set` =
  VEVENT / VTODO per collection.

Trade-off: `ical:href` and `ical:extra` are shared across both surfaces
(single datom per entity). Deleting via one surface retracts `ical:extra`
globally but keeps `ical:href`; per-collection bindings would need
per-surface attrs — noted as POC limit.

## Evidence

```
.venv\Scripts\python -m unittest discover -s tests
Ran 156 tests in 13.988s — OK
(128 unit + 15 plugin + 13 acceptance)
```

New tests in `tests/plugin/test_radicale.py`:

- `test_task_with_when_plots_in_calendar_as_vevent` — same UID in both
  collections; VEVENT render has DTSTART and no STATUS.
- `test_calendar_put_preserves_task_facet` — VEVENT PUT through
  `calendar/` lands title, keeps `status`, records
  `out-of-projection` refusal.
- `test_calendar_delete_keeps_task_facet` — DELETE via `calendar/`
  retracts `when`, keeps `status`; tasks/ still serves VTODO.
- `test_component_set_metadata` — PROPFIND-advertised component sets.
- `test_delete_retracts_keeps_history` updated: href + client-uid now
  asserted retained as provenance.

Environment fix (witness, not store): `agents-calendar` crashes on
Windows without `tzdata` (zoneinfo has no IANA db) — added
`tzdata; platform_system == 'Windows'` to its `dependencies`.
