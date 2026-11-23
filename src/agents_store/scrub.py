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

import json
import sqlite3
from dataclasses import dataclass

from .db import _schema_ddl
from .hlc import Hlc, HLC_GLOB

SCRUB_WRAPPER = "scrub"
_DELETE_TRIGGERS = (
    "datom_no_delete", "datom_no_update", "lineage_no_delete",
    "provenance_no_delete", "refusal_no_update",
)


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


def _mint_ord(conn: sqlite3.Connection) -> str:
    """Tombstone ordering key when the caller did not pin one: minted off
    the newest hlc in the log so it sorts above all recorded history."""
    clock = Hlc("local")
    row = conn.execute(
        "SELECT MAX(hlc) FROM tx WHERE hlc GLOB ?", (HLC_GLOB,)).fetchone()
    if row and row[0]:
        clock.observe(row[0])
    return clock.tick()


def _drop_purge_triggers(conn: sqlite3.Connection) -> None:
    for trig in _DELETE_TRIGGERS:
        conn.execute(f"DROP TRIGGER IF EXISTS {trig}")


def _restore_purge_triggers(conn: sqlite3.Connection) -> None:
    # single-statement executes: executescript would commit an open tx
    for trig in _DELETE_TRIGGERS:
        conn.execute(
            _schema_ddl(f"CREATE TRIGGER IF NOT EXISTS {trig}", "END;"))


def _prov_mentions(out_ref: str, in_refs: str, e: str) -> bool:
    try:
        if json.loads(out_ref).get("e") == e:
            return True
    except (ValueError, AttributeError):
        pass
    try:
        return any(
            isinstance(r, dict) and r.get("e") == e for r in json.loads(in_refs))
    except (ValueError, TypeError):
        return False


def _attr_purge(conn: sqlite3.Connection, spec: str) -> int:
    """Replay an attr-level scrub event ('a' or 'a=v') — the physical
    delete scrub_datoms performs, shared by remote replay."""
    a, eq, v = spec.partition("=")
    conn.execute("DROP TRIGGER IF EXISTS datom_no_delete")
    conn.execute("DROP TRIGGER IF EXISTS datom_no_update")
    try:
        if eq:
            return conn.execute(
                "DELETE FROM datom WHERE a = ? AND v = ?", (a, v)).rowcount
        return conn.execute("DELETE FROM datom WHERE a = ?", (a,)).rowcount
    finally:
        for trig in ("datom_no_delete", "datom_no_update"):
            conn.execute(
                _schema_ddl(f"CREATE TRIGGER IF NOT EXISTS {trig}", "END;"))


def _purge(conn: sqlite3.Connection, e: str) -> tuple[int, int]:
    """Delete e's datoms, lineage rows, provenance references and entity
    row, and redact refusal payloads for e; the append-only triggers are
    dropped and restored inside the caller's transaction."""
    _drop_purge_triggers(conn)
    try:
        d = conn.execute("DELETE FROM datom WHERE e = ?", (e,)).rowcount
        l = conn.execute(
            "DELETE FROM lineage WHERE child = ? OR parent = ?", (e, e)).rowcount
        conn.execute("DELETE FROM entity WHERE id = ?", (e,))
        prov_rows = conn.execute(
            "SELECT rowid, out_ref, in_refs FROM provenance").fetchall()
        for rid, out_ref, in_refs in prov_rows:
            if _prov_mentions(out_ref, in_refs, e):
                conn.execute("DELETE FROM provenance WHERE rowid = ?", (rid,))
        conn.execute("UPDATE refusal SET payload = NULL WHERE entity = ?", (e,))
    finally:
        _restore_purge_triggers(conn)
    return d, l


def scrub_entity(
    conn: sqlite3.Connection,
    e: str,
    *,
    reason: str = "scrub",
    ord_key: str = "",
) -> ScrubResult:
    """Physically remove an entity's datoms, lineage rows, and entity row;
    leaves a PII-free tombstone so sync propagates the deletion."""
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        if not ord_key:
            ord_key = _mint_ord(conn)
        already = conn.execute(
            "SELECT hlc FROM scrubbed WHERE e = ?", (e,)).fetchone()
        _audit(conn, e, reason)
        if already is None:
            tx_id = conn.execute(
                "INSERT INTO tx (op, agent, wrapper, note, hlc) VALUES ('scrub', ?, ?, ?, ?)",
                (SCRUB_WRAPPER, SCRUB_WRAPPER, e, ord_key),
            ).lastrowid
            conn.execute(
                "INSERT INTO scrubbed (e, hlc) VALUES (?, ?)", (e, ord_key))
        else:
            # repeat scrub (e.g. remote tombstone replayed after local one):
            # still delete anything that slipped in since, keep the LATEST
            # hlc (a later cutoff covers more late arrivals)
            cutoff = max(already[0], ord_key)
            if cutoff != already[0]:
                _update_scrubbed(conn, e, cutoff)
                # a stricter cutoff is a new tombstone event — it must
                # reach the peers too, or they keep the weaker one
                tx_id = conn.execute(
                    "INSERT INTO tx (op, agent, wrapper, note, hlc)"
                    " VALUES ('scrub', ?, ?, ?, ?)",
                    (SCRUB_WRAPPER, SCRUB_WRAPPER, e, cutoff)).lastrowid
            else:
                tx_row = conn.execute(
                    "SELECT id FROM tx WHERE op = 'scrub' AND note = ? ORDER BY id LIMIT 1",
                    (e,)).fetchone()
                tx_id = tx_row[0] if tx_row else 0
        d, l = _purge(conn, e)
        if own:
            conn.execute("COMMIT")
    except BaseException:
        if own:
            conn.execute("ROLLBACK")
        raise
    return ScrubResult(entity=e, tx=tx_id, datoms_removed=d,
                       lineage_removed=l)


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
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        _audit(conn, f"attr:{a}", reason)
        spec = a if v is None else f"{a}={v}"
        n = _attr_purge(conn, spec)
        if n:
            # propagate the attr-level delete as a scrub event: peers
            # replay the same delete and the origined tx dedupes the echo
            conn.execute(
                "INSERT INTO tx (op, agent, wrapper, note, hlc)"
                " VALUES ('scrub', ?, ?, ?, ?)",
                (SCRUB_WRAPPER, SCRUB_WRAPPER, f"attr:{spec}", _mint_ord(conn)))
        if own:
            conn.execute("COMMIT")
    except BaseException:
        if own:
            conn.execute("ROLLBACK")
        raise
    return n
