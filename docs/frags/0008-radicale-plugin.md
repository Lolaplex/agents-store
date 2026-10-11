---
id: 0008
task: T07
tree: <commit sha — this file>
date: 2026-10-11
---

# T07 evidence — Radicale plugin

## What landed

`plugins/radicale_agents_store/` (GPLv3): `Storage(BaseStorage)` +
`Collection(BaseCollection)` over the canonical store. `radicale==3.8.1`.

- Topology `/<principal>/{calendar,tasks}/<href>` — Radicale rights require
  principal-nested collections; flat collection paths refused.
- `calendar`/`tasks` are membership views (`when` / `status`), not folders.
- href = `ical:href` datum (client-chosen on create; `<eid>.ics` virtual for
  store-side entities). Emitted `UID:` = entity id; client UID kept as
  `ical:client-uid`.
- Upload → `ical.put` → `transact` → mint/update; refusals hit `refusal`
  table AND HTTP error (ValueError → 400/409).
- DELETE retracts round-trip attrs + href; history retained.
- Sync = base-class token impl (stale tokens rejected loudly).
- Meta in-memory (documented POC limit).

## Evidence

```
python -m unittest discover -s tests
Ran 131 tests in 2.772s
OK
```

11 plugin tests exercise real `radicale.Application` over WSGI:
PUT create/update/delete VEVENT+VTODO, If-Match/If-None-Match,
tz-unsupported refusal → 400 + refusal row, collection refusals,
delete-keeps-history, sync token, extras preserved losslessly, move.

## Not done / limits

- No PROPFIND-report deep test (get_filtered inherited, works on etag path).
- In-memory collection meta; single-user auth (`type=none`).
- `examples/radicale.config` + manual Thunderbird run = T12.
