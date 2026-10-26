# Task board — subagent pickup protocol

Each `T*.md` here is a self-contained work card for a SWE-2-level subagent.
Read `../ARCHITECTURE.md` and `../../AGENTS.md` first; the card alone should
be enough after that.

## Card format

Frontmatter:

| field | meaning |
|---|---|
| `status` | `open` → `claimed` → `done` (or `blocked` with reason appended) |
| `depends` | task ids whose `done` you need before starting |
| `owns` | file globs only this task may create/edit |
| `accepts` | acceptance criteria (A-ids from MEGAPLAN) this task moves |

## Rules for picking up a card

1. Claim: set `status: claimed`, add `agent:` (your run id) and today's date in
   frontmatter. One card per agent at a time.
2. Touch **only** files under `owns`, plus `scratch/` for temporary work.
3. Shared contracts — `src/agents_store/contracts.py`, `schema.sql`,
   `seed.sql`, this README, `docs/ARCHITECTURE.md` — are **never** edited by a
   task. If your design requires a change, write the delta in your card's
   "Contract changes proposed" section and stop that part; the orchestrator
   applies it.
4. Tests: `tests/unit/` must run on stdlib unittest with `:memory:` databases.
   No network in unit tests. Plugin/acceptance dirs per card.
5. Done means: tests green
   (`.venv\Scripts\python -m unittest discover -s tests -v`), evidence frag
   written (see `docs/frags/README.md`), `status: done`, `commit:` recorded.

## Dependency graph

```
T01 store core ──┬─ T02 kinds ──┐
                 ├─ T03 lineage ┤
                 ├─ T04 certify ─┼─ T05 markdown wrapper+folder ── T08 html render
                 │               └─ T06 ical wrapper ── T07 radicale plugin (GPLv3)
                 └───────────────┴─ T09 mediator ── T10 pane
                                          │
T11 acceptance (A1–A11) ← T05,T06,T07,T08
T12 demo + walkthrough  ← T07,T11
```

Post-POC (§6.1 generated mediators, started after tag `poc-v1`):

```
T13 jsoncal wrapper+jsonfile ─┐
T14 correspondence match ─────┴─ T15 derive (materialize) ── T16 write-back+accept
```

MORe companion + store bridge (after kernel port landed):

```
T17 MORe event log in entity store (done)
```

Parallel at kickoff: **T13 ∥ T14**.

## Verification command (all cards)

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
```
