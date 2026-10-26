# 0015 more-store integration

- commit: e9f470868be05a5031217382bd0aa48583d09737
- task: T17
- claim: MORe events co-locate with the entity store; ADR `decision` kind + `latest_live_decision`; 114 MORe tests pass.
- evidence:
  ```bash
  git rev-parse HEAD   # e9f470868be05a5031217382bd0aa48583d09737
  python3 -m pip install -e . -q
  python3 -m unittest discover -s tests/more -q
  ```
  → `Ran 114 tests in 0.304s` / `OK`
- limits: No CLI/MCP surface (T18); subjects in MORe are still string ids, not necessarily store entities.
