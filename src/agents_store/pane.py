"""pane: the user-facing view. Given an entity + target kind, find and run
a capability path; an unreachable target is a named refusal, not a crash.

Gates: an entity is 'substantive' iff its view holds at least one of
SUBSTANTIVE (title alone is not viewable). A repr target additionally
requires the attrs that make it meaningful (markdown needs body, ical
needs when|status).
"""
from __future__ import annotations

import sqlite3
from collections import deque
from typing import Any

from .contracts import Refusal
from .mediator import Artifact, mediate
from .registry import Registry
from .store import Store

SUBSTANTIVE = frozenset({"body", "when", "status", "end"})
REPR_GATES: dict[str, frozenset[str]] = {
    "markdown": frozenset({"body"}),
    "ical": frozenset({"when", "status"}),
}


def _reachable(reg: Registry, in_kind: str = "entity") -> set[str]:
    seen = {in_kind}
    q: deque[str] = deque([in_kind])
    while q:
        k = q.popleft()
        for c in reg.capabilities.values():
            if c.in_kind == k and c.out_kind not in seen:
                seen.add(c.out_kind)
                q.append(c.out_kind)
    return seen - {in_kind}


def targets(conn: sqlite3.Connection, reg: Registry, e: str) -> set[str]:
    view = Store(conn).view(e)
    if not (set(view) & SUBSTANTIVE):
        return set()
    out = set()
    for k in _reachable(reg):
        gate = REPR_GATES.get(k)
        if gate is None or (set(view) & gate):
            out.add(k)
    return out


def render(conn: sqlite3.Connection, reg: Registry, e: str, target: str) -> Artifact | Refusal:
    if target not in targets(conn, reg, e):
        return Refusal("pane", "no-capability-path", e=e, a=target)
    art = mediate(conn, reg, e, target)
    if art is None:  # path vanished between targets() and mediate — treat as refusal
        return Refusal("pane", "no-capability-path", e=e, a=target)
    return art


def entities_viewable(conn: sqlite3.Connection, reg: Registry, target: str) -> list[str]:
    rows = conn.execute("SELECT id FROM entity ORDER BY id").fetchall()
    return [r[0] for r in rows if target in targets(conn, reg, r[0])]
