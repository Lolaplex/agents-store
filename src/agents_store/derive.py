"""derive: generated mediators materialize core attrs from source attrs.

Given witnessed correspondences, `generate` writes a `mediator` row; `run`
asserts the derived datoms on every entity carrying a source attr, with
`provenance` rows naming the inputs and the deriving tx. `on_transact`
re-derives after any tx that touched a mediated source attr — a jcal
adapter write is a normal tx, so derivation is automatic.

Laws:
- derived values are datoms like any other (append-only, viewable); the
  provenance rows are what marks them derived;
- a mediated attr never clobbers a NON-derived current value — that is a
  visible `mediator_conflict` refusal, not silent takeover;
- derivation runs under the internal authority ('store'): the mediator is
  substrate-generated code, its provenance says so;
- writes to derived attrs from OTHER wrappers are handled in transact
  (T16): equal+witnessed edges invert to the source, else 'derived_attr'.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from .contracts import Change, WriteRefusal


def _ref(e: str, a: str) -> str:
    return json.dumps({"e": e, "a": a}, sort_keys=True)


@dataclass
class Mediator:
    id: int
    source: str
    target: str
    exactness: str
    edges: list[tuple[str, str]] = field(default_factory=list)  # (a_from, a_to)


def _load(conn: sqlite3.Connection, mediator_id: int) -> Mediator | None:
    row = conn.execute(
        "SELECT id, source, target, path, exactness FROM mediator WHERE id = ?",
        (mediator_id,)).fetchone()
    if row is None:
        return None
    ids = json.loads(row[3])
    edges = conn.execute(
        f"SELECT a_from, a_to FROM correspondence WHERE id IN "
        f"({','.join('?' * len(ids))})", ids).fetchall()
    return Mediator(id=row[0], source=row[1], target=row[2],
                    exactness=row[4], edges=[(a, b) for a, b in edges])


def mediators(conn: sqlite3.Connection) -> list[Mediator]:
    return [m for m in
            (_load(conn, r[0]) for r in
             conn.execute("SELECT id FROM mediator ORDER BY id"))
            if m is not None]


def generate(conn: sqlite3.Connection, source_ns: str,
             corr_ids: list[int]) -> int:
    """Insert a mediator row from witnessed correspondences. `exact` iff
    every edge is equal+witnessed; anything weaker -> `contained`
    (declared-lossy). Empty or unknown paths are refused."""
    if not corr_ids:
        raise ValueError("generate: empty path")
    rows = conn.execute(
        f"SELECT kind, status FROM correspondence WHERE id IN "
        f"({','.join('?' * len(corr_ids))})", corr_ids).fetchall()
    if len(rows) != len(corr_ids):
        raise ValueError("generate: unknown correspondence in path")
    exact = all(k == "equal" and s == "witnessed" for k, s in rows)
    cur = conn.execute(
        "INSERT INTO mediator (source, target, path, exactness)"
        " VALUES (?, 'core', ?, ?)",
        (source_ns, json.dumps(corr_ids), "exact" if exact else "contained"))
    return cur.lastrowid


def is_derived(conn: sqlite3.Connection, e: str, a: str) -> int | None:
    """Mediator id whose live assertion currently provides (e, a), else
    None. Live = its asserted datom is still in v_current."""
    row = conn.execute(
        "SELECT p.mediator_id FROM provenance p"
        " JOIN v_current vc ON vc.tx = p.tx"
        "   AND vc.e = (CASE WHEN json_valid(p.out_ref)"
        "     THEN json_extract(p.out_ref, '$.e') END)"
        "   AND vc.a = (CASE WHEN json_valid(p.out_ref)"
        "     THEN json_extract(p.out_ref, '$.a') END)"
        " WHERE vc.e = ? AND vc.a = ? LIMIT 1", (e, a)).fetchone()
    return row[0] if row else None


def derived_edge(conn: sqlite3.Connection, e: str, a_to: str):
    """(mediator_id, a_from, kind, status) if a live mediator currently
    derives (e, a_to), else None. Drives write-back inversion."""
    mid = is_derived(conn, e, a_to)
    if mid is None:
        return None
    m = _load(conn, mid)
    for a_from, at in m.edges:
        if at == a_to:
            row = conn.execute(
                "SELECT kind, status FROM correspondence"
                " WHERE a_from = ? AND a_to = ?", (a_from, a_to)).fetchone()
            return (mid, a_from, row[0], row[1]) if row else None
    return None


def run(store, mediator_id: int) -> dict:
    """Materialize derived attrs for every entity carrying a source attr
    of this mediator. Returns {derived, conflicts}."""
    m = _load(store.conn, mediator_id)
    if m is None:
        raise ValueError(f"no mediator {mediator_id}")
    es = {r[0] for a_from, _ in m.edges for r in store.conn.execute(
        "SELECT DISTINCT e FROM v_current WHERE a = ?", (a_from,))}
    return _rederive(store, m, es)


def on_transact(store, touched: set[tuple[str, str]]) -> None:
    """Post-transact hook: re-derive entities whose mediated source
    attrs this tx touched."""
    for m in mediators(store.conn):
        es = {e for e, a in touched
              for a_from, _ in m.edges if a == a_from}
        if es:
            _rederive(store, m, es)


def _rederive(store, m: Mediator, entities: set[str]) -> dict:
    report = {"derived": 0, "conflicts": 0}
    changes: list[Change] = []
    provs: list[tuple[str, str, str]] = []  # (e, a_to, a_from)
    for e in sorted(entities):
        view = store.view(e)
        for a_from, a_to in m.edges:
            src = view.get(a_from)
            src_set = set(src) if isinstance(src, (list, tuple)) else (
                {src} if src is not None else set())
            cur = view.get(a_to)
            cur_set = set(cur) if isinstance(cur, (list, tuple)) else (
                {cur} if cur is not None else set())
            live_mid = is_derived(store.conn, e, a_to)
            # residue values not in the desired set are lawful only when
            # THIS mediator produced them (stale derivations we retract);
            # native or foreign-mediator values are a visible conflict
            if cur_set - src_set and live_mid != m.id:
                # value present that this mediator did not produce
                store.record_refusal(WriteRefusal(
                    wrapper="store", reason="mediator_conflict", e=e, a=a_to,
                    payload=f"mediator {m.id}: {a_to} has non-derived value"))
                report["conflicts"] += 1
                continue
            for v in sorted(cur_set - src_set):
                if live_mid == m.id:
                    changes.append(Change(e=e, a=a_to, v=v, added=False))
            for v in sorted(src_set - cur_set):
                changes.append(Change(e=e, a=a_to, v=v))
                provs.append((e, a_to, a_from))
                report["derived"] += 1
    if not changes:
        return report
    res = store.transact(changes, wrapper="store",
                         note=f"mediator:{m.id} derive")
    for e, a_to, a_from in provs:
        store.conn.execute(
            "INSERT INTO provenance (out_ref, in_refs, mediator_id, tx)"
            " VALUES (?, ?, ?, ?)",
            (_ref(e, a_to), json.dumps(
                [{"e": e, "a": a_from}]), m.id, res.tx))
    return report
