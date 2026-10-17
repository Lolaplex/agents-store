---
id: T16
status: done
depends: [T13, T15]
owns: [src/agents_store/store.py, tests/acceptance/test_mediation.py]
accepts: []
---

# T16 — mediated write-back + acceptance

## Goal

Close the loop (MEGAPLAN §6.1): a write through *any* surface to a
derived attr routes back through the correspondence to the source attr —
or is refused. "Write-back refused for non-round-trippable attrs."

## Store change (`store.py`, owns-listed)

In `transact`, before the grant check for a Change `(e, a)` where
`is_derived(conn, e, a)` is true AND `wrapper != 'store'`:

- Find the live provenance → `mediator_id` → path → the edge whose
  `a_to == a`. If `kind='equal'` AND `status='witnessed'` → rewrite the
  change to `(e, a_from, value)` and apply it under internal authority
  (`wrapper='store'`); the tx records `wrapper=<origin wrapper>` and
  `note='mediated-write via mediator N'`. Re-derivation (T15 hook) then
  refreshes the derived `a` in the follow-up tx.
- Otherwise (`refines`/`derivable` edge, or unwitnessed) → refusal
  `derived-attr`, rest of batch still applies.
- Asserting a value that equals the current derived value → no-op
  (existing no-op semantics), not a refusal.

## Acceptance test (`tests/acceptance/test_mediation.py`)

The §6.1 demo end to end, real surfaces only:

1. Write `export.json` with 2 items (one with `dtstart`, one with
   `dtstart`+`status`) → `jsonfile.sync` → entities minted with `jcal:*`.
2. `match.propose` → confirm exactly 2 correspondences
   (`dtstart→when`, `status→status`... the acceptance says "confirm 2",
   choose the two that make the demo); `match.witness` → `witnessed`.
3. `derive.generate` + `run` → mediated attrs land.
4. Assert (no plugin code touched): GET `/test/calendar/<href>` returns
   a VEVENT with the right `DTSTART` — drive it through the WSGI app;
   and the dual-facet item renders VTODO in `tasks/` — reuses the
   acceptance-harness server.
5. agents-calendar CLI `list` (subprocess witness) sees the items.
6. Update the event's `DTSTART` via agents-calendar `update` →
   `jcal:dtstart` changed on the entity, `when` re-derived, and the
   re-exported `export.json` contains the new dtstart. Provenance:
   `provenance` rows name the mediator + txs.
7. A write to a derived attr through an *unequal* edge → `derived-attr`
   refusal row (construct via a `refines` test edge).

## Rules

- No changes to the Radicale plugin, ical wrapper, or folder adapter —
  the demo works *because* they don't know jcal exists. If acceptance
  needs a plugin edit, the design is wrong; stop and flag.
- agents-calendar must be installed for step 5/6; when absent, that part
  skips with a named skip (independent-witness law: skip is named, not
  silent).

## Contract changes proposed

(none)

## Landed (deviations from `owns`)

- `derive.py` — `is_derived`/`derived_edge` lookup + `json_valid` guard
  (`out_ref` is shared with T09's capability mediators, whose rows are
  non-JSON strings; `json_extract` on them raised `malformed JSON` and
  broke every `transact` once a capability mediation ran — caught by
  `test_demo` regression).
- `jsoncal.py` — one new adapter-owned attr `jcal:rev`
  (`'<slot> <sha256>'`, cardinality many).
- `adapters/jsonfile.py` — last-render tracking: ingest skips an item
  whose file content still equals the hash exported last time, so a
  stale file cannot revert a store-side edit (silent data-loss path
  found by the acceptance test itself — CalDAV edit was reverted by the
  re-export sync before the fix). `folder.py` has the same semantic gap
  and is unchanged — see BACKLOG.
- agents-calendar CLI is the write-back witness (list→update with
  etag); its `update` requires DTEND, so the test event carries one.
