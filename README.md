# agents-store

One identity, many lawful projections.

A thing (an event, a task, a note) is stored once with a minted ID, typed attributes, relations and an append-only history. Calendars, markdown folders and HTML panes are projections of it, not copies. A write through a projection is refused unless a certificate grants it.

Status: **POC landed** — all 12 task cards done, 152 tests (128 unit + 11 plugin + 13 acceptance; see `docs/AUDIT.md`) including the agents-calendar subprocess witness over real CalDAV when the CLI is installed. See [docs/walkthrough.md](docs/walkthrough.md) to run it end to end, [docs/acceptance-matrix.md](docs/acceptance-matrix.md) for criterion status, [docs/tasks/](docs/tasks/README.md) for the task cards, [docs/MEGAPLAN.md](docs/MEGAPLAN.md) for the plan, [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the module map.

## POC target

One entity with `title`, `when`, `status`, `body` shows up as:

- a VEVENT and a VTODO in Thunderbird, through a Radicale storage plugin,
- a markdown file in a folder Obsidian can open,
- an HTML pane rendered from registered capabilities.

An edit in any of them lands in the others. An edit that can't round-trip (an RRULE, a changed `id:`) is refused with a reason.

Stack: Python 3.11 standard library + `sqlite3`. The Radicale plugin is a separate GPLv3 sub-package. The core is MIT.
