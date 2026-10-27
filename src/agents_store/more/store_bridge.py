"""Materialize admitted MORe events as store entities in the same SQLite file.

All datom writes go through Store.transact (the store's only write API), in
one tx per event: the entity row, the more:* datoms, the ADR projection for
decisions and the more:pin version pin all land under that tx.

Queryable references (see docs/more/README.md, "Queryable subjects and pins"):
more:subject is a ref to a subject that is a store entity, more:subject_ptr
keeps every other subject as a pointer target id, and more:pinned_against
holds the envelope's pins verbatim.

Lineage edges are not datoms; they are appended under the same tx via
lineage.record_edge. The caller (EventLog.append) owns the surrounding SQLite transaction, so the
event row, its datoms and its edges commit or roll back together.
"""
from __future__ import annotations

import sqlite3

from agents_store.contracts import Change, WriteRefusal
from agents_store.grant import INTERNAL_WRAPPER
from agents_store.lineage import record_edge
from agents_store.store import Store

from .events import Event
from .numbers import number_issues
from .said import event_said


class StoreWriteRefused(RuntimeError):
    """transact refused part of an event's datoms. The event must not be
    admitted half-materialized, so the caller rolls the whole append back."""

    def __init__(self, refusals: tuple[WriteRefusal, ...]):
        self.refusals = refusals
        super().__init__("; ".join(f"{r.a}: {r.reason}" for r in refusals))


def assert_canonical_numbers(event: Event) -> None:
    """Refuse an event that carries a non-canonical number (numbers.py, C4):
    a binary float, NaN, ±Infinity, or an integer beyond ±(2**53 - 1).
    Runs on the append path before anything is hashed or written. Each
    refusal has a typed reason (numbers.REASONS), the envelope field in `a`
    and the JSON path in `payload`."""
    issues = number_issues(event.envelope())
    if issues:
        raise StoreWriteRefused(tuple(
            WriteRefusal(INTERNAL_WRAPPER, i.reason, a=i.path.split(".")[1].split("[")[0],
                    payload=i.path)
            for i in issues))


def _store_backed(conn: sqlite3.Connection) -> bool:
    # schema probe; the store has no read API for "is this a store database"
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='entity'"
    ).fetchone()
    return row is not None


def subject_changes(store: Store, event: Event, e: str | None = None) -> list[Change]:
    """Subjects as queryable datoms. A subject that is a store entity becomes
    a ref (more:subject); any other subject stays a pointer target id
    (more:subject_ptr). No stub entity is minted for an external artifact:
    the kernel holds a pointer to it, never a copy (core_primitives.artifact,
    core_primitives.pointer)."""
    out: list[Change] = []
    for s in dict.fromkeys(event.subjects):
        a = "more:subject" if store.exists(s) else "more:subject_ptr"
        out.append(Change(e, a, s))
    return out


def pinned_changes(event: Event, e: str | None = None) -> list[Change]:
    """pinned_against as datoms, verbatim (artifact@version, commit or
    baseline; same target@version shape as more:pin)."""
    return [Change(e, "more:pinned_against", p) for p in dict.fromkeys(event.pinned_against)]


def said_changes(eid: str, event: Event, e: str | None = None) -> list[Change]:
    """The name -> SAID binding: more:said on the event entity (said.py)."""
    return [Change(e, "more:said", event_said(event, eid))]


def event_changes(event: Event, store: Store | None = None) -> list[Change]:
    """The datoms of one event, all on the entity this tx creates (e=None).
    Without a store every subject is treated as a pointer (more:subject_ptr)."""
    body = dict(event.body or {})
    changes = [
        Change(None, "more:type", event.type),
        Change(None, "more:actor", event.actor),
        Change(None, "more:at", event.at),
        Change(None, "more:body", body),
    ]
    if store is not None:
        changes += subject_changes(store, event)
    else:
        changes += [Change(None, "more:subject_ptr", s) for s in dict.fromkeys(event.subjects)]
    changes += pinned_changes(event)
    if event.type == "decision":
        changes += _adr_changes(body)
    return changes


def _adr_changes(body: dict) -> list[Change]:
    """Project ADR fields onto the decision artifact kind (title, body, more:topic)."""
    out: list[Change] = []
    if "title" in body:
        out.append(Change(None, "title", str(body["title"])))
    if body.get("body") is not None:
        out.append(Change(None, "body", str(body["body"])))
    if body.get("topic") is not None:
        out.append(Change(None, "more:topic", str(body["topic"])))
    return out


def _pin(tx_id: int, eid: str | None) -> list[Change]:
    return [Change(None, "more:pin", f"{eid}@{tx_id}")]


def materialize_entity(store: Store, eid: str, event: Event) -> int:
    """Write the entity and datoms for one admitted event (entity id = event
    id) in one transact call. Returns the tx id."""
    result = store.transact(
        event_changes(event, store) + said_changes(eid, event),
        wrapper=INTERNAL_WRAPPER,
        agent=event.actor,
        op="assert",
        note=f"more:{event.type}",
        entity=eid,
        tx_changes=_pin,
    )
    if result.refusals:
        raise StoreWriteRefused(result.refusals)
    if result.entity != eid:  # pragma: no cover - transact contract
        raise RuntimeError(f"store_bridge: expected entity {eid}, got {result.entity}")
    return result.tx


def materialize_lineage(store: Store, eid: str, tx_id: int, event: Event) -> None:
    if event.type not in ("supersession", "overrule"):
        return
    for parent in event.supersedes:
        record_edge(store.conn, eid, parent, "wasRevisionOf", tx_id, event.reason)


def store_backed(conn: sqlite3.Connection) -> bool:
    return _store_backed(conn)
