"""Privileged physical redaction: the only path that deletes datom rows.

Append-only triggers block DELETE on datom/lineage. Redaction (GDPR /
accident) needs real removal, so this module drops the triggers inside a
guarded section, deletes, and always restores them. Audit comes first: a
refusal row records the scrub before anything is removed — the audit
itself is append-only.

Ordinary code must never call this; it is operator tooling, reached via
an explicit API/CLI, not through transact().
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .db import _sql

SCRUB_WRAPPER = "scrub"
_DELETE_TRIGGERS = ("datom_no_delete", "datom_no_update", "lineage_no_delete")


@dataclass(frozen=True)
class ScrubResult:
    entity: str
    datoms_removed: int
    lineage_removed: int


def _audit(conn: sqlite3.Connection, entity: str, reason: str) -> None:
    conn.execute(
        "INSERT INTO refusal (wrapper, entity, attr, reason, payload) VALUES (?, ?, NULL, ?, NULL)",
        (SCRUB_WRAPPER, entity, reason),
    )


def scrub_entity(conn: sqlite3.Connection, e: str, *, reason: str = "scrub") -> ScrubResult:
    """Physically remove an entity's datoms, lineage rows, and entity row."""
    _audit(conn, e, reason)
    for trig in _DELETE_TRIGGERS:
        conn.execute(f"DROP TRIGGER IF EXISTS {trig}")
    try:
        datoms = conn.execute("DELETE FROM datom WHERE e = ?", (e,)).rowcount
        lineage = conn.execute(
            "DELETE FROM lineage WHERE child = ? OR parent = ?", (e, e)
        ).rowcount
        conn.execute("DELETE FROM entity WHERE id = ?", (e,))
    finally:
        conn.executescript(_sql("schema.sql"))  # recreate triggers, IF NOT EXISTS
    return ScrubResult(entity=e, datoms_removed=datoms, lineage_removed=lineage)


def scrub_datoms(
    conn: sqlite3.Connection,
    *,
    a: str,
    v: str | None = None,
    reason: str = "scrub",
) -> int:
    """Remove all datoms carrying attr `a` (optionally restricted to value
    `v`) across entities — e.g. one leaked secret field everywhere."""
    _audit(conn, f"attr:{a}", reason)
    conn.execute("DROP TRIGGER IF EXISTS datom_no_delete")
    conn.execute("DROP TRIGGER IF EXISTS datom_no_update")
    try:
        if v is None:
            n = conn.execute("DELETE FROM datom WHERE a = ?", (a,)).rowcount
        else:
            n = conn.execute("DELETE FROM datom WHERE a = ? AND v = ?", (a, v)).rowcount
    finally:
        conn.executescript(_sql("schema.sql"))
    return n
