"""SQLite connection with the shared schema and core vocabulary applied."""
from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = 3

_HISTORY_TABLES = (
    "tx", "lineage", "certificate", "grant_", "refusal", "provenance",
)


def _sql(name: str) -> str:
    return resources.files("agents_store").joinpath(name).read_text(encoding="utf-8")


def _table_sql(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row[0] if row else None


def _migrate_v2(conn: sqlite3.Connection) -> None:
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    if ver >= 2:
        return

    cols = {r[1] for r in conn.execute("PRAGMA table_info(certificate)")}
    if "code_hash" not in cols:
        conn.execute("ALTER TABLE certificate ADD COLUMN code_hash TEXT NOT NULL DEFAULT ''")

    conn.executescript(_sql("schema.sql"))

    tx_sql = _table_sql(conn, "tx") or ""
    if "'retire'" not in tx_sql:
        conn.executescript("""
            PRAGMA foreign_keys=OFF;
            CREATE TABLE tx_new (
              id      INTEGER PRIMARY KEY AUTOINCREMENT,
              ts      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
              agent   TEXT,
              wrapper TEXT,
              op      TEXT NOT NULL CHECK (op IN ('assert','evolve','split','merge','correct','retire')),
              note    TEXT
            );
            INSERT INTO tx_new SELECT * FROM tx;
            DROP TABLE tx;
            ALTER TABLE tx_new RENAME TO tx;
            PRAGMA foreign_keys=ON;
        """)

    lin_sql = _table_sql(conn, "lineage") or ""
    if "'severs'" not in lin_sql:
        conn.executescript("""
            PRAGMA foreign_keys=OFF;
            CREATE TABLE lineage_new (
              child  TEXT    NOT NULL REFERENCES entity(id),
              parent TEXT    NOT NULL REFERENCES entity(id),
              kind   TEXT    NOT NULL CHECK (kind IN (
                'wasDerivedFrom','wasRevisionOf','alternateOf','specializationOf','severs')),
              tx     INTEGER NOT NULL REFERENCES tx(id),
              reason TEXT,
              PRIMARY KEY (child, parent, kind, tx)
            );
            INSERT INTO lineage_new SELECT * FROM lineage;
            DROP TABLE lineage;
            ALTER TABLE lineage_new RENAME TO lineage;
            PRAGMA foreign_keys=ON;
        """)

    conn.execute("PRAGMA user_version = 2")


def _migrate_v3(conn: sqlite3.Connection) -> None:
    """Queryable MORe references: more:subject as ref, more:subject_ptr,
    more:pinned_against; backfilled from the event envelopes."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 3:
        return
    from .more.migrate import migrate_queryable_refs
    migrate_queryable_refs(conn)
    conn.execute("PRAGMA user_version = 3")


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    """Open (or create) a store database. Idempotent: safe on an existing file."""
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(_sql("schema.sql"))
    conn.executescript(_sql("seed.sql"))
    conn.executescript(
        resources.files("agents_store.more").joinpath("schema.sql").read_text(encoding="utf-8")
    )
    _migrate_v2(conn)
    _migrate_v3(conn)
    if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return conn
