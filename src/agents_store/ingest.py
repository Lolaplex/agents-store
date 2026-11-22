"""Remote op ingest + local log tail for the sync distributor.

The distributor (agents-sync) owns delivery; this module owns semantics.
A remote op is one remote tx: its datoms land verbatim under a new local
tx stamped with the remote's hlc (ord) and (origin_actor, origin_seq).

Rules (frontier review 22.11):

- Idempotent: (origin_actor, origin_seq) is unique — redelivery of the
  same remote tx returns the existing local tx, no new datoms.
- Self-echo: ops that originated HERE (actor == local_node_id) and whose
  local tx still exists dedupe to zero new rows, no phantom tx.
- Per-datom dedupe: ux_datom_eav_ord ignores facts already present
  (partial replay, re-delivered single facts).
- Canonicalization, deterministic for every receiver:
  * same (e,a,v) twice in one tx -> retract (added=0) wins;
  * >1 distinct asserted value for a card-one (e,a) at the same ord ->
    max(v) wins + refusal 'card_one_same_ord'.
- Scrub tombstones: datoms for a scrubbed entity with ord <= the scrub
  hlc are dropped; op='scrub' replays a local scrub_entity.
- Grants are NOT re-checked: the origin already gate-kept the write;
  re-checking would diverge across nodes with different cert state.
  Unknown and never-syncable attrs are skipped loudly as refusal rows.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable

# (e, a, v, added) — v already store-encoded text
RemoteDatom = tuple[str, str, str, bool]

INGEST_WRAPPER = "sync"

# attr names starting with these prefixes never cross the wire, in either
# direction — enforced here so agents-sync can stay store-agnostic.
NEVER_SYNC_PREFIXES = ("local:", "secret:", "vault:", "host:")


class ResyncRequired(Exception):
    """ops_since called with a cursor behind the compaction floor: the
    caller must request a snapshot replay instead of a tail."""


@dataclass(frozen=True)
class IngestResult:
    tx: int             # local tx the op landed under (existing one on dedupe)
    applied: int        # datoms newly written
    dupes: int          # datoms already present (re-delivery / self-echo)
    refused: int        # datoms skipped as refusals


def _syncable(conn: sqlite3.Connection, a: str, known: set[str]) -> bool:
    if a not in known:
        return False
    if a.startswith(NEVER_SYNC_PREFIXES):
        return False
    row = conn.execute("SELECT syncable FROM attr WHERE name = ?", (a,)).fetchone()
    return bool(row and row[0])


def _refuse(conn, e: str, a: str | None, reason: str, payload) -> None:
    conn.execute(
        "INSERT INTO refusal (wrapper, entity, attr, reason, payload) VALUES (?, ?, ?, ?, ?)",
        (INGEST_WRAPPER, e, a, reason, None if payload is None else str(payload)),
    )


def _collapse(items: list[RemoteDatom]) -> list[RemoteDatom]:
    """Retract wins on same (e,a,v) within one tx; then card-one
    canonicalize: multiple asserted values for the same (e,a) collapse to
    max(v) + are flagged for refusal logging by the caller."""
    best: dict[tuple, bool] = {}
    order: dict[tuple, int] = {}
    for i, (e, a, v, added) in enumerate(items):
        key = (e, a, v)
        if key not in best:
            order[key] = i
        best[key] = best.get(key, added) and added
    return [(e, a, v, added) for (e, a, v), added in
            sorted(best.items(), key=lambda kv: order[kv[0]])]


def ingest(
    conn: sqlite3.Connection,
    actor: str,
    seq: int,
    hlc: str,
    datoms: Iterable[RemoteDatom],
    *,
    op: str = "assert",
    note: str | None = None,
    clock=None,
    local_node_id: str | None = None,
) -> IngestResult:
    if op == "scrub":
        # Remote hard-delete tombstone: note carries the entity id, hlc
        # is the cutoff. Replay locally; idempotent via scrubbed PK.
        from .scrub import scrub_entity
        e = str(note or "")
        res = scrub_entity(conn, e, reason="remote scrub", ord_key=hlc)
        if clock is not None and hlc:
            clock.observe(hlc)
        return IngestResult(tx=res.tx, applied=res.datoms_removed, dupes=0, refused=0)

    row = conn.execute(
        "SELECT id FROM tx WHERE origin_actor = ? AND origin_seq = ?",
        (actor, seq),
    ).fetchone()
    items = _collapse(list(datoms))
    if row is not None:
        return IngestResult(tx=row[0], applied=0, dupes=len(items), refused=0)
    # self-echo: this op was minted here; dedupe without a new tx row
    if local_node_id and actor == local_node_id:
        own = conn.execute(
            "SELECT id FROM tx WHERE id = ? AND origin_actor IS NULL", (seq,)
        ).fetchone()
        if own is not None:
            return IngestResult(tx=own[0], applied=0, dupes=len(items), refused=0)

    specs = {r[0]: r[1] for r in conn.execute(
        "SELECT name, cardinality FROM attr")}
    known = set(specs)
    scrubbed = {r[0]: r[1] for r in conn.execute("SELECT e, hlc FROM scrubbed")}

    # card-one canonicalize: distinct asserted values at same (e,a) -> max
    one_multi: dict[tuple, list[str]] = {}
    for e, a, v, added in items:
        if added and specs.get(a) == "one":
            one_multi.setdefault((e, a), [])
            if v not in one_multi[(e, a)]:
                one_multi[(e, a)].append(v)
    losers: set[tuple] = set()
    for (e, a), vs in one_multi.items():
        if len(vs) > 1:
            losers.update((e, a, v) for v in vs if v != max(vs))

    tx_id = conn.execute(
        "INSERT INTO tx (op, agent, wrapper, note, hlc, origin_actor, origin_seq)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (op, actor, INGEST_WRAPPER, note, hlc, actor, seq),
    ).lastrowid
    # pre-v6 remote ops may carry an empty hlc; fall back to the origin
    # seq so distinct remote txs still get distinct ordering keys
    ord_key = hlc or f"{seq:012d}.{actor}"
    applied = dupes = refused = 0
    for e, a, v, added in items:
        if not _syncable(conn, a, known):
            _refuse(conn, e, a, "non_syncable_attr" if a in known else "unknown_attr", v)
            refused += 1
            continue
        if (e, a, v) in losers:
            _refuse(conn, e, a, "card_one_same_ord", v)
            refused += 1
            continue
        scrub_hlc = scrubbed.get(e)
        if scrub_hlc is not None and ord_key <= scrub_hlc:
            dupes += 1  # tombstoned: entity was hard-deleted after this ord
            continue
        conn.execute(
            "INSERT OR IGNORE INTO entity (id, created_tx) VALUES (?, ?)",
            (e, tx_id),
        )
        cur = conn.execute(
            "INSERT OR IGNORE INTO datom (e, a, v, tx, added, ord)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (e, a, v, tx_id, 1 if added else 0, ord_key),
        )
        if cur.rowcount:
            applied += 1
        else:
            dupes += 1
    if clock is not None and hlc:
        clock.observe(hlc)
    return IngestResult(tx=tx_id, applied=applied, dupes=dupes, refused=refused)


def floor_tx(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'floor_tx'").fetchone()
    return int(row[0]) if row else 0


def ops_since(
    conn: sqlite3.Connection,
    since_tx: int,
    *,
    limit: int = 1000,
    origin_only: bool = False,
    local_origins: tuple = (),
) -> list[dict]:
    """Local log tail for the distributor: every tx > since_tx with its
    datoms and the origin identity the receiver should dedupe on.

    A locally-minted tx is identified as (None, id) — the sender fills in
    its own node id on the wire. An ingested tx keeps its remote origin so
    re-broadcast dedupes at the fact's true origin.

    origin_only=True returns only locally-minted ops (spoke -> hub: never
    echo foreign ops back to the hub that delivered them). Locally-
    originated ops may still carry an origin identity — e.g. ingest-based
    projections stamp `proj:<session>`; pass their prefixes in
    local_origins so they count as local for the echo filter.

    Never-syncable datoms are filtered out at the source. since_tx below
    the compaction floor raises ResyncRequired — caller must snapshot.
    """
    if since_tx < floor_tx(conn):
        raise ResyncRequired(
            f"cursor {since_tx} behind floor_tx {floor_tx(conn)}")
    where = "id > ?"
    if origin_only:
        local = "origin_actor IS NULL"
        for prefix in local_origins:
            esc = str(prefix).replace("'", "''")
            local += f" OR origin_actor LIKE '{esc}%'"
        where += f" AND ({local})"
    rows = conn.execute(
        "SELECT id, agent, wrapper, op, note, hlc, origin_actor, origin_seq, ts"
        f" FROM tx WHERE {where} ORDER BY id LIMIT ?",
        (since_tx, limit),
    ).fetchall()
    out = []
    for tx_id, agent, wrapper, op, note, hlc, oa, osq, ts in rows:
        datoms = conn.execute(
            "SELECT d.e, d.a, d.v, d.added FROM datom d JOIN attr t ON t.name = d.a"
            f" WHERE d.tx = ? AND t.syncable = 1"
            + "".join(f" AND d.a NOT LIKE '{p}%'" for p in NEVER_SYNC_PREFIXES)
            + " ORDER BY d.rowid",
            (tx_id,),
        ).fetchall()
        out.append({
            "tx": tx_id,
            "origin_actor": oa,
            "origin_seq": osq if oa is not None else tx_id,
            "hlc": hlc or "",
            "agent": agent,
            "op": op,
            "note": note,
            "ts": ts,
            "datoms": [{"e": e, "a": a, "v": v, "added": bool(ad)} for e, a, v, ad in datoms],
        })
    return out


def cursor(conn: sqlite3.Connection) -> int:
    """Largest local tx id — the resume marker a peer sends back as since."""
    row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM tx").fetchone()
    return row[0]
