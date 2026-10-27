"""Append-only event log over sqlite3 (Cypoe/more-framework@e32e5c3:lean-model/more-lean-model.md §8 rules: no
update, no delete; ending anything is an event).

Each row carries a hash chain: digest = sha256(prev || id || canonical
envelope). verify() recomputes it, so an edit or removal made below the
triggers (raw file access) shows up as event_mutated.

When opened on a store database (``entity`` table present), each admitted
event is also materialized as an entity with the same id through
Store.transact, in the same atomic SQLite transaction as the event row.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Iterator

from agents_store.ids import mint
from agents_store.store import Store

from .checks import EVENT_MUTATED, Violation, check_event
from .events import Event
from .profile import Profile, load_profile
from .store_bridge import materialize_entity, materialize_lineage, store_backed

SCHEMA = Path(__file__).resolve().parent / "schema.sql"


class Refused(Exception):
    def __init__(self, violations: list[Violation]):
        self.violations = violations
        super().__init__("; ".join(f"{v.id}: {v.detail}" for v in violations))


def _digest(prev: str, event_id: str, envelope: bytes) -> str:
    h = hashlib.sha256()
    h.update(prev.encode("ascii"))
    h.update(b"\x00")
    h.update(event_id.encode("ascii"))
    h.update(b"\x00")
    h.update(envelope)
    return h.hexdigest()


def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))


class EventLog:
    def __init__(
        self,
        path: str | Path = ":memory:",
        profile: Profile | None = None,
        *,
        conn: sqlite3.Connection | None = None,
    ):
        self.profile = profile or load_profile()
        if conn is not None:
            self.conn = conn
            self._owns_conn = False
            _apply_schema(conn)
        else:
            self.conn = sqlite3.connect(str(path), isolation_level=None)
            self._owns_conn = True
            _apply_schema(self.conn)
        self._integrated = store_backed(self.conn)
        self._store = Store(self.conn) if self._integrated else None

    def close(self) -> None:
        if self._owns_conn:
            self.conn.close()

    def _head(self) -> str:
        row = self.conn.execute("SELECT digest FROM event ORDER BY seq DESC LIMIT 1").fetchone()
        return row[0] if row else ""

    def append(self, event: Event) -> Event:
        """Append or refuse. A refusal is recorded and raised, never silent."""
        if event.id is not None or event.seq is not None:
            raise ValueError("append takes a fresh event; ids are minted by the log")
        violations = check_event(event, self.profile)
        payload = event.canonical().decode("utf-8")
        if violations:
            for v in violations:
                self.conn.execute(
                    "INSERT INTO more_refusal (violation, detail, payload) VALUES (?, ?, ?)",
                    (v.id, v.detail, payload))
            raise Refused(violations)
        eid = mint()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            prev = self._head()
            digest = _digest(prev, eid, event.canonical())
            tx_id: int | None = None
            if self._integrated:
                tx_id = materialize_entity(self._store, eid, event)
            seq = self.conn.execute(
                "INSERT INTO event (id, type, actor, at, envelope, prev, digest) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (eid, event.type, event.actor, event.at, payload, prev, digest)).lastrowid
            self.conn.executemany(
                "INSERT INTO event_subject (event_id, subject) VALUES (?, ?)",
                [(eid, s) for s in dict.fromkeys(event.subjects)])
            if self._integrated and tx_id is not None:
                materialize_lineage(self._store, eid, tx_id, event)
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        return event.with_assigned(id=eid, seq=seq, prev=prev, digest=digest)

    def _row(self, row) -> Event:
        seq, eid, envelope, prev, digest = row
        return Event.from_envelope(json.loads(envelope), id=eid, seq=seq, prev=prev, digest=digest)

    def events(self, subject: str | None = None) -> Iterator[Event]:
        if subject is None:
            q = self.conn.execute("SELECT seq, id, envelope, prev, digest FROM event ORDER BY seq")
        else:
            q = self.conn.execute(
                "SELECT e.seq, e.id, e.envelope, e.prev, e.digest FROM event e "
                "JOIN event_subject s ON s.event_id = e.id WHERE s.subject = ? ORDER BY e.seq",
                (subject,))
        for row in q:
            yield self._row(row)

    def get(self, event_id: str) -> Event | None:
        row = self.conn.execute(
            "SELECT seq, id, envelope, prev, digest FROM event WHERE id = ?", (event_id,)).fetchone()
        return self._row(row) if row else None

    def refusals(self) -> list[tuple[str, str]]:
        return list(self.conn.execute(
            "SELECT violation, detail FROM more_refusal ORDER BY id"))

    def verify(self) -> list[Violation]:
        """Recompute the hash chain. Any break is event_mutated."""
        out: list[Violation] = []
        prev = ""
        for seq, eid, envelope, stored_prev, digest in self.conn.execute(
                "SELECT seq, id, envelope, prev, digest FROM event ORDER BY seq"):
            canon = Event.from_envelope(json.loads(envelope)).canonical()
            if canon != envelope.encode("utf-8"):
                out.append(Violation(EVENT_MUTATED, f"seq {seq}: envelope is not canonical", eid))
            if stored_prev != prev:
                out.append(Violation(EVENT_MUTATED, f"seq {seq}: chain broken (prev mismatch; an event was removed or reordered)", eid))
            if _digest(stored_prev, eid, envelope.encode("utf-8")) != digest:
                out.append(Violation(EVENT_MUTATED, f"seq {seq}: digest mismatch (content changed after append)", eid))
            prev = digest
        return out
