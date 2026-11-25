# AGENTS.md: agents-store

One identity, many lawful projections. The plan is the source of truth: `docs/MEGAPLAN.md`.

## Guardrails (lessons from the ISAR/plex lineage)

1. **No new substrate before POC acceptance (A1–A11) passes.** Python `>=3.10` (see `pyproject.toml`), stdlib + `sqlite3` + `blake3>=1.0` (MORe SAIDs, `agents_store.more.said`) in `src/agents_store/`. Radicale only in `plugins/radicale_agents_store/` (GPLv3).
2. **Claims need executed evidence.** No "O(1)", "proven" or "verified" without the command output that shows it. Write-ups pin the tree they measured (`git rev-parse HEAD`).
3. **Refuse by default.** An attribute is writable through a wrapper only if a certificate (witness or proof) grants it. Every refusal is a `refusal` row with a reason. Never a silent default or fallback.
4. **Identity is minted, never positional.** Entity IDs are never reused and never derived from content, path, rank or order. Paths, ordinals and filenames are projections.
5. **History is append-only.** `datom` has no UPDATE or DELETE. Current state is a view.
6. **Kind changes are explicit.** Adding an attribute is a revision. Split, merge and correct mint IDs or sever links, with lineage rows (PROV vocabulary).
7. **Labels name code that does the work.** No decorative semantics.
8. **Witnesses stay independent.** Thunderbird and agents-calendar test the CalDAV projection. A missing oracle is a named refusal, not a fallback.
9. **Hygiene.** Commit landed work. Scratch goes in `scratch/` (ignored). No stray files in the repo root.

## Verification

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[acceptance]" -e plugins/radicale_agents_store
.venv/bin/python -m unittest discover -s tests -v
```

Windows: use `.venv\Scripts\python` instead of `.venv/bin/python`.

Manual pass for A1–A6: `.venv/bin/python -m radicale --config examples/radicale.config` (Windows: `.venv\Scripts\python -m radicale ...`), then `python examples/demo.py` and check in Thunderbird. Full transcript + Thunderbird checklist: `docs/walkthrough.md`. Status per criterion: `docs/acceptance-matrix.md`.

## Distributed op-log (ord / origin / ingest / scrub)

The store is one `store.db` op-log per workspace; remote ops arrive as
txs over agents-sync's `opdist` carrier (distributor owns delivery,
this module owns semantics):

- `hlc.py` — hybrid-logical-clock ord keys
  `f"{ms:013d}.{counter:05d}.{node}"`: lexicographically sortable,
  total order across nodes. The 13-digit epoch always sorts after the
  12-digit legacy backfill keys from `_migrate_v6`, so synced writes
  win over old local history.
- `ingest.py` — the only write path for remote ops. A remote op's
  datoms land verbatim under a local tx stamped with the remote's hlc
  and `(origin_actor, origin_seq)`; that pair is unique, so redelivery
  is idempotent, self-echo dedupes to zero rows, and `ux_datom_eav_ord`
  drops facts already present. Canonicalization is deterministic for
  every receiver (same-`(e,a,v)` retract wins; `card_one_same_ord`
  refusals). Grants are NOT re-checked — the origin gate-kept the
  write. Unknown and never-syncable attrs are skipped loudly as
  refusal rows. `ops_since(cursor)` is the tail the distributor drains;
  `cursor()` is the resume point.
- `scrub.py` — the only path that deletes datom rows (privileged
  operator tooling, never via `transact()`): drops append-only triggers
  inside a guarded section, deletes, restores them, and writes a
  PII-free `tx(op='scrub')` + `scrubbed(e,T)` tombstone first so synced
  peers replay the same scrub and can never resurrect the content.
- Current state is the `v_current` view keyed by `ord`
  (`db.py`); raw `store.db` files never file-sync — only ops move.

## Picking up work (subagents)

Work is broken into self-contained cards under `docs/tasks/` (protocol in `docs/tasks/README.md`, module map in `docs/ARCHITECTURE.md`). One card per agent; only touch files under `owns`; shared contracts (`contracts.py`, `schema.sql`, `seed.sql`) are never edited by a task.

## Current state

POC frozen at annotated tag `poc-v1` (`git rev-parse poc-v1^{commit}` →
`e031973`, 156 tests at freeze). Megaplan §6.1 (generated mediators)
complete through T16 (189 tests at T16 land). **T17** (MORe event log
co-located with the entity store) landed on `main` — **303 tests**
(159 unit + 15 plugin + 15 acceptance + 114 MORe companion) at
`e9f470868be05a5031217382bd0aa48583d09737` (`origin/main` HEAD when
measured). Audit ledger: `docs/AUDIT.md`. Post-POC work continues in
`docs/tasks/BACKLOG.md` (agent-rules projections, koru layer,
file-adapter merge semantics, glue specialization). Since then the
distributed op-log line landed: `hlc.py` ord keys, `ingest.py` remote
op ingest, `scrub.py` tombstoned redaction (see *Distributed op-log*
above).
