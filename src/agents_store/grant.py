"""Writability: a wrapper may write an attribute only when a passing
certificate backs a grant_ row. Everything else is refused.

INTERNAL_WRAPPER ('store') is the substrate's own authority — identity ops
(lineage) run under it. It is trusted by construction, not by certificate;
this is structural discipline, not a security boundary (same process).
"""
from __future__ import annotations

import sqlite3

from .code_hash import code_hash_for_impl_ref

INTERNAL_WRAPPER = "store"


def _live_code_hash(conn: sqlite3.Connection, wrapper_id: str) -> str | None:
    row = conn.execute("SELECT impl_ref FROM wrapper WHERE id = ?", (wrapper_id,)).fetchone()
    if row is None:
        return None
    return code_hash_for_impl_ref(row[0])


def grant(conn: sqlite3.Connection, wrapper_id: str, attr_name: str, cert_id: int) -> None:
    """Record that `wrapper_id` may write `attr_name`, backed by `cert_id`.
    Loud on: unknown certificate, certificate that did not pass, duplicate."""
    row = conn.execute(
        "SELECT result, code_hash FROM certificate WHERE id = ?", (cert_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"grant: no certificate {cert_id}")
    if row[0] != "pass":
        raise ValueError(f"grant: certificate {cert_id} result={row[0]!r}, need 'pass'")
    live = _live_code_hash(conn, wrapper_id)
    if live is None or row[1] != live:
        raise ValueError(
            f"grant: certificate {cert_id} code_hash does not match current wrapper code"
        )
    conn.execute(
        "INSERT INTO grant_ (wrapper, attr, certificate_id) VALUES (?, ?, ?)",
        (wrapper_id, attr_name, cert_id),
    )


def is_writable(conn: sqlite3.Connection, wrapper_id: str, attr_name: str) -> bool:
    if wrapper_id == INTERNAL_WRAPPER:
        return True
    live = _live_code_hash(conn, wrapper_id)
    if live is None:
        return False
    return conn.execute(
        """SELECT 1 FROM grant_ g
           JOIN certificate c ON c.id = g.certificate_id
           WHERE g.wrapper = ? AND g.attr = ? AND c.result = 'pass'
             AND c.code_hash = ?
           LIMIT 1""",
        (wrapper_id, attr_name, live),
    ).fetchone() is not None
