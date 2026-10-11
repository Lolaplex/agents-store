# 0007 render capabilities + mediator + pane (T08/T09/T10)

- commit: <this commit>
- task: T08, T09, T10
- claim: two render capabilities (markdown->html stdlib subset with XSS-safe
  escaping; entity->html card with kinds/derived/lineage); mediator composes
  capability paths (BFS), writes mediator+provenance rows with exactness;
  pane gates targets by substantive attrs and returns named refusals.
- evidence: `.venv\Scripts\python -m unittest discover -s tests` → 120 tests OK.
  Covers: path search direct/2-hop/none, exact vs contained, provenance rows,
  derived `end` shown in html but never written into ical, same-id all reprs.
- limits: exactness = all-lens vs any-render (no finer loss measure);
  mediator rows are written per call (recompute), no caching; pane target
  gates are hardcoded REPR_GATES.
