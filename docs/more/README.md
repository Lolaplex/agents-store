# MORe kernel in agents-store

The Python MORe v4 companion from [Cypoe/more-framework](https://github.com/Cypoe/more-framework) lives under `src/agents_store/more/`. Spec data is vendored as `kernel-proposal.json` beside the package; profile knobs are in `profiles/default.json`.

Porting contract and Lean reference: **`kernel/More/PORTING.md`** in more-framework (do not restate kernel semantics here).

## Loaded here

- Event log, checks, derived status, gates, JWF board state, relations, readiness, hierarchy lint, compliance projection, cut-over profile
- Companion unit tests in `tests/more/`

## Still owned by the board (agents-store integration)

- Persisting the MORe event log into the entity store (datoms), not only `:memory:` / local sqlite
- Board UI projection of JWF / work-item state from store-backed logs
