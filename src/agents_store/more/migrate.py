"""Backfills for MORe datoms: queryable references (schema v3) and SAIDs (v4).

v3 (migrate_queryable_refs):

Databases written before v3 hold every subject as a text more:subject datom
and pinned_against only inside the event envelope. migrate_queryable_refs():

1. vocabulary: more:subject becomes value_type 'ref'; more:subject_ptr and
   more:pinned_against are added; the more-event and decision kinds list
   them as optional;
2. data: for every event that has an entity, re-derive the subject and pin
   datoms from the immutable envelope and transact only the difference
   (retract a more:subject value that is not a store entity, assert it as
   more:subject_ptr, assert missing refs and pins), in one 'evolve' tx.

Idempotent: a second run finds no difference and writes no tx. It can be
re-run later, e.g. after a pointer target became a store entity.

v4 (migrate_said): adds the more:said attr (and the kind optionals) and
asserts more:said, computed from the stored envelope and the event name, on
every event entity that has none, in one 'evolve' tx. An existing more:said
that differs from the recomputed SAID is not overwritten: the migration
raises SaidMismatch (a name is never rebound to other content). Idempotent.
"""
from __future__ import annotations

import json
import sqlite3

from agents_store.contracts import Change
from agents_store.grant import INTERNAL_WRAPPER
from agents_store.store import Store

from .events import Event
from .said import event_said
from .store_bridge import pinned_changes, subject_changes

NOTE = "more:migrate queryable-refs (v3)"
NOTE_SAID = "more:migrate said (v4)"

_ATTRS = (
    ("more:subject_ptr", "text", "many",
     "MORe subject that is not a store entity: pointer target id (artifact id or external locator), never a copy"),
    ("more:pinned_against", "text", "many",
     "MORe envelope pinned_against, verbatim: artifact@version, commit or baseline"),
)
_SUBJECT_DOC = "MORe subject that is a store entity (entity id)"
_KIND_OPTIONAL = {
    "more-event": ("more:subject_ptr", "more:pinned_against"),
    "decision": ("more:subject_ptr", "more:pinned_against"),
}
_MANAGED = ("more:subject", "more:subject_ptr", "more:pinned_against")


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _vocabulary(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO attr (name, value_type, cardinality, doc) VALUES (?, ?, ?, ?)",
        _ATTRS)
    conn.execute(
        "UPDATE attr SET value_type = 'ref', doc = ? "
        "WHERE name = 'more:subject' AND value_type <> 'ref'", (_SUBJECT_DOC,))
    for kind, extra in _KIND_OPTIONAL.items():
        row = conn.execute("SELECT optional FROM kind WHERE name = ?", (kind,)).fetchone()
        if row is None:
            continue
        opt = json.loads(row[0])
        missing = [a for a in extra if a not in opt]
        if missing:
            conn.execute("UPDATE kind SET optional = ? WHERE name = ?",
                         (json.dumps(opt + missing), kind))


def planned_changes(store: Store) -> list[Change]:
    """The changes that bring every materialized event's subject and pin
    datoms in line with its envelope. Empty when already migrated."""
    out: list[Change] = []
    rows = store.conn.execute(
        "SELECT e.id, e.envelope FROM event e JOIN entity n ON n.id = e.id ORDER BY e.seq"
    ).fetchall()
    for eid, envelope in rows:
        ev = Event.from_envelope(json.loads(envelope))
        want = {(c.a, c.v) for c in subject_changes(store, ev, eid) + pinned_changes(ev, eid)}
        view = store.view(eid)
        have = {(a, v) for a in _MANAGED for v in view.get(a, ())}
        out += [Change(eid, a, v, added=False) for a, v in sorted(have - want)]
        out += [Change(eid, a, v) for a, v in sorted(want - have)]
    return out


def migrate_queryable_refs(conn: sqlite3.Connection) -> int | None:
    """Run the v3 vocabulary change and backfill. Returns the backfill tx id,
    or None when nothing had to change."""
    if not (_has_table(conn, "entity") and _has_table(conn, "event")):
        return None
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        _vocabulary(conn)
        store = Store(conn)
        changes = planned_changes(store)
        tx = None
        if changes:
            result = store.transact(changes, wrapper=INTERNAL_WRAPPER, op="evolve", note=NOTE)
            if result.refusals:
                raise RuntimeError(f"migrate_queryable_refs: refused {result.refusals}")
            tx = result.tx
        if own:
            conn.execute("COMMIT")
        return tx
    except BaseException:
        if own:
            conn.execute("ROLLBACK")
        raise


class SaidMismatch(RuntimeError):
    """A stored more:said differs from the SAID recomputed from the envelope."""


_SAID_ATTR = ("more:said", "text", "one",
              "KERI/CESR Blake3-256 SAID of the event content, bound to the event name (E + 43 chars)")


def _said_vocabulary(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO attr (name, value_type, cardinality, doc) VALUES (?, ?, ?, ?)",
        _SAID_ATTR)
    for kind in ("more-event", "decision"):
        row = conn.execute("SELECT optional FROM kind WHERE name = ?", (kind,)).fetchone()
        if row is None:
            continue
        opt = json.loads(row[0])
        if "more:said" not in opt:
            conn.execute("UPDATE kind SET optional = ? WHERE name = ?",
                         (json.dumps(opt + ["more:said"]), kind))


def planned_said_changes(store: Store) -> list[Change]:
    """more:said for every materialized event that has none. Raises
    SaidMismatch when a stored SAID does not match its envelope."""
    out: list[Change] = []
    rows = store.conn.execute(
        "SELECT e.id, e.envelope FROM event e JOIN entity n ON n.id = e.id ORDER BY e.seq"
    ).fetchall()
    for eid, envelope in rows:
        want = event_said(Event.from_envelope(json.loads(envelope)), eid)
        have = store.view(eid).get("more:said")
        if have is None:
            out.append(Change(eid, "more:said", want))
        elif have != want:
            raise SaidMismatch(f"{eid}: stored more:said {have} != {want}")
    return out


def migrate_said(conn: sqlite3.Connection) -> int | None:
    """Run the v4 vocabulary change and SAID backfill. Returns the backfill
    tx id, or None when nothing had to change."""
    if not (_has_table(conn, "entity") and _has_table(conn, "event")):
        return None
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        _said_vocabulary(conn)
        store = Store(conn)
        changes = planned_said_changes(store)
        tx = None
        if changes:
            result = store.transact(changes, wrapper=INTERNAL_WRAPPER, op="evolve", note=NOTE_SAID)
            if result.refusals:
                raise RuntimeError(f"migrate_said: refused {result.refusals}")
            tx = result.tx
        if own:
            conn.execute("COMMIT")
        return tx
    except BaseException:
        if own:
            conn.execute("ROLLBACK")
        raise
