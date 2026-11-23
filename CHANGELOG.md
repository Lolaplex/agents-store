# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `connect(path, check_same_thread=False)` for owners that serialize one connection across threads themselves.
- `ops_since(..., local_origins=(prefix, ...))`: ingest-based local projections/imports whose `origin_actor` starts with a listed prefix count as locally minted for the `origin_only` echo filter. Prefix match is parameterized (`substr(origin_actor, 1, ?) = ?`), so quotes and `%`/`_` are literal.

### Changed
- Lower `requires-python` floor to `>=3.10`; no 3.11-only syntax in `src/` (the floor had blocked editable installs in the 3.10 MCP environment).
- Acceptance tests skip cleanly when `radicale` is not installed (Windows dev hosts); EOL pin handling fixed.
- CI triggers now match suite policy: `pull_request` to `main` + `workflow_dispatch` only.
- Added `publish.yml` (PyPI trusted publishing) and `notify-feature.yml` workflows, `.mailmap`, and this changelog.
- Packaging aligned with the suite for the first PyPI release: `__version__` from distribution metadata, project URLs, classifiers, README install section.
- `acceptance` extra pins `agents-calendar>=0.2.0` from PyPI instead of a git commit URL (PyPI rejects direct URL dependencies).
- ical wrapper accepts the time forms agents-calendar and other CalDAV clients write: `TZID=<IANA zone>` wall times, floating times (resolved in `AGENTS_STORE_TIMEZONE`, then `TZ`, then the host zone, then UTC) and all-day `VALUE=DATE`, plus `TZID` on a UTC value. Canonical `when`/`end` stay UTC instants; the client's form is kept in `ical:tz` and VTIMEZONE blocks in `ical:vtimezone`, so the projection renders the same form back. Unknown TZIDs, wall times the zone skips (DST gap) and mixed DATE/DATE-TIME values still refuse with `tz_unsupported`. The Radicale surfaces may write both new attrs.
