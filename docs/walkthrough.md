# POC walkthrough — "you can just do things"

Pinned tree: commit `5fd347a` (+ T12 docs). Commands run from the repo
root on Windows/PowerShell.

## 1. Setup (once)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e . -e plugins\radicale_agents_store -e C:\Users\fabi0\repos\agents-calendar
```

## 2. Tests

```powershell
.venv\Scripts\python -m unittest discover -s tests
# Ran 143 tests ... OK
```

## 3. Demo script

```powershell
.venv\Scripts\python examples\demo.py
```

Creates `scratch/demo.sqlite` + `scratch/notes/demo-entity.md` and prints:
the minted entity id, its kinds (`event note task`), the markdown file,
the status flip **made by editing the file** (open→done→open each run),
the ical representation `UID:<entity-id>`, the HTML pane (with `end`
shown as derived via `plus_1h`), and the append-only datom count.

Second run: same `entity:` line, history grows by exactly the delta
datoms. That is the whole thesis in one line of output.

## 4. CalDAV surface

```powershell
$env:AGENTS_STORE_DB = "$PWD\scratch\demo.sqlite"
.venv\Scripts\python -m radicale --config examples\radicale.config
```

The demo entity is now served at
`http://127.0.0.1:5232/<user>/tasks/` (it has `status`) and
`http://127.0.0.1:5232/<user>/calendar/` (it has `when`).
With `auth type=none` any username/password is accepted; the principal is
the username (`test` → `/test/calendar/`).

## 5. agents-calendar (independent witness, scripted)

```powershell
$env:CALDAV_URL = "http://127.0.0.1:5232/"
$env:CALDAV_USERNAME = "test"; $env:CALDAV_PASSWORD = "anything"
$env:CALDAV_CALENDAR = "calendar"
agents-calendar calendars
agents-calendar list --from 2026-10-01T00:00:00Z --to 2026-12-31T00:00:00Z
agents-calendar add --summary "from CLI" --dtstart 2026-12-01T10:00:00Z --dtend 2026-12-01T11:00:00Z
```

After `add`, re-run `examples\demo.py`-style checks: the entity exists in
`scratch/demo.sqlite` with `ical:href` + `ical:client-uid` data, and
`folder.sync` materializes it into `scratch/notes/` on next sync.

## 6. Thunderbird (manual A5 checklist)

1. Run the server as in step 4.
2. Thunderbird → Calendar → New Calendar → On the Network.
3. Username `test` (any password), location
   `http://127.0.0.1:5232/test/calendar/` — subscribe.
4. Also subscribe `http://127.0.0.1:5232/test/tasks/` via the Tasks pane
   (same URL form; Thunderbird treats VTODO collections as tasks).
5. Drag the demo event to a different time → sync. Expected: a new `tx`
   in the store, `when` updated, markdown + pane reflect it.
6. Complete the task → expected `status: done` everywhere.
7. Try to add a recurrence rule → expected refusal (HTTP error; a
   `refusal` row with reason appears — only unresolvable times (unknown
   TZID, a wall time the zone skips) and component-shape violations
   refuse today; TZID, floating and all-day times are accepted and kept
   in the client's form; unknown props are preserved
   losslessly in `ical:extra` and re-emitted).

## What "lawful" means here, concretely

- Every write is a proposed `Change` set gated by certificate-backed
  grants; ungranted/unknown writes become `refusal` rows, never silent.
- `UID:`/`id:`/filename/href are projections, never identity — renaming
  the md file or the .ics href keeps the entity.
- DELETE retracts membership attrs; every datom stays in `datom`
  (UPDATE/DELETE on it is trigger-blocked).
