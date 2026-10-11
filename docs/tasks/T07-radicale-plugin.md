---
id: T07
status: open
depends: [T06]
owns: [plugins/radicale_agents_store/**, tests/plugin/test_radicale.py, examples/radicale.config]
accepts: [A4, A5]
---

# T07 — Radicale storage plugin (GPLv3 sub-package)

## Goal

Radicale `BaseStorage` implementation so CalDAV collections/items are backed
by the canonical store. Thunderbird is the acceptance client.

## Boundaries

- `plugins/radicale_agents_store/` is a **separate package**, license GPLv3,
  depends on `agents_store` (MIT) + `radicale` (GPLv3). MIT core must never
  import it.
- Item href = `<entity-id>.ics`; collection = one calendar listing all
  entities the `ical` wrapper can `get` (event+task membership via kinds).
- Writes: Radicale calls `put`-equivalents → `ical.put` → `store.transact` with
  `wrapper='ical'`. Refusals surface as HTTP errors (4xx), never silent.

## Files

- `plugins/radicale_agents_store/{LICENSE(GPLv3),pyproject.toml,radicale_agents_store/storage.py}`
- `examples/radicale.config` — minimal working config pointing storage at the plugin.
- `tests/plugin/test_radicale.py` — in-process Radicale app:
  create/update/delete VEVENT+VTODO through the WSGI API; assert datoms,
  refusals, UID↔entity-id mapping. agents-calendar as independent witness for
  A5 where feasible.

## Tests

- PROPFIND/PUT/REPORT round-trip via Radicale test harness.
- write VEVENT via CalDAV → store entity exists, markdown wrapper renders it.
- malformed ics → 4xx + refusal row.
- no credentials, no secrets in repo; auth config lives in
  `examples/radicale.config` with localhost-only, no-password test setup —
  document that production auth is out of scope.

## Contract changes proposed

(none)
