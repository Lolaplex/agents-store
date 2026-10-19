-- MORe kernel event log. Same conventions as agents-store v0 schema.sql:
-- idempotent DDL, append-only via triggers, refusals in more_refusal.

CREATE TABLE IF NOT EXISTS event (
  seq      INTEGER PRIMARY KEY AUTOINCREMENT,   -- log order
  id       TEXT    NOT NULL UNIQUE,             -- minted ULID, never reused
  type     TEXT    NOT NULL CHECK (type IN ('decision','verification','inclusion','supersession','overrule','move')),
  actor    TEXT    NOT NULL,
  at       TEXT    NOT NULL,
  envelope TEXT    NOT NULL,                    -- canonical JSON (events.Event.canonical)
  prev     TEXT    NOT NULL,                    -- digest of the previous event ('' for the first)
  digest   TEXT    NOT NULL,                    -- sha256(prev || id || envelope)
  ts       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS event_subject (
  event_id TEXT NOT NULL REFERENCES event(id),
  subject  TEXT NOT NULL,
  PRIMARY KEY (event_id, subject)
);
CREATE INDEX IF NOT EXISTS idx_event_subject ON event_subject(subject);

CREATE TRIGGER IF NOT EXISTS event_no_update BEFORE UPDATE ON event
BEGIN SELECT RAISE(ABORT, 'event is append-only'); END;
CREATE TRIGGER IF NOT EXISTS event_no_delete BEFORE DELETE ON event
BEGIN SELECT RAISE(ABORT, 'event is append-only'); END;
CREATE TRIGGER IF NOT EXISTS event_subject_no_update BEFORE UPDATE ON event_subject
BEGIN SELECT RAISE(ABORT, 'event_subject is append-only'); END;
CREATE TRIGGER IF NOT EXISTS event_subject_no_delete BEFORE DELETE ON event_subject
BEGIN SELECT RAISE(ABORT, 'event_subject is append-only'); END;

CREATE TABLE IF NOT EXISTS more_refusal (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  ts        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  violation TEXT NOT NULL,
  detail    TEXT NOT NULL,
  payload   TEXT NOT NULL                       -- the refused envelope, for the record
);
