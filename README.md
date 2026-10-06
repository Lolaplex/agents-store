# agents-store

One identity, many lawful projections.

A thing (an event, a task, a note) is stored once with a minted ID, typed attributes, relations and an append-only history. Calendars, markdown folders and HTML panes are projections of it, not copies. A write through a projection is refused unless a certificate grants it.

Status: **Step 0**. Plan only. See [docs/MEGAPLAN.md](docs/MEGAPLAN.md).

## POC target

One entity with `title`, `when`, `status`, `body` shows up as:

- a VEVENT and a VTODO in Thunderbird, through a Radicale storage plugin,
- a markdown file in a folder Obsidian can open,
- an HTML pane rendered from registered capabilities.

An edit in any of them lands in the others. An edit that can't round-trip (an RRULE, a changed `id:`) is refused with a reason.

Stack: Python 3.11 standard library + `sqlite3`. The Radicale plugin is a separate GPLv3 sub-package. The core is MIT.
