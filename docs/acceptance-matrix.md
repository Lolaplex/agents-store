# POC acceptance matrix

Status of A1–A11 (task-card numbering in `docs/tasks/T11-acceptance.md`,
mapping to the megaplan numbering noted where different).

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| A1 | One entity visible through md/ical/html, same id | ✅ scripted | `test_A1_entity_projects_everywhere` |
| A2 | Edit through one lawful path propagates to all projections | ✅ scripted | `test_A2_caldav_move_propagates` (agents-calendar CLI drives the edit) |
| A3 | Markdown round-trip; rename keeps entity id | ✅ scripted | `test_A3_md_edit_and_rename` |
| A4 | Emitted UID = entity id; event/task membership | ✅ scripted | `test_A4_uid_and_membership`, plugin `test_put_get_vevent` |
| A5 | Independent witness: agents-calendar over real HTTP | ✅ scripted | `test_A5_agents_calendar_list_update_delete` (subprocess, real socket) |
| A5 | Thunderbird manual pass | ⏳ manual | checklist in `examples/` (T12) |
| A6 | HTML pane renders same identity | ✅ scripted | `test_A6_pane_same_id` |
| A7 | History append-only; UPDATE/DELETE on `datom` fail | ✅ scripted | `test_A7_datom_immutable` |
| A8 | Malformed payloads refused, no partial writes | ✅ scripted | `test_A8_bad_ics_no_partial`, `test_A8_md_id_edit_refused` |
| A9 | +status → task same id; split → new id + lineage edge | ✅ scripted | `test_A9_note_becomes_task_and_split` |
| A10 | Non-lawful write refused with reason + refusal row | ✅ scripted | `test_A10_tz_refused`, plugin `test_tz_refusal_http_and_table` |
| A11 | No secrets in artifacts/fixtures/records | ✅ scripted | `test_A11_password_absent_everywhere` |

Megaplan A8 (certification grants, disabling cert → refused): covered by
`tests/unit/test_certify.py` (`test_pass_writes_cert_and_grants`,
`test_fail_cert_no_grants`, `test_uncertified_wrapper_refused`).

Run: `.venv\Scripts\python -m unittest discover -s tests`
(143 tests: 120 core + 11 plugin + 12 acceptance).

## Known POC limits (documented, not bugs)

- Collections are `/​<principal>/​{calendar,tasks}/` — Radicale's rights
  model requires principal nesting; with `auth type=none` the principal is
  the username (`/test/calendar/` for user `test`).
- `auth type=none`: any Basic credential is accepted. Production auth is
  out of POC scope.
- Sync tokens: base implementation returns a fresh token and rejects stale
  ones loudly; delta-sync is BACKLOG.
- Collection metadata writes are in-memory per process (meta-projection =
  BACKLOG).
- Deleted entities keep provenance attrs (`ical:client-uid`, `ical:extra`)
  — history is append-only by design.
