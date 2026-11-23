"""SQLite connection with the shared schema and core vocabulary applied."""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = 7

_HISTORY_TABLES = (
    "tx", "lineage", "certificate", "grant_", "refusal", "provenance",
)


def _sql(name: str) -> str:
    return resources.files("agents_store").joinpath(name).read_text(encoding="utf-8")


def _schema_ddl(marker: str, terminator: str = ";") -> str:
    """One statement out of schema.sql by its opening text — lets migrations
    recreate a trigger or view without executescript (which would commit an
    open transaction)."""
    m = re.search(
        re.escape(marker) + r".*?" + re.escape(terminator),
        _sql("schema.sql"), re.S)
    if m is None:
        raise KeyError(f"schema.sql: no statement starting {marker!r}")
    return m.group(0)


def _table_sql(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row[0] if row else None


@contextmanager
def _migration_tx(conn: sqlite3.Connection):
    """One migration step: BEGIN IMMEDIATE..COMMIT, rolled back whole on
    error. FKs go off first (only outside a transaction can the pragma
    change) so table rebuilds may drop/rename parent tables. Joins an
    already-open transaction instead of nesting."""
    own = not conn.in_transaction
    if own:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        if own:
            conn.execute("ROLLBACK")
            conn.execute("PRAGMA foreign_keys = ON")
        raise
    else:
        if own:
            conn.execute("COMMIT")
            conn.execute("PRAGMA foreign_keys = ON")


def _migrate_v2(conn: sqlite3.Connection) -> None:
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    if ver >= 2:
        return

    with _migration_tx(conn):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(certificate)")}
        if cols and "code_hash" not in cols:
            conn.execute("ALTER TABLE certificate ADD COLUMN code_hash TEXT NOT NULL DEFAULT ''")

        tx_sql = _table_sql(conn, "tx")
        if tx_sql and "'retire'" not in tx_sql:
            # explicit column list: _migrate_v6_pre may already have added
            # origin cols, which must survive the rebuild
            tcols = {r[1] for r in conn.execute("PRAGMA table_info(tx)")}
            origin = {"hlc", "origin_actor", "origin_seq"} <= tcols
            conn.execute("DROP TABLE IF EXISTS tx_new")
            conn.execute(f"""
                CREATE TABLE tx_new (
                  id      INTEGER PRIMARY KEY AUTOINCREMENT,
                  ts      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                  agent   TEXT,
                  wrapper TEXT,
                  op      TEXT NOT NULL CHECK (op IN ('assert','evolve','split','merge','correct','retire')),
                  note    TEXT
                  {", hlc TEXT, origin_actor TEXT, origin_seq INTEGER" if origin else ""}
                )""")
            conn.execute(
                "INSERT INTO tx_new (id, ts, agent, wrapper, op, note"
                f"{', hlc, origin_actor, origin_seq' if origin else ''})"
                " SELECT id, ts, agent, wrapper, op, note"
                f"{', hlc, origin_actor, origin_seq' if origin else ''} FROM tx")
            conn.execute("DROP TABLE tx")
            conn.execute("ALTER TABLE tx_new RENAME TO tx")

        lin_sql = _table_sql(conn, "lineage")
        if lin_sql and "'severs'" not in lin_sql:
            conn.execute("DROP TABLE IF EXISTS lineage_new")
            conn.execute("""
                CREATE TABLE lineage_new (
                  child  TEXT    NOT NULL REFERENCES entity(id),
                  parent TEXT    NOT NULL REFERENCES entity(id),
                  kind   TEXT    NOT NULL CHECK (kind IN (
                    'wasDerivedFrom','wasRevisionOf','alternateOf','specializationOf','severs')),
                  tx     INTEGER NOT NULL REFERENCES tx(id),
                  reason TEXT,
                  PRIMARY KEY (child, parent, kind, tx)
                )""")
            conn.execute(
                "INSERT INTO lineage_new (child, parent, kind, tx, reason)"
                " SELECT child, parent, kind, tx, reason FROM lineage")
            conn.execute("DROP TABLE lineage")
            conn.execute("ALTER TABLE lineage_new RENAME TO lineage")

        conn.execute("PRAGMA user_version = 2")


def _migrate_v3(conn: sqlite3.Connection) -> None:
    """Queryable MORe references: more:subject as ref, more:subject_ptr,
    more:pinned_against; backfilled from the event envelopes."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 3:
        return
    from .more.migrate import migrate_queryable_refs
    with _migration_tx(conn):
        migrate_queryable_refs(conn)
        conn.execute("PRAGMA user_version = 3")


def _migrate_v4(conn: sqlite3.Connection) -> None:
    """MORe SAIDs: more:said on every event entity, backfilled from the
    stored envelopes."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 4:
        return
    from .more.migrate import migrate_said
    with _migration_tx(conn):
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
    with _migration_tx(conn):
        conn.execute("DROP TRIGGER IF EXISTS refusal_no_update")
        try:
            for old, new in renames:
                conn.execute("UPDATE refusal SET reason = ? WHERE reason = ?", (new, old))
        finally:
            conn.execute(
                _schema_ddl("CREATE TRIGGER IF NOT EXISTS refusal_no_update", "END;"))
        conn.execute("PRAGMA user_version = 5")


def _migrate_v6_pre(conn: sqlite3.Connection) -> None:
    """Column ALTERs that must exist BEFORE anything else runs: transact,
    ingest and the v3/v4 Store backfills already read datom.ord / tx.hlc,
    and schema.sql creates indexes on them — on a pre-v6 database the
    columns have to be added first either way."""
    dcols = {r[1] for r in conn.execute("PRAGMA table_info(datom)")}
    if dcols and "ord" not in dcols:
        conn.execute("ALTER TABLE datom ADD COLUMN ord TEXT NOT NULL DEFAULT ''")
    tcols = {r[1] for r in conn.execute("PRAGMA table_info(tx)")}
    if tcols and "hlc" not in tcols:
        conn.execute("ALTER TABLE tx ADD COLUMN hlc TEXT")
        conn.execute("ALTER TABLE tx ADD COLUMN origin_actor TEXT")
        conn.execute("ALTER TABLE tx ADD COLUMN origin_seq INTEGER")


def _migrate_v6(conn: sqlite3.Connection) -> None:
    """Distributed ordering: datom.ord + tx origin/hlc + ord-keyed v_current.

    Backfills ord from tx so pre-v6 local history keeps its relative order;
    every 12-digit backfill key sorts below any minted hlc key.
    """
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 6:
        return
    with _migration_tx(conn):
        _migrate_v6_pre(conn)
        # backfill rewrites datom rows -> briefly drop the append-only update
        # trigger, restore it right after (same pattern as _migrate_v5)
        conn.execute("DROP TRIGGER IF EXISTS datom_no_update")
        try:
            conn.execute("UPDATE datom SET ord = printf('%012d', tx) WHERE ord = ''")
        finally:
            conn.execute(
                _schema_ddl("CREATE TRIGGER IF NOT EXISTS datom_no_update", "END;"))
        conn.execute("DROP VIEW IF EXISTS v_current")
        conn.execute(_schema_ddl("CREATE VIEW IF NOT EXISTS v_current"))
        conn.execute("PRAGMA user_version = 6")


def _migrate_v7(conn: sqlite3.Connection) -> None:
    """op='scrub' + attr.syncable + meta/scrubbed tables (frontier review).

    The tx CHECK list changes -> table rebuild (same pattern as _migrate_v2).
    """
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 7:
        return
    with _migration_tx(conn):
        _migrate_v6_pre(conn)  # guarantee origin cols for the SELECT below
        acols = {r[1] for r in conn.execute("PRAGMA table_info(attr)")}
        if acols and "syncable" not in acols:
            try:
                conn.execute(
                    "ALTER TABLE attr ADD COLUMN syncable INTEGER NOT NULL DEFAULT 1"
                    " CHECK (syncable IN (0,1))")
            except sqlite3.OperationalError:
                # sqlite < 3.37 cannot express CHECK in ADD COLUMN
                conn.execute(
                    "ALTER TABLE attr ADD COLUMN syncable INTEGER NOT NULL DEFAULT 1")
        tx_sql = _table_sql(conn, "tx")
        if tx_sql and "'scrub'" not in tx_sql:
            conn.execute("DROP TRIGGER IF EXISTS tx_no_update")
            conn.execute("DROP TRIGGER IF EXISTS tx_no_delete")
            conn.execute("DROP TABLE IF EXISTS tx_new")
            conn.execute("""
                CREATE TABLE tx_new (
                  id      INTEGER PRIMARY KEY AUTOINCREMENT,
                  ts      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                  agent   TEXT,
                  wrapper TEXT,
                  op      TEXT NOT NULL CHECK (op IN ('assert','evolve','split','merge','correct','retire','scrub')),
                  note    TEXT,
                  hlc           TEXT,
                  origin_actor  TEXT,
                  origin_seq    INTEGER
                )""")
            conn.execute(
                "INSERT INTO tx_new (id, ts, agent, wrapper, op, note,"
                " hlc, origin_actor, origin_seq)"
                " SELECT id, ts, agent, wrapper, op, note,"
                " hlc, origin_actor, origin_seq FROM tx")
            conn.execute("DROP TABLE tx")
            conn.execute("ALTER TABLE tx_new RENAME TO tx")
        conn.execute("PRAGMA user_version = 7")


def connect(
    path: str | Path = ":memory:",
    *,
    check_same_thread: bool = True,
) -> sqlite3.Connection:
    """Open (or create) a store database. Idempotent: safe on an existing file.

    check_same_thread=False is for owners that serialize access across
    threads themselves (e.g. the serve sync worker holds one conn behind
    a lock shared by the SSE reader and the drain tick).
    """
    conn = sqlite3.connect(
        str(path), isolation_level=None, check_same_thread=check_same_thread)
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    if _table_sql(conn, "tx") is not None:
        # existing history: additive column ALTERs first (the v3/v4
        # backfills and every write path already read datom.ord / tx.hlc),
        # then versioned migrations in order — each atomic — and only then
        # schema.sql's unique indexes + v_current: v6 backfills ord before
        # ux_datom_eav_ord can see ''-dupes.
        with _migration_tx(conn):
            _migrate_v6_pre(conn)
        for migrate in (_migrate_v2, _migrate_v3, _migrate_v4,
                        _migrate_v5, _migrate_v6, _migrate_v7):
            migrate(conn)
    conn.executescript(_sql("schema.sql"))
    conn.executescript(_sql("seed.sql"))
    conn.executescript(
        resources.files("agents_store.more").joinpath("schema.sql").read_text(encoding="utf-8")
    )
    if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return conn
