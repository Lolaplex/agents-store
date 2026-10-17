# v0 POC audit ledger

Tree under test: `audit/v0-ledger` (pin with `git rev-parse HEAD` on the release tag).

| Scenario | Setup | Expected invariant | Test / witness | Result |
|----------|-------|-------------------|----------------|--------|
| Markdown `id:` edit refused, no mutation | Entity + folder sync; edit `id:` in file | Refusal; canonical attrs unchanged | `test_A8_md_id_edit_refused` | pass |
| Malformed ICS refused, no partial tx | HTTP PUT bad syntax or TZID | No new entity; no partial datoms | `test_A8_bad_ics_no_partial` | pass |
| Non-round-trippable RRULE/TZ refused, prior state kept | PUT TZID event | 400 + refusal row; store unchanged | `test_A10_tz_refused`, `test_tz_refusal_http_and_table` | pass |
| Rename keeps same entity | CalDAV MOVE or `md:path` change | Same entity id; href/path is data | `test_A2_caldav_move_propagates`, `test_A3_md_edit_and_rename` | pass |
| Delete then recreate same path ≠ same identity | DELETE item; PUT same href | New minted entity id | `test_delete_retracts_keeps_history` (history); recreate id covered by store mint semantics + demo idempotency | pass |
| Restart preserves history | Per-test temp `AGENTS_STORE_SCRATCH` + `demo.sqlite` | Prior datoms readable after reconnect | `test_demo_runs_clean_and_idempotent` | pass |
| Repeated demo appends only deltas | Run `examples/demo.py` twice in same scratch dir | Same entity; `history` count grows | `test_demo_runs_clean_and_idempotent` | pass |
| Stale ETag refused | PUT/DELETE with old `If-Match` | 412 / error; no silent apply | `test_etag_precondition` | pass |
| Direct SQLite UPDATE/DELETE on `datom` aborts | Bootstrap store | `IntegrityError` | `test_A7_datom_immutable`, `test_datom_is_append_only` | pass |
| **Hole a** — history tables append-only (not only `datom`) | Bootstrap store with rows in each history table | `UPDATE certificate SET result='pass'` and peers abort | `test_certificate_update_aborts`, `test_all_history_tables_reject_update_and_delete` | pass (fixed: triggers on `tx`, `lineage`, `certificate`, `grant_`, `refusal`, `provenance`) |
| **Hole b** — certificate binds wrapper code hash | Certify + grant; stale hash cert | Grant / `is_writable` reject mismatch | `test_grant_rejects_stale_code_hash`, `test_code_hash_recorded` | pass (fixed: `certificate.code_hash`, `grant.py` / `is_writable`) |
| **Hole c** — attr re-declaration loud | `register_wrapper` twice with conflicting type | `RegistryError` | `test_conflicting_attr_spec_raises` | pass (fixed: no `INSERT OR IGNORE` on attrs) |
| **Hole d** — provenance carries `tx`; retire clears adapter attrs | `mediate()`; CalDAV DELETE | `provenance.tx` set; `ical:*` not current after retire | `test_mediator_provenance_carries_tx`, `test_delete_retracts_keeps_history` | pass (fixed: `mediator.py`, `storage.delete` retracts `ical:*`) |
| **Hole e** — delete is `op=retire` | CalDAV DELETE | Latest tx `op='retire'`, note is href not prose | `test_delete_retracts_keeps_history`, `test_retire_op_on_retract_batch` | pass (fixed: `storage.delete`) |
| **Hole f** — correct vs evolve distinguishable | `lineage.correct` vs `evolve(..., record_edge=True)` | `severs` vs `wasRevisionOf` self-edge | `test_correct_uses_severs_evolve_uses_wasRevisionOf`, `test_correct_records_revision_edge` | pass (fixed: `severs` kind in schema + `lineage.correct`) |

## Verification

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[acceptance]" -e plugins/radicale_agents_store
.venv/bin/python -m unittest discover -s tests
```

Latest measured count: **152** (128 unit + 11 plugin + 13 acceptance) at `git rev-parse HEAD` on this branch.
