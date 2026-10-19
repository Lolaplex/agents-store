"""Materialize admitted MORe events as store entities in the same SQLite file."""
from __future__ import annotations

import json
import sqlite3

from agents_store.grant import INTERNAL_WRAPPER
from agents_store.store import _encode

from .events import Event


def _store_backed(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='entity'"
    ).fetchone()
    return row is not None


def _edge(conn: sqlite3.Connection, child: str, parent: str, kind: str, tx: int, reason: str | None) -> None:
    conn.execute(
        "INSERT INTO lineage (child, parent, kind, tx, reason) VALUES (?, ?, ?, ?, ?)",
        (child, parent, kind, tx, reason),
    )


def materialize_entity(conn: sqlite3.Connection, eid: str, tx_id: int, event: Event) -> None:
    """Write entity row and datoms for one admitted event (same id as the event row)."""
    conn.execute("INSERT INTO entity (id, created_tx) VALUES (?, ?)", (eid, tx_id))
    body = dict(event.body or {})
    rows = [
        ("more:type", event.type, "text"),
        ("more:actor", event.actor, "text"),
        ("more:at", event.at, "instant"),
        ("more:body", body, "json"),
    ]
    for a, v, vt in rows:
        conn.execute(
            "INSERT INTO datom (e, a, v, tx, added) VALUES (?, ?, ?, ?, 1)",
            (eid, a, _encode(vt, v), tx_id),
        )
    for subj in event.subjects:
        conn.execute(
            "INSERT INTO datom (e, a, v, tx, added) VALUES (?, 'more:subject', ?, ?, 1)",
            (eid, subj, tx_id),
        )
    conn.execute(
        "INSERT INTO datom (e, a, v, tx, added) VALUES (?, 'more:pin', ?, ?, 1)",
        (eid, f"{eid}@{tx_id}", tx_id),
    )
    if event.type == "decision":
        _materialize_adr(conn, eid, tx_id, body)


def _materialize_adr(conn: sqlite3.Connection, eid: str, tx_id: int, body: dict) -> None:
    """Project ADR fields onto the decision artifact kind (title, body, more:topic)."""
    if "title" in body:
        conn.execute(
            "INSERT INTO datom (e, a, v, tx, added) VALUES (?, 'title', ?, ?, 1)",
            (eid, str(body["title"]), tx_id),
        )
    text = body.get("body")
    if text is not None:
        conn.execute(
            "INSERT INTO datom (e, a, v, tx, added) VALUES (?, 'body', ?, ?, 1)",
            (eid, str(text), tx_id),
        )
    topic = body.get("topic")
    if topic is not None:
        conn.execute(
            "INSERT INTO datom (e, a, v, tx, added) VALUES (?, 'more:topic', ?, ?, 1)",
            (eid, str(topic), tx_id),
        )


def materialize_lineage(conn: sqlite3.Connection, eid: str, tx_id: int, event: Event) -> None:
    if event.type not in ("supersession", "overrule"):
        return
    for parent in event.supersedes:
        _edge(conn, eid, parent, "wasRevisionOf", tx_id, event.reason)


def open_tx(conn: sqlite3.Connection, event: Event) -> int:
    note = f"more:{event.type}"
    return conn.execute(
        "INSERT INTO tx (op, agent, wrapper, note) VALUES ('assert', ?, ?, ?)",
        (event.actor, INTERNAL_WRAPPER, note),
    ).lastrowid


def store_backed(conn: sqlite3.Connection) -> bool:
    return _store_backed(conn)
