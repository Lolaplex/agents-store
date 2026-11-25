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

### Fixed
- `connect()` crashed on pre-v6 databases whose `datom` table carried repeated `(e,a,v)` history: the v6 `ord` backfill now runs inside one migration transaction, before schema DDL, grouped by `(e,a,v,tx)` so `ux_datom_eav_ord` cannot collide. All schema-version migrations run transactionally.
- `connect()` crashed on pre-v2 databases (`OperationalError: no such column: hlc`): the v2 lineage rebuild now reads the six-column `tx` shape and adds `hlc`/`origin_actor`/`origin_seq` when absent.
- `transact()` and `ingest()` are atomic (`BEGIN IMMEDIATE`/commit/rollback): a mid-write exception leaves no half-applied op. `transact` collapses encoded duplicates per tx (retract wins on a shared `(e,a,v)`; the last card-one value wins) and refuses to write into a scrubbed entity.
- Ingest rejects malformed HLC strings and unknown `op` values, refuses non-syncable/never-syncable attrs instead of recording raw datoms, dedupes local self-echo before minting phantom tx rows, dedupes `(origin_actor, origin_seq)` before scrub side effects, and ignores empty scrub target notes. `scrub` ops propagate physically: the peer writes a tombstone (`max` of any existing cutoff), deletes the entity's datoms/lineage/provenance/refusal payloads, and the tombstone replicates on to block stale resends.
- `scrub()`/`scrub_datoms()` mint an HLC cutoff when none is given, take the max of an existing tombstone cutoff, and re-create the append-only triggers inside the same transaction.
- The HLC parser rejects malformed values, node ids normalize into the hlc alphabet (`did:key:...` hashes to a deterministic `k_<sha256[:16]>` part rather than being rejected), the clock bounds remote drift at 60 s past local wall time, the counter wraps past 99,999 by advancing the millisecond, and `Store` re-seeds its clock from `MAX(tx.hlc)` before each local tick.
- `view(e, tx=…)` orders on `ord` (the global HLC key) with card-one argmax, matching `v_current`; `ops_since` and ingest filter the never-sync prefixes case-insensitively and never emit empty non-scrub envelopes; `local_origins` rejects a bare string.
- `lineage` tx rows carry a real HLC, `merge` records conflict references without writing divergent same-`ord` card-one datoms, and `view()` picks the max-`v` winner for a same-`ord` card-one tie (same rule ingest applies).
