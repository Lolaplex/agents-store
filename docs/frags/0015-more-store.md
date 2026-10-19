# 0015 more-store integration

- commit: (see PR)
- task: T17
- claim: MORe events co-locate with the entity store; admitted events share id with entities; refusals use `more_refusal`; 110 MORe tests pass.
- evidence:
  ```bash
  git rev-parse HEAD
  python3 -m pip install -e . -q
  python3 -m unittest discover -s tests/more -v
  ```
  → `Ran 110 tests` / `OK`
- limits: No CLI/MCP surface (T18); subjects in MORe are still string ids, not necessarily store entities.
