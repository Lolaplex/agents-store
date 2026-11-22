"""Privileged physical redaction: the only path that deletes datom rows.

Append-only triggers block DELETE on datom/lineage. Redaction (GDPR /
accident) needs real removal, so this module drops the triggers inside a
guarded section, deletes, and always restores them. Audit comes first: a
refusal row records the scrub before anything is removed — the audit
itself is append-only.

A scrub is also a distributed event: it writes one PII-free
tx(op='scrub', hlc=T, note=e) plus a scrubbed(e,T) tombstone. Synced
peers ingest the tombstone and replay the same local scrub, and any
datoms for e arriving later with ord <= T are dropped — an offline peer
cannot resurrect scrubbed content.

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
    tx: int                 # tombstone tx id (existing tx on repeat scrub)
    datoms_removed: int
    lineage_removed: int


def _audit(conn: sqlite3.Connection, entity: str, reason: str) -> None:
    conn.execute(
        "INSERT INTO refusal (wrapper, entity, attr, reason, payload) VALUES (?, ?, NULL, ?, NULL)",
        (SCRUB_WRAPPER, entity, reason),
    )


def scrub_entity(
    conn: sqlite3.Connection,
    e: str,
    *,
    reason: str = "scrub",
    ord_key: str = "",
) -> ScrubResult:
    """Physically remove an entity's datoms, lineage rows, and entity row;
    leaves a PII-free tombstone so sync propagates the deletion."""
    already = conn.execute(
        "SELECT hlc FROM scrubbed WHERE e = ?", (e,)).fetchone()
    if already is not None:
        # repeat scrub (e.g. remote tombstone replayed after local one):
        # still delete anything that slipped in since, keep the FIRST hlc
        # (stricter cutoff wins — an earlier scrub covers more arrivals)
        cutoff = min(already[0], ord_key) if ord_key else already[0]
        if cutoff != already[0]:
            _update_scrubbed(conn, e, cutoff)
        _audit(conn, e, reason)
        for trig in _DELETE_TRIGGERS:
            conn.execute(f"DROP TRIGGER IF EXISTS {trig}")
        try:
            d = conn.execute("DELETE FROM datom WHERE e = ?", (e,)).rowcount
            l = conn.execute(
                "DELETE FROM lineage WHERE child = ? OR parent = ?", (e, e)).rowcount
            conn.execute("DELETE FROM entity WHERE id = ?", (e,))
        finally:
            conn.executescript(_sql("schema.sql"))
        tx_row = conn.execute(
            "SELECT id FROM tx WHERE op = 'scrub' AND note = ? ORDER BY id LIMIT 1",
            (e,)).fetchone()
        return ScrubResult(entity=e, tx=tx_row[0] if tx_row else 0,
                           datoms_removed=d, lineage_removed=l)

    _audit(conn, e, reason)
    tx_id = conn.execute(
        "INSERT INTO tx (op, agent, wrapper, note, hlc) VALUES ('scrub', ?, ?, ?, ?)",
        (SCRUB_WRAPPER, SCRUB_WRAPPER, e, ord_key),
    ).lastrowid
    conn.execute("INSERT OR IGNORE INTO scrubbed (e, hlc) VALUES (?, ?)", (e, ord_key))
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
    return ScrubResult(entity=e, tx=tx_id, datoms_removed=datoms,
                       lineage_removed=lineage)


def _update_scrubbed(conn: sqlite3.Connection, e: str, hlc: str) -> None:
    """scrubbed has no append-only trigger; the stricter cutoff is stored."""
    conn.execute("UPDATE scrubbed SET hlc = ? WHERE e = ?", (hlc, e))


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
