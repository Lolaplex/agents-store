"""match: propose `correspondence` rows between attr namespaces.

Model-management's `Match` operator, kept decidable: candidates come from
structural rules (local-name equality, prefix relation, a declared alias
table), never guessed semantics. Proposals are `status='proposed'` —
untrusted. The operator confirms by selecting ids for `witness`; a
passing witness certificate raises the edge to `witnessed`. `proven`
needs the Lean tier (out of scope here).

Witness content (POC tier): representational compatibility — every
sampled source value encodes/decodes under the target attr spec without
loss, including the Z-format check for `instant` edges. It does NOT
certify semantic alignment; value-level vocabulary mismatch (e.g.
jcal:status 'confirmed' vs core status 'open|done') is a real limit the
caller resolves by choosing which edges to witness.
"""
from __future__ import annotations

import json
import sqlite3

# Claimed cross-vocabulary alignments a human confirms. Explicit and
# auditable on purpose: name-equality cannot align 'dtstart' with 'when'.
# Each entry: (namespaced source, target) -> proposed kind.
ALIAS: dict[tuple[str, str], str] = {
    ("jcal:summary", "title"): "equal",
    ("jcal:dtstart", "when"): "equal",
    ("jcal:dtend", "end"): "equal",
    ("jcal:status", "status"): "equal",
}


def _local(attr: str) -> str:
    return attr.split(":", 1)[1] if ":" in attr else attr


def _in_ns(attr: str, ns: str) -> bool:
    return attr.startswith(ns + ":") if ns else ":" not in attr


def _attrs(conn: sqlite3.Connection, ns: str) -> dict[str, tuple[str, str]]:
    return {
        r[0]: (r[1], r[2])
        for r in conn.execute("SELECT name, value_type, cardinality FROM attr")
        if _in_ns(r[0], ns)
    }


def propose(conn: sqlite3.Connection, left_ns: str, right_ns: str) -> list[int]:
    """Insert `proposed` correspondence rows for structurally plausible
    edges between the two namespaces. Idempotent. Returns new row ids."""
    left = _attrs(conn, left_ns)
    right = _attrs(conn, right_ns)
    have = {
        (r[0], r[1], r[2])
        for r in conn.execute(
            "SELECT a_from, a_to, kind FROM correspondence")
    }
    out: list[int] = []

    def add(a_from: str, a_to: str, kind: str) -> None:
        if (a_from, a_to, kind) in have:
            return
        cur = conn.execute(
            "INSERT INTO correspondence (a_from, a_to, kind) VALUES (?,?,?)",
            (a_from, a_to, kind))
        have.add((a_from, a_to, kind))
        out.append(cur.lastrowid)

    for a_from, (t1, c1) in left.items():
        for a_to, (t2, c2) in right.items():
            if t1 != t2 or c1 != c2:
                continue
            if _local(a_from) == _local(a_to):
                add(a_from, a_to, "equal")
            elif _local(a_from).startswith(_local(a_to)) or \
                    _local(a_to).startswith(_local(a_from)):
                add(a_from, a_to, "refines")
            elif (a_from, a_to) in ALIAS:
                add(a_from, a_to, ALIAS[(a_from, a_to)])
    return out


def proposals(conn: sqlite3.Connection, *, status: str | None = None) -> list[sqlite3.Row]:
    q = ("SELECT id, a_from, a_to, kind, status FROM correspondence"
         + (" WHERE status = ?" if status else "") + " ORDER BY id")
    return conn.execute(q, (status,) if status else ()).fetchall()


def witness(conn: sqlite3.Connection, corr_ids: list[int],
            corpus_e: list[str] | None = None) -> int | None:
    """Witness-check `equal` edges: every sampled a_from value survives
    encode->decode under the a_to spec (plus Z-format for `instant`).

    Confirmation IS the selection: the caller passes the ids it confirms;
    unselected proposals stay `proposed`. On pass each edge gets a
    certificate (subject 'corr:<id>', tier 'witness') and status
    'witnessed'. Returns the first certificate id, or None if no edge
    passed."""
    first_cert: int | None = None
    for cid in corr_ids:
        row = conn.execute(
            "SELECT a_from, a_to, kind, status FROM correspondence WHERE id = ?",
            (cid,)).fetchone()
        if row is None or row[2] != "equal" or row[3] != "proposed":
            continue  # only proposed equal edges can be witnessed
        a_from, a_to = row[0], row[1]
        spec = conn.execute(
            "SELECT value_type, cardinality FROM attr WHERE name = ?", (a_to,)
        ).fetchone()
        spec_from = conn.execute(
            "SELECT value_type, cardinality FROM attr WHERE name = ?", (a_from,)
        ).fetchone()
        if spec is None or spec_from is None or spec != spec_from:
            continue
        if corpus_e is None:
            values = [r[0] for r in conn.execute(
                "SELECT DISTINCT v FROM v_current WHERE a = ?", (a_from,))]
        else:
            ph = ",".join("?" * len(corpus_e))
            values = [r[0] for r in conn.execute(
                f"SELECT DISTINCT v FROM v_current WHERE a = ? AND e IN ({ph})",
                (a_from, *corpus_e))]
        if spec[0] == "instant" and any(
                not isinstance(v, str) or not v.endswith("Z") for v in values):
            _fail_cert(conn, cid, f"non-Z instant in {len(values)} samples")
            continue
        _pass_cert(conn, cid, a_from, a_to, len(values))
        if first_cert is None:
            row = conn.execute(
                "SELECT certificate_id FROM correspondence WHERE id = ?",
                (cid,)).fetchone()
            first_cert = row[0]
    return first_cert


def _cert(conn: sqlite3.Connection, cid: int, result: str, corpus: str) -> None:
    conn.execute(
        "INSERT INTO certificate (tier, subject, ref, corpus, result)"
        " VALUES ('witness', ?, ?, ?, ?)",
        (f"corr:{cid}", "match.witness", corpus, result))


def _pass_cert(conn: sqlite3.Connection, cid: int,
               a_from: str, a_to: str, n: int) -> None:
    _cert(conn, cid, "pass", f"{a_from}->{a_to} n={n}")
    cert_id = conn.execute(
        "SELECT MAX(id) FROM certificate WHERE subject = ?", (f"corr:{cid}",)
    ).fetchone()[0]
    conn.execute(
        "UPDATE correspondence SET status = 'witnessed',"
        " certificate_id = ? WHERE id = ?", (cert_id, cid))


def _fail_cert(conn: sqlite3.Connection, cid: int, why: str) -> None:
    _cert(conn, cid, "fail", why)
