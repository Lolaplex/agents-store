"""ADR-style decisions as store entities; resolve the latest live decision."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable

from agents_store.store import Store

from .events import Event, parse_ref
from .status import _events, _inactive


@dataclass(frozen=True)
class LiveDecision:
    """A decision event that still counts in MORe folds, with optional store pin."""
    event: Event
    pin: str | None = None


def _tx_for_event(conn: sqlite3.Connection, event_id: str) -> int | None:
    row = conn.execute(
        "SELECT created_tx FROM entity WHERE id = ?", (event_id,)
    ).fetchone()
    return row[0] if row else None


def inactive_event_ids(
    events: list[Event],
    *,
    as_of_tx: int | None = None,
    tx_for: Callable[[str], int | None] | None = None,
) -> set[str]:
    """Event ids superseded or overruled; optional cut-off by materialization tx."""
    if as_of_tx is None or tx_for is None:
        return _inactive(events)
    out: set[str] = set()
    for e in events:
        if e.type not in ("supersession", "overrule"):
            continue
        tx = tx_for(e.id)
        if tx is not None and tx <= as_of_tx:
            out.update(e.supersedes)
    return out


def _matches_ref(e: Event, subject_ref: str, inactive: set[str]) -> bool:
    subject, version = parse_ref(subject_ref)
    if version is None:
        return False
    return subject in e.subjects and subject_ref in e.pinned_against and e.id not in inactive


def latest_live_decision(
    source,
    store: Store | sqlite3.Connection | None = None,
    *,
    subject_ref: str | None = None,
    topic: str | None = None,
    at_tx: int | None = None,
) -> LiveDecision | None:
    """Latest decision still active in MORe folds.

    Filter by ``subject_ref`` (``SUBJECT@VERSION``), by ``body.topic``, or both.
    With ``at_tx``, only events materialized at or before that tx count, and
    supersessions after that tx do not inactivate earlier decisions yet.
    """
    if subject_ref is None and topic is None:
        raise ValueError("latest_live_decision needs subject_ref and/or topic")
    conn = store.conn if isinstance(store, Store) else store
    events = _events(source)
    tx_for = (lambda eid: _tx_for_event(conn, eid)) if conn is not None else None
    inactive = inactive_event_ids(events, as_of_tx=at_tx, tx_for=tx_for)
    best: Event | None = None
    for e in events:
        if e.type != "decision" or e.id in inactive:
            continue
        if subject_ref is not None and not _matches_ref(e, subject_ref, inactive):
            continue
        if topic is not None and e.body.get("topic") != topic:
            continue
        if at_tx is not None and conn is not None:
            etx = _tx_for_event(conn, e.id)
            if etx is None or etx > at_tx:
                continue
        if best is None or (e.seq or 0) > (best.seq or 0):
            best = e
    if best is None:
        return None
    pin = None
    if conn is not None:
        st = store if isinstance(store, Store) else Store(conn)
        view = st.view(best.id, tx=at_tx) if at_tx is not None else st.view(best.id)
        pins = view.get("more:pin")
        if pins:
            pin = pins[0] if isinstance(pins, tuple) else pins
    return LiveDecision(event=best, pin=pin)
