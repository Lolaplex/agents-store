---
id: T07
status: done
depends: [T06]
owns: [plugins/radicale_agents_store/**, tests/plugin/test_radicale.py, examples/radicale.config]
accepts: [A4, A5]
claimed-by: devin
completed: "2026-10-11 (HEAD~: tests 131 green; commit follows)"
---

# T07 — Radicale storage plugin (GPLv3 sub-package)

## Goal

Radicale `BaseStorage` implementation so CalDAV collections/items are backed
by the canonical store. Thunderbird is the acceptance client.

## Landed semantics (differs from the original sketch — recorded here)

- `plugins/radicale_agents_store/` is a separate package, GPLv3,
  `radicale==3.8.1` pinned (>=7 days old rule). MIT core never imports it.
- **Topology**: `/ -> <principal>/ -> {calendar,tasks}/ -> <item>`.
  Collections must live under a principal — Radicale's `owner_only` rights
  model nests them there. With `auth type=none` any Basic credential is
  accepted and the principal is the username (e.g. `/test/calendar/`).
  Flat `/<collection>/` paths are refused.
- **Two fixed membership-view collections**: `calendar` = entities carrying
  `when`, `tasks` = entities carrying `status`. There is no collection
  table; membership derives from canonical attrs. `create_collection`
  refuses nested/tagged collections, tolerates tagless principals
  (Radicale auto-creates them on login).
- **href is data, not identity**: `ical:href` attr stores the client's
  resource name; entities created store-side render virtual href
  `<eid>.ics`. Emitted `UID:` is always the entity id — the client's
  original UID is kept as `ical:client-uid` provenance.
- **Upload**: `put` → `store.transact(wrapper='ical')`. Refusals land in
  `refusal` (via new `Store.record_refusal`) AND surface as HTTP errors
  (ValueError → BAD_REQUEST / CONFLICT). New hrefs mint exactly one entity.
- **DELETE** retracts the round-trip attrs (`title,status,when,end`) plus
  `ical:href`; provenance attrs stay, all datoms remain in history.
- **Sync**: base-class default — fresh token per etag, stale tokens raise
  (loud, not silent-delta). Real sync-token support → BACKLOG.
- **Meta**: `tag=VCALENDAR` + displayname; `set_meta` is in-memory for the
  POC (documented limit; persistence belongs to a meta-projection).

## Files

- `plugins/radicale_agents_store/{LICENSE(GPLv3),pyproject.toml,radicale_agents_store/__init__.py,radicale_agents_store/storage.py}`
- `tests/plugin/test_radicale.py` — in-process WSGI: discover topology,
  PUT/GET/DELETE, If-Match/If-None-Match, tz refusal → 400 + refusal row,
  unknown-collection refusal, delete-retracts-keeps-history, sync token,
  upload-mints-entity-preserves-extras, move-repaths-href.

## Shared-contract changes made

- `store.py`: added public `record_refusal(r)` — adapters persist
  wrapper-level refusals without reaching into `_refuse`.
- `wrappers/ical.py`: declared adapter-owned attrs `ical:href`,
  `ical:client-uid` (same pattern as `md:path`).

## Verified

`python -m unittest discover -s tests` → 131 tests OK
(120 core + 11 plugin, in-process WSGI against real `radicale.Application`).
