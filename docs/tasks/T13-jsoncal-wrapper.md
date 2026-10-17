---
id: T13
status: claimed
agent: devin-local
claimed: 2026-10-17
depends: []
owns: [src/agents_store/wrappers/jsoncal.py, src/agents_store/adapters/jsonfile.py, tests/unit/test_jsoncal.py, tests/unit/test_jsonfile.py]
accepts: []
---

# T13 — jsoncal wrapper + JSON file adapter

## Goal

A second calendar source *in its own terms* (MEGAPLAN §6.1): a JSON
export format with its own `jcal` namespace. No core attrs are produced —
alignment happens through correspondences (T14/T15), not inside the
wrapper. That is the point of the demo.

## Format

`export.json` — a JSON array of items:

```json
[{"uid": "abc-1", "summary": "Dentist", "dtstart": "2026-12-01T10:00:00Z",
  "dtend": "2026-12-01T11:00:00Z", "status": "confirmed",
  "category": ["health"]}]
```

## Wrapper (`id='jcal'`, namespace `jcal`)

Attrs (register on wrapper registration, like `md:`/`ical:`):

- `jcal:uid` (text, one) — source-local id; provenance, NOT entity id
  (minted ids only; uid reuse across sources is possible).
- `jcal:summary` (text, one), `jcal:dtstart` (instant, one),
  `jcal:dtend` (instant, one), `jcal:status` (text, one — free text,
  jsoncal's own vocabulary, e.g. `confirmed|cancelled|done|open`).
- `jcal:extra` (json, one) — lossless: unmapped keys kept verbatim
  (same law as `md:extra`/`ical:extra`).
- `jcal:path` (text, one) — adapter-owned: which file this item lives in
  (one file may hold many items; value = `path#uid`).

`get(e, view)` renders one item object (dict → JSON text of the single
item). `put(rep, e, view)` parses one item object; a `uid` change is an
ordinary revision of `jcal:uid` (provenance, not identity — PutGet
requires it to be writable; uid→entity alignment is the adapter's job
via `_by_uid`, not a wrapper refusal); non-dict/array or unparseable
JSON → `parse-fail`; instant fields not ISO-8601 `Z` → `tz-unsupported`.

## Adapter (`adapters/jsonfile.py`)

`sync(store, path, wrapper, registry)` — folder-adapter law applied to a
single multi-item file:

- read: items with known `jcal:uid` → diff → `put` changes; unknown uid →
  mint entity; malformed item → refusal row, item skipped, others land.
- write-back: after sync, re-export the file from the store (all entities
  carrying `jcal:path` for this file), preserving `jcal:extra` keys.
  Round-trip: file → store → file is byte-modulo-ordering stable.

## Tests

- get/put round-trip incl. `jcal:extra` keys preserved.
- `parse-fail`, `uid-mismatch`, `tz-unsupported` refusals land in `refusal`.
- adapter: ingest 2 items → 2 entities minted with `jcal:*` attrs; second
  sync with an edited `summary` → update lands on the same entity;
  unknown file edits never mint positional ids.
- certify: `certify.run` passes on the declared attr set (GetPut/PutGet)
  → grants exist for `jcal:*` mapped attrs.

## Contract changes proposed

(none — attrs self-register on wrapper registration, same as md/ical)
