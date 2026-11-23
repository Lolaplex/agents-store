"""Canonical write/read path over the datom tables.

transact() is the only write API. Its semantics:
- one `tx` row per call; at most one entity minted per call (all e=None
  changes land on it);
- every Change is checked against grants (grant.is_writable); granted
  changes apply, ungranted ones become refusal rows — loudly recorded,
  never silently dropped, and the rest of the batch still applies;
- cardinality 'one': asserting a different value retracts the current one
  in the same tx; re-asserting the current value is a no-op;
- `entity=` pre-assigns the id of the entity the call creates (instead of
  minting one), for callers whose records already carry an id (the MORe
  event log: event id = entity id). The id must not exist yet;
- `tx_changes=` (internal authority only) yields changes whose values need
  the tx id this call opens, e.g. a version pin `entity@tx`. They are
  applied in the same tx, after `changes`.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from . import ids
from .contracts import Change, Datom, WriteRefusal, TxOp, VALID_OPS
from .grant import is_writable
from .hlc import Hlc, HLC_GLOB


@dataclass(frozen=True)
class TxResult:
    """Outcome of one transact call. Module-local until promoted to contracts."""
    tx: int
    entity: str | None           # minted id if this call created one
    applied: tuple[Datom, ...]   # datoms written (includes auto-retractions)
    refusals: tuple[WriteRefusal, ...]


def _encode(value_type: str, v: Any) -> str:
    if value_type == "json":
        return json.dumps(v, sort_keys=True, separators=(",", ":"))
    if value_type == "bool":
        return "true" if v in (True, "true") else "false"
    if value_type == "int":
        return str(int(v))
    return str(v)


def _encode_key(v: Any) -> str:
    """Hashable key for change dedupe, regardless of value type."""
    return v if isinstance(v, str) else json.dumps(v, sort_keys=True, separators=(",", ":"))


def _decode(value_type: str, s: str) -> Any:
    if value_type == "json":
        return json.loads(s)
    if value_type == "bool":
        return s == "true"
    if value_type == "int":
        return int(s)
    return s


_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _valid_text(value_type: str, v: str) -> bool:
    """Stored text must parse under the attr's value_type — guards both
    local encodes and remote wire values from corrupting the log."""
    if value_type == "int":
        try:
            int(v)
            return True
        except (TypeError, ValueError):
            return False
    if value_type == "bool":
        return v in ("true", "false")
    if value_type == "json":
        try:
            json.loads(v)
            return True
        except (TypeError, ValueError):
            return False
    if value_type == "instant":
        return isinstance(v, str) and bool(_INSTANT_RE.match(v))
    return True


class Store:
    def __init__(self, conn: sqlite3.Connection, node_id: str = "local"):
        self.conn = conn
        self.node_id = node_id
        self._specs: dict[str, tuple[str, str]] | None = None
        self._deriving = False  # re-entrancy guard for derive.on_transact
        self._clock = Hlc(node_id)
        self._hlc_col = "hlc" in {
            r[1] for r in conn.execute("PRAGMA table_info(tx)")}
        self._seed_clock()

    def _seed_clock(self) -> None:
        """Resume/merge the newest minted hlc so a restart (or a second
        process that minted meanwhile) never lets this node mint keys that
        order behind recorded history. The GLOB keeps non-hlc strings —
        e.g. legacy notes sorting above '9' — from shadowing the max."""
        if not self._hlc_col:
            return  # mid-migration Store on a pre-v6 tx: no hlc column yet
        row = self.conn.execute(
            "SELECT MAX(hlc) FROM tx WHERE hlc GLOB ?", (HLC_GLOB,)
        ).fetchone()
        if row and row[0]:
            self._clock.observe(row[0])

    def _tick(self) -> str:
        """Mint a local ordering key; re-seeds first so a second process
        cannot have minted past this clock since boot."""
        self._seed_clock()
        return self._clock.tick()

    # ---- writes -------------------------------------------------------

    def transact(
        self,
        changes: Iterable[Change],
        *,
        wrapper: str,
        agent: str | None = None,
        op: TxOp = "assert",
        note: str | None = None,
        entity: str | None = None,
        tx_changes: Callable[[int, str | None], Iterable[Change]] | None = None,
    ) -> TxResult:
        # mediated write-back: an external write to a derived attr routes
        # through its correspondence back to the source attr (equal +
        # witnessed only); non-round-trippable writes are refused.
        from . import derive, grant as _grant
        if tx_changes is not None and wrapper != _grant.INTERNAL_WRAPPER:
            raise ValueError("transact: tx_changes is reserved for the internal authority")
        if op not in VALID_OPS:
            raise ValueError(f"transact: bad op {op!r}")
        if entity is not None:
            if self._exists(entity):
                raise ValueError(f"transact: entity {entity!r} already exists")
            if self.conn.execute(
                "SELECT 1 FROM scrubbed WHERE e = ?", (entity,)
            ).fetchone() is not None:
                raise ValueError(f"transact: entity {entity!r} was scrubbed")
        # atomic: the tx row, its datoms and any refusals land together or
        # not at all. Joins an already-open transaction instead of nesting
        # (lineage.evolve, migrations) — the outer owner then owns commit.
        own = not self.conn.in_transaction
        if own:
            self.conn.execute("BEGIN IMMEDIATE")
        try:
            refusals: list[WriteRefusal] = []
            mediated: set[int] = set()
            planned: list[tuple[Change, str]] = []
            for ch in changes:
                if ch.e is not None and wrapper != _grant.INTERNAL_WRAPPER:
                    edge = derive.derived_edge(self.conn, ch.e, ch.a)
                    if edge is not None:
                        mid, a_from, kind, status = edge
                        if kind == "equal" and status == "witnessed":
                            planned.append((Change(
                                e=ch.e, a=a_from, v=ch.v, added=ch.added),
                                _grant.INTERNAL_WRAPPER))
                            mediated.add(mid)
                        else:
                            refusals.append(self._refuse(
                                wrapper, ch.e, ch.a, "derived_attr", ch.v))
                        continue
                planned.append((ch, wrapper))
            if mediated:
                note = f"{note or ''} | mediated-write via mediator {sorted(mediated)}"
            tx_hlc = self._tick()
            tx_id = self.conn.execute(
                "INSERT INTO tx (op, agent, wrapper, note, hlc) VALUES (?, ?, ?, ?, ?)",
                (op, agent, wrapper, note, tx_hlc),
            ).lastrowid
            if tx_changes is not None:
                # internal authority: no derived_attr mediation applies
                planned.extend((ch, wrapper) for ch in tx_changes(tx_id, entity))
            minted: str | None = None
            if any(ch.e is None for ch, _ in planned):
                minted = entity if entity is not None else ids.mint()
                self.conn.execute(
                    "INSERT INTO entity (id, created_tx) VALUES (?, ?)",
                    (minted, tx_id),
                )
            # resolve e and encode v BEFORE collapsing, so dedupe keys are
            # the stored text (raw values miss: int 1 vs '1', json spacing,
            # e=None dupes); unencodable values are loud refusals, never
            # partial corrupt rows.
            resolved: list[tuple] = []  # (e, ch, v_text, wrapper, card)
            for ch, ch_wrapper in planned:
                e = ch.e if ch.e is not None else minted
                spec = self._spec(ch.a)
                if spec is None:
                    resolved.append((e, ch, _encode_key(ch.v), ch_wrapper, None))
                    continue
                try:
                    v_text = _encode(spec[0], ch.v)
                except (TypeError, ValueError):
                    v_text = None
                if v_text is None or not _valid_text(spec[0], v_text):
                    refusals.append(self._refuse(
                        ch_wrapper, e, ch.a, "bad_value", ch.v))
                    continue
                resolved.append((e, ch, v_text, ch_wrapper, spec[1]))
            # collapse: cardinality 'one' keeps the LAST change per (e,a)
            # in this tx; 'many' dedupes (e,a,v) with retract winning.
            last_one: dict[tuple, int] = {}
            for i, (e, ch, _v, _w, card) in enumerate(resolved):
                if card == "one":
                    last_one[(e, ch.a)] = i
            kept: list[tuple] = []
            seen_many: dict[tuple, int] = {}
            for i, item in enumerate(resolved):
                e, ch, v_text, ch_wrapper, card = item
                if card == "one":
                    if i == last_one[(e, ch.a)]:
                        kept.append(item)
                    continue
                key = (e, ch.a, v_text)
                if key in seen_many:
                    if not ch.added:
                        kept[seen_many[key]] = item  # retract wins
                else:
                    seen_many[key] = len(kept)
                    kept.append(item)
            applied: list[Datom] = []
            for e, ch, _vt, ch_wrapper, _card in kept:
                if not self._exists(e):
                    refusals.append(self._refuse(
                        wrapper, e, ch.a, "unknown_entity", ch.v))
                    continue
                outcome = self._apply(e, ch, tx_id, ch_wrapper, tx_hlc)
                if isinstance(outcome, WriteRefusal):
                    refusals.append(outcome)
                else:
                    applied.extend(outcome)
            # mediated re-derivation: source-attr changes refresh their
            # derived attrs inside this transaction (atomic with the writes)
            if applied and not self._deriving:
                from . import derive
                self._deriving = True
                try:
                    derive.on_transact(self, {(d.e, d.a) for d in applied})
                finally:
                    self._deriving = False
            if own:
                self.conn.execute("COMMIT")
            return TxResult(tx=tx_id, entity=minted, applied=tuple(applied),
                            refusals=tuple(refusals))
        except BaseException:
            if own:
                self.conn.execute("ROLLBACK")
            raise

    def _apply(self, e: str, ch: Change, tx_id: int, wrapper: str, ord_key: str) -> list[Datom] | WriteRefusal:
        spec = self._spec(ch.a)
        if spec is None:
            return self._refuse(wrapper, e, ch.a, "unknown_attr", ch.v)
        value_type, cardinality = spec
        if not is_writable(self.conn, wrapper, ch.a):
            return self._refuse(wrapper, e, ch.a, "no_grant", ch.v)
        v_text = _encode(value_type, ch.v)
        out: list[Datom] = []
        if ch.added:
            current = [r[1] for r in self._current_rows(e, ch.a)]
            if v_text in current:
                return out  # no-op
            if cardinality == "one":
                for old in current:
                    self._datom(e, ch.a, old, tx_id, added=False, ord_key=ord_key)
                    out.append(Datom(e, ch.a, _decode(value_type, old), tx_id, False))
            self._datom(e, ch.a, v_text, tx_id, added=True, ord_key=ord_key)
            out.append(Datom(e, ch.a, ch.v, tx_id, True))
        else:
            if v_text in [r[1] for r in self._current_rows(e, ch.a)]:
                self._datom(e, ch.a, v_text, tx_id, added=False, ord_key=ord_key)
                out.append(Datom(e, ch.a, ch.v, tx_id, False))
        return out

    def _datom(self, e: str, a: str, v: str, tx_id: int, *, added: bool,
               ord_key: str | None = None) -> None:
        if ord_key is None:
            row = self.conn.execute(
                "SELECT hlc FROM tx WHERE id = ?", (tx_id,)
            ).fetchone()
            ord_key = row[0] if row and row[0] else ""
        self.conn.execute(
            "INSERT INTO datom (e, a, v, tx, added, ord) VALUES (?, ?, ?, ?, ?, ?)",
            (e, a, v, tx_id, 1 if added else 0, ord_key),
        )

    def _refuse(self, wrapper: str, e: str | None, a: str | None, reason: str, payload: Any) -> WriteRefusal:
        self.conn.execute(
            "INSERT INTO refusal (wrapper, entity, attr, reason, payload) VALUES (?, ?, ?, ?, ?)",
            (wrapper, e, a, reason, None if payload is None else str(payload)),
        )
        return WriteRefusal(wrapper=wrapper, reason=reason, e=e, a=a, payload=str(payload))

    def record_refusal(self, r: WriteRefusal) -> WriteRefusal:
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

    def refusals(self, e: str | None = None) -> list[WriteRefusal]:
        if e is None:
            rows = self.conn.execute(
                "SELECT wrapper, entity, attr, reason, payload FROM refusal ORDER BY id"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT wrapper, entity, attr, reason, payload FROM refusal WHERE entity = ? ORDER BY id",
                (e,),
            ).fetchall()
        return [WriteRefusal(wrapper=w, reason=r, e=ent, a=a, payload=p) for w, ent, a, r, p in rows]

    def exists(self, e: str) -> bool:
        return self._exists(e)

    def ingest(self, actor: str, seq: int, hlc: str, datoms, *,
               op: str = "assert", note: str | None = None):
        """Ingest one remote op under this node's clock — the remote hlc is
        observed inside ingest so future local ticks order after it, and
        ops minted here dedupe as self-echo."""
        from .ingest import ingest as _ingest
        return _ingest(
            self.conn, actor, seq, hlc, datoms, op=op, note=note,
            clock=self._clock, local_node_id=self.node_id)

    def find(self, a: str, v: Any = None, *, prefix: str | None = None) -> list[str]:
        """Entities whose current value of `a` equals `v` (or, with `prefix=`,
        starts with that text), in creation order. Uses the (a, v) index."""
        spec = self._spec(a)
        if spec is None:
            raise ValueError(f"find: unknown attr {a!r}")
        if prefix is None:
            where, params = "c.v = ?", [_encode(spec[0], v)]
        else:
            # index-friendly range instead of LIKE (no wildcard escaping)
            where, params = "c.v >= ? AND c.v < ?", [prefix, prefix + "\U0010ffff"]
        rows = self.conn.execute(
            f"""SELECT DISTINCT c.e FROM v_current c JOIN entity n ON n.id = c.e
                WHERE c.a = ? AND {where} ORDER BY n.created_tx, c.e""",
            [a, *params],
        ).fetchall()
        return [r[0] for r in rows]

    # ---- internals ----------------------------------------------------

    def _exists(self, e: str) -> bool:
        return self.conn.execute("SELECT 1 FROM entity WHERE id = ?", (e,)).fetchone() is not None

    def _spec(self, a: str) -> tuple[str, str] | None:
        if self._specs is None:
            self._refresh_specs()
        spec = self._specs.get(a)
        if spec is None:
            self._refresh_specs()  # an attr may have been added after boot
            spec = self._specs.get(a)
        return spec

    def _refresh_specs(self) -> None:
        self._specs = {
            r[0]: (r[1], r[2])
            for r in self.conn.execute("SELECT name, value_type, cardinality FROM attr")
        }

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
        # as-of: same ord-argmax rule as v_current, restricted to d.tx <= bound.
        # (tx order is local arrival order; ord is the global order — a remote
        # retract that arrived early still outranks a later-arriving assert.)
        sql = """SELECT d.a, d.v FROM datom d JOIN attr t ON t.name = d.a
                 WHERE d.e = ? AND d.tx <= ? AND d.added = 1 AND (
                   (t.cardinality = 'many' AND d.ord = (
                     SELECT MAX(x.ord) FROM datom x
                     WHERE x.e = d.e AND x.a = d.a AND x.v = d.v AND x.tx <= ?))
                   OR
                   (t.cardinality = 'one' AND d.ord = (
                     SELECT MAX(y.ord) FROM datom y
                     WHERE y.e = d.e AND y.a = d.a AND y.tx <= ?)))"""
        params: list[Any] = [e, bound, bound, bound]
        if a is not None:
            sql += " AND d.a = ?"
            params.append(a)
        sql += " ORDER BY d.a, d.v"
        return self.conn.execute(sql, params).fetchall()
