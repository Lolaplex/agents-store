"""Canonical write/read path over the datom tables.

transact() is the only write API. Its semantics:
- one `tx` row per call; at most one entity minted per call (all e=None
  changes land on it);
- every Change is checked against grants (grant.is_writable); granted
  changes apply, ungranted ones become refusal rows — loudly recorded,
  never silently dropped, and the rest of the batch still applies;
- cardinality 'one': asserting a different value retracts the current one
  in the same tx; re-asserting the current value is a no-op.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from . import ids
from .contracts import Change, Datom, Refusal, TxOp
from .grant import is_writable


@dataclass(frozen=True)
class TxResult:
    """Outcome of one transact call. Module-local until promoted to contracts."""
    tx: int
    entity: str | None           # minted id if this call created one
    applied: tuple[Datom, ...]   # datoms written (includes auto-retractions)
    refusals: tuple[Refusal, ...]


def _encode(value_type: str, v: Any) -> str:
    if value_type == "json":
        return json.dumps(v, sort_keys=True, separators=(",", ":"))
    if value_type == "bool":
        return "true" if v in (True, "true") else "false"
    if value_type == "int":
        return str(int(v))
    return str(v)


def _decode(value_type: str, s: str) -> Any:
    if value_type == "json":
        return json.loads(s)
    if value_type == "bool":
        return s == "true"
    if value_type == "int":
        return int(s)
    return s


class Store:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._specs: dict[str, tuple[str, str]] | None = None
        self._deriving = False  # re-entrancy guard for derive.on_transact

    # ---- writes -------------------------------------------------------

    def transact(
        self,
        changes: Iterable[Change],
        *,
        wrapper: str,
        agent: str | None = None,
        op: TxOp = "assert",
        note: str | None = None,
    ) -> TxResult:
        tx_id = self.conn.execute(
            "INSERT INTO tx (op, agent, wrapper, note) VALUES (?, ?, ?, ?)",
            (op, agent, wrapper, note),
        ).lastrowid
        minted: str | None = None
        applied: list[Datom] = []
        refusals: list[Refusal] = []
        for ch in changes:
            e = ch.e
            if e is None:
                if minted is None:
                    minted = ids.mint()
                    self.conn.execute(
                        "INSERT INTO entity (id, created_tx) VALUES (?, ?)",
                        (minted, tx_id),
                    )
                e = minted
            elif not self._exists(e):
                refusals.append(self._refuse(wrapper, e, ch.a, "unknown-entity", ch.v))
                continue
            outcome = self._apply(e, ch, tx_id, wrapper)
            if isinstance(outcome, Refusal):
                refusals.append(outcome)
            else:
                applied.extend(outcome)
        # mediated re-derivation: source-attr changes refresh their
        # derived attrs in a follow-up tx (append-only: no tx nesting)
        if applied and not self._deriving:
            from . import derive
            self._deriving = True
            try:
                derive.on_transact(self, {(d.e, d.a) for d in applied})
            finally:
                self._deriving = False
        return TxResult(tx=tx_id, entity=minted, applied=tuple(applied), refusals=tuple(refusals))

    def _apply(self, e: str, ch: Change, tx_id: int, wrapper: str) -> list[Datom] | Refusal:
        spec = self._spec(ch.a)
        if spec is None:
            return self._refuse(wrapper, e, ch.a, "unknown-attr", ch.v)
        value_type, cardinality = spec
        if not is_writable(self.conn, wrapper, ch.a):
            return self._refuse(wrapper, e, ch.a, "no-grant", ch.v)
        v_text = _encode(value_type, ch.v)
        out: list[Datom] = []
        if ch.added:
            current = [r[1] for r in self._current_rows(e, ch.a)]
            if v_text in current:
                return out  # no-op
            if cardinality == "one":
                for old in current:
                    self._datom(e, ch.a, old, tx_id, added=False)
                    out.append(Datom(e, ch.a, _decode(value_type, old), tx_id, False))
            self._datom(e, ch.a, v_text, tx_id, added=True)
            out.append(Datom(e, ch.a, ch.v, tx_id, True))
        else:
            if v_text in [r[1] for r in self._current_rows(e, ch.a)]:
                self._datom(e, ch.a, v_text, tx_id, added=False)
                out.append(Datom(e, ch.a, ch.v, tx_id, False))
        return out

    def _datom(self, e: str, a: str, v: str, tx_id: int, *, added: bool) -> None:
        self.conn.execute(
            "INSERT INTO datom (e, a, v, tx, added) VALUES (?, ?, ?, ?, ?)",
            (e, a, v, tx_id, 1 if added else 0),
        )

    def _refuse(self, wrapper: str, e: str | None, a: str | None, reason: str, payload: Any) -> Refusal:
        self.conn.execute(
            "INSERT INTO refusal (wrapper, entity, attr, reason, payload) VALUES (?, ?, ?, ?, ?)",
            (wrapper, e, a, reason, None if payload is None else str(payload)),
        )
        return Refusal(wrapper=wrapper, reason=reason, e=e, a=a, payload=str(payload))

    def record_refusal(self, r: Refusal) -> Refusal:
        """Persist a wrapper-level refusal (parse/type rejections produced by
        put() before transact ever runs) so every refusal is recorded."""
        return self._refuse(r.wrapper, r.e, r.a, r.reason, r.payload)

    # ---- reads --------------------------------------------------------

    def view(self, e: str, *, tx: int | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for a, v in self._current_rows(e, None, bound=tx):
            spec = self._spec(a)
            if spec is None:  # attr row removed later? cannot happen (attr is append-only vocab)
                continue
            value_type, cardinality = spec
            val = _decode(value_type, v)
            if cardinality == "many":
                out.setdefault(a, []).append(val)
            else:
                out[a] = val
        return {k: tuple(v) if isinstance(v, list) else v for k, v in out.items()}

    def history(self, e: str) -> list[Datom]:
        rows = self.conn.execute(
            "SELECT a, v, tx, added FROM datom WHERE e = ? ORDER BY tx, rowid", (e,)
        ).fetchall()
        return [Datom(e, a, self._decode_by_attr(a, v), tx, bool(added)) for a, v, tx, added in rows]

    def refusals(self, e: str | None = None) -> list[Refusal]:
        if e is None:
            rows = self.conn.execute(
                "SELECT wrapper, entity, attr, reason, payload FROM refusal ORDER BY id"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT wrapper, entity, attr, reason, payload FROM refusal WHERE entity = ? ORDER BY id",
                (e,),
            ).fetchall()
        return [Refusal(wrapper=w, reason=r, e=ent, a=a, payload=p) for w, ent, a, r, p in rows]

    def exists(self, e: str) -> bool:
        return self._exists(e)

    # ---- internals ----------------------------------------------------

    def _exists(self, e: str) -> bool:
        return self.conn.execute("SELECT 1 FROM entity WHERE id = ?", (e,)).fetchone() is not None

    def _spec(self, a: str) -> tuple[str, str] | None:
        if self._specs is None:
            self._specs = {
                r[0]: (r[1], r[2])
                for r in self.conn.execute("SELECT name, value_type, cardinality FROM attr")
            }
        return self._specs.get(a)

    def _decode_by_attr(self, a: str, v: str) -> Any:
        spec = self._spec(a)
        return _decode(spec[0], v) if spec else v

    def _current_rows(self, e: str, a: str | None = None, *, bound: int | None = None):
        """(a, v) pairs currently asserted for e — v_current, or as-of `bound` tx."""
        if bound is None:
            if a is None:
                return self.conn.execute(
                    "SELECT a, v FROM v_current WHERE e = ? ORDER BY a, v", (e,)
                ).fetchall()
            return self.conn.execute(
                "SELECT a, v FROM v_current WHERE e = ? AND a = ?", (e, a)
            ).fetchall()
        # as-of: recompute from the log
        sql = """SELECT d.a, d.v FROM datom d
                 WHERE d.e = ? AND d.tx <= ? AND d.added = 1
                   AND NOT EXISTS (SELECT 1 FROM datom r
                       WHERE r.e = d.e AND r.a = d.a AND r.v = d.v
                         AND r.added = 0 AND r.tx > d.tx AND r.tx <= ?)"""
        params: list[Any] = [e, bound, bound]
        if a is not None:
            sql += " AND d.a = ?"
            params.append(a)
        sql += " GROUP BY d.a, d.v ORDER BY d.a, d.v"
        return self.conn.execute(sql, params).fetchall()
