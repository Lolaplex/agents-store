"""SQLite connection with the shared schema and core vocabulary applied."""
from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = 6

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


def _migrate_v4(conn: sqlite3.Connection) -> None:
    """MORe SAIDs: more:said on every event entity, backfilled from the
    stored envelopes."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 4:
        return
    from .more.migrate import migrate_said
    migrate_said(conn)
    conn.execute("PRAGMA user_version = 4")



def _migrate_v5(conn: sqlite3.Connection) -> None:
    """WriteRefusal.reason ids: kebab-case -> snake_case. Idempotent one-shot.

    The refusal table is append-only at runtime; this migration briefly drops
    the update trigger, rewrites the known reason ids, and restores it.
    Already-snake rows and unknown reasons are left untouched.
    """
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 5:
        return
    renames = (
        ("parse-fail", "parse_fail"),
        ("tz-unsupported", "tz_unsupported"),
        ("uid-mismatch", "uid_mismatch"),
        ("status-map", "status_map"),
        ("id-mismatch", "id_mismatch"),
        ("mediator-conflict", "mediator_conflict"),
        ("unknown-entity", "unknown_entity"),
        ("path-collision", "path_collision"),
        ("derived-attr", "derived_attr"),
        ("unknown-attr", "unknown_attr"),
        ("no-grant", "no_grant"),
        ("no-capability-path", "no_capability_path"),
        ("out-of-projection", "out_of_projection"),
    )
    conn.execute("DROP TRIGGER IF EXISTS refusal_no_update")
    for old, new in renames:
        conn.execute("UPDATE refusal SET reason = ? WHERE reason = ?", (new, old))
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS refusal_no_update BEFORE UPDATE ON refusal "
        "BEGIN SELECT RAISE(ABORT, 'refusal is append-only'); END"
    )
    conn.execute("PRAGMA user_version = 5")


def _migrate_v6(conn: sqlite3.Connection) -> None:
    """Distributed ordering: datom.ord + tx origin/hlc + ord-keyed v_current.

    Backfills ord from tx so pre-v6 local history keeps its relative order;
    every 12-digit backfill key sorts below any minted hlc key.
    """
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 6:
        return
    dcols = {r[1] for r in conn.execute("PRAGMA table_info(datom)")}
    if "ord" not in dcols:
        conn.execute("ALTER TABLE datom ADD COLUMN ord TEXT NOT NULL DEFAULT ''")
    tcols = {r[1] for r in conn.execute("PRAGMA table_info(tx)")}
    if "hlc" not in tcols:
        conn.execute("ALTER TABLE tx ADD COLUMN hlc TEXT")
        conn.execute("ALTER TABLE tx ADD COLUMN origin_actor TEXT")
        conn.execute("ALTER TABLE tx ADD COLUMN origin_seq INTEGER")
    # backfill rewrites datom rows -> briefly drop the append-only update
    # trigger, restore it right after (same pattern as _migrate_v5)
    conn.execute("DROP TRIGGER IF EXISTS datom_no_update")
    try:
        conn.execute("UPDATE datom SET ord = printf('%012d', tx) WHERE ord = ''")
    finally:
        conn.execute(
            "CREATE TRIGGER IF NOT EXISTS datom_no_update BEFORE UPDATE ON datom "
            "BEGIN SELECT RAISE(ABORT, 'datom is append-only'); END"
        )
    conn.execute("DROP VIEW IF EXISTS v_current")
    conn.executescript(_sql("schema.sql"))
    conn.execute("PRAGMA user_version = 6")


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
    _migrate_v4(conn)
    _migrate_v5(conn)
    _migrate_v6(conn)
    if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return conn
