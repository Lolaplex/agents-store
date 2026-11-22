"""Remote op ingest + local log tail for the sync distributor.

The distributor (agents-sync) owns delivery; this module owns semantics.
A remote op is one remote tx: its datoms land verbatim under a new local
tx stamped with the remote's hlc (ord) and (origin_actor, origin_seq).

- Idempotent: (origin_actor, origin_seq) is unique — redelivery of the
  same remote tx returns the existing local tx, no new datoms.
- Per-datom dedupe: ux_datom_eav_ord ignores facts already present
  (partial replay, echo of a self-originated fact re-delivered by a hub).
- Grants are NOT re-checked: the origin already gate-kept the write;
  re-checking would diverge across nodes with different cert state.
  Unknown attrs are skipped loudly as refusal rows.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable, Sequence

# (e, a, v, added) — v already store-encoded text
RemoteDatom = tuple[str, str, str, bool]

INGEST_WRAPPER = "sync"


@dataclass(frozen=True)
class IngestResult:
    tx: int             # local tx the op landed under (existing one on dedupe)
    applied: int        # datoms newly written
    dupes: int          # datoms already present (re-delivery)
    refused: int        # datoms skipped as refusals (unknown attr)


def ingest(
    conn: sqlite3.Connection,
    actor: str,
    seq: int,
    hlc: str,
    datoms: Iterable[RemoteDatom],
    *,
    op: str = "assert",
    note: str | None = None,
) -> IngestResult:
    row = conn.execute(
        "SELECT id FROM tx WHERE origin_actor = ? AND origin_seq = ?",
        (actor, seq),
    ).fetchone()
    known = {r[0] for r in conn.execute("SELECT name FROM attr")}
    items = list(datoms)
    if row is not None:
        return IngestResult(tx=row[0], applied=0, dupes=len(items), refused=0)
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
        if a not in known:
            conn.execute(
                "INSERT INTO refusal (wrapper, entity, attr, reason, payload)"
                " VALUES (?, ?, ?, 'unknown_attr', ?)",
                (INGEST_WRAPPER, e, a, str(v)),
            )
            refused += 1
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
    return IngestResult(tx=tx_id, applied=applied, dupes=dupes, refused=refused)


def ops_since(
    conn: sqlite3.Connection,
    since_tx: int,
    *,
    limit: int = 1000,
) -> list[dict]:
    """Local log tail for the distributor: every tx > since_tx with its
    datoms and the origin identity the receiver should dedupe on.

    A locally-minted tx is identified as (None, id) — the sender fills in
    its own node id on the wire. An ingested tx keeps its remote origin so
    re-broadcast dedupes at the fact's true origin.
    """
    rows = conn.execute(
        "SELECT id, agent, wrapper, op, note, hlc, origin_actor, origin_seq, ts"
        " FROM tx WHERE id > ? ORDER BY id LIMIT ?",
        (since_tx, limit),
    ).fetchall()
    out = []
    for tx_id, agent, wrapper, op, note, hlc, oa, osq, ts in rows:
        datoms = conn.execute(
            "SELECT e, a, v, added FROM datom WHERE tx = ? ORDER BY rowid",
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
