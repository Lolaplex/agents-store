"""SQLite connection with the shared schema and core vocabulary applied."""
from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = 1


def _sql(name: str) -> str:
    return resources.files("agents_store").joinpath(name).read_text(encoding="utf-8")


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    """Open (or create) a store database. Idempotent: safe on an existing file."""
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(_sql("schema.sql"))
    conn.executescript(_sql("seed.sql"))
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return conn
