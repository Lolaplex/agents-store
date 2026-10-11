"""mediator: compose registered capabilities into derived artifacts,
recording the path (mediator row) and inputs (provenance row).

A wrapper's `get` is exposed as a capability edge entity -> <repr kind>
(mode 'lens'): `wrapper_capability(w, 'markdown')`. Path search is BFS
over capability in_kind/out_kind edges.

Exactness: 'exact' iff every step is mode 'lens'; any 'render' step makes
the artifact 'contained' (rendered output is a lossy view by nature).
"""
from __future__ import annotations

import json
import sqlite3
from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping

from . import kinds as kinds_mod
from .contracts import Capability, CapabilityPath, EntityView, Wrapper
from .registry import Registry
from .store import Store


class WrapperGet:
    """Capability adapter: wrapper.get as an entity -> repr-kind edge."""

    def __init__(self, wrapper: Wrapper, out_kind: str):
        self.wrapper = wrapper
        self.id = f"{wrapper.id}-get"
        self.in_kind = "entity"
        self.out_kind = out_kind
        self.mode = "lens"

    def run(self, value: Any, ctx: Mapping[str, Any]) -> str:
        return self.wrapper.get(value["id"], value.get("view") or {})


def wrapper_capability(w: Wrapper, out_kind: str) -> WrapperGet:
    return WrapperGet(w, out_kind)


@dataclass(frozen=True)
class Artifact:
    value: Any
    out_kind: str
    exactness: str              # 'exact' | 'contained'
    path: CapabilityPath
    mediator_id: int


def find_path(reg: Registry, in_kind: str, out_kind: str) -> CapabilityPath | None:
    """BFS over the capability graph (in_kind -> out_kind edges)."""
    if in_kind == out_kind:
        return CapabilityPath(steps=())
    seen = {in_kind}
    q: deque[tuple[str, tuple[str, ...]]] = deque([(in_kind, ())])
    while q:
        kind, path = q.popleft()
        for c in reg.capabilities.values():
            if c.in_kind != kind:
                continue
            nxt = path + (c.id,)
            if c.out_kind == out_kind:
                return CapabilityPath(steps=nxt)
            if c.out_kind not in seen:
                seen.add(c.out_kind)
                q.append((c.out_kind, nxt))
    return None


def _derived_map(conn: sqlite3.Connection, e: str, member_kinds: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k in member_kinds:
        g = kinds_mod.gaps(conn, e, k)
        spec_rows = conn.execute(
            "SELECT derivations FROM kind WHERE name = ?", (k,)
        ).fetchall()
        for a in g.derivable:
            for row in spec_rows:
                for d in json.loads(row[0]):
                    if d["attr"] == a:
                        out[a] = d["rule"]
    return out


def mediate(conn: sqlite3.Connection, reg: Registry, e: str, out_kind: str,
            *, in_kind: str = "entity") -> Artifact | None:
    """Find a path entity -> out_kind, run it, record mediator + provenance.
    None when no path exists (caller decides how to surface that)."""
    path = find_path(reg, in_kind, out_kind)
    if path is None:
        return None
    store = Store(conn)
    view = store.view(e)
    member = kinds_mod.of(conn, e)
    payload: dict[str, Any] = {
        "id": e,
        "view": view,
        "kinds": sorted(member),
        "derived": _derived_map(conn, e, member),
        "lineage": conn.execute(
            "SELECT child, parent, kind FROM lineage WHERE child = ? OR parent = ?", (e, e)
        ).fetchall(),
    }
    value: Any = payload
    steps: list[str] = []
    exact = True
    for cid in path.steps:
        c = reg.capabilities[cid]
        value = c.run(value, {})
        steps.append(cid)
        if c.mode != "lens":
            exact = False
    exactness = "exact" if exact else "contained"
    mid = conn.execute(
        "INSERT INTO mediator (source, target, path, exactness) VALUES (?, ?, ?, ?)",
        (in_kind, out_kind, json.dumps(steps), exactness),
    ).lastrowid
    conn.execute(
        "INSERT INTO provenance (out_ref, in_refs, mediator_id) VALUES (?, ?, ?)",
        (f"{e}:{out_kind}:{mid}", json.dumps([e, in_kind]), mid),
    )
    return Artifact(value=value, out_kind=out_kind, exactness=exactness,
                    path=path, mediator_id=mid)
