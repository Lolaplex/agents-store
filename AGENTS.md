# AGENTS.md: agents-store

One identity, many lawful projections. The plan is the source of truth: `docs/MEGAPLAN.md`.

## Guardrails (lessons from the ISAR/plex lineage)

1. **No new substrate before POC acceptance (A1–A11) passes.** Python 3.11 stdlib + `sqlite3` only in `src/agents_store/`. Radicale only in `plugins/radicale_agents_store/` (GPLv3).
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
file-adapter merge semantics, glue specialization).
