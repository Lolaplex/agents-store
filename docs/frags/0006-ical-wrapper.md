# 0006 ical wrapper (T06)

- commit: <this commit>
- task: T06
- claim: entity <-> VEVENT/VTODO text. UID=entity id; when/end/title/status map;
  unmapped props preserved verbatim in ical:extra; tz-unsupported/status-map/
  parse-fail/uid-mismatch refusals. VEVENT for a task entity proposes status
  retraction (component-type change IS the signal — the lens laws caught this).
- evidence: `.venv\Scripts\python -m unittest discover -s tests` → 95 tests OK.
- limits: UTC Z only; folding is char-based not byte-strict; one component per
  repr; VEVENT can't see task attrs it strips (retraction is the declared
  semantic).
