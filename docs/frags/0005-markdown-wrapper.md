# 0005 markdown wrapper + folder adapter (T05)

- commit: <this commit>
- task: T05
- claim: entity <-> markdown frontmatter lens (id anchored, extra keys lossless
  via md:extra, parse-fail/id-mismatch refusals); folder.sync reconciles a dir:
  mints+rewrites files without id, retracts vanished md:path, writes back
  store-side notes, refuses unknown-entity/path-collision; converges on re-sync.
- evidence: `.venv\Scripts\python -m unittest discover -s tests` → 83 tests OK.
  Covers: lens laws over corpus, rename-keeps-id, delete → path retract without
  resurrection, forged id refusal, edit propagation, write-back.
- limits: flat dir only (no recursion); frontmatter is `key: value` subset
  (no YAML nesting/quoting); delete = projection op, entity persists.
