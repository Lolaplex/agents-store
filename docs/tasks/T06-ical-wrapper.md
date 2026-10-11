---
id: T06
status: done
agent: devin-local
claimed: 2026-10-11
done: 2026-10-11
depends: [T04]
owns: [src/agents_store/wrappers/ical.py, tests/unit/test_ical.py]
accepts: [A4]
---

# T06 — iCalendar wrapper (VEVENT/VTODO text)

## Goal

`Wrapper` impl (`id='ical'`, namespace `ical`) mapping entity ↔ single
iCalendar component text. This is the CalDAV payload layer; the transport is
T07.

## Mapping (declared round-trip set — drives certification)

- `when` ↔ `DTSTART` (UTC `…Z` only; non-UTC input → refusal `tz-unsupported`)
- `end` ↔ `DTEND`; `title` ↔ `SUMMARY`; `status` ↔ VTODO `STATUS`
  (`open→NEEDS-ACTION`, `done→COMPLETED`; anything else refusal `status-map`)
- `UID` = entity id. VEVENT iff `when` present and no `status`; VTODO iff
  `status` present; both attrs → emit VTODO (document choice).
- Unknown iCal props on put (e.g. `ATTENDEE`, `RRULE`) → preserved-lossless is
  NOT required for POC: propose them as `ical:raw` blob attr OR refuse with
  `prop-unmapped` — pick one, document, keep consistent.

## Tests

- get: entity {when, title} → valid VEVENT text (`BEGIN:VCALENDAR` wrapper,
  `UID:<eid>`).
- put: VTODO with STATUS:COMPLETED → `status=done` change.
- put: local-time DTSTART (TZID) → refusal `tz-unsupported`, zero changes.
- put: garbage → refusal `parse-fail`.
- lens corpus: 50 seeded views GetPut+PutGet pass on declared attrs.

## Contract changes proposed

(none)
