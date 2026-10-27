"""Identity ops: evolve, split, merge, correct.

Each op is one tx row (atomic via an explicit transaction over the
autocommit connection) and writes `lineage` edges in PROV vocabulary.
Runs under the internal 'store' authority — these are substrate identity
ops, not wrapper-mediated attribute writes. Package-internal use of
store._datom/store._spec is deliberate.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from .contracts import Change
from .grant import INTERNAL_WRAPPER
from .ids import mint
from .store import Store, _encode


def _tx(conn, op: str, agent: str | None, reason: str | None) -> int:
    return conn.execute(
        "INSERT INTO tx (op, agent, wrapper, note) VALUES (?, ?, ?, ?)",
        (op, agent, INTERNAL_WRAPPER, reason),
    ).lastrowid


def record_edge(conn, child: str, parent: str, kind: str, tx: int, reason: str | None) -> None:
    """Append one lineage edge under an already-open tx. Lineage edges are
    not datoms, so they sit beside transact(); callers own the tx and the
    surrounding transaction."""
    conn.execute(
        "INSERT INTO lineage (child, parent, kind, tx, reason) VALUES (?, ?, ?, ?, ?)",
        (child, parent, kind, tx, reason),
    )


_edge = record_edge


def split(store: Store, e: str, into: Sequence[Sequence[str]], *, reason: str,
          agent: str | None = None) -> list[str]:
    """Mint one child per entry in `into`; each child carries copies of the
    parent's current values for the named attrs. PROV: wasDerivedFrom."""
    conn = store.conn
    if not store.exists(e):
        raise ValueError(f"split: unknown entity {e!r}")
    view = store.view(e)
    conn.execute("BEGIN")
    try:
        tx = _tx(conn, "split", agent, reason)
        children = []
        for carry in into:
            child = mint()
            conn.execute("INSERT INTO entity (id, created_tx) VALUES (?, ?)", (child, tx))
            for a in carry:
                vs = view.get(a)
                if vs is None:
                    continue
                for v in (vs if isinstance(vs, tuple) else (vs,)):
                    store._datom(child, a, _enc(store, a, v), tx, added=True)
            _edge(conn, child, e, "wasDerivedFrom", tx, reason)
            children.append(child)
        conn.execute("COMMIT")
        return children
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def merge(store: Store, es: Sequence[str], *, reason: str,
          choose: dict[str, Any] | None = None,
          agent: str | None = None) -> str:
    """Mint a survivor carrying the union of source attrs. Conflicting
    cardinality-one values are all retained in history (later wins in
    current view) unless `choose` picks one explicitly.
    PROV: wasDerivedFrom survivor -> each source."""
    conn = store.conn
    for e in es:
        if not store.exists(e):
            raise ValueError(f"merge: unknown entity {e!r}")
    views = [store.view(e) for e in es]
    conn.execute("BEGIN")
    try:
        tx = _tx(conn, "merge", agent, reason)
        survivor = mint()
        conn.execute("INSERT INTO entity (id, created_tx) VALUES (?, ?)", (survivor, tx))
        merged: dict[str, list[Any]] = {}
        for view in views:
            for a, v in view.items():
                for val in (v if isinstance(v, tuple) else (v,)):
                    merged.setdefault(a, [])
                    if val not in merged[a]:
                        merged[a].append(val)
        for a, values in merged.items():
            spec = store._spec(a)
            if spec is None:
                continue
            if choose and a in choose:
                values = choose[a] if isinstance(choose[a], list) else [choose[a]]
            # Conflicting cardinality-one values are ALL left asserted:
            # (e,a,v,tx) is the datom PK, so assert+retract of the same v in
            # one tx can't express a merge anyway. Multiple current values
            # for a 'one' attr are the visible mark of an unresolved merge;
            # `choose` resolves. History retains every source value.
            for v in values:
                store._datom(survivor, a, _enc(store, a, v), tx, added=True)
        for e in es:
            _edge(conn, survivor, e, "wasDerivedFrom", tx, reason)
        conn.execute("COMMIT")
        return survivor
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def correct(store: Store, e: str, supersedes: str, *, reason: str,
            agent: str | None = None) -> int:
    """Record that `e` is the corrected form of `supersedes`.
    Lineage kind `severs` (not wasRevisionOf) distinguishes correction from
    evolve. The superseded entity is not deleted; callers detect it via
    superseded_by()."""
    conn = store.conn
    for x in (e, supersedes):
        if not store.exists(x):
            raise ValueError(f"correct: unknown entity {x!r}")
    conn.execute("BEGIN")
    try:
        tx = _tx(conn, "correct", agent, reason)
        _edge(conn, e, supersedes, "severs", tx, reason)
        conn.execute("COMMIT")
        return tx
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def superseded_by(store: Store, e: str) -> str | None:
    """Latest entity that supersedes e, if any."""
    row = store.conn.execute(
        "SELECT child FROM lineage WHERE parent = ? AND kind = 'severs' ORDER BY tx DESC LIMIT 1",
        (e,),
    ).fetchone()
    return row[0] if row else None


def evolve(store: Store, e: str, changes: Iterable[Change], *, reason: str,
           record_edge: bool = False, agent: str | None = None):
    """A revision under op='evolve' (same id). Optionally record a
    wasRevisionOf self-edge for provenance."""
    conn = store.conn
    if not store.exists(e):
        raise ValueError(f"evolve: unknown entity {e!r}")
    conn.execute("BEGIN")
    try:
        result = store.transact(
            (Change(e=e, a=c.a, v=c.v, added=c.added) for c in changes),
            wrapper=INTERNAL_WRAPPER, agent=agent, op="evolve", note=reason,
        )
        if record_edge:
            _edge(conn, e, e, "wasRevisionOf", result.tx, reason)
        conn.execute("COMMIT")
        return result
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _enc(store: Store, a: str, v: Any) -> str:
    spec = store._spec(a)
    return _encode(spec[0], v) if spec else str(v)
