-- agents-store schema v1. Idempotent: every statement is IF NOT EXISTS.
-- Shared contract: changes require a contract-change note (docs/tasks/README.md).

CREATE TABLE IF NOT EXISTS entity (
  id         TEXT PRIMARY KEY,
  created_tx INTEGER NOT NULL REFERENCES tx(id)
);

CREATE TABLE IF NOT EXISTS attr (
  name        TEXT PRIMARY KEY,
  value_type  TEXT NOT NULL CHECK (value_type IN ('text','instant','int','bool','ref','json')),
  cardinality TEXT NOT NULL CHECK (cardinality IN ('one','many')),
  doc         TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tx (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  ts      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  agent   TEXT,
  wrapper TEXT,
  op      TEXT NOT NULL CHECK (op IN ('assert','evolve','split','merge','correct')),
  note    TEXT
);

CREATE TABLE IF NOT EXISTS datom (
  e     TEXT    NOT NULL REFERENCES entity(id),
  a     TEXT    NOT NULL REFERENCES attr(name),
  v     TEXT    NOT NULL,
  tx    INTEGER NOT NULL REFERENCES tx(id),
  added INTEGER NOT NULL CHECK (added IN (0,1)),
  PRIMARY KEY (e, a, v, tx)
);
CREATE INDEX IF NOT EXISTS idx_datom_av ON datom(a, v);
CREATE INDEX IF NOT EXISTS idx_datom_tx ON datom(tx);

CREATE TRIGGER IF NOT EXISTS datom_no_update BEFORE UPDATE ON datom
BEGIN SELECT RAISE(ABORT, 'datom is append-only'); END;
CREATE TRIGGER IF NOT EXISTS datom_no_delete BEFORE DELETE ON datom
BEGIN SELECT RAISE(ABORT, 'datom is append-only'); END;

CREATE VIEW IF NOT EXISTS v_current AS
SELECT d.e, d.a, d.v, MAX(d.tx) AS tx
FROM datom d
WHERE d.added = 1 AND NOT EXISTS (
  SELECT 1 FROM datom r
  WHERE r.e = d.e AND r.a = d.a AND r.v = d.v AND r.added = 0 AND r.tx > d.tx)
GROUP BY d.e, d.a, d.v;

CREATE TABLE IF NOT EXISTS lineage (
  child  TEXT    NOT NULL REFERENCES entity(id),
  parent TEXT    NOT NULL REFERENCES entity(id),
  kind   TEXT    NOT NULL CHECK (kind IN ('wasDerivedFrom','wasRevisionOf','alternateOf','specializationOf')),
  tx     INTEGER NOT NULL REFERENCES tx(id),
  reason TEXT,
  PRIMARY KEY (child, parent, kind, tx)
);

CREATE TABLE IF NOT EXISTS kind (
  name        TEXT PRIMARY KEY,
  required    TEXT NOT NULL,              -- JSON array of attr names
  optional    TEXT NOT NULL DEFAULT '[]', -- JSON array of attr names
  derivations TEXT NOT NULL DEFAULT '[]'  -- JSON array of {attr, from, rule}
);

CREATE TABLE IF NOT EXISTS certificate (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  tier    TEXT NOT NULL CHECK (tier IN ('witness','proof')),
  subject TEXT NOT NULL,                  -- 'wrapper:md', 'corr:12', 'capability:md-html'
  ref     TEXT NOT NULL,                  -- test id, Lean theorem name, ...
  corpus  TEXT,                           -- e.g. 'seed=1,n=500'
  result  TEXT NOT NULL CHECK (result IN ('pass','fail')),
  ts      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS wrapper (
  id        TEXT PRIMARY KEY,
  namespace TEXT NOT NULL,
  impl_ref  TEXT NOT NULL,
  doc       TEXT NOT NULL DEFAULT ''
);

-- Writability grant: wrapper may write attr once a passing certificate backs it.
CREATE TABLE IF NOT EXISTS grant_ (
  wrapper        TEXT    NOT NULL REFERENCES wrapper(id),
  attr           TEXT    NOT NULL REFERENCES attr(name),
  certificate_id INTEGER NOT NULL REFERENCES certificate(id),
  PRIMARY KEY (wrapper, attr, certificate_id)
);

CREATE TABLE IF NOT EXISTS correspondence (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  a_from         TEXT NOT NULL REFERENCES attr(name),
  a_to           TEXT NOT NULL REFERENCES attr(name),
  kind           TEXT NOT NULL CHECK (kind IN ('equal','refines','derivable')),
  lens_ref       TEXT,
  status         TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','witnessed','proven')),
  certificate_id INTEGER REFERENCES certificate(id)
);

CREATE TABLE IF NOT EXISTS capability (
  id             TEXT PRIMARY KEY,
  in_kind        TEXT NOT NULL,
  out_kind       TEXT NOT NULL,
  mode           TEXT NOT NULL CHECK (mode IN ('render','lens')),
  impl_ref       TEXT NOT NULL,
  certificate_id INTEGER REFERENCES certificate(id)
);

CREATE TABLE IF NOT EXISTS mediator (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  source         TEXT NOT NULL,
  target         TEXT NOT NULL,
  path           TEXT NOT NULL,             -- JSON array of capability/correspondence ids
  exactness      TEXT NOT NULL CHECK (exactness IN ('exact','contained')),
  certificate_id INTEGER REFERENCES certificate(id)
);

CREATE TABLE IF NOT EXISTS provenance (
  out_ref     TEXT NOT NULL,
  in_refs     TEXT NOT NULL,                -- JSON array
  mediator_id INTEGER REFERENCES mediator(id),
  tx          INTEGER REFERENCES tx(id)
);

CREATE TABLE IF NOT EXISTS refusal (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  ts      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  wrapper TEXT NOT NULL,
  entity  TEXT,
  attr    TEXT,
  reason  TEXT NOT NULL,
  payload TEXT
);
